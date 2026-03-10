"""Google ADK orchestration integration tests.

Goal: validate the actual ADK SequentialAgent wiring, session state flow, and
(or later) end-to-end orchestration without requiring live LLM calls.

Per Ty's instruction: commit per class.
"""

from __future__ import annotations

import uuid

import pytest


def _make_user_content(text: str):
    from google.genai.types import Content, Part

    return Content(role="user", parts=[Part(text=text)])


async def _run_agent(agent, session_service, session, *, user_text: str = "") -> None:
    """Run an ADK agent against an in-memory session until completion.

    If ADK_TEST_DEBUG=1, prints state key accumulation per agent.
    """

    from google.adk.agents.invocation_context import InvocationContext

    ctx = InvocationContext(
        session_service=session_service,
        invocation_id=str(uuid.uuid4()),
        agent=agent,
        session=session,
        user_content=_make_user_content(user_text) if user_text else None,
    )

    import os
    debug = os.getenv("ADK_TEST_DEBUG") == "1"

    async for _event in agent.run_async(ctx):
        actions = getattr(_event, "actions", None)
        state_delta = getattr(actions, "state_delta", None) if actions else None
        if isinstance(state_delta, dict) and state_delta:
            session.state.update(state_delta)
            if debug:
                print(f"[ADK_TEST_DEBUG] event.author={getattr(_event,'author',None)} state_delta_keys={list(state_delta.keys())}")
            continue

        # Fallback: some agents emit content but no state_delta
        if debug:
            print(f"[ADK_TEST_DEBUG] event.author={getattr(_event,'author',None)} NO state_delta")

    if debug:
        print(f"[ADK_TEST_DEBUG] after agent={getattr(agent,'name',type(agent))} state_keys={sorted(session.state.keys())}")


@pytest.mark.e2e
class TestADKAgentInstantiation:
    def test_root_agent_and_pipelines_wire_up(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ACTIVE_DATASET", "trade_data")
        monkeypatch.setenv("DATA_ANALYST_TEST_MODE", "false")

        from google.adk.agents.sequential_agent import SequentialAgent

        from data_analyst_agent.agent import root_agent, data_fetch_workflow, target_analysis_pipeline

        assert isinstance(root_agent, SequentialAgent)
        assert isinstance(data_fetch_workflow, SequentialAgent)
        assert isinstance(target_analysis_pipeline, SequentialAgent)

        root_names = [a.name for a in getattr(root_agent, "sub_agents", [])]
        fetch_names = [a.name for a in getattr(data_fetch_workflow, "sub_agents", [])]
        target_names = [a.name for a in getattr(target_analysis_pipeline, "sub_agents", [])]

        assert root_names == [
            "timed_contract_loader",
            "timed_cli_parameter_injector",
            "timed_data_fetch_workflow",
            "parallel_dimension_target_analysis",
            "timed_weather_context_agent",
            "timed_executive_brief_agent",
        ]

        assert fetch_names == ["date_initializer", "universal_data_fetcher"]

        assert target_names == [
            "timed_analysis_context_initializer",
            "timed_planner_agent",
            "timed_dynamic_parallel_analysis",
            "timed_narrative_agent",
            "timed_conditional_alert_scoring",
            "timed_report_synthesis_agent",
            "timed_output_persistence_agent",
        ]


@pytest.mark.e2e
class TestSessionStateFlow:
    @pytest.mark.asyncio
    async def test_contract_loader_then_date_initializer_accumulates_state(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ACTIVE_DATASET", "trade_data")
        monkeypatch.setenv("DATA_ANALYST_TEST_MODE", "false")

        from google.adk.sessions.in_memory_session_service import InMemorySessionService

        from data_analyst_agent.core_agents.loaders import ContractLoader, DateInitializer

        svc = InMemorySessionService()
        session = svc.create_session_sync(
            app_name="data-analyst-agent",
            user_id="test-user",
            state={
                "user_message": "Analyze trade data",
                "active_dataset": "trade_data",
            },
        )

        await _run_agent(ContractLoader(), svc, session, user_text="Analyze trade data")
        assert session.state.get("dataset_contract"), "dataset_contract not set"

        await _run_agent(DateInitializer(), svc, session)
        # DateInitializer should populate date-related keys
        # (Exact key names may evolve; require at least one date range output)
        has_dates = any(
            k in session.state
            for k in (
                "date_ranges",
                "date_range",
                "analysis_period",
                "period_end_date",
                "current_period",
                "prior_period",
                "primary_query_start_date",
                "primary_query_end_date",
            )
        )
        assert has_dates, f"Expected date fields in state, got keys={sorted(session.state.keys())}"


@pytest.mark.e2e
class TestDataFetchPipeline:
    @pytest.mark.asyncio
    async def test_data_fetch_workflow_populates_primary_data_csv(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ACTIVE_DATASET", "trade_data")
        monkeypatch.setenv("DATA_ANALYST_TEST_MODE", "false")

        from google.adk.sessions.in_memory_session_service import InMemorySessionService

        from data_analyst_agent.core_agents.loaders import ContractLoader, DateInitializer
        from data_analyst_agent.agent import data_fetch_workflow

        svc = InMemorySessionService()
        session = svc.create_session_sync(
            app_name="data-analyst-agent",
            user_id="test-user",
            state={
                "user_message": "Analyze trade data",
                "active_dataset": "trade_data",
            },
        )

        await _run_agent(ContractLoader(), svc, session, user_text="Analyze trade data")
        await _run_agent(DateInitializer(), svc, session)

        await _run_agent(data_fetch_workflow, svc, session)

        csv_data = session.state.get("primary_data_csv")
        assert isinstance(csv_data, str) and len(csv_data) > 1000

        header = csv_data.splitlines()[0].split(",")
        for col in (
            "grain",
            "period_end",
            "flow",
            "region",
            "state",
            "port_code",
            "hs2",
            "hs4",
            "trade_value_usd",
        ):
            assert col in header


def _install_global_llm_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    """Globally stub ADK LLM Agent.run_async to avoid external API calls."""

    import json

    from google.adk.agents.llm_agent import Agent as LlmAgent
    from google.adk.events.event import Event
    from google.adk.events.event_actions import EventActions

    # Also stub direct google-genai calls (some agents bypass ADK Agent.run_async)
    from google.genai.models import Models
    from google.genai.types import Content, Part, Candidate, GenerateContentResponse

    async def _stub_run_async(self: LlmAgent, ctx):
        name = getattr(self, "name", "") or ""
        output_key = getattr(self, "output_key", None) or "output"

        if "planner" in name:
            payload = {
                "selected_agents": [
                    {"name": "hierarchical_analysis_agent"},
                    {"name": "statistical_insights_agent"},
                    {"name": "seasonal_baseline_agent"},
                    {"name": "alert_scoring_coordinator"},
                ]
            }
            state_delta = {"execution_plan": json.dumps(payload)}
        elif "narrative" in name:
            payload = {
                "narrative_summary": "Stub narrative (LLM disabled).",
                "insight_cards": [],
                "recommended_actions": [
                    "Investigate top variance drivers by region and HS4.",
                    "Validate anomaly scenarios against baseline periods.",
                    "Adjust seasonal thresholds for March/October effects.",
                ],
            }
            state_delta = {output_key: json.dumps(payload)}
        elif "report_synthesis" in name or "report" in name:
            txt = (
                "# Stub Report\n\n"
                "## Executive Summary\nStub executive summary text.\n\n"
                "## Variance\nStub variance narrative with drivers and totals.\n\n"
                "## Anomalies\nStub anomaly narrative with at least one bullet.\n- Example anomaly (±12.3%).\n\n"
                "## Seasonality\nStub seasonality narrative (peak/trough).\n\n"
                "## Recommended Actions\n"
                "1. Stub action with specificity (HS4 8542 @ LAX).\n"
                "2. Stub action with specificity (HS4 2711 @ HOU).\n"
                "3. Stub action with specificity (port NWK weather disruption).\n"
            )
            state_delta = {output_key: txt, "report_markdown": txt}
        else:
            # Generic LLM output
            state_delta = {output_key: json.dumps({"stub": True, "agent": name})}

        yield Event(invocation_id=ctx.invocation_id, author=name or "llm_stub", actions=EventActions(state_delta=state_delta))

    monkeypatch.setattr(LlmAgent, "run_async", _stub_run_async, raising=True)

    def _stub_generate_content(self: Models, *, model: str, contents, config=None):
        # Return a minimal response object with a usable text payload.
        txt = "# Stub Report\n\n## Executive Summary\nStub\n\n## Variance\nStub\n\n## Anomalies\nStub\n\n## Seasonality\nStub\n\n## Recommended Actions\n1. Stub action\n2. Stub action\n3. Stub action\n"
        return GenerateContentResponse(
            candidates=[Candidate(content=Content(role="model", parts=[Part(text=txt)]))]
        )

    monkeypatch.setattr(Models, "generate_content", _stub_generate_content, raising=True)


@pytest.mark.e2e
class TestAnalysisPipelineIntegration:
    @pytest.mark.asyncio
    async def test_target_analysis_pipeline_accumulates_state(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ACTIVE_DATASET", "trade_data")
        monkeypatch.setenv("DATA_ANALYST_TEST_MODE", "false")

        _install_global_llm_stub(monkeypatch)

        from google.adk.sessions.in_memory_session_service import InMemorySessionService

        from data_analyst_agent.core_agents.loaders import ContractLoader, DateInitializer
        from data_analyst_agent.agent import data_fetch_workflow, target_analysis_pipeline

        svc = InMemorySessionService()
        session = svc.create_session_sync(
            app_name="data-analyst-agent",
            user_id="test-user",
            state={
                "user_message": "Analyze trade variance by region and anomalies",
                "active_dataset": "trade_data",
            },
        )

        # Pre-load state: contract + dates + primary_data_csv
        await _run_agent(ContractLoader(), svc, session, user_text=session.state["user_message"])
        await _run_agent(DateInitializer(), svc, session)
        await _run_agent(data_fetch_workflow, svc, session)
        assert session.state.get("primary_data_csv")

        # Run target_analysis_pipeline agents one-by-one
        sub_agents = list(getattr(target_analysis_pipeline, "sub_agents", []))
        assert sub_agents, "target_analysis_pipeline has no sub_agents"

        # 1) AnalysisContextInitializer
        await _run_agent(sub_agents[0], svc, session)
        assert session.state.get("analysis_context_ready") is True
        assert session.state.get("analysis_context") is not None

        # 2) Planner (LLM stub)
        await _run_agent(sub_agents[1], svc, session)
        assert session.state.get("execution_plan"), "execution_plan missing"

        # Ensure planner selects the parallel analysis agents (or inject a default plan for orchestration testing)
        import json as _json
        try:
            _plan = _json.loads(session.state.get("execution_plan") or "{}")
        except Exception:
            _plan = {}
        if not (_plan.get("selected_agents") or []):
            session.state["execution_plan"] = _json.dumps(
                {
                    "selected_agents": [
                        {"name": "hierarchical_analysis_agent"},
                        {"name": "statistical_insights_agent"},
                        {"name": "seasonal_baseline_agent"},
                        {"name": "alert_scoring_coordinator"},
                    ]
                }
            )

        # 3) Dynamic parallel analysis (real tools)
        await _run_agent(sub_agents[2], svc, session)
        # Expect at least one analysis artifact
        assert any(
            k in session.state
            for k in (
                "statistical_summary",
                "data_analyst_result",
                "level_0_analysis",
                "level_1_analysis",
            )
        ), f"No analysis artifacts found. keys={sorted(session.state.keys())}"

        # 4) Narrative (LLM stub)
        await _run_agent(sub_agents[3], svc, session)
        assert session.state.get("narrative_results"), "narrative_results missing"

        # 5) Conditional alert scoring
        await _run_agent(sub_agents[4], svc, session)
        # Alert payload keys vary; require something alert-ish
        assert any("alert" in k for k in session.state.keys()), f"No alert keys. keys={sorted(session.state.keys())}"

        # 6) Report synthesis
        await _run_agent(sub_agents[5], svc, session)
        assert session.state.get("report_markdown"), "report_markdown missing"


@pytest.mark.e2e
class TestFullPipelineOrchestration:
    @pytest.mark.asyncio
    async def test_root_agent_run_async_completes_with_report_and_alerts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ACTIVE_DATASET", "trade_data")
        monkeypatch.setenv("DATA_ANALYST_TEST_MODE", "false")

        _install_global_llm_stub(monkeypatch)

        from google.adk.sessions.in_memory_session_service import InMemorySessionService

        from data_analyst_agent.agent import root_agent

        svc = InMemorySessionService()
        session = svc.create_session_sync(
            app_name="data-analyst-agent",
            user_id="test-user",
            state={
                "user_message": "Run a trade variance analysis and summarize key anomalies.",
                "active_dataset": "trade_data",
                # Force at least one target so ParallelDimensionTargetAgent executes the analysis pipeline.
                "extracted_targets": ["total"],
            },
        )

        await _run_agent(root_agent, svc, session, user_text=session.state["user_message"])

        assert session.state.get("report_markdown"), "report_markdown missing"
        assert len(session.state["report_markdown"]) > 200

        assert any("alert" in k for k in session.state.keys()), f"No alert keys. keys={sorted(session.state.keys())}"

        # Ensure no error-shaped payloads
        bad_keys = [k for k, v in session.state.items() if isinstance(v, dict) and v.get("error")]
        assert not bad_keys, f"Found error payloads in keys: {bad_keys}"
