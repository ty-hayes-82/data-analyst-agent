import json
from types import SimpleNamespace

import pytest

from data_analyst_agent.sub_agents.report_synthesis_agent import agent as report_agent_module
from data_analyst_agent.sub_agents.report_synthesis_agent.agent import ReportSynthesisWrapper


class _NeverRunAgent:
    """Stub agent that should never be invoked when fast-path triggers."""

    def run_async(self, ctx):  # pragma: no cover - generator should not run
        async def _generator():
            raise AssertionError("LLM path should not run during fast-path tests")
            yield  # Unreachable

        return _generator()


def _build_ctx_state(**overrides):
    state = {
        "dataset_contract": None,
        "statistical_summary": '{"summary_stats": {"temporal_grain": "daily", "period_unit": "day"}}',
        "narrative_results": '{"insight_cards": []}',
        "data_analyst_result": '{"analysis": []}',
        "alert_scoring_result": '{"top_alerts": []}',
        "analysis_focus": [],
        "custom_focus": "",
        "temporal_grain": "daily",
        "primary_query_end_date": "2024-01-31",
        "analysis_period": "the period ending 2024-01-31",
        "timeframe": {},
        "current_analysis_target": "cases",
        "analysis_target": "cases",
        "target_label": "Metric",
    }
    state.update(overrides)
    return state


def _build_ctx(**state_overrides):
    state = _build_ctx_state(**state_overrides)
    session = SimpleNamespace(state=state, events=[])
    return SimpleNamespace(invocation_id="test-run", session=session)


@pytest.mark.asyncio
async def test_force_direct_tool_fast_path(monkeypatch):
    ctx = _build_ctx()
    wrapper = ReportSynthesisWrapper(_NeverRunAgent())

    async def fake_generate_markdown_report(**kwargs):
        fake_generate_markdown_report.calls.append(kwargs)
        return "# Fast Report\n"

    fake_generate_markdown_report.calls = []
    monkeypatch.setattr(report_agent_module, "generate_markdown_report", fake_generate_markdown_report)
    monkeypatch.setenv("REPORT_SYNTHESIS_FORCE_DIRECT_TOOL", "1")

    events = [event async for event in wrapper._run_async_impl(ctx)]

    assert fake_generate_markdown_report.calls
    assert ctx.session.state["report_markdown"].startswith("# Fast Report")
    assert ctx.session.state["report_synthesis_result"].startswith("# Fast Report")
    assert events  # yielded state update event
    assert ctx.session.events == []  # no injection because LLM skipped


@pytest.mark.asyncio
async def test_auto_fast_path_when_no_hierarchical_payload(monkeypatch):
    ctx = _build_ctx()
    wrapper = ReportSynthesisWrapper(_NeverRunAgent())

    async def fake_generate_markdown_report(**kwargs):
        fake_generate_markdown_report.calls.append(kwargs)
        return "# Auto Report\n"

    fake_generate_markdown_report.calls = []
    monkeypatch.delenv("REPORT_SYNTHESIS_FORCE_DIRECT_TOOL", raising=False)
    monkeypatch.setattr(report_agent_module, "generate_markdown_report", fake_generate_markdown_report)

    events = [event async for event in wrapper._run_async_impl(ctx)]

    assert fake_generate_markdown_report.calls
    assert ctx.session.state["report_markdown"].startswith("# Auto Report")
    assert ctx.session.state["report_synthesis_result"].startswith("# Auto Report")
    assert events
    assert ctx.session.events == []


@pytest.mark.asyncio
async def test_auto_fast_path_when_level_payload_has_no_cards(monkeypatch):
    level_payload = {"insight_cards": [], "level_results": {"rows": [{"variance": 0}]}}
    ctx = _build_ctx(level_0_analysis=json.dumps(level_payload), levels_analyzed=[0])
    wrapper = ReportSynthesisWrapper(_NeverRunAgent())

    async def fake_generate_markdown_report(**kwargs):
        fake_generate_markdown_report.calls.append(kwargs)
        return "# OWID Report\n"

    fake_generate_markdown_report.calls = []
    monkeypatch.delenv("REPORT_SYNTHESIS_FORCE_DIRECT_TOOL", raising=False)
    monkeypatch.setattr(report_agent_module, "generate_markdown_report", fake_generate_markdown_report)

    events = [event async for event in wrapper._run_async_impl(ctx)]

    assert fake_generate_markdown_report.calls
    assert ctx.session.state["report_markdown"].startswith("# OWID Report")
    assert ctx.session.state["report_synthesis_result"].startswith("# OWID Report")
    assert events
    assert ctx.session.events == []


@pytest.mark.asyncio
async def test_auto_fast_path_when_rule_based_plan_detected(monkeypatch):
    level_payload = {"insight_cards": [], "level_results": {"rows": [{"variance": 0}]}}
    execution_plan = json.dumps({"summary": "Rule-based plan: 0 agents"})
    ctx = _build_ctx(
        level_0_analysis=json.dumps(level_payload),
        levels_analyzed=[0],
        execution_plan=execution_plan,
    )
    wrapper = ReportSynthesisWrapper(_NeverRunAgent())

    async def fake_generate_markdown_report(**kwargs):
        fake_generate_markdown_report.calls.append(kwargs)
        return "# Rule Report\n"

    fake_generate_markdown_report.calls = []
    monkeypatch.delenv("REPORT_SYNTHESIS_FORCE_DIRECT_TOOL", raising=False)
    monkeypatch.setattr(report_agent_module, "generate_markdown_report", fake_generate_markdown_report)

    events = [event async for event in wrapper._run_async_impl(ctx)]

    assert fake_generate_markdown_report.calls
    assert ctx.session.state["report_markdown"].startswith("# Rule Report")
    assert ctx.session.state["report_synthesis_result"].startswith("# Rule Report")
    assert events
    assert ctx.session.events == []
