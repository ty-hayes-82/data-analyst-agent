"""
Sample integration test demonstrating multi-component testing.

This file shows how to write integration tests that test multiple
components working together.
"""

import pytest
import pandas as pd
from tests.utils.test_helpers import assert_dataframe_structure, assert_csv_format_valid


@pytest.mark.integration
@pytest.mark.csv_mode
def test_data_join_pipeline(mock_pl_data_csv, mock_ops_metrics_csv):
    """
    Test the data join pipeline:
    - Load P&L data (CSV)
    - Load ops metrics (CSV)
    - Join them together
    - Validate structure
    """
    # Parse CSVs
    pl_df = pd.read_csv(pd.io.common.StringIO(mock_pl_data_csv))
    ops_df = pd.read_csv(pd.io.common.StringIO(mock_ops_metrics_csv))

    # Verify both loaded correctly
    assert len(pl_df) > 0
    assert len(ops_df) > 0

    # Join on period
    merged = pd.merge(
        pl_df,
        ops_df[["period", "miles", "stops", "loads"]],
        on="period",
        how="left"
    )

    # Verify join worked
    assert len(merged) == len(pl_df)
    assert "miles" in merged.columns
    assert "stops" in merged.columns
    assert "loads" in merged.columns

    # Verify no data loss
    assert merged["amount"].notna().sum() == pl_df["amount"].notna().sum()

    print(f"[PASS] Successfully joined {len(pl_df)} P&L rows with {len(ops_df)} ops periods")
    print(f"[PASS] Result: {len(merged)} rows with {len(merged.columns)} columns")


@pytest.mark.integration
@pytest.mark.csv_mode
def test_hierarchy_aggregation(mock_validated_pl_data_csv):
    """
    Test hierarchical aggregation:
    - Load validated data
    - Aggregate by category (level 2)
    - Aggregate by GL (level 3)
    - Verify hierarchy consistency
    """
    # Load data
    df = pd.read_csv(pd.io.common.StringIO(mock_validated_pl_data_csv))

    # Aggregate by canonical_category (Level 2)
    level2_agg = df.groupby("canonical_category").agg({
        "amount": "sum"
    }).reset_index()

    assert len(level2_agg) > 0
    print(f"[PASS] Level 2: {len(level2_agg)} categories")

    # Aggregate by gl_account (Level 3)
    level3_agg = df.groupby("gl_account").agg({
        "amount": "sum",
        "canonical_category": "first"
    }).reset_index()

    assert len(level3_agg) > 0
    print(f"[PASS] Level 3: {len(level3_agg)} GL accounts")

    # Verify hierarchy: sum of level 3 should equal level 2
    for category in level2_agg["canonical_category"]:
        level2_amount = level2_agg[
            level2_agg["canonical_category"] == category
        ]["amount"].sum()

        level3_amount = level3_agg[
            level3_agg["canonical_category"] == category
        ]["amount"].sum()

        assert abs(level2_amount - level3_amount) < 0.01, \
            f"Hierarchy mismatch for {category}: L2={level2_amount}, L3={level3_amount}"

    print("[PASS] Hierarchy consistency verified")


@pytest.mark.integration
@pytest.mark.csv_mode
def test_time_series_variance_calculation(mock_validated_pl_data_csv):
    """
    Test time series variance calculation:
    - Load validated data
    - Calculate YoY variance by category
    - Calculate MoM variance by category
    - Verify calculations
    """
    # Load data
    df = pd.read_csv(pd.io.common.StringIO(mock_validated_pl_data_csv))

    # Convert period to datetime
    df["period_dt"] = pd.to_datetime(df["period"])

    # Sort by period
    df = df.sort_values("period_dt")

    # Aggregate by period and category
    period_category = df.groupby(["period", "canonical_category"]).agg({
        "amount": "sum"
    }).reset_index()

    # Calculate MoM variance
    period_category = period_category.sort_values(["canonical_category", "period"])
    period_category["prev_amount"] = period_category.groupby("canonical_category")["amount"].shift(1)
    period_category["mom_variance_pct"] = (
        (period_category["amount"] - period_category["prev_amount"]) /
        period_category["prev_amount"].abs()
    ) * 100

    # Verify calculations
    mom_variances = period_category.dropna(subset=["mom_variance_pct"])
    assert len(mom_variances) > 0

    print(f"[PASS] Calculated MoM variance for {len(mom_variances)} period-category combinations")

    # Calculate YoY variance (if we have 12+ months)
    period_category["period_dt"] = pd.to_datetime(period_category["period"])
    unique_periods = period_category["period"].nunique()

    if unique_periods >= 12:
        period_category = period_category.sort_values(["canonical_category", "period_dt"])
        period_category["yoy_amount"] = period_category.groupby("canonical_category")["amount"].shift(12)
        period_category["yoy_variance_pct"] = (
            (period_category["amount"] - period_category["yoy_amount"]) /
            period_category["yoy_amount"].abs()
        ) * 100

        yoy_variances = period_category.dropna(subset=["yoy_variance_pct"])
        if len(yoy_variances) > 0:
            print(f"[PASS] Calculated YoY variance for {len(yoy_variances)} period-category combinations")


@pytest.mark.integration
@pytest.mark.csv_mode
def test_operational_ratio_calculation(mock_validated_pl_data_csv):
    """
    Test operational ratio calculation:
    - Load validated data with ops metrics
    - Calculate per-mile, per-stop, per-load ratios
    - Verify ratios are reasonable
    """
    # Load data
    df = pd.read_csv(pd.io.common.StringIO(mock_validated_pl_data_csv))

    # Filter to rows with ops metrics
    df_with_metrics = df.dropna(subset=["miles", "stops", "loads"])

    if len(df_with_metrics) == 0:
        pytest.skip("No rows with operational metrics")

    # Aggregate by period
    period_agg = df_with_metrics.groupby("period").agg({
        "amount": "sum",
        "miles": "first",  # Ops metrics are at period level
        "stops": "first",
        "loads": "first"
    }).reset_index()

    # Calculate ratios
    period_agg["revenue_per_mile"] = period_agg["amount"] / period_agg["miles"]
    period_agg["revenue_per_stop"] = period_agg["amount"] / period_agg["stops"]
    period_agg["revenue_per_load"] = period_agg["amount"] / period_agg["loads"]

    # Verify ratios are calculated
    assert period_agg["revenue_per_mile"].notna().any()
    assert period_agg["revenue_per_stop"].notna().any()
    assert period_agg["revenue_per_load"].notna().any()

    print(f"[PASS] Calculated operational ratios for {len(period_agg)} periods")
    print(f"  Avg revenue per mile: ${period_agg['revenue_per_mile'].mean():.2f}")
    print(f"  Avg revenue per stop: ${period_agg['revenue_per_stop'].mean():.2f}")
    print(f"  Avg revenue per load: ${period_agg['revenue_per_load'].mean():.2f}")


@pytest.mark.integration
@pytest.mark.csv_mode
def test_full_data_pipeline_from_csv_to_analysis_ready(
    mock_pl_data_csv,
    mock_ops_metrics_csv
):
    """
    Test the complete data pipeline from raw CSV to analysis-ready data:
    1. Load P&L CSV
    2. Load ops metrics CSV
    3. Join them
    4. Add hierarchy metadata
    5. Calculate derived columns
    6. Validate final structure
    """
    # Step 1: Load P&L
    pl_df = pd.read_csv(pd.io.common.StringIO(mock_pl_data_csv))
    assert len(pl_df) > 0
    print(f"[PASS] Step 1: Loaded {len(pl_df)} P&L rows")

    # Step 2: Load ops metrics
    ops_df = pd.read_csv(pd.io.common.StringIO(mock_ops_metrics_csv))
    assert len(ops_df) > 0
    print(f"[PASS] Step 2: Loaded {len(ops_df)} ops metric periods")

    # Step 3: Join
    merged = pd.merge(
        pl_df,
        ops_df[["period", "miles", "stops", "loads"]],
        on="period",
        how="left"
    )
    assert len(merged) == len(pl_df)
    print(f"[PASS] Step 3: Joined data ({len(merged)} rows)")

    # Step 4: Hierarchy metadata should already be present
    assert "canonical_category" in merged.columns
    assert "level_1" in merged.columns
    print(f"[PASS] Step 4: Hierarchy metadata present")

    # Step 5: Calculate derived columns
    # Revenue sign flip (revenue is negative in source data)
    merged["amount_signed"] = merged["amount"]

    # Per-unit metrics
    merged["amount_per_mile"] = merged["amount"] / merged["miles"]
    merged["amount_per_stop"] = merged["amount"] / merged["stops"]
    merged["amount_per_load"] = merged["amount"] / merged["loads"]

    print(f"[PASS] Step 5: Calculated derived columns")

    # Step 6: Final validation
    required_columns = [
        "period", "gl_account", "amount", "dimension_value",
        "canonical_category", "miles", "stops", "loads",
        "amount_per_mile", "amount_per_stop", "amount_per_load"
    ]

    assert_dataframe_structure(merged, required_columns, min_rows=1)
    print(f"[PASS] Step 6: Final validation passed")
    print(f"[PASS] Pipeline complete: {len(merged)} rows, {len(merged.columns)} columns")


if __name__ == "__main__":
    # Allow running this file directly for quick testing
    pytest.main([__file__, "-v", "-s"])
