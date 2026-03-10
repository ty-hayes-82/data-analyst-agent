import json
import os
from pathlib import Path
from typing import AsyncGenerator
from google.adk.agents.llm_agent import Agent
from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.genai import types
from google.genai.types import Content, Part
from .prompt import NARRATIVE_AGENT_INSTRUCTION
from config.model_loader import get_agent_model, get_agent_thinking_config

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
    """Wrapper to dynamically update narrative agent instruction from contract."""
    
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
        contract = ctx.session.state.get("dataset_contract")
        if contract:
            display_name = getattr(contract, 'display_name', contract.name)
            materiality = getattr(contract, 'materiality', {})
            var_pct = materiality.get("variance_pct", 5.0)
            var_abs = materiality.get("variance_absolute", 50000.0)

            # NOTE: Avoid str.format() because prompts often contain JSON examples
            # with braces that would be interpreted as format fields.
            instr = NARRATIVE_AGENT_INSTRUCTION
            instr = instr.replace("{dataset_display_name}", str(display_name))
            instr = instr.replace("{variance_pct}", str(var_pct))
            instr = instr.replace("{variance_absolute}", str(var_abs))
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
                data_analyst_result = json.dumps(da_dict, indent=2)
            except (json.JSONDecodeError, TypeError):
                pass

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
                    for d in _drivers_sorted
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
                    for a in _sorted[:12]
                ]
                slim_stats = {
                    "summary_stats": stats_dict.get("summary_stats"),
                    "top_drivers": slim_drivers,
                    "anomalies": slim_anomalies,
                    "correlations": stats_dict.get("correlations"),
                }
                # Include cross_metric_correlations only when not skipped
                cmc = stats_dict.get("cross_metric_correlations")
                if cmc and not cmc.get("skipped"):
                    slim_stats["cross_metric_correlations"] = cmc
                # Include dq_flags only when suspected_uniform_growth is true
                dqf = stats_dict.get("dq_flags")
                if dqf and dqf.get("suspected_uniform_growth"):
                    slim_stats["dq_flags"] = dqf
                statistical_summary = _json.dumps(slim_stats, indent=2)
            except (_json.JSONDecodeError, TypeError):
                pass

        level_parts = []
        for lvl in range(5):
            val = state.get(f"level_{lvl}_analysis")
            if val:
                level_parts.append(f"HIERARCHICAL_LEVEL_{lvl}:\n{val}")
        hierarchical_text = "\n\n".join(level_parts) if level_parts else "(none)"

        # Collect independent flat-scan findings (only present when INDEPENDENT_LEVEL_ANALYSIS=true)
        independent_parts = []
        for lvl in range(1, 5):
            val = state.get(f"independent_level_{lvl}_analysis")
            if val:
                independent_parts.append(f"INDEPENDENT_LEVEL_{lvl}:\n{val}")
        independent_text = "\n\n".join(independent_parts) if independent_parts else ""

        independent_section = (
            f"\n\nINDEPENDENT_LEVEL_FINDINGS (entities masked at higher levels, net-new only):\n{independent_text}"
            if independent_text else ""
        )

        injection = (
            "Here are the analysis results for you to transform into Insight Cards:\n\n"
            f"DATA_ANALYST_RESULT (Statistical Insight Cards):\n{data_analyst_result}\n\n"
            f"STATISTICAL_SUMMARY (Raw Statistics):\n{statistical_summary}\n\n"
            f"HIERARCHICAL_ANALYSIS:\n{hierarchical_text}"
            f"{independent_section}\n\n"
            "Please generate Insight Cards based on these findings."
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
