from __future__ import annotations

import json
from typing import AsyncGenerator

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.agents.llm_agent import Agent as LlmAgent
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.genai import types

from config.model_loader import get_agent_model, get_agent_thinking_config

from .prompt import DRILL_DOWN_DECISION_INSTRUCTION


class DrillDownDecisionFunction(BaseAgent):
    """Code-based drill-down decision agent — deterministic replacement."""

    def __init__(self) -> None:
        super().__init__(name="drill_down_decision_agent")

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        from ..hierarchy_variance_agent.tools.format_insight_cards import should_continue_drilling

        level_result_raw = ctx.session.state.get("level_analysis_result", "{}")
        current_level = ctx.session.state.get("current_level", 0)
        max_depth = ctx.session.state.get("max_drill_depth", 5)

        try:
            level_result = (
                json.loads(level_result_raw)
                if isinstance(level_result_raw, str)
                else level_result_raw
            )
        except json.JSONDecodeError:
            level_result = {}

        decision = should_continue_drilling(level_result, current_level, max_depth)
        decision_json = json.dumps(decision)

        print(
            f"[DrillDownDecisionFunction] Level {current_level}: "
            f"action={decision['action']} — {decision['reasoning']}"
        )

        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            actions=EventActions(state_delta={"drill_down_decision": decision_json}),
        )


class DrillDownDecisionAgent(LlmAgent):
    """LLM agent that decides whether to drill down to next level (fallback path)."""

    def __init__(self) -> None:
        super().__init__(
            name="drill_down_decision_agent",
            model=get_agent_model("drill_down_decision_agent"),
            instruction=DRILL_DOWN_DECISION_INSTRUCTION,
            output_key="drill_down_decision",
            generate_content_config=types.GenerateContentConfig(
                response_modalities=["TEXT"],
                response_mime_type="application/json",
                temperature=0.0,
                thinking_config=get_agent_thinking_config("drill_down_decision_agent"),
            ),
        )


class ProcessDrillDownDecision(BaseAgent):
    """Process drill-down decision and update loop state."""

    def __init__(self) -> None:
        super().__init__(name="process_drill_down_decision")

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        phase_logger = ctx.session.state.get("phase_logger")

        level_analysis_result = ctx.session.state.get("level_analysis_result", "{}")
        try:
            level_result = (
                json.loads(level_analysis_result)
                if isinstance(level_analysis_result, str)
                else level_analysis_result
            )
        except json.JSONDecodeError:
            level_result = {}

        is_duplicate = level_result.get("is_duplicate", False)
        is_last_level = level_result.get("is_last_level", False)

        decision_str = ctx.session.state.get("drill_down_decision", "{}")
        current_level = ctx.session.state.get("current_level", 0)
        drill_down_history = ctx.session.state.get("drill_down_history", [])
        levels_analyzed = ctx.session.state.get("levels_analyzed", [])

        if is_duplicate:
            next_level = current_level + 1

            if phase_logger:
                phase_logger.log_drill_down_decision(
                    level=current_level,
                    decision="SKIP",
                    reasoning=f"Level {current_level} is duplicate of Level {current_level-1}",
                    next_level=next_level,
                )

            state_delta = {"current_level": next_level, "continue_loop": not is_last_level}

            yield Event(
                invocation_id=ctx.invocation_id,
                author=self.name,
                actions=EventActions(state_delta=state_delta),
            )
            return

        try:
            decision = (
                json.loads(decision_str) if isinstance(decision_str, str) else decision_str
            )
        except json.JSONDecodeError:
            decision = {"action": "STOP", "reasoning": "Invalid decision format"}

        action = decision.get("action", "STOP")
        reasoning = decision.get("reasoning", "No reasoning provided")

        if current_level not in levels_analyzed:
            levels_analyzed.append(current_level)

        drill_down_history.append(
            {
                "level": current_level,
                "action": action,
                "reasoning": reasoning,
            }
        )

        max_depth = ctx.session.state.get("max_drill_depth", 5)
        if action == "CONTINUE" and not is_last_level and current_level < max_depth:
            next_level = current_level + 1

            if phase_logger:
                phase_logger.log_drill_down_decision(
                    level=current_level,
                    decision="CONTINUE",
                    reasoning=reasoning,
                    next_level=next_level,
                )

            state_delta = {
                "current_level": next_level,
                "drill_down_history": drill_down_history,
                "continue_loop": True,
                "levels_analyzed": levels_analyzed,
            }

            yield Event(
                invocation_id=ctx.invocation_id,
                author=self.name,
                actions=EventActions(state_delta=state_delta),
            )
            return

        if is_last_level:
            stop_reason = "Reached end of hierarchy"
        elif current_level >= (max_depth - 1):
            stop_reason = f"Reached max drill depth ({max_depth})"
        else:
            stop_reason = reasoning

        if phase_logger:
            phase_logger.log_drill_down_decision(
                level=current_level,
                decision="STOP",
                reasoning=stop_reason,
                next_level=None,
            )

        state_delta = {
            "drill_down_history": drill_down_history,
            "continue_loop": False,
            "levels_analyzed": levels_analyzed,
        }

        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            actions=EventActions(state_delta=state_delta, escalate=True),
        )
