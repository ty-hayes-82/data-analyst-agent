# Copyright 2025 Google LLC
import os
import json
from typing import AsyncGenerator

from google.adk.agents.llm_agent import Agent
from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.genai import types

from .prompt import PLANNER_INSTRUCTION
from .tools.generate_execution_plan import generate_execution_plan, refine_plan
from config.model_loader import get_agent_model, get_agent_thinking_config
from ...utils.focus_directives import (
    augment_instruction,
    focus_search_text,
    get_custom_focus,
    get_focus_modes,
)

USE_CODE_INSIGHTS = os.environ.get("USE_CODE_INSIGHTS", "true").lower() == "true"


class RuleBasedPlanner(BaseAgent):
    """Code-based execution planner — replaces the LLM planner agent.

    Calls generate_execution_plan() for the deterministic baseline plan, then
    calls refine_plan() to add any agents explicitly mentioned in the user query.
    No LLM call is made.
    """

    def __init__(self):
        super().__init__(name="planner_agent")

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        print(f"\n[RuleBasedPlanner] Generating execution plan (no LLM)...", flush=True)

        # Step 1: Get deterministic baseline plan
        try:
            baseline_json = await generate_execution_plan()
            baseline = json.loads(baseline_json)
        except Exception as exc:
            error_plan = json.dumps({
                "selected_agents": [],
                "summary": f"Plan generation failed: {exc}",
                "error": str(exc),
            })
            yield Event(
                invocation_id=ctx.invocation_id,
                author=self.name,
                actions=EventActions(state_delta={"execution_plan": error_plan}),
            )
            return

        if "error" in baseline:
            error_plan = json.dumps({
                "selected_agents": [],
                "summary": baseline.get("error", "Unknown error"),
                "error": baseline["error"],
            })
            yield Event(
                invocation_id=ctx.invocation_id,
                author=self.name,
                actions=EventActions(state_delta={"execution_plan": error_plan}),
            )
            return

        recommended = baseline.get("recommended_agents", [])

        # Step 2: Keyword-based refinement from user query + focus directives
        user_query = (
            ctx.session.state.get("user_query")
            or ctx.session.state.get("original_request")
            or ""
        )
        analysis_focus = get_focus_modes(ctx.session.state)
        custom_focus = get_custom_focus(ctx.session.state)

        focus_blob = focus_search_text(ctx.session.state)
        combined = " ".join(v for v in [user_query, focus_blob] if v).strip()
        if combined.strip():
            recommended = refine_plan(recommended, combined)

        # Step 3: Format as execution_plan schema
        selected_agents = [
            {"name": a["name"], "reasoning": a.get("justification", a.get("reasoning", ""))}
            for a in recommended
        ]
        context_summary = baseline.get("context_summary", {})
        plan = {
            "selected_agents": selected_agents,
            "summary": (
                f"Rule-based plan: {len(selected_agents)} agent(s) selected for "
                f"contract '{context_summary.get('contract', 'unknown')}' "
                f"({context_summary.get('periods', 0)} periods)."
            ),
            "context_summary": context_summary,
        }
        if analysis_focus:
            plan["focus_modes"] = analysis_focus
        if custom_focus:
            plan["custom_focus"] = custom_focus
        plan_json = json.dumps(plan, indent=2)

        agent_names = [a["name"] for a in selected_agents]
        print(f"[RuleBasedPlanner] Plan: {agent_names}\n")

        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            actions=EventActions(state_delta={"execution_plan": plan_json}),
        )


# LLM fallback agent (used when USE_CODE_INSIGHTS=false)

class FocusAwarePlannerAgent(BaseAgent):
    """Wraps the LLM planner so focus directives reach the prompt context."""

    def __init__(self, wrapped_agent: Agent):
        super().__init__(name="planner_agent")
        self._wrapped = wrapped_agent
        self.output_key = getattr(wrapped_agent, "output_key", "execution_plan")
        self.description = getattr(wrapped_agent, "description", "")
        self._base_instruction = getattr(wrapped_agent, "instruction", PLANNER_INSTRUCTION)

    def __getattr__(self, item):
        if item in {"output_key", "description"}:
            return getattr(self, item)
        return getattr(self._wrapped, item)

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        instruction = augment_instruction(
            self._base_instruction,
            ctx.session.state,
            suffix="Prioritize or de-prioritize agents accordingly.",
        )
        self._wrapped.instruction = instruction

        async for event in self._wrapped.run_async(ctx):
            yield event


_llm_planner = Agent(
    model=get_agent_model("planner_agent"),
    name="planner_agent",
    description="Orchestrates the analysis pipeline by deciding which sub-agents to execute based on data characteristics and user intent.",
    instruction=PLANNER_INSTRUCTION,
    tools=[generate_execution_plan],
    output_key="execution_plan",
    generate_content_config=types.GenerateContentConfig(
        response_modalities=["TEXT"],
        temperature=0.0,
        thinking_config=get_agent_thinking_config("planner_agent"),
    ),
)

root_agent = RuleBasedPlanner() if USE_CODE_INSIGHTS else FocusAwarePlannerAgent(_llm_planner)

print(
    f"[Planner] Using "
    f"{'rule-based planner' if USE_CODE_INSIGHTS else 'LLM planner'} "
    f"(USE_CODE_INSIGHTS={USE_CODE_INSIGHTS})"
)
