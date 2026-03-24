import pytest
from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.agents.run_config import RunConfig
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.adk.sessions.session import Session

from data_analyst_agent.core_agents import targets as targets_module
from data_analyst_agent.core_agents.targets import (
    ParallelDimensionTargetAgent,
    _read_parallel_cap,
    _read_parallel_compute_cap,
    _read_parallel_llm_cap,
)


class _ComputeStubAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="compute_stub")

    async def _run_async_impl(self, ctx):
        target = ctx.session.state.get("current_analysis_target")
        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            actions=EventActions(state_delta={"phase_a_marker": f"done-{target}"}),
        )


class _LLMStubAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="llm_stub")

    async def _run_async_impl(self, ctx):
        target = ctx.session.state.get("current_analysis_target")
        phase_a = ctx.session.state.get("phase_a_marker")
        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            actions=EventActions(state_delta={"target_seen": target, "phase_b_seed": phase_a}),
        )


def _build_ctx(agent, targets):
    session = Session(
        id="session-1",
        app_name="pl_analyst",
        user_id="cli_user",
        state={"extracted_targets": targets},
        events=[],
    )
    return InvocationContext(
        agent=agent,
        invocation_id="inv-1",
        session=session,
        session_service=InMemorySessionService(),
        run_config=RunConfig(),
    )


def test_parallel_cap_reads_new_and_legacy_vars(monkeypatch):
    monkeypatch.setenv("MAX_PARALLEL_COMPUTE", "0")
    monkeypatch.setenv("MAX_PARALLEL_LLM", "3")
    monkeypatch.setenv("MAX_PARALLEL_METRICS", "2")

    assert _read_parallel_compute_cap() == 0
    assert _read_parallel_llm_cap() == 3
    assert _read_parallel_cap() == 3


def test_parallel_cap_uses_legacy_alias_when_llm_unset(monkeypatch):
    monkeypatch.delenv("MAX_PARALLEL_LLM", raising=False)
    monkeypatch.setenv("MAX_PARALLEL_METRICS", "5")
    assert _read_parallel_llm_cap() == 5


@pytest.mark.asyncio
async def test_two_phase_pipeline_seeds_phase_b_from_phase_a(monkeypatch):
    monkeypatch.setattr(targets_module, "_make_compute_pipeline", lambda: _ComputeStubAgent())
    monkeypatch.setattr(targets_module, "_make_llm_pipeline", lambda: _LLMStubAgent())
    monkeypatch.setenv("MAX_PARALLEL_COMPUTE", "0")
    monkeypatch.setenv("MAX_PARALLEL_LLM", "2")

    agent = ParallelDimensionTargetAgent()
    ctx = _build_ctx(agent, ["metric_a", "metric_b"])
    events = [event async for event in agent._run_async_impl(ctx)]

    seeded_values = []
    targets_seen = []
    for event in events:
        delta = getattr(getattr(event, "actions", None), "state_delta", None) or {}
        if "phase_b_seed" in delta:
            seeded_values.append(delta["phase_b_seed"])
            targets_seen.append(delta["target_seen"])

    assert sorted(targets_seen) == ["metric_a", "metric_b"]
    assert sorted(seeded_values) == ["done-metric_a", "done-metric_b"]
