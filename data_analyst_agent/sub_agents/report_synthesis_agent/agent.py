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
from typing import AsyncGenerator

from google.adk import Agent
from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.genai import types

from config.model_loader import get_agent_model, get_agent_thinking_config
from .prompt import REPORT_SYNTHESIS_AGENT_INSTRUCTION, build_report_instruction
from .tools import generate_markdown_report
from ...utils import parse_bool_env


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

    return {
        "item": alert.get("item_name") or alert.get("dimension_value") or alert.get("gl_code") or alert.get("item_id", "Unknown"),
        "period": alert.get("period", ""),
        "category": alert.get("category", ""),
        "priority": alert.get("priority", ""),
        "variance_pct": alert.get("variance_pct"),
        "variance_amount": alert.get("variance_amount"),
        "description": details.get("description", ""),
        "signals": triggered,
    }


def _safe_int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


_MAX_REPORT_NARRATIVE_CARDS = _safe_int_env("REPORT_SYNTHESIS_MAX_NARRATIVE_CARDS", 5)
_MAX_REPORT_ACTIONS = _safe_int_env("REPORT_SYNTHESIS_MAX_ACTIONS", 3)
_MAX_STATS_TOP_DRIVERS = _safe_int_env("REPORT_SYNTHESIS_MAX_STATS_DRIVERS", 8)
_MAX_STATS_ANOMALIES = _safe_int_env("REPORT_SYNTHESIS_MAX_STATS_ANOMALIES", 5)


def _slim_narrative_payload(raw: str | dict | None) -> str:
    """Trim narrative_results to the essentials to reduce prompt size."""
    if not raw:
        return ""
    try:
        payload = json.loads(raw) if isinstance(raw, str) else dict(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return raw if isinstance(raw, str) else json.dumps(raw, indent=2)

    cards = payload.get("insight_cards")
    if isinstance(cards, list) and cards:
        payload["insight_cards"] = [_slim_card(card) for card in cards[:_MAX_REPORT_NARRATIVE_CARDS]]

    actions = payload.get("recommended_actions")
    if isinstance(actions, list) and len(actions) > _MAX_REPORT_ACTIONS:
        payload["recommended_actions"] = actions[:_MAX_REPORT_ACTIONS]

    summary = payload.get("narrative_summary")
    if isinstance(summary, str) and len(summary) > 600:
        payload["narrative_summary"] = summary[:600].rstrip() + " …"

    return json.dumps(payload, indent=2)


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
        if cache_path:
            if not os.path.isabs(cache_path):
                project_root = Path(__file__).resolve().parent.parent.parent.parent
                cache_path = str(project_root / cache_path)
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    cache = json.load(f)
                formatted_instruction = cache["instruction"]
                injection_message = cache["injection"]
                wrapped_agent.instruction = formatted_instruction
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
            wrapped_agent.instruction = formatted_instruction
            if contract:
                print(f"[REPORT_SYNTHESIS] Instruction built from contract: {contract.name}")
            else:
                print("[REPORT_SYNTHESIS] WARNING: No contract in state. Using generic fallback instruction.")

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
                    statistical_summary = json.dumps(slim_stats, indent=2)
                except (json.JSONDecodeError, TypeError):
                    pass

            raw_narrative = state.get("narrative_results") or state.get("narrative_result")
            if raw_narrative:
                narrative_results = _slim_narrative_payload(raw_narrative)
            else:
                narrative_results = "No narrative results available."
            raw_da_result = state.get("data_analyst_result") or ""
            data_analyst_result = raw_da_result

            # --- OPTIMIZATION: Remove redundant level_results from data_analyst_result ---
            if raw_da_result:
                try:
                    da_dict = json.loads(raw_da_result)
                    da_dict.pop("level_results", None)  # Redundant with HIERARCHICAL_ANALYSIS
                    data_analyst_result = json.dumps(da_dict, indent=2)
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
                    alert_scoring_result = json.dumps(alert_dict, indent=2)
                except (json.JSONDecodeError, TypeError):
                    alert_scoring_result = raw_alert_result
            else:
                alert_scoring_result = "No alert scoring results available."

            # Collect hierarchical level analyses
            level_parts = []
            for lvl in range(6):
                val = state.get(f"level_{lvl}_analysis")
                if val:
                    try:
                        lvl_dict = json.loads(val)
                        cards = lvl_dict.get("insight_cards", [])
                        # Slim and cap: only keep high-impact cards
                        if len(cards) > 3:
                            lvl_dict["insight_cards"] = [_slim_card(c) for c in cards[:3]]
                            lvl_dict["message"] = f"Showing top 3 of {len(cards)} hierarchical candidates"
                        else:
                            lvl_dict["insight_cards"] = [_slim_card(c) for c in cards]
                        val = json.dumps(lvl_dict, indent=2)
                    except (json.JSONDecodeError, TypeError):
                        pass
                    level_parts.append(f"HIERARCHICAL_LEVEL_{lvl}:\n{val}")
            hierarchical_text = "\n\n".join(level_parts) if level_parts else "No hierarchical analysis results available."

            # Collect independent flat-scan findings (only present when INDEPENDENT_LEVEL_ANALYSIS=true)
            independent_parts = []
            for lvl in range(1, 6):
                val = state.get(f"independent_level_{lvl}_analysis")
                if val:
                    try:
                        lvl_dict = json.loads(val)
                        cards = lvl_dict.get("insight_cards", [])
                        # Slim and cap: only keep high-impact net-new cards
                        if len(cards) > 2:
                            lvl_dict["insight_cards"] = [_slim_card(c) for c in cards[:2]]
                            lvl_dict["message"] = f"Showing top 2 of {len(cards)} independent scans"
                        else:
                            lvl_dict["insight_cards"] = [_slim_card(c) for c in cards]
                        val = json.dumps(lvl_dict, indent=2)
                    except (json.JSONDecodeError, TypeError):
                        pass
                    independent_parts.append(f"INDEPENDENT_LEVEL_{lvl}:\n{val}")
            independent_findings_text = "\n\n".join(independent_parts) if independent_parts else ""

            # --- TEMPORAL CONTEXT: Mandatory grain and period anchoring ---
            temporal_grain = state.get("temporal_grain", "unknown")
            period_end = state.get("primary_query_end_date")
            timeframe = state.get("timeframe", {})
            analysis_period_val = state.get("analysis_period", "the period ending")
            
            temporal_context = {
                "temporal_grain": temporal_grain,
                "period_unit": "week" if temporal_grain == "weekly" else "month",
                "analysis_period": f"{analysis_period_val} {period_end}" if period_end else analysis_period_val,
                "reference_period_end": period_end,
                "timeframe": timeframe
            }

            # --- PRE-SUMMARIZE: Optionally reduce each component via fast LLM ---
            if parse_bool_env(os.environ.get("REPORT_SYNTHESIS_PRE_SUMMARIZE")):
                from .pre_summarize import summarize_components
                components_raw = {
                    "temporal_context": json.dumps(temporal_context, indent=2),
                    "narrative_results": narrative_results,
                    "data_analyst_result": data_analyst_result,
                    "hierarchical_text": hierarchical_text,
                    "alert_scoring_result": alert_scoring_result,
                    "statistical_summary": statistical_summary,
                }
                summarized = await summarize_components(components_raw)
                temporal_context_str = summarized.get("temporal_context") or json.dumps(temporal_context, indent=2)
                narrative_results = summarized["narrative_results"]
                data_analyst_result = summarized["data_analyst_result"]
                hierarchical_text = summarized["hierarchical_text"]
                alert_scoring_result = summarized["alert_scoring_result"]
                statistical_summary = summarized["statistical_summary"]
                print("[REPORT_SYNTHESIS] Pre-summarized components via fast LLM")
            else:
                temporal_context_str = json.dumps(temporal_context, indent=2)

            # Log prompt component sizes for diagnostics
            print(f"[REPORT_SYNTHESIS] Prompt component sizes:")
            print(f"  temporal_context: {len(temporal_context_str):,} chars")
            print(f"  narrative_results: {len(str(narrative_results)):,} chars")
            print(f"  data_analyst_result: {len(str(data_analyst_result)):,} chars")
            print(f"  hierarchical_text: {len(str(hierarchical_text)):,} chars")
            print(f"  independent_findings: {len(independent_findings_text):,} chars")
            print(f"  alert_scoring_result: {len(str(alert_scoring_result)):,} chars")
            print(f"  statistical_summary: {len(str(statistical_summary)):,} chars")

            # Build canonical format guidance for consistent tool inputs
            canonical_format = (
                "\n**CANONICAL FORMAT for generate_markdown_report:**\n"
                "Pass parameters in one call. hierarchical_results: JSON with level_0, level_1, etc., "
                "AND independent_level_results if present in INDEPENDENT_LEVEL_FINDINGS. "
                "Each level has insight_cards array and total_variance_dollar. narrative_results: from NARRATIVE_RESULTS as-is. "
                "statistical_summary: PASS THE FULL JSON BLOCK from STATISTICAL_SUMMARY context unchanged. "
                "analysis_target and analysis_period: Use exact values provided in TEMPORAL_CONTEXT.\n"
            )
            
            independent_section = (
                f"\n\nindependent_findings (anomalies masked at higher levels, net-new):\n{independent_findings_text}"
                if independent_findings_text else ""
            )
            injection_message = (
                "Here are the results from the specialized analysis agents:\n\n"
                f"TEMPORAL_CONTEXT:\n{temporal_context_str}\n\n"
                f"NARRATIVE_RESULTS:\n{narrative_results}\n\n"
                f"DATA_ANALYST_RESULT (Statistical Insight Cards):\n{data_analyst_result}\n\n"
                f"hierarchical_analysis:\n{hierarchical_text}"
                f"{independent_section}\n\n"
                f"ALERT_SCORING_RESULT:\n{alert_scoring_result}\n\n"
                f"STATISTICAL_SUMMARY (Full Data Context):\n{statistical_summary}\n\n"
                "Synthesize these into the final executive report. "
                "Call generate_markdown_report EXACTLY ONCE with all parameters. Do NOT call the tool again. "
                "Do NOT output report text directly." + canonical_format
            )

            print(f"  TOTAL injection: {len(injection_message):,} chars")

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
            thinking_config=thinking_config,
        ),
    )
    return ReportSynthesisWrapper(base)


# Export root_agent for backward compatibility
root_agent = create_report_synthesis_agent()

