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
    """Iterates through extracted targets and seeds per-target state.
    
    This agent implements the loop control for multi-metric analysis. It
    uses the iterate_analysis_targets tool to maintain loop state and
    emit the next target for analysis.
    
    This agent is primarily used in sequential multi-metric mode. For
    parallel execution, ParallelDimensionTargetAgent is preferred.
    
    Session State Inputs:
        extracted_targets: List of metric/dimension values to analyze
        target_loop_state: Loop iteration state from previous cycle
        target_label: Human-readable label for targets (e.g., "Metric")
        
    Session State Outputs:
        current_analysis_target: Current target being analyzed
        target_loop_state: Updated loop state for next iteration
        target_loop_complete: True when all targets processed
        phase_logger: PhaseLogger instance for current target
        
    Behavior:
        - If target_loop_complete: escalates to parent agent
        - Otherwise: emits next target and updates loop state
        
    Example:
        >>> # With 3 metrics:
        >>> ctx.session.state["extracted_targets"] = ["revenue", "orders", "margin"]
        >>> # First iteration:
        >>> # current_analysis_target = "revenue"
        >>> # Second iteration:
        >>> # current_analysis_target = "orders"
        >>> # Third iteration:
        >>> # current_analysis_target = "margin"
        >>> # Fourth iteration:
        >>> # target_loop_complete = True, escalate
    """

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

        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            actions=EventActions(
                state_delta={
                    "target_loop_state": new_state,
                    "target_loop_complete": False,
                    "current_analysis_target": target,
                }
            ),
        )


class ParallelDimensionTargetAgent(BaseAgent):
    """Executes the per-target pipeline with a configurable concurrency cap.
    
    This agent is the core parallelization engine for multi-metric analysis.
    It creates isolated session contexts for each target (metric or dimension
    value) and runs them concurrently using asyncio with a semaphore-based
    concurrency limit.
    
    Architecture:
        - Creates SingleTargetRunner instances (one per target)
        - Each runner gets an isolated session with cloned state
        - Runners share a semaphore to enforce MAX_PARALLEL_METRICS cap
        - Results stream back via asyncio.Queue
        - Each runner gets a unique session ID for cache isolation
        
    Concurrency Control:
        Environment variable MAX_PARALLEL_METRICS controls parallelism:
        - 0 or negative: All targets in parallel (use with caution)
        - 1: Sequential execution (one target at a time)
        - N > 1: Up to N targets concurrently
        - Default: 4
        
    Session State Inputs:
        extracted_targets: List of targets to analyze in parallel
        dataset_contract: Contract for creating per-target contexts
        [all state keys needed by target_analysis_pipeline]
        
    Session State Outputs:
        [Per-target outputs from target_analysis_pipeline]
        - analysis_context: Per-target AnalysisContext
        - statistical_summary: Per-target stats
        - hierarchy_results: Per-target hierarchy analysis
        - narrative_cards: Per-target narrative
        - alert_scores: Per-target alerts
        - executive_brief: Per-target synthesis
        
    Performance Notes:
        - Each target gets ~1-2 minutes of LLM-powered analysis
        - With 10 metrics and MAX_PARALLEL_METRICS=4:
          * Sequential: ~10-20 minutes
          * Parallel (cap=4): ~3-5 minutes
        - High parallelism (>8) may hit rate limits or memory constraints
        
    Example:
        >>> # Analyze 5 LOBs in parallel (cap=3):
        >>> ctx.session.state["extracted_targets"] = ["Retail", "Wholesale", "Services", "Digital", "Other"]
        >>> os.environ["MAX_PARALLEL_METRICS"] = "3"
        >>> # Execution:
        >>> # Wave 1: Retail, Wholesale, Services (parallel)
        >>> # Wave 2: Digital, Other (parallel)
        
    Note:
        Session isolation is achieved via contextvars (current_session_id token)
        to prevent data_cache collisions between parallel runners.
    """

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
    """Read the MAX_PARALLEL_METRICS environment variable.
    
    Parses MAX_PARALLEL_METRICS as an integer with safe fallback to 4.
    
    Args:
        None (reads from environment).
        
    Returns:
        int: Concurrency cap (0 = unlimited, 1 = sequential, N > 1 = parallel cap).
        
    Example:
        >>> os.environ["MAX_PARALLEL_METRICS"] = "8"
        >>> _read_parallel_cap()
        8
        >>> os.environ["MAX_PARALLEL_METRICS"] = "invalid"
        >>> _read_parallel_cap()
        4  # Safe fallback
    """
    raw = os.environ.get("MAX_PARALLEL_METRICS", "4").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 4
