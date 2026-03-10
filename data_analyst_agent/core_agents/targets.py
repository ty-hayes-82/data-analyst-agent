"""Target iteration and parallel execution helpers."""

from __future__ import annotations

import os
import re
from typing import AsyncGenerator

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.sequential_agent import SequentialAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from pydantic import Field

from ..tools import iterate_analysis_targets
from ..utils.phase_logger import PhaseLogger
from ..utils.timing_utils import TimedAgentWrapper
from .loaders import AnalysisContextInitializer


class TargetIteratorAgent(BaseAgent):
    """Iterates through extracted targets and seeds per-target state."""

    def __init__(self):
        super().__init__(name="target_iterator")

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        loop_target = getattr(ctx, "loop_target", None)
        if loop_target:
            target = loop_target
            new_state = {}
            complete = False
        else:
            extracted_targets = ctx.session.state.get("extracted_targets", [])
            loop_state = ctx.session.state.get("target_loop_state")
            target_label = ctx.session.state.get("target_label", "Analysis Target")
            target, new_state, complete = iterate_analysis_targets(extracted_targets, loop_state, target_label)

        if not target or complete:
            yield Event(
                invocation_id=ctx.invocation_id,
                author=self.name,
                actions=EventActions(state_delta={"target_loop_complete": True}, escalate=True),
            )
            return

        phase_logger = PhaseLogger(dimension_value=target)
        phase_logger.log_workflow_transition("root_agent", "target_analysis", f"Starting analysis for {target}")
        phase_logger.start_phase(
            phase_name=f"{target} Analysis",
            description=f"Complete analysis workflow for {target}",
            input_data={"target": target},
        )
        ctx.session.state["phase_logger"] = phase_logger

        ctx.session.state["current_analysis_target"] = target
        ctx.session.state["dimension_value"] = target
        ctx.session.state["primary_target_value"] = target

        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            actions=EventActions(
                state_delta={
                    "target_loop_state": new_state,
                    "target_loop_complete": False,
                    "current_analysis_target": target,
                    "dimension_value": target,
                    "primary_target_value": target,
                }
            ),
        )


class ParallelDimensionTargetAgent(BaseAgent):
    """Executes the per-target pipeline with a configurable concurrency cap."""

    def __init__(self):
        super().__init__(name="parallel_dimension_target_analysis")

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        targets = ctx.session.state.get("extracted_targets", [])
        if not targets:
            yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=EventActions())
            return

        cap = _read_parallel_cap()
        effective_cap = cap if 0 < cap < len(targets) else len(targets)
        mode = "sequential" if effective_cap == 1 else f"parallel (cap={effective_cap})"
        print(
            f"[ParallelDimensionTargetAnalysis] {len(targets)} target(s), MAX_PARALLEL_METRICS={cap} -> running {mode}"
        )

        from google.adk.agents.invocation_context import InvocationContext as _IC
        from google.adk.agents.run_config import RunConfig
        from google.adk.sessions.session import Session
        from ..sub_agents.data_cache import current_session_id
        from ..sub_agents.dynamic_parallel_agent import DynamicParallelAnalysisAgent
        from ..sub_agents.narrative_agent.agent import create_narrative_agent
        from ..sub_agents.alert_scoring_agent.agent import root_agent as alert_scoring_agent
        from ..sub_agents.report_synthesis_agent.agent import create_report_synthesis_agent
        from ..sub_agents.output_persistence_agent.agent import OutputPersistenceAgent
        from ..sub_agents.planner_agent.agent import RuleBasedPlanner

        class SingleTargetRunner(BaseAgent):
            target_val: str
            inner_pipeline: BaseAgent = Field(..., exclude=True)

            def __init__(self, target, pipeline):
                safe_name = re.sub(r"_+", "_", re.sub(r"[^a-zA-Z0-9_]", "_", str(target))).strip("_")
                super().__init__(name=f"run_{safe_name}", target_val=target, inner_pipeline=pipeline)

            async def _run_async_impl(self, inner_ctx: _IC) -> AsyncGenerator[Event, None]:
                import asyncio
                session_id = getattr(inner_ctx.session, "id", str(__import__("uuid").uuid4()))
                isolated_id = f"{session_id}_{self.target_val.replace('/', '_').replace(' ', '_')}"
                token = current_session_id.set(isolated_id)
                isolated_session = Session(
                    id=isolated_id,
                    app_name=inner_ctx.session.app_name,
                    user_id=inner_ctx.session.user_id,
                    state=inner_ctx.session.state.copy(),
                    events=list(inner_ctx.session.events),
                )
                new_ctx = _IC(
                    agent=self.inner_pipeline,
                    session=isolated_session,
                    session_service=inner_ctx.session_service,
                    invocation_id=inner_ctx.invocation_id,
                    run_config=inner_ctx.run_config or RunConfig(),
                )
                new_ctx.session.state["current_analysis_target"] = self.target_val
                new_ctx.session.state["dimension_value"] = self.target_val
                new_ctx.session.state["primary_target_value"] = self.target_val
                new_ctx.session.state["phase_logger"] = PhaseLogger(dimension_value=self.target_val)
                try:
                    async for event in self.inner_pipeline.run_async(new_ctx):
                        if event.actions and event.actions.state_delta:
                            new_ctx.session.state.update(event.actions.state_delta)
                        yield event
                finally:
                    current_session_id.reset(token)

        def _make_pipeline() -> BaseAgent:
            pipeline = SequentialAgent(
                name="target_analysis_pipeline",
                sub_agents=[
                    TimedAgentWrapper(AnalysisContextInitializer()),
                    TimedAgentWrapper(RuleBasedPlanner()),
                    TimedAgentWrapper(DynamicParallelAnalysisAgent()),
                    TimedAgentWrapper(create_narrative_agent()),
                    TimedAgentWrapper(alert_scoring_agent),
                    TimedAgentWrapper(create_report_synthesis_agent()),
                    TimedAgentWrapper(OutputPersistenceAgent(level="dimension_value")),
                ],
            )
            for agent in pipeline.sub_agents:
                if hasattr(agent, "parent") and agent.parent is not None:
                    object.__setattr__(agent, "parent", None)
            return pipeline

        runners = [SingleTargetRunner(target, _make_pipeline()) for target in targets]
        for runner in runners:
            if hasattr(runner, "parent") and runner.parent is not None:
                object.__setattr__(runner, "parent", None)

        import asyncio

        sem = asyncio.Semaphore(effective_cap)
        queue: asyncio.Queue[Event | None] = asyncio.Queue()

        async def _run_runner(runner: SingleTargetRunner):
            async with sem:
                async for event in runner.run_async(ctx):
                    await queue.put(event)
            await queue.put(None)

        for runner in runners:
            asyncio.create_task(_run_runner(runner))

        finished = 0
        while finished < len(runners):
            event = await queue.get()
            if event is None:
                finished += 1
            else:
                yield event


def _read_parallel_cap() -> int:
    raw = os.environ.get("MAX_PARALLEL_METRICS", "4").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 4
