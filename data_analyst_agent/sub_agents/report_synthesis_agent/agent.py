# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Report Synthesis Agent - Main agent module.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator, Any, Optional

from google.adk import Agent
from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.genai import types

from config.model_loader import get_agent_model, get_agent_thinking_config
from .prompt import REPORT_SYNTHESIS_AGENT_INSTRUCTION, build_report_instruction
from .tools import generate_markdown_report
from ...utils import parse_bool_env
from ...utils.contract_summary import build_contract_metadata
from ...utils.focus_directives import (
    augment_instruction,
    focus_payload as build_focus_payload,
)
from ...utils.temporal_grain import (
    normalize_temporal_grain,
    temporal_grain_to_period_unit,
)
from ...utils.hierarchy_levels import hierarchy_level_range, independent_level_range
from ...utils.stub_guard import contains_stub_content, stub_outputs_allowed


_base_agent = Agent(
    model=get_agent_model("report_synthesis_agent"),
    name="report_synthesis_agent",
    description="Synthesizes results from all parallel analysis agents into a structured executive report using 3-level framework.",
    instruction=REPORT_SYNTHESIS_AGENT_INSTRUCTION,
    output_key="report_synthesis_result",
    tools=[generate_markdown_report],
    generate_content_config=types.GenerateContentConfig(
        response_modalities=["TEXT"],
        temperature=0.2,
        max_output_tokens=4096,
        thinking_config=get_agent_thinking_config("report_synthesis_agent"),
    ),
)


def _get_thinking_config_for_model(model: str, thinking_budget: int | None = None) -> types.ThinkingConfig | None:
    """Return ThinkingConfig for a model string when bypassing agent config (e.g. benchmark)."""
    if not model:
        return None
    _NO_THINKING = ("flash-lite", "gemini-2.0-flash", "embedding")
    if any(s in model for s in _NO_THINKING):
        return None
    if "gemini-2.5-flash" in model and "lite" not in model:
        if thinking_budget is not None:
            try:
                return types.ThinkingConfig(thinking_budget=thinking_budget)
            except Exception:
                pass
        return None
    if "gemini-2.5-pro" in model or ("gemini-3" in model and "pro" in model):
        try:
            if thinking_budget:
                return types.ThinkingConfig(include_thoughts=True, thinking_budget=thinking_budget)
            return types.ThinkingConfig(include_thoughts=True)
        except Exception:
            return None
    if "gemini-3" in model and "flash" in model:
        if thinking_budget is not None:
            try:
                return types.ThinkingConfig(thinking_budget=thinking_budget)
            except Exception:
                pass
        return None
    return None


def _slim_card(card: dict) -> dict:
    """Return a report-synthesis-friendly subset of an insight card.
    
    Drops redundant fields and condenses evidence to keep prompt size manageable.
    """
    evidence = card.get("evidence", {})
    slim_evidence = {
        k: v for k, v in evidence.items() 
        if k in ("variance_dollar", "variance_pct", "current", "prior", "share_of_total")
    }
    # Include mix/pvm details if present but slimmed
    if "mix_details" in evidence:
        slim_evidence["mix_details"] = evidence["mix_details"]
    if "pvm_details" in evidence:
        slim_evidence["pvm_details"] = evidence["pvm_details"]

    return {
        "title": card.get("title", ""),
        "what_changed": card.get("what_changed", ""),
        "why": card.get("why", ""),
        "evidence": slim_evidence,
        "priority": card.get("priority", ""),
        "impact_score": card.get("impact_score", 0),
        "materiality_weight": card.get("materiality_weight", 0),
        "discovery_method": card.get("discovery_method", "standard_drill")
    }


def _slim_alert(alert: dict) -> dict:
    """Return a report-synthesis-friendly subset of a scored alert.

    Keeps only narrative-relevant fields and condenses the signals dict into a
    compact list of triggered signal names, dropping internal scoring mechanics
    that the LLM doesn't need to write the executive report.
    """
    signals_dict = alert.get("signals", {})
    triggered = [k for k, v in signals_dict.items() if v]

    details = alert.get("details", {})
    description = details.get("description", "")
    if isinstance(description, str) and len(description) > 240:
        description = description[:240].rstrip() + " …"

    return {
        "item": alert.get("item_name") or alert.get("dimension_value") or alert.get("gl_code") or alert.get("item_id", "Unknown"),
        "period": alert.get("period", ""),
        "category": alert.get("category", ""),
        "priority": alert.get("priority", ""),
        "variance_pct": alert.get("variance_pct"),
        "variance_amount": alert.get("variance_amount"),
        "description": description,
        "signals": triggered,
    }


def _compact_json(payload: Any) -> str:
    try:
        return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    except TypeError:
        return str(payload)


def _loads_or_passthrough(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError, ValueError):
            return value
    return value


def _note_for_truncation(label: str, max_chars: int) -> dict[str, str]:
    return {
        "warning": f"{label} payload exceeded {max_chars} chars; truncated for prompt budget."
    }


def _safe_int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


_MAX_REPORT_NARRATIVE_CARDS = _safe_int_env("REPORT_SYNTHESIS_MAX_NARRATIVE_CARDS", 3)
_MAX_REPORT_ACTIONS = _safe_int_env("REPORT_SYNTHESIS_MAX_ACTIONS", 2)
_MAX_STATS_TOP_DRIVERS = _safe_int_env("REPORT_SYNTHESIS_MAX_STATS_DRIVERS", 3)
_MAX_STATS_ANOMALIES = _safe_int_env("REPORT_SYNTHESIS_MAX_STATS_ANOMALIES", 2)

_MAX_NARRATIVE_CHARS = _safe_int_env("REPORT_SYNTHESIS_MAX_NARRATIVE_CHARS", 1300)
_MAX_DATA_ANALYST_CHARS = _safe_int_env("REPORT_SYNTHESIS_MAX_DA_CHARS", 900)
_MAX_HIERARCHICAL_CHARS = _safe_int_env("REPORT_SYNTHESIS_MAX_HIERARCHICAL_CHARS", 1100)
_MAX_INDEPENDENT_CHARS = _safe_int_env("REPORT_SYNTHESIS_MAX_INDEPENDENT_CHARS", 650)
_MAX_ALERT_CHARS = _safe_int_env("REPORT_SYNTHESIS_MAX_ALERT_CHARS", 650)
_MAX_STAT_SUMMARY_CHARS = _safe_int_env("REPORT_SYNTHESIS_MAX_STAT_SUMMARY_CHARS", 900)


_FAST_PATH_PLACEHOLDER_PHRASES = (
    "no hierarchical analysis results available",
    "no hierarchical data available",
    "no drill-down results available",
)


def _string_has_hierarchical_signal(text: str | None) -> bool:
    if not text:
        return False
    normalized = str(text).strip()
    if not normalized:
        return False
    lowered = normalized.lower()
    return not any(phrase in lowered for phrase in _FAST_PATH_PLACEHOLDER_PHRASES)


def _entry_has_hierarchical_signal(entry: Any) -> bool:
    if entry is None:
        return False
    parsed = _loads_or_passthrough(entry)
    if isinstance(parsed, dict):
        if parsed.get("insight_cards"):
            return True
        for key in ("level_summary", "summary", "message"):
            if parsed.get(key):
                return True
        return False
    if isinstance(parsed, list):
        return any(_entry_has_hierarchical_signal(item) for item in parsed)
    if isinstance(parsed, str):
        return _string_has_hierarchical_signal(parsed)
    return bool(parsed)


def _has_hierarchical_signal(payload: dict[str, Any], fallback_text: str | None) -> bool:
    if payload:
        for value in payload.values():
            if _entry_has_hierarchical_signal(value):
                return True
        return False
    return _string_has_hierarchical_signal(fallback_text)


def _contract_has_hierarchy(contract: Any) -> bool:
    if not contract:
        return False
    hierarchies = getattr(contract, "hierarchies", None)
    if hierarchies is None and isinstance(contract, dict):
        hierarchies = contract.get("hierarchies")
    try:
        return bool(hierarchies)
    except Exception:
        return False


def _deterministic_plan_hint(plan_entry: Any) -> Optional[str]:
    if not plan_entry:
        return None
    parsed: Any = plan_entry
    if isinstance(plan_entry, str):
        try:
            parsed = json.loads(plan_entry)
        except (json.JSONDecodeError, TypeError, ValueError):
            lowered = plan_entry.lower()
            if "rule-based plan" in lowered or "rule based plan" in lowered:
                return "rule-based execution plan"
            return None
    if isinstance(parsed, dict):
        summary = str(parsed.get("summary", ""))
        if summary and "rule-based plan" in summary.lower():
            return "rule-based execution plan"
        context_summary = parsed.get("context_summary") or {}
        if isinstance(context_summary, dict):
            planner_mode = str(context_summary.get("planner_mode", "")).strip().lower()
            if planner_mode in {"rule_based", "deterministic"}:
                return f"{planner_mode.replace('_', ' ')} planner"
        metadata = parsed.get("metadata") or {}
        if isinstance(metadata, dict):
            planner_mode = str(metadata.get("planner_mode", "")).strip().lower()
            if planner_mode in {"rule_based", "deterministic"}:
                return f"{planner_mode.replace('_', ' ')} planner"
    return None


def _truncate_block(block: str | None, max_chars: int, label: str) -> str:
    if not block:
        return ""
    text = str(block)
    if len(text) <= max_chars:
        return text
    suffix = f" … [truncated {label} to {max_chars} chars]"
    keep = max(0, max_chars - len(suffix))
    return text[:keep].rstrip() + suffix


_PRUNABLE_ANALYST_KEYS = {
    "level_results",
    "entity_rows",
    "child_rows",
    "dimension_rows",
    "dimension_results",
    "raw_rows",
    "raw_children",
    "records",
    "detailed_rows",
}


_PRUNABLE_LEVEL_KEYS = {
    "level_results",
    "entity_rows",
    "child_rows",
    "raw_rows",
    "raw_children",
    "dimension_rows",
    "dimension_results",
    "level_summary",
    "level_summary_table",
    "entity_rankings",
    "records",
}




def _prune_analysis_dict(payload):
    """Strip bulky table artifacts from serialized analysis payloads (recursive)."""
    if isinstance(payload, dict):
        for key in list(payload.keys()):
            if key in _PRUNABLE_ANALYST_KEYS:
                payload.pop(key, None)
                continue
            payload[key] = _prune_analysis_dict(payload.get(key))
        return payload
    if isinstance(payload, list):
        return [_prune_analysis_dict(item) for item in payload]
    return payload


def _prune_level_payload(payload):
    """Remove bulky table fields before sending to the LLM (recursive)."""
    if isinstance(payload, dict):
        for key in list(payload.keys()):
            if key in _PRUNABLE_LEVEL_KEYS:
                payload.pop(key, None)
                continue
            payload[key] = _prune_level_payload(payload.get(key))
        return payload
    if isinstance(payload, list):
        return [_prune_level_payload(item) for item in payload]
    return payload


def _slim_narrative_payload(raw: str | dict | None) -> str:
    """Trim narrative_results to the essentials to reduce prompt size."""
    if not raw:
        return ""
    try:
        payload = json.loads(raw) if isinstance(raw, str) else dict(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return raw if isinstance(raw, str) else _compact_json(raw)

    cards = payload.get("insight_cards")
    if isinstance(cards, list) and cards:
        payload["insight_cards"] = [_slim_card(card) for card in cards[:_MAX_REPORT_NARRATIVE_CARDS]]

    actions = payload.get("recommended_actions")
    if isinstance(actions, list) and len(actions) > _MAX_REPORT_ACTIONS:
        payload["recommended_actions"] = actions[:_MAX_REPORT_ACTIONS]

    summary = payload.get("narrative_summary")
    if isinstance(summary, str) and len(summary) > 600:
        payload["narrative_summary"] = summary[:600].rstrip() + " …"

    return _compact_json(payload)


def _compact_contract_context(contract) -> dict[str, Any]:
    metadata = build_contract_metadata(contract)
    if not metadata:
        return {}
    metrics = [m.get("name") for m in metadata.get("metrics", []) if m.get("name")]
    primary_dims = [
        d.get("name")
        for d in metadata.get("dimensions", [])
        if (d.get("role") or "").lower() == "primary" and d.get("name")
    ]
    hierarchies = []
    for entry in metadata.get("hierarchies", [])[:2]:
        if not entry:
            continue
        hierarchies.append(
            {
                "name": entry.get("name"),
                "path": entry.get("children"),
                "level_names": entry.get("level_names"),
            }
        )
    return {
        "display_name": metadata.get("display_name"),
        "description": metadata.get("description"),
        "time": metadata.get("time"),
        "metrics": metrics,
        "primary_dimensions": primary_dims,
        "hierarchies": hierarchies,
        "materiality": metadata.get("materiality"),
        "capabilities": metadata.get("capabilities"),
    }



class ReportSynthesisWrapper(BaseAgent):
    """Wrapper to add debug logging for report synthesis agent."""
    
    def __init__(self, wrapped_agent):
        super().__init__(name="report_synthesis_agent")
        # Store agent in __dict__ to avoid Pydantic validation issues
        object.__setattr__(self, 'wrapped_agent', wrapped_agent)
    
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        from google.genai.types import Content, Part
        from google.adk.events.event import Event

        print(f"\n{'='*80}")
        print(f"[REPORT_SYNTHESIS] Starting report synthesis agent")
        print(f"{'='*80}\n")

        wrapped_agent = object.__getattribute__(self, "wrapped_agent")

        # --- CACHE LOAD: Use cached prompt if REPORT_SYNTHESIS_USE_PROMPT_CACHE is set ---
        cache_path = os.environ.get("REPORT_SYNTHESIS_USE_PROMPT_CACHE")
        tool_arguments = None

        if cache_path:
            if not os.path.isabs(cache_path):
                project_root = Path(__file__).resolve().parent.parent.parent.parent
                cache_path = str(project_root / cache_path)
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    cache = json.load(f)
                formatted_instruction = cache["instruction"]
                injection_message = cache["injection"]
                wrapped_agent.instruction = augment_instruction(formatted_instruction, ctx.session.state)
                print(f"[REPORT_SYNTHESIS] Loaded prompt from cache: {cache_path}")
                print(f"[REPORT_SYNTHESIS] Instruction: {len(formatted_instruction):,} chars, injection: {len(injection_message):,} chars")
            except Exception as e:
                print(f"[REPORT_SYNTHESIS] Cache load failed: {e}. Falling back to state collection.")
                cache_path = None  # Fall through to normal flow

        if not cache_path:
            # Dynamically build the instruction from the loaded DatasetContract so
            # that all dimension labels, hierarchy names, and dataset references come
            # from the contract config rather than being hardcoded in the prompt.
            contract = ctx.session.state.get("dataset_contract")
            formatted_instruction = build_report_instruction(contract)
            wrapped_agent.instruction = augment_instruction(formatted_instruction, ctx.session.state)
            if contract:
                print(f"[REPORT_SYNTHESIS] Instruction built from contract: {contract.name}")
            else:
                print("[REPORT_SYNTHESIS] WARNING: No contract in state. Using generic fallback instruction.")
            contract_context = _compact_contract_context(contract)

            # Collect results from session state and inject as a conversation message.
            # DynamicParallelAnalysisAgent stores results via state_delta only (no message
            # content), so they are in session state but not in conversation history.
            state = ctx.session.state

            # --- OPTIMIZATION: Truncate statistical_summary to reduce prompt bloat ---
            raw_stats = state.get("statistical_summary", "")
            statistical_summary = raw_stats
            if raw_stats:
                try:
                    stats_dict = json.loads(raw_stats) if isinstance(raw_stats, str) else raw_stats
                    # Keep only what's needed for synthesis
                    # Handle correlations as dict or list safely
                    raw_correlations = stats_dict.get("correlations") or {}
                    if isinstance(raw_correlations, dict):
                        correlations_list = list(raw_correlations.items())
                    else:
                        correlations_list = raw_correlations

                    # ENSURE temporal granularity fields are preserved in slim payload
                    summary_stats = stats_dict.get("summary_stats") or {}
                    temporal_grain = summary_stats.get("temporal_grain", "unknown")
                    period_unit = summary_stats.get("period_unit", "period")

                    slim_stats = {
                        "summary_stats": {
                            **summary_stats,
                            "temporal_grain": temporal_grain,
                            "period_unit": period_unit
                        },
                        "top_drivers": (stats_dict.get("enhanced_top_drivers") or stats_dict.get("top_drivers") or [])[:_MAX_STATS_TOP_DRIVERS],
                        "anomalies": (stats_dict.get("anomalies") or [])[:_MAX_STATS_ANOMALIES],
                        "correlations": correlations_list[:3],
                        "dq_flags": stats_dict.get("dq_flags"),
                        "metadata": {
                            **(stats_dict.get("metadata") or {}),
                            "temporal_grain": temporal_grain,
                            "period_unit": period_unit
                        }
                    }
                    statistical_summary = _compact_json(slim_stats)
                except (json.JSONDecodeError, TypeError):
                    pass

            raw_narrative = state.get("narrative_results") or state.get("narrative_result")
            if raw_narrative:
                narrative_results = _slim_narrative_payload(raw_narrative)
            else:
                narrative_results = "No narrative results available."
            raw_da_result = state.get("data_analyst_result") or ""
            data_analyst_result = raw_da_result

            # --- OPTIMIZATION: Remove bulky level_results/raw rows from data_analyst_result ---
            if raw_da_result:
                try:
                    da_dict = json.loads(raw_da_result)
                    da_dict = _prune_analysis_dict(da_dict)
                    data_analyst_result = _compact_json(da_dict)
                except (json.JSONDecodeError, TypeError):
                    pass

            # Trim the alert scoring result for synthesis:
            raw_alert_result = state.get("alert_scoring_result") or ""
            if raw_alert_result:
                try:
                    alert_dict = json.loads(raw_alert_result)
                    alert_dict.pop("all_scored_alerts", None)
                    top_alerts = alert_dict.get("top_alerts", [])
                    if len(top_alerts) > 10:
                        alert_dict["top_alerts"] = [_slim_alert(a) for a in top_alerts[:10]]
                        alert_dict["message"] = f"Showing top 10 of {len(top_alerts)} alerts"
                    else:
                        alert_dict["top_alerts"] = [_slim_alert(a) for a in top_alerts]
                    alert_scoring_result = _compact_json(alert_dict)
                except (json.JSONDecodeError, TypeError):
                    alert_scoring_result = raw_alert_result
            else:
                alert_scoring_result = "No alert scoring results available."

            # Collect hierarchical level analyses
            level_parts = []
            hierarchical_payload: dict[str, Any] = {}
            for lvl in hierarchy_level_range(state, contract):
                val = state.get(f"level_{lvl}_analysis")
                if not val:
                    continue
                parsed_level = None
                had_rows = False
                try:
                    lvl_dict = json.loads(val)
                    cards = lvl_dict.get("insight_cards", [])
                    # Slim and cap: only keep high-impact cards
                    if len(cards) > 3:
                        lvl_dict["insight_cards"] = [_slim_card(c) for c in cards[:3]]
                        lvl_dict["message"] = f"Showing top 3 of {len(cards)} hierarchical candidates"
                    else:
                        lvl_dict["insight_cards"] = [_slim_card(c) for c in cards]
                    had_rows = bool(lvl_dict.get("level_results"))
                    lvl_dict = _prune_level_payload(lvl_dict)
                    parsed_level = lvl_dict
                    val = _compact_json(lvl_dict)
                except (json.JSONDecodeError, TypeError):
                    parsed_level = None
                if parsed_level:
                    has_cards = bool(parsed_level.get("insight_cards"))
                    if not (has_cards or had_rows):
                        continue
                level_parts.append(f"HIERARCHICAL_LEVEL_{lvl}:\n{val}")
                entry_key = f"level_{lvl}"
                hierarchical_payload[entry_key] = parsed_level if parsed_level else _loads_or_passthrough(val)
            hierarchical_text = "\n\n".join(level_parts) if level_parts else "No hierarchical analysis results available."

            # Collect independent flat-scan findings (only present when INDEPENDENT_LEVEL_ANALYSIS=true)
            independent_parts = []
            independent_payload: dict[str, Any] = {}
            for lvl in independent_level_range(state, contract):
                val = state.get(f"independent_level_{lvl}_analysis")
                if not val:
                    continue
                parsed_independent = None
                try:
                    lvl_dict = json.loads(val)
                    cards = lvl_dict.get("insight_cards", [])
                    # Slim and cap: only keep high-impact net-new cards
                    if len(cards) > 2:
                        lvl_dict["insight_cards"] = [_slim_card(c) for c in cards[:2]]
                        lvl_dict["message"] = f"Showing top 2 of {len(cards)} independent scans"
                    else:
                        lvl_dict["insight_cards"] = [_slim_card(c) for c in cards]
                    lvl_dict = _prune_level_payload(lvl_dict)
                    parsed_independent = lvl_dict
                    val = _compact_json(lvl_dict)
                except (json.JSONDecodeError, TypeError):
                    parsed_independent = None
                if parsed_independent:
                    has_cards = bool(parsed_independent.get("insight_cards"))
                    if not has_cards:
                        continue
                independent_parts.append(f"INDEPENDENT_LEVEL_{lvl}:\n{val}")
                entry_key = f"level_{lvl}"
                independent_payload[entry_key] = parsed_independent if parsed_independent else _loads_or_passthrough(val)
            independent_findings_text = "\n\n".join(independent_parts) if independent_parts else ""

            # --- TEMPORAL CONTEXT: Mandatory grain and period anchoring ---
            # --- FOCUS CONTEXT: Capture analysis directives ---
            focus_payload = build_focus_payload(state)

            # --- TEMPORAL CONTEXT: Mandatory grain and period anchoring ---
            temporal_grain = state.get("temporal_grain", "unknown")
            period_end = state.get("primary_query_end_date")
            timeframe = state.get("timeframe", {})
            analysis_period_val = state.get("analysis_period")
            if not analysis_period_val:
                analysis_period_val = f"the period ending {period_end}" if period_end else "the period ending"
            
            canonical_grain = normalize_temporal_grain(temporal_grain)
            temporal_context = {
                "temporal_grain": canonical_grain,
                "period_unit": temporal_grain_to_period_unit(canonical_grain),
                "analysis_period": analysis_period_val,
                "reference_period_end": period_end,
                "timeframe": timeframe
            }

            # --- PRE-SUMMARIZE: Optionally reduce each component via fast LLM ---
            if parse_bool_env(os.environ.get("REPORT_SYNTHESIS_PRE_SUMMARIZE")):
                from .pre_summarize import summarize_components
                components_raw = {
                    "temporal_context": _compact_json(temporal_context),
                    "narrative_results": narrative_results,
                    "data_analyst_result": data_analyst_result,
                    "hierarchical_text": hierarchical_text,
                    "alert_scoring_result": alert_scoring_result,
                    "statistical_summary": statistical_summary,
                }
                summarized = await summarize_components(components_raw)
                temporal_context_str = summarized.get("temporal_context") or _compact_json(temporal_context)
                narrative_results = summarized.get("narrative_results", narrative_results)
                data_analyst_result = summarized.get("data_analyst_result", data_analyst_result)
                alert_scoring_result = summarized.get("alert_scoring_result", alert_scoring_result)
                statistical_summary = summarized.get("statistical_summary", statistical_summary)
                # Preserve canonical hierarchical/independent payload structure for downstream tooling.
                summarized_hier = summarized.get("hierarchical_text")
                if summarized_hier and "HIERARCHICAL_LEVEL_" in summarized_hier:
                    hierarchical_text = summarized_hier
                summarized_independent = summarized.get("independent_findings")
                if summarized_independent and "INDEPENDENT_LEVEL_" in summarized_independent:
                    independent_findings_text = summarized_independent
                print("[REPORT_SYNTHESIS] Pre-summarized components via fast LLM")
            else:
                temporal_context_str = _compact_json(temporal_context)

            narrative_results = _truncate_block(narrative_results, _MAX_NARRATIVE_CHARS, "narrative_results")
            data_analyst_result = _truncate_block(data_analyst_result, _MAX_DATA_ANALYST_CHARS, "data_analyst_result")
            hierarchical_text = _truncate_block(hierarchical_text, _MAX_HIERARCHICAL_CHARS, "hierarchical_analysis")
            independent_findings_text = _truncate_block(independent_findings_text, _MAX_INDEPENDENT_CHARS, "independent_findings")
            alert_scoring_result = _truncate_block(alert_scoring_result, _MAX_ALERT_CHARS, "alert_scoring_result")
            statistical_summary = _truncate_block(statistical_summary, _MAX_STAT_SUMMARY_CHARS, "statistical_summary")

            # Log prompt component sizes for diagnostics
            print(f"[REPORT_SYNTHESIS] Prompt component sizes:")
            print(f"  temporal_context: {len(temporal_context_str):,} chars")
            print(f"  narrative_results: {len(str(narrative_results)):,} chars")
            print(f"  data_analyst_result: {len(str(data_analyst_result)):,} chars")
            print(f"  hierarchical_text: {len(str(hierarchical_text)):,} chars")
            print(f"  independent_findings: {len(independent_findings_text):,} chars")
            print(f"  alert_scoring_result: {len(str(alert_scoring_result)):,} chars")
            print(f"  statistical_summary: {len(str(statistical_summary)):,} chars")

            narrative_component = _loads_or_passthrough(narrative_results)
            data_analyst_component = _loads_or_passthrough(data_analyst_result)
            alert_component = _loads_or_passthrough(alert_scoring_result)
            stats_component = _loads_or_passthrough(statistical_summary)

            dataset_display_name = (
                contract_context.get("display_name")
                or getattr(contract, "display_name", None)
                or getattr(contract, "name", None)
            )
            dataset_description = contract_context.get("description")
            if not dataset_description and getattr(contract, "description", None):
                dataset_description = contract.description

            presentation_unit = None
            if contract and getattr(contract, "presentation", None):
                try:
                    presentation_unit = (contract.presentation or {}).get("unit")
                except AttributeError:
                    presentation_unit = None

            analysis_target_value = state.get("current_analysis_target") or ctx.session.state.get("analysis_target")
            report_payload = {
                "dataset_context": contract_context,
                "dataset_display_name": dataset_display_name,
                "dataset_description": dataset_description,
                "analysis_target": analysis_target_value,
                "focus": focus_payload,
                "temporal_context": temporal_context,
                "components": {
                    "narrative_results": narrative_component,
                    "data_analyst_result": data_analyst_component,
                    "hierarchical_analysis": hierarchical_payload,
                    "independent_findings": independent_payload,
                    "alert_scoring_result": alert_component,
                    "statistical_summary": stats_component,
                },
                "tool_contract": {
                    "tool": "generate_markdown_report",
                    "call_once": True,
                    "required_arguments": [
                        "temporal_context",
                        "analysis_target",
                        "narrative_results",
                        "statistical_summary",
                        "hierarchical_analysis",
                        "independent_findings",
                        "alert_scoring_result",
                        "dataset_display_name",
                        "dataset_description",
                    ],
                    "output_format": "markdown",
                    "no_raw_markdown": True,
                },
            }

            def _json_arg(value):
                if value in (None, ""):
                    return ""
                if isinstance(value, str):
                    return value
                try:
                    return json.dumps(value, separators=(',', ':'), ensure_ascii=False)
                except TypeError:
                    return str(value)

            tool_arguments = {
                "hierarchical_results": _json_arg(hierarchical_payload),
                "analysis_target": analysis_target_value,
                "analysis_period": temporal_context.get("analysis_period"),
                "statistical_summary": _json_arg(stats_component),
                "narrative_results": _json_arg(narrative_component),
                "target_label": state.get("target_label") or "Metric",
                "anomaly_indicators": _json_arg(alert_component),
                "dataset_display_name": dataset_display_name,
                "dataset_description": dataset_description or "",
                "presentation_unit": presentation_unit,
            }

            plan_hint = _deterministic_plan_hint(ctx.session.state.get("execution_plan"))
            contract_has_hierarchy = _contract_has_hierarchy(contract)

            payload_json = json.dumps(report_payload, separators=(',', ':'), ensure_ascii=False)
            injection_message = (
                "REPORT_SYNTHESIS_INPUT_JSON (strict JSON — do not change keys):\n"
                f"{payload_json}\n"
                "Use this JSON to decide on a single generate_markdown_report tool call."
            )
            print(f"  TOTAL payload: {len(payload_json):,} chars")

            # DEBUG: Save prompt to txt and JSON cache for optimization/benchmarking
            try:
                debug_dir = Path(__file__).resolve().parent.parent.parent.parent / "outputs" / "debug"
                debug_dir.mkdir(parents=True, exist_ok=True)
                txt_path = debug_dir / "report_synthesis_prompt.txt"
                with open(txt_path, "w", encoding="utf-8") as f:
                    f.write(f"--- INSTRUCTION ---\n{formatted_instruction}\n\n")
                    f.write(f"--- INJECTION ---\n{injection_message}\n")
                print(f"[REPORT_SYNTHESIS] DEBUG: Saved prompt to {txt_path}")

                components = {
                    "narrative_results": narrative_results,
                    "data_analyst_result": data_analyst_result,
                    "hierarchical_text": hierarchical_text,
                    "alert_scoring_result": alert_scoring_result,
                    "statistical_summary": statistical_summary,
                }
                char_counts = {k: len(str(v)) for k, v in components.items()}
                cache_data = {
                    "instruction": formatted_instruction,
                    "injection": injection_message,
                    "components": components,
                    "meta": {
                        "dataset": contract.name if contract else None,
                        "saved_at": datetime.now(timezone.utc).isoformat(),
                        "char_counts": char_counts,
                    },
                }
                cache_path_out = debug_dir / "report_synthesis_cache.json"
                with open(cache_path_out, "w", encoding="utf-8") as f:
                    json.dump(cache_data, f, indent=2)
                print(f"[REPORT_SYNTHESIS] DEBUG: Saved cache to {cache_path_out}")
            except Exception as e:
                print(f"[REPORT_SYNTHESIS] DEBUG ERROR: Failed to save prompt: {e}")

        fast_path_reason = None
        if tool_arguments:
            force_direct = parse_bool_env(os.environ.get("REPORT_SYNTHESIS_FORCE_DIRECT_TOOL"))
            has_hierarchy_signal = _has_hierarchical_signal(hierarchical_payload, hierarchical_text)
            if force_direct:
                fast_path_reason = "REPORT_SYNTHESIS_FORCE_DIRECT_TOOL=1"
            elif not has_hierarchy_signal:
                if plan_hint:
                    fast_path_reason = f"{plan_hint}; no hierarchical payload detected"
                elif not contract_has_hierarchy:
                    fast_path_reason = "no hierarchical payload expected"
                else:
                    fast_path_reason = "no hierarchical payload detected"

        if fast_path_reason and tool_arguments:
            print(f"[REPORT_SYNTHESIS] Fast-path triggered ({fast_path_reason}); calling generate_markdown_report directly.", flush=True)
            try:
                direct_markdown = await generate_markdown_report(**tool_arguments)
            except Exception as fast_exc:
                print(f"[REPORT_SYNTHESIS] Fast-path failed: {fast_exc}; continuing with LLM path.", flush=True)
            else:
                ctx.session.state["report_markdown"] = direct_markdown
                ctx.session.state["report_synthesis_result"] = direct_markdown
                yield Event(
                    invocation_id=ctx.invocation_id,
                    author=self.name,
                    actions=EventActions(state_delta={"report_markdown": direct_markdown, "report_synthesis_result": direct_markdown}),
                )
                print("[REPORT_SYNTHESIS] Fast-path completed; skipping LLM agent.", flush=True)
                return

        ctx.session.events.append(Event(
            invocation_id="result_injection",
            author="user",
            content=Content(role="user", parts=[Part(text=injection_message)])
        ))

        import asyncio

        # Use a timeout for the LLM call to prevent infinite hangs.
        # We yield events as they come to allow streaming progress to the user.
        timeout_s = 300.0
        start_time = asyncio.get_event_loop().time()
        
        print(f"[REPORT_SYNTHESIS] Calling LLM agent (timeout={timeout_s}s)...", flush=True)
        
        event_count = 0
        tool_call_count = 0
        try:
            max_tool_calls = 1
            try:
                max_tool_calls = max(1, int(os.environ.get("REPORT_SYNTHESIS_MAX_TOOL_CALLS", "1")))
            except (ValueError, TypeError):
                pass

            gen = wrapped_agent.run_async(ctx)
            
            while True:
                remaining = timeout_s - (asyncio.get_event_loop().time() - start_time)
                if remaining <= 0:
                    raise asyncio.TimeoutError()
                
                try:
                    event = await asyncio.wait_for(gen.__anext__(), timeout=remaining)
                    event_count += 1
                    yield event

                    # Compatibility: ensure markdown lands in session state.
                    try:
                        delta = getattr(getattr(event, "actions", None), "state_delta", None)
                        if isinstance(delta, dict) and delta.get("report_synthesis_result") and not ctx.session.state.get("report_markdown"):
                            yield Event(
                                invocation_id=ctx.invocation_id,
                                author=self.name,
                                actions=EventActions(state_delta={"report_markdown": delta["report_synthesis_result"]}),
                            )

                        if not ctx.session.state.get("report_markdown") and event.content and getattr(event.content, "parts", None):
                            for part in event.content.parts:
                                txt = getattr(part, "text", None)
                                if txt:
                                    yield Event(
                                        invocation_id=ctx.invocation_id,
                                        author=self.name,
                                        actions=EventActions(state_delta={"report_markdown": txt}),
                                    )
                                    break
                    except Exception:
                        pass

                    # Cap tool calls: stop after first successful generate_markdown_report result
                    stop_early = False
                    if event.content and event.content.parts:
                        for part in event.content.parts:
                            if getattr(part, "function_response", None):
                                name = getattr(part.function_response, "name", "") or ""
                                if name == "generate_markdown_report":
                                    tool_call_count += 1
                                    if tool_call_count >= max_tool_calls:
                                        print(f"[REPORT_SYNTHESIS] Reached max tool calls ({max_tool_calls}), stopping.", flush=True)
                                        stop_early = True
                                        break
                    if stop_early:
                        break
                except StopAsyncIteration:
                    break
                    
        except asyncio.TimeoutError:
            print(f"[REPORT_SYNTHESIS] TIMEOUT: LLM agent exceeded {timeout_s:.0f}s total execution time. "
                  "Proceeding with whatever state is available.", flush=True)
        except Exception as e:
            import traceback
            print(f"[REPORT_SYNTHESIS] ERROR: {str(e) or type(e).__name__}", flush=True)
            traceback.print_exc()

        report_output = ctx.session.state.get("report_markdown") or ctx.session.state.get("report_synthesis_result")
        fallback_reason = None
        if not report_output:
            fallback_reason = "missing LLM output"
        elif contains_stub_content(report_output) and not stub_outputs_allowed():
            fallback_reason = "stub output detected"
        elif isinstance(report_output, str) and report_output.lstrip().startswith("# Error"):
            fallback_reason = "LLM returned error payload"

        if fallback_reason and tool_arguments:
            print(f"[REPORT_SYNTHESIS] Fallback triggered ({fallback_reason}); calling generate_markdown_report directly.", flush=True)
            try:
                fallback_markdown = await generate_markdown_report(**tool_arguments)
                ctx.session.state["report_markdown"] = fallback_markdown
                ctx.session.state["report_synthesis_result"] = fallback_markdown
                yield Event(
                    invocation_id=ctx.invocation_id,
                    author=self.name,
                    actions=EventActions(state_delta={"report_markdown": fallback_markdown, "report_synthesis_result": fallback_markdown}),
                )
            except Exception as fallback_exc:
                print(f"[REPORT_SYNTHESIS] Fallback failed: {fallback_exc}", flush=True)

        print(f"\n{'='*80}")
        print(f"[REPORT_SYNTHESIS] Report synthesis agent complete ({event_count} events)", flush=True)
        print(f"{'='*80}\n", flush=True)


def create_report_synthesis_agent(model: str | None = None, thinking_budget: int | None = None):
    """Create a fresh instance of the report synthesis agent to avoid race conditions.

    Args:
        model: Optional model override (e.g. for benchmarking). When provided, uses this
            model and infers thinking config from model name. Otherwise uses config.
        thinking_budget: Optional thinking token budget when model supports it (e.g. 8192).
            Used only when model is overridden; ignored otherwise.
    """
    if model is not None:
        thinking_config = _get_thinking_config_for_model(model, thinking_budget=thinking_budget)
        agent_model = model
    else:
        agent_model = get_agent_model("report_synthesis_agent")
        thinking_config = get_agent_thinking_config("report_synthesis_agent")

    base = Agent(
        model=agent_model,
        name="report_synthesis_agent",
        description="Synthesizes results from all parallel analysis agents into a structured executive report using 3-level framework.",
        instruction=REPORT_SYNTHESIS_AGENT_INSTRUCTION,
        output_key="report_synthesis_result",
        tools=[generate_markdown_report],
        generate_content_config=types.GenerateContentConfig(
            response_modalities=["TEXT"],
            temperature=0.2,
            max_output_tokens=4096,
            thinking_config=thinking_config,
        ),
    )
    return ReportSynthesisWrapper(base)


# Export root_agent for backward compatibility
root_agent = create_report_synthesis_agent()

