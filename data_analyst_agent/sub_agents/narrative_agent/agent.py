import json
import os
from pathlib import Path
from typing import Any, AsyncGenerator
from google.adk.agents.llm_agent import Agent
from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.genai import types
from google.genai.types import Content, Part
from .prompt import NARRATIVE_AGENT_INSTRUCTION
from config.model_loader import get_agent_model, get_agent_thinking_config
from ...utils.contract_summary import build_contract_metadata
from ...utils.focus_directives import augment_instruction, focus_lines
from ...utils.hierarchy_levels import hierarchy_level_range, independent_level_range


def _safe_int_env(var: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(var, default)))
    except (TypeError, ValueError):
        return default


MAX_NARRATIVE_TOP_DRIVERS = _safe_int_env("NARRATIVE_MAX_TOP_DRIVERS", 3)
MAX_NARRATIVE_ANOMALIES = _safe_int_env("NARRATIVE_MAX_ANOMALIES", 3)
MAX_NARRATIVE_HIERARCHY_CARDS = _safe_int_env("NARRATIVE_MAX_HIERARCHY_CARDS", 2)
MAX_NARRATIVE_INDEPENDENT_CARDS = _safe_int_env("NARRATIVE_MAX_INDEPENDENT_CARDS", 1)
MAX_NARRATIVE_ANALYST_CHARS = _safe_int_env("NARRATIVE_MAX_ANALYST_CHARS", 3200)
MAX_NARRATIVE_STATS_CHARS = _safe_int_env("NARRATIVE_MAX_STATS_CHARS", 2100)
MAX_NARRATIVE_HIERARCHY_CHARS = _safe_int_env("NARRATIVE_MAX_HIER_CHARS", 2000)
MAX_NARRATIVE_INDEPENDENT_CHARS = _safe_int_env("NARRATIVE_MAX_INDEPENDENT_CHARS", 1200)


def _truncate_text(block: str | None, max_chars: int, label: str) -> str:
    if not block:
        return block or ""
    text = str(block)
    if len(text) <= max_chars:
        return text
    suffix = f" … [truncated {label} to {max_chars} chars]"
    keep = max(0, max_chars - len(suffix))
    return text[:keep].rstrip() + suffix


_PRUNABLE_ANALYSIS_KEYS = {
    "level_results",
    "entity_rows",
    "child_rows",
    "raw_rows",
    "raw_children",
    "level_summary",
    "level_summary_table",
    "dimension_rows",
    "dimension_results",
    "entity_rankings",
    "detail_rows",
    "records",
}


def _prune_analysis_payload(payload: dict) -> dict:
    """Drop bulky table fields that overwhelm prompt budgets."""
    if not isinstance(payload, dict):
        return payload
    for key in list(payload.keys()):
        if key in _PRUNABLE_ANALYSIS_KEYS:
            payload.pop(key, None)
    return payload



def _slim_insight_cards(cards, limit: int):
    trimmed = []
    for card in cards or []:
        if not isinstance(card, dict):
            continue
        evidence = card.get("evidence") or {}
        trimmed.append(
            {
                "title": card.get("title") or card.get("item") or "",
                "what_changed": card.get("what_changed") or card.get("summary") or "",
                "why": card.get("why") or "",
                "priority": card.get("priority") or "",
                "variance_dollar": evidence.get("variance_dollar", card.get("variance_dollar")),
                "variance_pct": evidence.get("variance_pct", card.get("variance_pct")),
            }
        )
    return trimmed[:limit]


def _compress_analysis_block(raw_value, limit: int) -> str:
    if not raw_value:
        return ""
    try:
        payload = json.loads(raw_value) if isinstance(raw_value, str) else dict(raw_value)
    except (json.JSONDecodeError, TypeError, ValueError):
        return raw_value
    cards = payload.get("insight_cards")
    payload["insight_cards"] = _slim_insight_cards(cards, limit)
    payload = _prune_analysis_payload(payload)
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def _loads_or_passthrough(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError, ValueError):
            return value
    return value


def _json_payload_or_note(raw: str | None, max_chars: int, label: str, preview_len: int = 320) -> Any:
    if not raw:
        return ""
    if len(raw) <= max_chars:
        return _loads_or_passthrough(raw)
    note = {"warning": f"{label} payload exceeded {max_chars} chars; truncated for prompt budget."}
    if raw:
        note["preview"] = raw[:preview_len]
    return note


_base_agent = Agent(
    model=get_agent_model("narrative_agent"),
    name="narrative_agent",
    description="Transforms raw analytical findings into semantic Insight Cards with root-cause classification.",
    instruction=NARRATIVE_AGENT_INSTRUCTION,
    output_key="narrative_results",
    generate_content_config=types.GenerateContentConfig(
        response_mime_type="application/json",
        temperature=0.0,
        thinking_config=get_agent_thinking_config("narrative_agent"),
    ),
)

class NarrativeWrapper(BaseAgent):
    """LLM-powered agent that transforms raw analytical findings into semantic Insight Cards.
    
    This agent is the final synthesis stage of the analysis pipeline. It receives
    structured results from statistical and hierarchy analysis agents and generates
    human-readable narrative summaries with root-cause classification.
    
    Responsibilities:
        - Rank and filter insights by materiality (dollar impact × percentage × share)
        - Classify root causes (price, volume, mix, seasonality, other)
        - Generate executive summaries (≤35 words)
        - Populate evidence fields (metric, baseline, period, delta, p-value)
        - Assign priority (critical/high/medium/low)
        - Tag insights with relevant categories
    
    Output Schema:
        insight_cards: List of cards with:
            - title: Concise headline (e.g., "Retail LOB drove 60% of revenue growth")
            - what_changed: Factual change description (≤28 words)
            - why: Root cause explanation (≤28 words)
            - evidence: Structured data (metric, baseline, delta, share, p-value)
            - priority: critical|high|medium|low
            - root_cause: price|volume|mix|seasonality|other
            - tags: List of relevant tags
        narrative_summary: One-sentence executive summary (≤35 words)
    
    Context Inputs (from session state):
        statistical_summary: Statistical insights tool output
        hierarchy_results: Hierarchy variance tool output
        independent_dimension_results: Independent dimension analysis
        analyst_results: Planner/ML analysis results
        dataset_contract: Contract metadata
        analysis_focus: Focus directives
        custom_focus: Custom user focus text
        temporal_grain: Monthly/weekly/daily
        analysis_period: Period being analyzed
    
    Model Configuration:
        - Uses Gemini 2.0 Flash (or configured narrative_agent model)
        - Temperature: 0.0 (deterministic)
        - Response format: JSON
        - Thinking mode: Configurable via get_agent_thinking_config
    
    Token Budget Management:
        - Truncates statistical_summary to MAX_NARRATIVE_STATS_CHARS (2100)
        - Truncates hierarchy_results to MAX_NARRATIVE_HIERARCHY_CHARS (2000)
        - Truncates independent_dimension_results to MAX_NARRATIVE_INDEPENDENT_CHARS (1200)
        - Limits top drivers to MAX_NARRATIVE_TOP_DRIVERS (3)
        - Limits anomalies to MAX_NARRATIVE_ANOMALIES (3)
        - Limits hierarchy cards to MAX_NARRATIVE_HIERARCHY_CARDS (2)
        - Prunes bulky table fields (level_results, entity_rows, raw_rows, etc.)
    
    Example:
        >>> # After statistical and hierarchy analysis:
        >>> narrative_results = ctx.session.state["narrative_results"]
        >>> cards = narrative_results["insight_cards"]
        >>> print(cards[0])
        >>> # {
        >>> #   "title": "Retail LOB drove 60% of revenue growth",
        >>> #   "what_changed": "Retail revenue increased $1.2M (+8.5% YoY)",
        >>> #   "why": "Strong same-store sales growth in Q4 holiday season",
        >>> #   "evidence": {
        >>> #     "metric": "revenue",
        >>> #     "baseline": "YoY",
        >>> #     "delta_abs": 1200000,
        >>> #     "delta_pct": 8.5,
        >>> #     "share_of_total": 60.0
        >>> #   },
        >>> #   "priority": "critical",
        >>> #   "root_cause": "volume"
        >>> # }
    
    Note:
        - Uses NarrativeWrapper to dynamically inject contract metadata into prompt
        - Respects materiality thresholds from contract (variance_pct, variance_absolute)
        - Filters out low-materiality insights (<10% share unless explaining >60% variance)
        - Flags partial periods explicitly
        - Only uses contract-defined metric/dimension names
        - Sets signal="statistically_confirmed" only if p < 0.05
    """
    
    def __init__(self, wrapped_agent):
        output_key = getattr(wrapped_agent, "output_key", None) or "narrative_results"
        description = getattr(wrapped_agent, "description", "")
        super().__init__(name="narrative_agent")
        object.__setattr__(self, 'wrapped_agent', wrapped_agent)
        object.__setattr__(self, '_wrapped_output_key', output_key)
        object.__setattr__(self, '_wrapped_description', description)
        object.__setattr__(self, 'output_key', output_key)
        object.__setattr__(self, 'description', description)
    
    def __getattr__(self, name: str):
        if name == "output_key":
            return getattr(self, "_wrapped_output_key", None)
        if name == "description":
            return getattr(self, "_wrapped_description", "")
        return super().__getattr__(name)
    
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        focus_lines_list = focus_lines(ctx.session.state)

        contract = ctx.session.state.get("dataset_contract")
        display_name = getattr(contract, 'display_name', getattr(contract, 'name', 'dataset')) if contract else "dataset"
        materiality = getattr(contract, 'materiality', {}) if contract else {}
        var_pct = materiality.get("variance_pct", 5.0)
        var_abs = materiality.get("variance_absolute", 50000.0)
        contract_metadata = build_contract_metadata(contract)
        compact_metadata: dict[str, Any] = {}
        if contract_metadata:
            metrics_list = [m.get("name") for m in contract_metadata.get("metrics", []) if m.get("name")]
            primary_dims = [
                d.get("name")
                for d in contract_metadata.get("dimensions", [])
                if (d.get("role") or "").lower() == "primary" and d.get("name")
            ]
            hierarchy_paths = [
                {
                    "name": h.get("name"),
                    "path": h.get("children"),
                }
                for h in contract_metadata.get("hierarchies", [])
                if h.get("children")
            ]
            compact_metadata = {
                "metrics": metrics_list,
                "primary_dimensions": primary_dims,
                "hierarchies": hierarchy_paths,
                "time": contract_metadata.get("time"),
            }

        if contract:
            # NOTE: Avoid str.format() because prompts often contain JSON examples
            # with braces that would be interpreted as format fields.
            instr = NARRATIVE_AGENT_INSTRUCTION
            instr = instr.replace("{dataset_display_name}", str(display_name))
            instr = instr.replace("{variance_pct}", str(var_pct))
            instr = instr.replace("{variance_absolute}", str(var_abs))
            instr = augment_instruction(instr, ctx.session.state)
            self.wrapped_agent.instruction = instr
            print(f"[NarrativeAgent] Instruction updated for contract: {contract.name}")

        # Inject analysis results as a conversation message so the LLM can see them.
        # DynamicParallelAnalysisAgent stores results via state_delta only (no content
        # in events), so they are in session state but not in conversation history.
        state = ctx.session.state
        raw_da_result = state.get("data_analyst_result", "") or ""
        data_analyst_result = raw_da_result
        if raw_da_result:
            try:
                da_dict = json.loads(raw_da_result)
                da_dict.pop("level_results", None)  # Redundant with HIERARCHICAL_ANALYSIS
                data_analyst_result = json.dumps(da_dict, separators=(",", ":"), ensure_ascii=False)
            except (json.JSONDecodeError, TypeError):
                pass
        data_analyst_result = _truncate_text(data_analyst_result, MAX_NARRATIVE_ANALYST_CHARS, "data analyst result")

        # --- OPTIMIZATION: Truncate statistical_summary to reduce prompt bloat ---
        raw_stats = state.get("statistical_summary", "")
        statistical_summary = raw_stats
        if raw_stats:
            try:
                import json as _json
                stats_dict = _json.loads(raw_stats)
                # Slim top_drivers: recency bias (anomaly_latest first), then by share*magnitude
                _drivers = stats_dict.get("enhanced_top_drivers") or stats_dict.get("top_drivers") or []
                _drivers_sorted = sorted(
                    (d for d in _drivers if isinstance(d, dict)),
                    key=lambda d: (
                        d.get("anomaly_latest", False),
                        (d.get("share_of_total", 0) or 0) * abs(d.get("avg", 0) or 0),
                    ),
                    reverse=True,
                )
                slim_drivers = [
                    {k: d.get(k) for k in ("item", "avg", "slope_3mo", "slope_3mo_p_value", "share_of_total", "anomaly_latest") if k in d}
                    for d in _drivers_sorted[:MAX_NARRATIVE_TOP_DRIVERS]
                ]
                # Slim anomalies: recency-first (last N periods), then by |z_score|; cap at 12
                _anomalies = stats_dict.get("anomalies") or []
                periods_list = sorted(stats_dict.get("monthly_totals", {}).keys())
                focus_periods = max(1, int(os.environ.get("ANALYSIS_FOCUS_PERIODS", "4")))
                recent_periods = set(periods_list[-focus_periods:]) if len(periods_list) >= focus_periods else set(periods_list)

                def _anomaly_rank(a):
                    z = abs(a.get("z_score", 0))
                    recency = 1 if str(a.get("period", "")) in recent_periods else 0
                    return (recency, z)

                _sorted = sorted(
                    (a for a in _anomalies if isinstance(a, dict)),
                    key=_anomaly_rank,
                    reverse=True,
                )
                slim_anomalies = [
                    {k: a.get(k) for k in ("item", "value", "z_score", "period") if k in a}
                    for a in _sorted[:MAX_NARRATIVE_ANOMALIES]
                ]
                correlations_raw = stats_dict.get("correlations")
                if isinstance(correlations_raw, list):
                    correlations_lite = correlations_raw[:3]
                else:
                    correlations_lite = correlations_raw
                slim_stats = {
                    "summary_stats": stats_dict.get("summary_stats"),
                    "top_drivers": slim_drivers,
                    "anomalies": slim_anomalies,
                    "correlations": correlations_lite,
                }
                # Include cross_metric_correlations only when not skipped
                cmc = stats_dict.get("cross_metric_correlations")
                if cmc and not cmc.get("skipped"):
                    slim_stats["cross_metric_correlations"] = cmc
                # Include dq_flags only when suspected_uniform_growth is true
                dqf = stats_dict.get("dq_flags")
                if dqf and dqf.get("suspected_uniform_growth"):
                    slim_stats["dq_flags"] = dqf
                statistical_summary = _json.dumps(slim_stats, separators=(",", ":"), ensure_ascii=False)
            except (_json.JSONDecodeError, TypeError):
                pass
        statistical_summary = _truncate_text(statistical_summary, MAX_NARRATIVE_STATS_CHARS, "statistical summary")

        level_parts = []
        hierarchical_payload: dict[str, Any] = {}
        level_range = hierarchy_level_range(state, contract, max_cap=6)
        for lvl in level_range:
            val = state.get(f"level_{lvl}_analysis")
            if not val:
                continue
            compressed = _compress_analysis_block(val, MAX_NARRATIVE_HIERARCHY_CARDS)
            level_parts.append(f"HIERARCHICAL_LEVEL_{lvl}:\n{compressed}")
            hierarchical_payload[f"level_{lvl}"] = _json_payload_or_note(
                compressed,
                MAX_NARRATIVE_HIERARCHY_CHARS,
                f"Level {lvl}",
            )
        hierarchical_text = "\n\n".join(level_parts) if level_parts else "(none)"
        hierarchical_text = _truncate_text(hierarchical_text, MAX_NARRATIVE_HIERARCHY_CHARS, "hierarchical analysis")

        # Collect independent flat-scan findings (only present when INDEPENDENT_LEVEL_ANALYSIS=true)
        independent_parts = []
        independent_payload: dict[str, Any] = {}
        independent_range = independent_level_range(state, contract, max_cap=2)
        for lvl in independent_range:
            val = state.get(f"independent_level_{lvl}_analysis")
            if not val:
                continue
            compressed = _compress_analysis_block(val, MAX_NARRATIVE_INDEPENDENT_CARDS)
            independent_parts.append(f"INDEPENDENT_LEVEL_{lvl}:\n{compressed}")
            independent_payload[f"level_{lvl}"] = _json_payload_or_note(
                compressed,
                MAX_NARRATIVE_INDEPENDENT_CHARS,
                f"Independent level {lvl}",
            )
        independent_text = "\n\n".join(independent_parts) if independent_parts else ""
        independent_text = _truncate_text(independent_text, MAX_NARRATIVE_INDEPENDENT_CHARS, "independent findings")


        focus_directives = focus_lines_list
        data_analyst_component = _loads_or_passthrough(data_analyst_result)
        stats_component = _loads_or_passthrough(statistical_summary)

        dataset_payload = {
            "display_name": display_name,
            "materiality": {
                "variance_pct": var_pct,
                "variance_absolute": var_abs,
            },
        }
        if compact_metadata:
            dataset_payload["metadata"] = compact_metadata

        prompt_payload = {
            "dataset": dataset_payload,
            "temporal_grain": state.get("temporal_grain", "unknown"),
            "analysis_period": state.get("analysis_period"),
            "period_end": state.get("primary_query_end_date"),
            "focus_directives": focus_directives,
            "components": {
                "data_analyst_result": data_analyst_component,
                "statistical_summary": stats_component,
                "hierarchical_analysis": hierarchical_payload,
                "independent_findings": independent_payload,
            },
        }
        payload_json = json.dumps(prompt_payload, separators=(",", ":"), ensure_ascii=False)

        injection = (
            "NARRATIVE_INPUT_JSON (strict JSON — do not change keys):\n"
            f"{payload_json}\n"
            "Transform this JSON into Insight Cards per the system instruction."
        )
        print(
            f"[NarrativeAgent] Prompt size — instruction={len(self.wrapped_agent.instruction):,} chars, payload={len(payload_json):,} chars"
        )

        # DEBUG: Save prompt to file for optimization review
        try:
            safe_target = ctx.session.state.get('current_analysis_target', 'unknown').replace('/', '_')
            output_dir = ctx.session.state.get('output_dir')
            debug_dir = Path(output_dir) / "debug" if output_dir else Path("outputs") / "debug"
            debug_dir.mkdir(parents=True, exist_ok=True)
            prompt_path = debug_dir / f"narrative_prompt_{safe_target}.txt"
            with open(prompt_path, "w", encoding="utf-8") as f:
                f.write(f"--- INSTRUCTION ---\n{self.wrapped_agent.instruction}\n\n")
                f.write(f"--- INJECTION ---\n{injection}\n")
            print(f"[NarrativeAgent] DEBUG: Saved prompt to {prompt_path}")
        except Exception as e:
            print(f"[NarrativeAgent] DEBUG ERROR: Failed to save prompt: {e}")

        ctx.session.events.append(Event(
            invocation_id="narrative_results_injection",
            author="user",
            content=Content(role="user", parts=[Part(text=injection)]),
            actions=EventActions(),
        ))

        try:
            async for event in self.wrapped_agent.run_async(ctx):
                yield event
        except Exception as exc:
            # Never let downstream stages fail because the LLM/narrative agent crashed.
            print(f"[NarrativeAgent] WARNING: falling back to deterministic summary ({exc!r})")
            fallback = {
                "narrative_summary": "Narrative unavailable. Fallback summary generated without LLM output.",
                "insight_cards": [],
                "recommended_actions": [
                    "Review the top variance drivers from the hierarchical analysis output.",
                    "Validate detected anomalies against baseline periods before escalation.",
                    "Incorporate the latest seasonal findings into monitoring thresholds.",
                ],
            }
            yield Event(
                invocation_id=ctx.invocation_id,
                author="narrative_agent",
                actions=EventActions(state_delta={self.output_key: json.dumps(fallback)}),
            )

def create_narrative_agent():
    """Create a fresh instance of the narrative agent to avoid race conditions."""
    base = Agent(
        model=get_agent_model("narrative_agent"),
        name="narrative_agent",
        description="Transforms raw analytical findings into semantic Insight Cards with root-cause classification.",
        instruction=NARRATIVE_AGENT_INSTRUCTION,
        output_key="narrative_results",
        generate_content_config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.0,
            thinking_config=get_agent_thinking_config("narrative_agent"),
        ),
    )
    return NarrativeWrapper(base)


# Export root_agent for backward compatibility
root_agent = create_narrative_agent()
