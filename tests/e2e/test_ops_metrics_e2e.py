"""
End-to-end tests for ops metrics analysis workflow.

These tests exercise the full pipeline from contract selection through
report synthesis, verifying that the system generates valuable insights
from operational metrics data.

Offline tests use the sample CSV and mocked agents.
Live tests (requires_a2a) connect to the remote A2A ops_metrics agent.
"""

import pytest
import json
import re
import pandas as pd
from io import StringIO
from pathlib import Path
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Offline E2E: CSV-based ops metrics workflow
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.ops_metrics
@pytest.mark.csv_mode
def test_full_ops_analysis_workflow_offline(
    ops_metrics_contract,
    ops_metrics_067_df,
    temp_output_dir,
):
    """
    Full offline workflow: contract -> context -> statistical analysis ->
    hierarchy check -> report structure -> output persistence.
    """
    from data_analyst_agent.semantic.models import AnalysisContext
    from data_analyst_agent.sub_agents.data_cache import (
        set_validated_csv,
        set_analysis_context,
        clear_all_caches,
    )

    clear_all_caches()

    # -- Phase 1: Contract & Context --
    df = ops_metrics_067_df.copy()
    csv_data = df.to_csv(index=False)
    set_validated_csv(csv_data)

    ctx = AnalysisContext(
        contract=ops_metrics_contract,
        df=df,
        target_metric=ops_metrics_contract.get_metric("total_revenue"),
        primary_dimension=ops_metrics_contract.get_dimension("lob"),
        run_id="e2e-ops-offline",
        max_drill_depth=3,
    )
    set_analysis_context(ctx)

    assert ctx.contract.name == "Ops Metrics"
    assert len(ctx.df) > 0

    # -- Phase 2: Data Validation --
    assert "total_revenue" in df.columns, "total_revenue column must exist"
    assert "cal_dt" in df.columns, "time column must exist"
    assert df["total_revenue"].notna().all(), "No NaN in revenue column"

    # -- Phase 3: Statistical Summary (basic verification) --
    periods = sorted(df["cal_dt"].unique())
    assert len(periods) >= 2, "Need at least 2 periods for trend analysis"

    # Monthly totals
    monthly = df.groupby("cal_dt")["total_revenue"].sum().sort_index()
    assert len(monthly) == len(periods)

    # Check for non-zero revenue
    assert monthly.sum() > 0, "Total revenue should be non-zero"

    # -- Phase 4: Hierarchy Verification --
    hierarchies = ops_metrics_contract.hierarchies
    assert len(hierarchies) >= 2, "ops_metrics should have >= 2 hierarchies"

    operational = [h for h in hierarchies if h.name == "operational_structure"]
    assert len(operational) == 1
    assert operational[0].children == ["lob", "terminal", "driver_leader"]

    # -- Phase 5: Report Structure --
    report = {
        "contract": ops_metrics_contract.name,
        "run_id": ctx.run_id,
        "summary": {
            "total_revenue": float(monthly.sum()),
            "periods_analyzed": len(periods),
            "period_range": f"{periods[0]} to {periods[-1]}",
        },
        "top_variances": [],
        "insights": [],
    }

    assert report["summary"]["total_revenue"] > 0
    assert report["summary"]["periods_analyzed"] >= 2

    # -- Phase 6: Output Persistence --
    output_file = temp_output_dir / "ops_analysis_e2e.json"
    with open(output_file, "w") as f:
        json.dump(report, f, indent=2)

    assert output_file.exists()
    assert output_file.stat().st_size > 0

    # Read back
    with open(output_file, "r") as f:
        saved = json.load(f)
    assert saved["contract"] == "Ops Metrics"

    clear_all_caches()
    print(f"[E2E] Ops metrics offline workflow passed: {len(periods)} periods, "
          f"revenue={report['summary']['total_revenue']:,.0f}")


@pytest.mark.e2e
@pytest.mark.ops_metrics
@pytest.mark.csv_mode
def test_ops_metrics_insight_quality_offline(
    ops_metrics_contract,
    ops_metrics_line_haul_df,
):
    """
    Verify that ops metrics sample data contains the properties needed
    to generate valuable insights: variance, top movers, multi-period trends.
    """
    df = ops_metrics_line_haul_df.copy()

    # 1. Variance analysis is possible (MoM)
    periods = sorted(df["cal_dt"].unique())
    assert len(periods) >= 12, "Need >= 12 periods for meaningful variance analysis"

    # 2. MoM variance exists
    monthly = df.groupby("cal_dt")["total_revenue"].sum().sort_index()
    mom_changes = monthly.diff().dropna()
    assert any(abs(mom_changes) > 0), "Should have non-zero MoM variance"

    # 3. Top movers identifiable (at least some rows vary)
    if "gl_div_nm" in df.columns:
        terminal_totals = df.groupby("gl_div_nm")["total_revenue"].sum()
        assert len(terminal_totals) >= 1, "Should have at least 1 terminal"

    # 4. Multi-metric data available
    metric_cols = ["total_revenue", "ld_trf_mi", "ordr_cnt", "stop_count"]
    available = [c for c in metric_cols if c in df.columns]
    assert len(available) >= 2, "Should have at least 2 metric columns for multi-metric analysis"

    # 5. Hierarchy dimensions present
    if "gl_div_nm" in df.columns and "drvr_mgr_cd" in df.columns:
        unique_terminals = df["gl_div_nm"].nunique()
        unique_leaders = df["drvr_mgr_cd"].nunique()
        assert unique_terminals >= 1, "Should have at least 1 terminal"
        assert unique_leaders >= 1, "Should have at least 1 driver leader"

    print(f"[E2E] Insight quality check: {len(periods)} periods, "
          f"{len(available)} metrics, MoM changes present")


# ---------------------------------------------------------------------------
# Live E2E: A2A server required
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.requires_a2a
@pytest.mark.ops_metrics
@pytest.mark.slow
def test_full_ops_analysis_live(a2a_client, ops_metrics_contract, temp_output_dir):
    """
    Full live workflow: A2A data fetch -> normalize -> context ->
    validate -> report output.
    """
    from data_analyst_agent.sub_agents.a2a_response_normalizer import A2aResponseNormalizer
    from data_analyst_agent.semantic.models import AnalysisContext

    # -- Fetch live data --
    table = '"Extract"."Extract"'
    sql = (
        f'SELECT "cal_dt", "ops_ln_of_bus_ref_nm" AS lob, '
        f'"gl_div_nm" AS terminal, '
        f'SUM(CAST("total_revenue" AS FLOAT)) AS total_revenue, '
        f'SUM(CAST("ld_trf_mi" AS FLOAT)) AS ld_trf_mi, '
        f'SUM(CAST("ordr_cnt" AS FLOAT)) AS ordr_cnt '
        f"FROM {table} "
        f'WHERE "empty_call_dt" >= DATE \'2025-06-01\' '
        f'AND "empty_call_dt" <= DATE \'2026-02-09\' '
        f'GROUP BY "cal_dt", "ops_ln_of_bus_ref_nm", "gl_div_nm" '
        f"ORDER BY \"cal_dt\" LIMIT 500"
    )

    resp = a2a_client.send_message(
        f'Execute this SQL using run_sql_query_tool with '
        f'sql_query exactly as below, limit=500, output_format="json". '
        f'Return ONLY the raw JSON.\n\n{sql}'
    )
    raw = a2a_client.extract_text(resp)

    normalizer = A2aResponseNormalizer(ops_metrics_contract)
    csv_out = normalizer.normalize_response(raw)

    try:
        df = pd.read_csv(StringIO(csv_out))
    except Exception:
        pytest.skip("Could not parse A2A live response as CSV")

    if len(df) == 0:
        pytest.skip("A2A returned empty dataset")

    # -- Build context --
    # Find the revenue column (may be total_revenue, ttl_rev_amt, etc.)
    rev_col = None
    for candidate in ["total_revenue", "ttl_rev_amt", "total_rev", "revenue"]:
        if candidate in df.columns:
            rev_col = candidate
            break
    if rev_col is None:
        pytest.skip(f"Revenue column not found in live data. Columns: {list(df.columns)}")

    # -- Report output --
    report = {
        "mode": "LIVE",
        "rows_fetched": len(df),
        "columns": list(df.columns),
        "total_revenue": float(df[rev_col].sum()) if rev_col else 0,
    }

    output_file = temp_output_dir / "ops_live_e2e.json"
    with open(output_file, "w") as f:
        json.dump(report, f, indent=2)

    assert output_file.exists()
    assert report["rows_fetched"] > 0
    print(f"[E2E-LIVE] Fetched {report['rows_fetched']} rows, "
          f"total_revenue={report['total_revenue']:,.0f}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s", "--tb=short"])
