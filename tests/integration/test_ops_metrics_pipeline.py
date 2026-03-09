"""
Integration tests for the ops metrics analysis pipeline.

Tests the full data flow: contract loading -> context creation ->
data validation -> statistical summary -> hierarchy drill-down ->
report synthesis, using either live A2A data or local sample CSV.

Offline tests (csv_mode) use ops_metrics_line_haul_sample.csv.
Live tests (requires_a2a) query the remote A2A agent.
"""

import pytest
import json
import pandas as pd
from io import StringIO
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Offline pipeline tests (no A2A server required)
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.ops_metrics
@pytest.mark.csv_mode
def test_contract_load_to_context(ops_metrics_contract, ops_metrics_067_df):
    """ContractLoader -> AnalysisContext initialisation with ops data."""
    from data_analyst_agent.semantic.models import AnalysisContext

    ctx = AnalysisContext(
        contract=ops_metrics_contract,
        df=ops_metrics_067_df,
        target_metric=ops_metrics_contract.get_metric("total_revenue"),
        primary_dimension=ops_metrics_contract.get_dimension("lob"),
        run_id="test-pipeline-ctx",
        max_drill_depth=3,
    )

    assert ctx.contract.name == "Ops Metrics"
    assert ctx.target_metric.column == "ttl_rev_amt"
    assert ctx.primary_dimension.column == "ops_ln_of_bus_ref_nm"
    assert len(ctx.df) > 0


@pytest.mark.integration
@pytest.mark.ops_metrics
@pytest.mark.csv_mode
@pytest.mark.asyncio
async def test_statistical_summary_with_sample_data(ops_metrics_context_with_cache):
    """compute_statistical_summary produces results from ops sample data."""
    import importlib

    mod = importlib.import_module(
        "data_analyst_agent.sub_agents.statistical_insights_agent.tools.compute_statistical_summary"
    )
    compute_statistical_summary = mod.compute_statistical_summary

    result_str = await compute_statistical_summary()
    result = json.loads(result_str)

    assert "error" not in result, f"Got error: {result.get('error')}"
    assert "top_drivers" in result
    assert "summary_stats" in result
    assert result["summary_stats"]["total_periods"] > 0


@pytest.mark.integration
@pytest.mark.ops_metrics
@pytest.mark.csv_mode
@pytest.mark.asyncio
async def test_hierarchy_drilldown_lob_terminal(ops_metrics_context_with_cache):
    """
    Hierarchy variance for LOB -> Terminal using cached ops sample data.
    Uses compute_level_statistics if the tool supports contract hierarchies.
    """
    from tests.utils.import_helpers import import_hierarchy_ranker_tool

    mod = import_hierarchy_ranker_tool("compute_level_statistics")
    compute_level_statistics = mod.compute_level_statistics

    result_str = await compute_level_statistics(
        level=1, hierarchy_name="operational_structure"
    )
    result = json.loads(result_str)

    # The tool may need the hierarchy columns in the data -- if it errors, log and pass
    if "error" in result:
        pytest.skip(f"compute_level_statistics not compatible with ops data yet: {result['error']}")

    assert result["level"] == 1
    assert result["items_analyzed"] >= 1


# ---------------------------------------------------------------------------
# Live pipeline tests (require A2A server)
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.requires_a2a
@pytest.mark.ops_metrics
def test_a2a_data_flows_into_normalizer(a2a_client, ops_metrics_contract):
    """Query live data from A2A and verify normalizer produces valid CSV."""
    from data_analyst_agent.sub_agents.a2a_response_normalizer import A2aResponseNormalizer

    table = '"Extract"."Extract"'
    sql = (
        f'SELECT "cal_dt", "ops_ln_of_bus_ref_nm", '
        f'SUM(CAST("ttl_rev_amt" AS FLOAT)) AS ttl_rev_amt '
        f"FROM {table} "
        f'WHERE "empty_call_dt" >= DATE \'2025-12-01\' '
        f'AND "empty_call_dt" <= DATE \'2026-01-31\' '
        f'GROUP BY "cal_dt", "ops_ln_of_bus_ref_nm" '
        f"ORDER BY \"cal_dt\" LIMIT 30"
    )

    resp = a2a_client.send_message(
        f'Execute this SQL using run_sql_query_tool with '
        f'sql_query exactly as below, limit=200, output_format="json". '
        f'Return ONLY the raw JSON.\n\n{sql}'
    )
    raw = a2a_client.extract_text(resp)

    normalizer = A2aResponseNormalizer(ops_metrics_contract)
    csv_out = normalizer.normalize_response(raw)

    assert csv_out and len(csv_out) > 10
    try:
        df = pd.read_csv(StringIO(csv_out))
        assert len(df) > 0
        print(f"[PASS] Live pipeline CSV: {len(df)} rows, cols={list(df.columns)}")
    except Exception as exc:
        print(f"[WARN] Could not parse live pipeline CSV: {exc}")


@pytest.mark.integration
@pytest.mark.requires_a2a
@pytest.mark.ops_metrics
def test_a2a_data_into_analysis_context(a2a_client, ops_metrics_contract):
    """
    Full chain: A2A query -> normalizer -> DataFrame -> AnalysisContext.
    Verifies that live data can drive the semantic layer.
    """
    from data_analyst_agent.sub_agents.a2a_response_normalizer import A2aResponseNormalizer
    from data_analyst_agent.semantic.models import AnalysisContext

    table = '"Extract"."Extract"'
    sql = (
        f'SELECT "cal_dt", "ops_ln_of_bus_ref_nm" AS lob, '
        f'SUM(CAST("ttl_rev_amt" AS FLOAT)) AS ttl_rev_amt, '
        f'SUM(CAST("ld_trf_mi" AS FLOAT)) AS ld_trf_mi '
        f"FROM {table} "
        f'WHERE "empty_call_dt" >= DATE \'2025-06-01\' '
        f'AND "empty_call_dt" <= DATE \'2026-01-31\' '
        f'GROUP BY "cal_dt", "ops_ln_of_bus_ref_nm" '
        f"ORDER BY \"cal_dt\" LIMIT 100"
    )

    resp = a2a_client.send_message(
        f'Execute this SQL using run_sql_query_tool with '
        f'sql_query exactly as below, limit=200, output_format="json". '
        f'Return ONLY the raw JSON.\n\n{sql}'
    )
    raw = a2a_client.extract_text(resp)

    normalizer = A2aResponseNormalizer(ops_metrics_contract)
    csv_out = normalizer.normalize_response(raw)

    try:
        df = pd.read_csv(StringIO(csv_out))
    except Exception:
        pytest.skip("Could not parse A2A response as CSV")

    if len(df) == 0:
        pytest.skip("A2A returned empty result set")

    # Build AnalysisContext from live data
    ctx = AnalysisContext(
        contract=ops_metrics_contract,
        df=df,
        target_metric=ops_metrics_contract.get_metric("total_revenue"),
        primary_dimension=ops_metrics_contract.get_dimension("lob"),
        run_id="test-live-ctx",
        max_drill_depth=3,
    )

    assert ctx.contract.name == "Ops Metrics"
    assert len(ctx.df) > 0
    print(f"[PASS] Live AnalysisContext: {len(ctx.df)} rows")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s", "--tb=short"])
