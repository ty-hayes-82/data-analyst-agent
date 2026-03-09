"""Alert-scoring integration helpers."""

from __future__ import annotations

from typing import Any, AsyncGenerator

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from pydantic import Field

from ..utils.json_utils import safe_parse_json


class ConditionalAlertScoringAgent(BaseAgent):
    """Runs alert scoring only when the planner explicitly selects it."""

    alert_agent: Any | None = Field(default=None, exclude=True)

    def __init__(self, alert_agent: BaseAgent | None):
        super().__init__(name="conditional_alert_scoring")
        object.__setattr__(self, "alert_agent", alert_agent)

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        plan_raw = ctx.session.state.get("execution_plan", {})
        plan = safe_parse_json(plan_raw)
        selected_agents = [agent.get("name") for agent in plan.get("selected_agents", [])]

        if "alert_scoring_coordinator" in selected_agents and self.alert_agent:
            async for event in self.alert_agent.run_async(ctx):
                yield event
        else:
            print("[ConditionalAlertScoring] Planner skipped alert scoring.")
            yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=EventActions())
