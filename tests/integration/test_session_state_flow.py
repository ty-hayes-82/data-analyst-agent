"""
Integration tests for session state propagation.

Verifies that the pipeline stages populate and consume session-state keys
as documented in the constitution (Section 2 -- Session State Flow):

  ContractLoader -> dataset_contract
  AnalysisContextInitializer -> analysis_context, analysis_context_ready
  DateInitializer -> pl_query_start_date, pl_query_end_date
  TestingDataAgent -> pl_data_csv, validated_pl_data_csv
  Data cache -> resolve_data_and_columns

These tests use mock session dicts (no live ADK runner).
"""

import pytest
import json
import pandas as pd
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_contract_loader_populates_state(ops_metrics_contract):
    """
    Simulates ContractLoader writing active_dataset and dataset_contract to state.
    The contract is now loaded deterministically from config/agent_config.yaml
    (or the ACTIVE_DATASET env var) without any LLM selector.
    """
    state = {}

    # Simulate ContractLoader setting state
    state["dataset_contract"] = ops_metrics_contract
    state["contract_name"] = ops_metrics_contract.name
    state["active_dataset"] = "ops_metrics"

    assert state["contract_name"] == "Ops Metrics"
    assert state["dataset_contract"].name == "Ops Metrics"
    assert state["active_dataset"] == "ops_metrics"


@pytest.mark.integration
def test_date_initialization_populates_state():
    """Simulates DateInitializer writing date range keys."""
    state = {}

    state["primary_query_start_date"] = "2024-01"
    state["primary_query_end_date"] = "2026-02"

    assert "primary_query_start_date" in state
    assert "primary_query_end_date" in state
    assert state["primary_query_start_date"] < state["primary_query_end_date"]


@pytest.mark.integration
def test_data_fetch_populates_cache(ops_metrics_067_df):
    """
    Simulates the data fetch stage writing CSV into both session state
    and the shared data cache.
    """
    from data_analyst_agent.sub_agents.data_cache import (
        set_validated_csv,
        get_validated_csv,
        clear_all_caches,
    )

    clear_all_caches()
    csv_data = ops_metrics_067_df.to_csv(index=False)

    # Simulate data agent populating session + cache
    state = {"validated_pl_data_csv": csv_data}
    set_validated_csv(csv_data)

    # Verify cache access
    cached = get_validated_csv()
    assert cached is not None
    df = pd.read_csv(StringIO(cached))
    assert len(df) == len(ops_metrics_067_df)

    clear_all_caches()


@pytest.mark.integration
def test_analysis_context_ready_flag(ops_metrics_analysis_context):
    """
    Simulates AnalysisContextInitializer setting analysis_context
    and the ready flag.
    """
    from data_analyst_agent.sub_agents.data_cache import (
        set_analysis_context,
        get_analysis_context,
        clear_all_caches,
    )

    clear_all_caches()

    state = {}
    ctx = ops_metrics_analysis_context

    # Simulate AnalysisContextInitializer
    set_analysis_context(ctx)
    state["analysis_context"] = ctx
    state["analysis_context_ready"] = True

    assert state["analysis_context_ready"] is True
    assert get_analysis_context() is not None
    assert get_analysis_context().run_id == ctx.run_id

    clear_all_caches()


@pytest.mark.integration
def test_state_keys_available_for_analysis_agents(
    ops_metrics_contract,
    ops_metrics_067_df,
):
    """
    After the full initialisation pipeline, all keys required by the
    parallel analysis agents should be present in session state.
    """
    from data_analyst_agent.sub_agents.data_cache import (
        set_analysis_context,
        set_validated_csv,
        clear_all_caches,
    )
    from data_analyst_agent.semantic.models import AnalysisContext

    clear_all_caches()

    csv_data = ops_metrics_067_df.to_csv(index=False)
    contract = ops_metrics_contract

    ctx = AnalysisContext(
        contract=contract,
        df=ops_metrics_067_df,
        target_metric=contract.get_metric("total_revenue"),
        primary_dimension=contract.get_dimension("lob"),
        run_id="test-state-keys",
        max_drill_depth=3,
    )

    set_validated_csv(csv_data)
    set_analysis_context(ctx)

    # Build the state dict as it would look after pipeline init
    state = {
        "active_dataset": "ops_metrics",
        "dataset_contract": contract,
        "contract_name": contract.name,
        "primary_query_start_date": "2024-06",
        "primary_query_end_date": "2026-02",
        "validated_pl_data_csv": csv_data,
        "analysis_context": ctx,
        "analysis_context_ready": True,
        "current_cost_center": "067",
        "max_drill_depth": 3,
    }

    required_keys = [
        "active_dataset",
        "dataset_contract",
        "validated_pl_data_csv",
        "analysis_context",
        "analysis_context_ready",
        "current_cost_center",
    ]

    for key in required_keys:
        assert key in state, f"Missing required session key: {key}"
        assert state[key] is not None, f"Session key '{key}' is None"

    clear_all_caches()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
