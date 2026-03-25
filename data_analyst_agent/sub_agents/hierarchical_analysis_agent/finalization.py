from __future__ import annotations

from typing import Any, AsyncGenerator, Dict, List

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions


class FinalizeAnalysisResults(BaseAgent):
    """Aggregate all level analysis results into hierarchical summary."""

    def __init__(self) -> None:
        super().__init__(name="finalize_analysis_results")

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        phase_logger = ctx.session.state.get("phase_logger")
        analysis_target = ctx.session.state.get("current_analysis_target", "unknown")

        print(
            f"[FinalizeAnalysisResults] Session keys: {list(ctx.session.state.keys())}"
        )

        levels_analyzed: List[int] = ctx.session.state.get("levels_analyzed", [])
        drill_down_history = ctx.session.state.get("drill_down_history", [])

        hierarchical_result: Dict[str, Any] = {
            "analysis_type": "hierarchical_drill_down",
            "dimension_value": analysis_target,
            "levels_analyzed": levels_analyzed,
            "drill_down_path": " -> ".join([f"Level {level}" for level in levels_analyzed]),
            "drill_down_history": drill_down_history,
            "level_results": {},
        }

        cross_dim_results: Dict[str, Any] = {}
        for level in levels_analyzed:
            level_key = f"level_{level}_analysis"
            level_result = ctx.session.state.get(level_key)
            if level_result:
                from ...utils.json_utils import safe_parse_json

                parsed = (
                    safe_parse_json(level_result) if isinstance(level_result, str) else level_result
                )
                if isinstance(parsed, dict):
                    for card in parsed.get("insight_cards", []):
                        card.setdefault("discovery_method", "standard_drill")
                    hierarchical_result["level_results"][f"level_{level}"] = parsed
                    ctx.session.state[level_key] = parsed

            for key in list(ctx.session.state.keys()):
                if key.startswith(f"level_{level}_cross_dimension_"):
                    cd_name = key.replace(f"level_{level}_cross_dimension_", "")
                    cd_val = ctx.session.state[key]
                    from ...utils.json_utils import safe_parse_json

                    cross_dim_results.setdefault(f"level_{level}", {})[cd_name] = (
                        safe_parse_json(cd_val) if isinstance(cd_val, str) else cd_val
                    )

        if cross_dim_results:
            hierarchical_result["cross_dimension_results"] = cross_dim_results

        independent_level_results: Dict[str, Any] = {}
        max_depth = ctx.session.state.get("max_drill_depth", 5)
        total_independent_cards = 0
        for lvl in range(1, max_depth + 1):
            ind_key = f"independent_level_{lvl}_analysis"
            ind_result = ctx.session.state.get(ind_key)
            if not ind_result:
                continue
            from ...utils.json_utils import safe_parse_json

            parsed_ind = safe_parse_json(ind_result) if isinstance(ind_result, str) else ind_result
            if isinstance(parsed_ind, dict):
                independent_level_results[f"level_{lvl}"] = parsed_ind
                total_independent_cards += len(parsed_ind.get("insight_cards", []))

        if independent_level_results:
            hierarchical_result["independent_level_results"] = independent_level_results
            print(
                f"[FinalizeAnalysisResults] Independent scans found {total_independent_cards} "
                f"net-new cards across {len(independent_level_results)} level(s)"
            )

        if not levels_analyzed:
            sample_keys = [
                k
                for k in ctx.session.state
                if "level_" in k and "_analysis" in k and not k.startswith("independent_")
            ][:20]
            print(
                f"[FinalizeAnalysisResults] WARNING: levels_analyzed is empty for "
                f"target={analysis_target!r}; check planner/drill loop and data availability. "
                f"Sample level-related session keys: {sample_keys}"
            )

        state_delta: Dict[str, Any] = {
            "data_analyst_result": hierarchical_result,
            "hierarchical_analysis_complete": True,
        }

        for level in levels_analyzed:
            level_key = f"level_{level}_analysis"
            if level_key in hierarchical_result["level_results"]:
                state_delta[level_key] = hierarchical_result["level_results"][level_key]

        if independent_level_results:
            state_delta["independent_level_results"] = independent_level_results
            ctx.session.state["independent_level_results"] = independent_level_results
            for lvl_key, lvl_val in independent_level_results.items():
                ind_state_key = f"independent_{lvl_key}_analysis"
                state_delta[ind_state_key] = lvl_val
                ctx.session.state[ind_state_key] = lvl_val

        ctx.session.state["data_analyst_result"] = hierarchical_result
        for key, value in state_delta.items():
            ctx.session.state[key] = value

        if phase_logger:
            phase_logger.log_workflow_transition(
                from_agent="hierarchical_drill_down_loop",
                to_agent="finalize_analysis_results",
                message="Aggregated hierarchical analysis results",
            )

        print(f"\n{'=' * 80}")
        print("[FinalizeAnalysisResults] COMPLETE - Yielding event (NO ESCALATION)")
        print(f"{'=' * 80}\n")

        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            actions=EventActions(state_delta=state_delta),
        )
