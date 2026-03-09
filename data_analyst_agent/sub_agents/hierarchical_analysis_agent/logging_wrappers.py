from __future__ import annotations

import json
from typing import AsyncGenerator

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions


class HierarchyRankerLoggingWrapper(BaseAgent):
    """Adds logging around the hierarchy variance ranker agent."""

    def __init__(self) -> None:
        super().__init__(name="hierarchy_ranker_logging")

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        phase_logger = ctx.session.state.get("phase_logger")
        current_level = ctx.session.state.get("current_level", 2)
        analysis_target = ctx.session.state.get("current_analysis_target", "unknown")
        dimension_value = ctx.session.state.get("dimension_value", analysis_target)

        if phase_logger:
            phase_logger.log_workflow_transition(
                from_agent="hierarchical_drill_down_loop",
                to_agent="hierarchy_variance_ranker_agent",
                message=f"Starting Level {current_level} aggregation and ranking",
            )

        print(
            f"\n[HierarchyVarianceRanker] Analyzing Level {current_level} "
            f"for target: {dimension_value}"
        )

        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            actions=EventActions(),
        )


class HierarchyRankerResultLogger(BaseAgent):
    """Logs results after hierarchy variance ranker completes."""

    def __init__(self) -> None:
        super().__init__(name="hierarchy_ranker_result_logger")

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        from ...utils.json_utils import safe_parse_json

        phase_logger = ctx.session.state.get("phase_logger")
        current_level = ctx.session.state.get("current_level", 0)
        result_data = ctx.session.state.get("level_analysis_result")

        if result_data:
            try:
                result = safe_parse_json(result_data)
                insight_cards = result.get("insight_cards", [])
                total_variance = result.get("total_variance_dollar", 0)

                if phase_logger:
                    summary = {
                        "level": current_level,
                        "insight_cards_count": len(insight_cards),
                        "total_variance_dollar": total_variance,
                    }
                    phase_logger.log_agent_output(
                        agent_name=f"hierarchy_variance_ranker_level_{current_level}",
                        output_summary=summary,
                    )

                print(f"[HierarchyVarianceRanker] Level {current_level} Results:")
                print(f"  Insight Cards: {len(insight_cards)}")
                print(f"  Total Variance: ${total_variance:,.0f}")

                if insight_cards:
                    print("  Top 3 Insights:")
                    for i, card in enumerate(insight_cards[:3], 1):
                        title = card.get("title", "No Title")
                        what = card.get("what_changed", "N/A")
                        print(f"    {i}. {title}: {what}")

                state_delta = {f"level_{current_level}_analysis": result}
                ctx.session.state[f"level_{current_level}_analysis"] = result

                yield Event(
                    invocation_id=ctx.invocation_id,
                    author=self.name,
                    actions=EventActions(state_delta=state_delta),
                )
                return

            except (json.JSONDecodeError, AttributeError, KeyError) as exc:
                print(
                    "[HierarchyVarianceRanker] Warning: Could not parse result data: "
                    f"{exc}"
                )

        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            actions=EventActions(),
        )
