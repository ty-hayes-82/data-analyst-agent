import json

import pytest
from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.agents.run_config import RunConfig
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.adk.sessions.session import Session

from data_analyst_agent.core_agents.narrative_gate import (
    ConditionalNarrativeAgent,
    build_template_summary,
    has_material_findings,
)


class _StubNarrativeAgent(BaseAgent):
    called: bool = False

    def __init__(self):
        super().__init__(name="stub_narrative")

    async def _run_async_impl(self, ctx):
        object.__setattr__(self, "called", True)
        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            actions=EventActions(
                state_delta={"narrative_results": json.dumps({"narrative_summary": "from_llm"})}
            ),
        )


def _ctx_with_state(agent, state):
    session = Session(
        id="narrative-gate-test",
        app_name="pl_analyst",
        user_id="cli_user",
        state=state,
        events=[],
    )
    return InvocationContext(
        agent=agent,
        invocation_id="test-inv",
        session=session,
        session_service=InMemorySessionService(),
        run_config=RunConfig(),
    )


def test_has_material_findings_detects_card_threshold_crossing():
    state = {
        "dataset_contract": {"materiality": {"variance_pct": 5, "variance_absolute": 10000}},
        "level_0_analysis": json.dumps(
            {"insight_cards": [{"evidence": {"delta_pct": 6.2, "delta_abs": 5000}}]}
        ),
    }
    assert has_material_findings(state) is True


def test_has_material_findings_detects_high_severity_anomaly():
    state = {
        "dataset_contract": {"materiality": {"variance_pct": 10, "variance_absolute": 50000}},
        "level_0_analysis": json.dumps({"insight_cards": []}),
        "statistical_summary": json.dumps({"anomalies": [{"severity": "critical"}]}),
    }
    assert has_material_findings(state) is True


def test_has_material_findings_false_when_below_thresholds():
    state = {
        "dataset_contract": {"materiality": {"variance_pct": 8, "variance_absolute": 20000}},
        "level_0_analysis": json.dumps(
            {"insight_cards": [{"evidence": {"delta_pct": 1.2, "delta_abs": 1500}}]}
        ),
        "statistical_summary": json.dumps({"anomalies": [{"severity": "low"}]}),
    }
    assert has_material_findings(state) is False


def test_build_template_summary_is_deterministic():
    state = {
        "current_analysis_target": "ttl_rev_amt",
        "analysis_period": "the period ending 2026-03-20",
    }
    summary = build_template_summary(state)
    assert "ttl_rev_amt" in summary
    assert "2026-03-20" in summary


@pytest.mark.asyncio
async def test_conditional_narrative_skips_when_immaterial(monkeypatch):
    monkeypatch.setenv("SKIP_NARRATIVE_BELOW_MATERIALITY", "true")
    wrapped = _StubNarrativeAgent()
    agent = ConditionalNarrativeAgent(wrapped)
    ctx = _ctx_with_state(
        agent,
        {
            "dataset_contract": {"materiality": {"variance_pct": 5, "variance_absolute": 10000}},
            "level_0_analysis": json.dumps({"insight_cards": []}),
            "statistical_summary": json.dumps({"anomalies": []}),
            "current_analysis_target": "lrpm",
            "analysis_period": "the period ending 2026-03-20",
        }
    )

    events = [event async for event in agent._run_async_impl(ctx)]

    assert wrapped.called is False
    payload = json.loads(events[-1].actions.state_delta["narrative_results"])
    assert payload["meta"]["narrative_skipped"] is True


@pytest.mark.asyncio
async def test_conditional_narrative_runs_when_gate_disabled(monkeypatch):
    monkeypatch.setenv("SKIP_NARRATIVE_BELOW_MATERIALITY", "false")
    wrapped = _StubNarrativeAgent()
    agent = ConditionalNarrativeAgent(wrapped)
    ctx = _ctx_with_state(agent, {"current_analysis_target": "lrpm"})

    events = [event async for event in agent._run_async_impl(ctx)]

    assert wrapped.called is True
    assert json.loads(events[-1].actions.state_delta["narrative_results"])["narrative_summary"] == "from_llm"
