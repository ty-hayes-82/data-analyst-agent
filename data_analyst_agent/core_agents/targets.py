"""Target iteration and parallel execution helpers."""

from __future__ import annotations

import os
import re
from typing import Any, AsyncGenerator

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.agents.run_config import RunConfig
from google.adk.agents.sequential_agent import SequentialAgent
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.adk.sessions.session import Session
from pydantic import Field

from ..tools import iterate_analysis_targets
from ..utils.phase_logger import PhaseLogger
from ..utils.timing_utils import TimedAgentWrapper
from .loaders import AnalysisContextInitializer


_TARGET_SCOPED_STATE_PATTERN = re.compile(
    r"^(?:"
    r"level_\d+_analysis|"
    r"level_\d+_cross_dimension_.*|"
    r"independent_level_\d+_analysis|"
    r"independent_level_results|"
    r"level_analysis_result|"
    r"hierarchical_analysis_complete|"
    r"data_analyst_result|"
    r"drill_down_decision|"
    r"drill_down_history|"
    r"levels_analyzed|"
    r"current_level|"
    r"continue_loop|"
    r"max_drill_depth|"
    r"hierarchy_name|"
    r"narrative_results|"
    r"narrative_result|"
    r"report_synthesis_result|"
    r"alert_scoring_result|"
    r"statistical_summary"
    r")$"
)


def _strip_target_scoped_state(state: dict[str, Any]) -> dict[str, Any]:
    """Remove keys that must not leak across target runs.

    Each target executes in its own isolated session, but the parent session emits
    merged state updates while runners execute. Stripping target-scoped keys here
    prevents stale hierarchy/narrative outputs from previous targets contaminating
    the next target's synthesis stage.
    """
    cleaned = dict(state)
    for key in list(cleaned.keys()):
        if _TARGET_SCOPED_STATE_PATTERN.match(key):
            cleaned.pop(key, None)
    return cleaned


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

        compute_cap = _read_parallel_compute_cap()
        llm_cap = _read_parallel_llm_cap()
        compute_effective_cap = _effective_cap(compute_cap, len(targets))
        llm_effective_cap = _effective_cap(llm_cap, len(targets))

        print(
            "[ParallelDimensionTargetAnalysis] "
            f"{len(targets)} target(s), "
            f"MAX_PARALLEL_COMPUTE={compute_cap} -> cap={compute_effective_cap}, "
            f"MAX_PARALLEL_LLM={llm_cap} -> cap={llm_effective_cap}"
        )

        compute_runners = [
            _SingleTargetRunner(target, _make_compute_pipeline())
            for target in targets
        ]
        async for event in _run_runners(compute_runners, ctx, semaphore_cap=compute_effective_cap):
            yield event

        compute_results: dict[str, dict[str, Any]] = {}
        session_id_by_target: dict[str, str] = {}
        for runner in compute_runners:
            compute_results[runner.target_val] = dict(runner.final_state)
            session_id_by_target[runner.target_val] = runner.isolated_session_id

        llm_runners = [
            _SingleTargetRunner(
                target,
                _make_llm_pipeline(),
                seed_state=compute_results.get(target),
                forced_session_id=session_id_by_target.get(target),
            )
            for target in targets
        ]
        async for event in _run_runners(llm_runners, ctx, semaphore_cap=llm_effective_cap):
            yield event


class _SingleTargetRunner(BaseAgent):
    """Runs one target in an isolated session and captures final state."""

    target_val: str
    inner_pipeline: BaseAgent = Field(..., exclude=True)
    seed_state: dict[str, Any] = Field(default_factory=dict, exclude=True)
    forced_session_id: str | None = Field(default=None, exclude=True)
    final_state: dict[str, Any] = Field(default_factory=dict, exclude=True)
    isolated_session_id: str = Field(default="", exclude=True)

    def __init__(
        self,
        target: str,
        pipeline: BaseAgent,
        seed_state: dict[str, Any] | None = None,
        forced_session_id: str | None = None,
    ):
        safe_name = re.sub(r"_+", "_", re.sub(r"[^a-zA-Z0-9_]", "_", str(target))).strip("_")
        super().__init__(
            name=f"run_{safe_name}",
            target_val=str(target),
            inner_pipeline=pipeline,
            seed_state=seed_state or {},
            forced_session_id=forced_session_id,
        )

    async def _run_async_impl(self, inner_ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        import uuid

        from ..sub_agents.data_cache import current_session_id

        session_id = getattr(inner_ctx.session, "id", str(uuid.uuid4()))
        isolated_id = (
            self.forced_session_id
            or f"{session_id}_{self.target_val.replace('/', '_').replace(' ', '_')}"
        )
        token = current_session_id.set(isolated_id)

        # Prevent per-target analysis artifacts from leaking between runners.
        state_copy = _strip_target_scoped_state(inner_ctx.session.state)
        if self.seed_state:
            state_copy.update(self.seed_state)
        isolated_session = Session(
            id=isolated_id,
            app_name=inner_ctx.session.app_name,
            user_id=inner_ctx.session.user_id,
            state=state_copy,
            events=list(inner_ctx.session.events),
        )

        new_ctx = InvocationContext(
            agent=self.inner_pipeline,
            session=isolated_session,
            session_service=inner_ctx.session_service,
            invocation_id=inner_ctx.invocation_id,
            run_config=inner_ctx.run_config or RunConfig(),
        )
        new_ctx.session.state["current_analysis_target"] = self.target_val
        if "phase_logger" not in new_ctx.session.state:
            new_ctx.session.state["phase_logger"] = PhaseLogger(dimension_value=self.target_val)

        try:
            async for event in self.inner_pipeline.run_async(new_ctx):
                if event.actions and event.actions.state_delta:
                    new_ctx.session.state.update(event.actions.state_delta)
                yield event
        finally:
            object.__setattr__(self, "final_state", dict(new_ctx.session.state))
            object.__setattr__(self, "isolated_session_id", isolated_id)
            current_session_id.reset(token)


def _clear_parent_links(pipeline: SequentialAgent) -> SequentialAgent:
    for agent in pipeline.sub_agents:
        if hasattr(agent, "parent") and agent.parent is not None:
            object.__setattr__(agent, "parent", None)
    return pipeline


def _make_compute_pipeline() -> BaseAgent:
    """Phase A: context + planning + compute + alerts."""
    from ..sub_agents.alert_scoring_agent.agent import root_agent as alert_scoring_agent
    from ..sub_agents.dynamic_parallel_agent import DynamicParallelAnalysisAgent
    from ..sub_agents.planner_agent.agent import RuleBasedPlanner

    return _clear_parent_links(
        SequentialAgent(
            name="compute_pipeline",
            sub_agents=[
                TimedAgentWrapper(AnalysisContextInitializer()),
                TimedAgentWrapper(RuleBasedPlanner()),
                TimedAgentWrapper(DynamicParallelAnalysisAgent()),
                TimedAgentWrapper(alert_scoring_agent),
            ],
        )
    )


def _make_llm_pipeline() -> BaseAgent:
    """Phase B: narrative + report synthesis + persistence."""
    from ..sub_agents.output_persistence_agent.agent import OutputPersistenceAgent
    from ..sub_agents.report_synthesis_agent.agent import create_report_synthesis_agent
    from .narrative_gate import create_conditional_narrative_agent

    return _clear_parent_links(
        SequentialAgent(
            name="llm_pipeline",
            sub_agents=[
                TimedAgentWrapper(create_conditional_narrative_agent()),
                TimedAgentWrapper(create_report_synthesis_agent()),
                TimedAgentWrapper(OutputPersistenceAgent(level="dimension_value")),
            ],
        )
    )


async def _run_runners(
    runners: list[_SingleTargetRunner],
    ctx: InvocationContext,
    semaphore_cap: int,
) -> AsyncGenerator[Event, None]:
    import asyncio

    if not runners:
        return

    effective_cap = _effective_cap(semaphore_cap, len(runners))
    sem = asyncio.Semaphore(effective_cap)
    queue: asyncio.Queue[tuple[str, Event | Exception | None]] = asyncio.Queue()

    async def _run_runner(runner: _SingleTargetRunner):
        try:
            async with sem:
                async for event in runner.run_async(ctx):
                    await queue.put(("event", event))
        except Exception as exc:
            await queue.put(("error", exc))
        finally:
            await queue.put(("done", None))

    tasks = [asyncio.create_task(_run_runner(runner)) for runner in runners]

    finished = 0
    while finished < len(runners):
        kind, payload = await queue.get()
        if kind == "done":
            finished += 1
            continue
        if kind == "error":
            await asyncio.gather(*tasks, return_exceptions=True)
            raise payload  # type: ignore[misc]
        if kind == "event" and isinstance(payload, Event):
            yield payload

    await asyncio.gather(*tasks)


def _effective_cap(cap: int, total: int) -> int:
    if total <= 0:
        return 1
    return cap if 0 < cap < total else total


def _parse_parallel_cap(var_name: str, default: int) -> int:
    raw = os.environ.get(var_name, str(default)).strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return default


def _read_parallel_compute_cap() -> int:
    return _parse_parallel_cap("MAX_PARALLEL_COMPUTE", 0)


def _read_parallel_llm_cap() -> int:
    if os.environ.get("MAX_PARALLEL_LLM"):
        return _parse_parallel_cap("MAX_PARALLEL_LLM", 4)
    return _parse_parallel_cap("MAX_PARALLEL_METRICS", 4)


def _read_parallel_cap() -> int:
    """Legacy compatibility alias for LLM phase cap."""
    return _read_parallel_llm_cap()
