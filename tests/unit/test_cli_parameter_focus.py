import json
import os
import pytest


@pytest.mark.asyncio
async def test_cli_parameter_injects_focus(monkeypatch):
    from data_analyst_agent.core_agents.cli import CLIParameterInjector
    from google.adk.sessions.in_memory_session_service import InMemorySessionService
    from google.adk.agents.invocation_context import InvocationContext
    from google.adk.sessions.session import Session

    monkeypatch.setenv("DATA_ANALYST_FOCUS", "anomaly_detection, recent_weekly_trends ")
    monkeypatch.setenv("DATA_ANALYST_CUSTOM_FOCUS", "  Investigate revenue gaps\nacross segments   ")
    monkeypatch.setenv("DATA_ANALYST_METRICS", "revenue, margin")
    monkeypatch.setenv("DATA_ANALYST_DIMENSION", "region")
    monkeypatch.setenv("DATA_ANALYST_DIMENSION_VALUE", "Total")

    svc = InMemorySessionService()
    session: Session = await svc.create_session(app_name="data-analyst-agent", user_id="focus-test")

    injector = CLIParameterInjector()
    ctx = InvocationContext(invocation_id="cli-focus", session=session, session_service=svc, agent=injector)

    events = []
    async for event in injector.run_async(ctx):
        events.append(event)

    for event in events:
        delta = getattr(getattr(event, "actions", None), "state_delta", None)
        if delta:
            session.state.update(delta)

    focus_modes = session.state.get("analysis_focus")
    custom_focus = session.state.get("custom_focus")
    assert focus_modes == ["anomaly_detection", "recent_weekly_trends"]
    assert custom_focus == "Investigate revenue gaps across segments"

    request = session.state.get("request_analysis")
    assert request
    assert request["analysis_focus"] == focus_modes
    assert request["custom_focus"] == custom_focus
    assert "focus" in request["description"]

    # Ensure emitted events carried the state delta including the focus keys
    state_deltas = [getattr(e.actions, "state_delta", {}) for e in events if getattr(e, "actions", None)]
    flattened = {k: v for delta in state_deltas for k, v in (delta or {}).items()}
    assert flattened["analysis_focus"] == focus_modes
    assert flattened["custom_focus"] == custom_focus
