from __future__ import annotations

import json
from typing import Any, AsyncGenerator, Dict

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions

from .settings import CROSS_DIMENSION_ANALYSIS


class CrossDimensionAnalysisStep(BaseAgent):
    """Run cross-dimension analysis for auxiliary dimensions at the current level."""

    def __init__(self) -> None:
        super().__init__(name="cross_dimension_analysis_step")

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        if not CROSS_DIMENSION_ANALYSIS:
            yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=EventActions())
            return

        current_level = ctx.session.state.get("current_level", 0)

        from ..data_cache import get_analysis_context

        analysis_ctx = get_analysis_context()
        if not analysis_ctx or not analysis_ctx.contract:
            yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=EventActions())
            return

        cross_dims = analysis_ctx.contract.get_cross_dimensions_for_level(current_level)
        if not cross_dims:
            yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=EventActions())
            return

        from ..statistical_insights_agent.tools.compute_cross_dimension_analysis import (
            compute_cross_dimension_analysis,
        )

        state_delta: Dict[str, Any] = {}

        for cd_cfg in cross_dims:
            cd_name = cd_cfg.name
            print(
                f"[CrossDimensionAnalysis] Level {current_level}: cross-analyzing with '{cd_name}'"
            )
            try:
                result_str = await compute_cross_dimension_analysis(
                    hierarchy_level=current_level,
                    auxiliary_dimension=cd_name,
                    min_sample_size=cd_cfg.min_sample_size,
                    max_cardinality=cd_cfg.max_cardinality,
                )
                state_key = f"level_{current_level}_cross_dimension_{cd_name}"
                state_delta[state_key] = result_str
                ctx.session.state[state_key] = result_str

                parsed = json.loads(result_str) if isinstance(result_str, str) else result_str
                summary = parsed.get("summary", {})
                if summary.get("interaction_significant"):
                    print(
                        "  -> Significant interaction detected "
                        f"(drags={summary.get('cross_cutting_drags', 0)}, "
                        f"boosts={summary.get('cross_cutting_boosts', 0)})"
                    )
                elif parsed.get("skipped"):
                    print(f"  -> Skipped: {parsed.get('reason', 'unknown')}")
                else:
                    print("  -> No significant interaction")
            except Exception as exc:  # noqa: BLE001
                print(f"  -> Failed: {exc}")

        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            actions=EventActions(state_delta=state_delta),
        )
