from __future__ import annotations

from typing import AsyncGenerator

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions


class InitializeHierarchicalLoop(BaseAgent):
    """Initialize hierarchical loop state - starts at Level 0."""

    def __init__(self) -> None:
        super().__init__(name="initialize_hierarchical_loop")

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        phase_logger = ctx.session.state.get("phase_logger")
        analysis_target = ctx.session.state.get("current_analysis_target", "unknown")
        dimension_value = ctx.session.state.get("dimension_value", analysis_target)

        from ..data_cache import get_analysis_context

        analysis_ctx = get_analysis_context()
        start_level = 0
        max_depth = 5
        hierarchy_name = None

        if analysis_ctx and analysis_ctx.contract:
            if analysis_ctx.contract.hierarchies:
                hierarchy = analysis_ctx.contract.hierarchies[0]
                max_depth = len(hierarchy.children)
                hierarchy_name = hierarchy.name

            if getattr(analysis_ctx, "max_drill_depth", None):
                max_depth = min(max_depth, analysis_ctx.max_drill_depth)

        initial_state = {
            "current_level": start_level,
            "max_drill_depth": max_depth,
            "hierarchy_name": hierarchy_name,
            "drill_down_history": [],
            "continue_loop": True,
            "levels_analyzed": [],
        }

        if phase_logger:
            phase_logger.log_workflow_transition(
                from_agent="data_analyst_agent",
                to_agent="hierarchical_drill_down_loop",
                message=(
                    f"Initializing recursive drill-down at Level {start_level} for target: "
                    f"{dimension_value}"
                ),
            )
            phase_logger.log_level_start(
                level=start_level,
                dimension_value=dimension_value,
                message=f"Starting analysis at level {start_level}",
            )

        print(f"\n{'=' * 80}")
        print("[InitializeHierarchicalLoop] Starting hierarchical analysis at Level 0")
        target_label = ctx.session.state.get("target_label", "Target")
        print(f"  {target_label}: {dimension_value}")
        print(f"  Hierarchy: {hierarchy_name or 'Default'}")
        print(f"  Max Drill Depth: {max_depth}")
        print(f"{'=' * 80}\n")

        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            actions=EventActions(state_delta=initial_state),
        )
