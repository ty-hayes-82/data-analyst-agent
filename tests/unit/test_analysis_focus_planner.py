import json
import pytest


@pytest.mark.asyncio
async def test_analysis_focus_influences_rule_based_planner(monkeypatch):
    """Ensure DATA_ANALYST_FOCUS->analysis_focus changes planner selection (not pass-through)."""
    from data_analyst_agent.sub_agents.planner_agent.agent import RuleBasedPlanner

    async def _fake_generate_execution_plan():
        return json.dumps({
            "recommended_agents": [
                {"name": "hierarchical_analysis_agent", "justification": "baseline"},
            ],
            "context_summary": {"contract": "x", "periods": 10, "rows": 100},
        })

    monkeypatch.setattr(
        "data_analyst_agent.sub_agents.planner_agent.agent.generate_execution_plan",
        _fake_generate_execution_plan,
    )

    from google.adk.sessions.in_memory_session_service import InMemorySessionService
    from google.adk.agents.invocation_context import InvocationContext
    from google.adk.sessions.session import Session

    svc = InMemorySessionService()
    session: Session = svc.create_session_sync(app_name="data-analyst-agent", user_id="test")
    session.state.update({
        "analysis_focus": ["anomaly_detection"],
        "custom_focus": "",
        "user_query": "",
    })

    planner = RuleBasedPlanner()
    ctx = InvocationContext(invocation_id="inv", session=session, session_service=svc, agent=planner)

    events = []
    async for e in planner.run_async(ctx):
        events.append(e)

    # state_delta should include execution_plan with statistical_insights_agent added
    plan_json = None
    for e in events:
        if getattr(e, "actions", None) and getattr(e.actions, "state_delta", None):
            plan_json = e.actions.state_delta.get("execution_plan")

    assert plan_json, "execution_plan not emitted"
    plan = json.loads(plan_json)
    names = [a["name"] for a in plan.get("selected_agents", [])]
    assert "statistical_insights_agent" in names
