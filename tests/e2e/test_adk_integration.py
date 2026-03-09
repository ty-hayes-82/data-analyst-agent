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
    """Run an ADK agent against an in-memory session until completion."""

    from google.adk.agents.invocation_context import InvocationContext

    ctx = InvocationContext(
        session_service=session_service,
        invocation_id=str(uuid.uuid4()),
        agent=agent,
        session=session,
        user_content=_make_user_content(user_text) if user_text else None,
    )

    async for _event in agent.run_async(ctx):
        actions = getattr(_event, "actions", None)
        state_delta = getattr(actions, "state_delta", None) if actions else None
        if isinstance(state_delta, dict) and state_delta:
            # Mimic the ADK app runner behavior: apply state_delta to session state.
            session.state.update(state_delta)


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
