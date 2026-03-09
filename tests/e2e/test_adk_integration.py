"""Google ADK orchestration integration tests.

Goal: validate the actual ADK SequentialAgent wiring (agent instantiation,
sub-agent chaining, and later session-state flow).

Per Ty's instruction: implement Class 1 first.
"""

from __future__ import annotations

import os

import pytest


@pytest.mark.e2e
class TestADKAgentInstantiation:
    def test_root_agent_and_pipelines_wire_up(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ACTIVE_DATASET", "trade_data")
        monkeypatch.setenv("DATA_ANALYST_TEST_MODE", "false")

        from google.adk.agents.sequential_agent import SequentialAgent

        # Import should succeed without requiring an A2A server for trade_data (CSV source)
        from data_analyst_agent.agent import root_agent, data_fetch_workflow, target_analysis_pipeline

        assert isinstance(root_agent, SequentialAgent)
        assert isinstance(data_fetch_workflow, SequentialAgent)
        assert isinstance(target_analysis_pipeline, SequentialAgent)

        root_names = [a.name for a in getattr(root_agent, "sub_agents", [])]
        fetch_names = [a.name for a in getattr(data_fetch_workflow, "sub_agents", [])]
        target_names = [a.name for a in getattr(target_analysis_pipeline, "sub_agents", [])]

        # Root agent chain (timed wrappers are expected)
        assert root_names == [
            "timed_contract_loader",
            "timed_cli_parameter_injector",
            "timed_data_fetch_workflow",
            "parallel_dimension_target_analysis",
            "timed_weather_context_agent",
            "timed_executive_brief_agent",
        ]

        # Data fetch workflow sub-agents
        assert fetch_names == [
            "date_initializer",
            "universal_data_fetcher",
        ]

        # Target analysis pipeline chain
        assert target_names == [
            "timed_analysis_context_initializer",
            "timed_planner_agent",
            "timed_dynamic_parallel_analysis",
            "timed_narrative_agent",
            "timed_conditional_alert_scoring",
            "timed_report_synthesis_agent",
            "timed_output_persistence_agent",
        ]
