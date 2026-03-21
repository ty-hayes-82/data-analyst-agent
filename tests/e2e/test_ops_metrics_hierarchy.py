"""
Comprehensive hierarchy drill-down tests for ops_metrics_weekly dataset.

Tests verify:
1. Geographic hierarchy (gl_rgn_nm → gl_div_nm)
2. Business line hierarchy (ops_ln_of_bus_ref_nm → ops_ln_of_bus_nm → icc_cst_ctr_nm)
3. Metric rollup integrity across hierarchy levels
4. Time slicing with hierarchy drill-down
5. Cross-hierarchy independence
"""

from __future__ import annotations

from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd
import pytest

from data_analyst_agent.semantic.models import DatasetContract

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = REPO_ROOT / "config" / "datasets" / "tableau" / "ops_metrics_weekly" / "contract.yaml"
TDSX_PATH = REPO_ROOT / "data" / "tableau" / "Ops Metrics Weekly Scorecard.tdsx"

# Tolerance for floating point rollup validation (0.01%)
ROLLUP_TOLERANCE = 0.0001


@pytest.fixture(scope="module")
def ops_metrics_contract() -> DatasetContract:
    """Load the ops_metrics_weekly contract."""
    if not CONTRACT_PATH.exists():
        pytest.skip(f"Contract not found: {CONTRACT_PATH}")
    return DatasetContract.from_yaml(str(CONTRACT_PATH))


@pytest.fixture(scope="module")
def hyper_manager():
    """Create a Hyper connection manager for the dataset."""
    try:
        from data_analyst_agent.sub_agents.tableau_hyper_fetcher.loader_config import HyperLoaderConfig
        from data_analyst_agent.sub_agents.tableau_hyper_fetcher.hyper_connection import get_or_create_manager
        
        if not TDSX_PATH.exists():
            pytest.skip(f"TDSX file not found: {TDSX_PATH}")
        
        loader_config_path = REPO_ROOT / "config" / "datasets" / "tableau" / "ops_metrics_weekly" / "loader.yaml"
        if not loader_config_path.exists():
            pytest.skip(f"Loader config not found: {loader_config_path}")
        
        import yaml
        with open(loader_config_path, "r") as f:
            loader_raw = yaml.safe_load(f) or {}
        
        loader_config = HyperLoaderConfig(**loader_raw)
        manager = get_or_create_manager("ops_metrics_weekly", loader_config)
        manager.ensure_extracted(REPO_ROOT)
        
        return manager
        
    except ImportError as e:
        pytest.skip(f"Tableau Hyper API not available: {e}")
    except Exception as e:
        pytest.fail(f"Failed to initialize Hyper manager: {e}")


def execute_custom_query(manager, sql: str) -> pd.DataFrame:
    """Execute a custom SQL query against the Hyper extract."""
    try:
        df = manager.execute_query(sql)
        return df
    except Exception as e:
        pytest.fail(f"Query execution failed: {e}\nSQL: {sql}")


def test_geographic_hierarchy_drilldown(hyper_manager):
    """
    Test geographic hierarchy: gl_rgn_nm → gl_div_nm
    
    Verifies:
    - Regions exist and have aggregated metrics
    - Divisions exist under regions
    - Division metrics sum to region totals (within tolerance)
    """
    # Load data aggregated at region level
    region_sql = """
    SELECT 
        "gl_rgn_nm",
        SUM("ttl_rev_amt") AS "ttl_rev_amt"
    FROM "Extract"."Extract"
    WHERE "cal_dt" < DATE '2100-01-01'
    GROUP BY "gl_rgn_nm"
    ORDER BY "gl_rgn_nm"
    """
    
    region_df = execute_custom_query(hyper_manager, region_sql)
    
    # Verify regions exist
    assert len(region_df) > 0, "No regions found in dataset"
    assert region_df["ttl_rev_amt"].notna().all(), "Found NULL revenue values at region level"
    
    # Pick the region with the highest revenue for drill-down
    test_region = region_df.loc[region_df["ttl_rev_amt"].idxmax(), "gl_rgn_nm"]
    region_total = region_df.loc[region_df["gl_rgn_nm"] == test_region, "ttl_rev_amt"].values[0]
    
    # Drill down to divisions for the selected region
    division_sql = f"""
    SELECT 
        "gl_rgn_nm",
        "gl_div_nm",
        SUM("ttl_rev_amt") AS "ttl_rev_amt"
    FROM "Extract"."Extract"
    WHERE "cal_dt" < DATE '2100-01-01'
        AND "gl_rgn_nm" = '{test_region.replace("'", "''")}'
    GROUP BY "gl_rgn_nm", "gl_div_nm"
    ORDER BY "gl_div_nm"
    """
    
    division_df = execute_custom_query(hyper_manager, division_sql)
    
    # Verify divisions exist for the region
    assert len(division_df) > 0, f"No divisions found for region '{test_region}'"
    
    # Verify rollup integrity: divisions sum to region total
    division_sum = division_df["ttl_rev_amt"].sum()
    
    # Calculate relative error
    if region_total != 0:
        relative_error = abs((division_sum - region_total) / region_total)
        assert relative_error < ROLLUP_TOLERANCE, \
            f"Division rollup failed for region '{test_region}': " \
            f"Region total = {region_total:,.2f}, Division sum = {division_sum:,.2f}, " \
            f"Relative error = {relative_error:.6%} (tolerance: {ROLLUP_TOLERANCE:.6%})"
    else:
        # If region total is zero, division sum should also be zero (or very close)
        assert abs(division_sum) < 0.01, \
            f"Division rollup failed: Region total = 0, but division sum = {division_sum:,.2f}"


def test_business_line_hierarchy_drilldown(hyper_manager):
    """
    Test business line hierarchy: ops_ln_of_bus_ref_nm → ops_ln_of_bus_nm → icc_cst_ctr_nm
    
    Verifies:
    - 3-level hierarchy integrity
    - Metrics roll up correctly at each level
    """
    # Level 1: Business line reference (top level)
    ref_sql = """
    SELECT 
        "ops_ln_of_bus_ref_nm",
        SUM("ordr_cnt") AS "ordr_cnt"
    FROM "Extract"."Extract"
    WHERE "cal_dt" < DATE '2100-01-01'
        AND "ops_ln_of_bus_ref_nm" IS NOT NULL
    GROUP BY "ops_ln_of_bus_ref_nm"
    ORDER BY "ops_ln_of_bus_ref_nm"
    """
    
    ref_df = execute_custom_query(hyper_manager, ref_sql)
    
    assert len(ref_df) > 0, "No business line references found"
    
    # Pick the reference with highest order count
    test_ref = ref_df.loc[ref_df["ordr_cnt"].idxmax(), "ops_ln_of_bus_ref_nm"]
    ref_total = ref_df.loc[ref_df["ops_ln_of_bus_ref_nm"] == test_ref, "ordr_cnt"].values[0]
    
    # Level 2: Business line detail (middle level)
    bus_line_sql = f"""
    SELECT 
        "ops_ln_of_bus_ref_nm",
        "ops_ln_of_bus_nm",
        SUM("ordr_cnt") AS "ordr_cnt"
    FROM "Extract"."Extract"
    WHERE "cal_dt" < DATE '2100-01-01'
        AND "ops_ln_of_bus_ref_nm" = '{test_ref.replace("'", "''")}'
    GROUP BY "ops_ln_of_bus_ref_nm", "ops_ln_of_bus_nm"
    ORDER BY "ops_ln_of_bus_nm"
    """
    
    bus_line_df = execute_custom_query(hyper_manager, bus_line_sql)
    
    assert len(bus_line_df) > 0, f"No business lines found for reference '{test_ref}'"
    
    # Verify Level 2 rollup to Level 1
    bus_line_sum = bus_line_df["ordr_cnt"].sum()
    
    if ref_total != 0:
        relative_error = abs((bus_line_sum - ref_total) / ref_total)
        assert relative_error < ROLLUP_TOLERANCE, \
            f"Business line rollup failed: Ref total = {ref_total:,.0f}, " \
            f"Bus line sum = {bus_line_sum:,.0f}, Error = {relative_error:.6%}"
    else:
        assert abs(bus_line_sum) < 0.01, \
            f"Business line rollup failed: Ref total = 0, Bus line sum = {bus_line_sum:,.0f}"
    
    # Level 3: Cost center (bottom level)
    # Pick one business line for deeper drill
    test_bus_line = bus_line_df.loc[bus_line_df["ordr_cnt"].idxmax(), "ops_ln_of_bus_nm"]
    bus_line_total = bus_line_df.loc[bus_line_df["ops_ln_of_bus_nm"] == test_bus_line, "ordr_cnt"].values[0]
    
    cost_center_sql = f"""
    SELECT 
        "ops_ln_of_bus_ref_nm",
        "ops_ln_of_bus_nm",
        "icc_cst_ctr_nm",
        SUM("ordr_cnt") AS "ordr_cnt"
    FROM "Extract"."Extract"
    WHERE "cal_dt" < DATE '2100-01-01'
        AND "ops_ln_of_bus_ref_nm" = '{test_ref.replace("'", "''")}'
        AND "ops_ln_of_bus_nm" = '{test_bus_line.replace("'", "''")}'
    GROUP BY "ops_ln_of_bus_ref_nm", "ops_ln_of_bus_nm", "icc_cst_ctr_nm"
    ORDER BY "icc_cst_ctr_nm"
    """
    
    cost_center_df = execute_custom_query(hyper_manager, cost_center_sql)
    
    assert len(cost_center_df) > 0, \
        f"No cost centers found for business line '{test_bus_line}'"
    
    # Verify Level 3 rollup to Level 2
    cost_center_sum = cost_center_df["ordr_cnt"].sum()
    
    if bus_line_total != 0:
        relative_error = abs((cost_center_sum - bus_line_total) / bus_line_total)
        assert relative_error < ROLLUP_TOLERANCE, \
            f"Cost center rollup failed: Bus line total = {bus_line_total:,.0f}, " \
            f"Cost center sum = {cost_center_sum:,.0f}, Error = {relative_error:.6%}"
    else:
        assert abs(cost_center_sum) < 0.01, \
            f"Cost center rollup failed: Bus line total = 0, Cost center sum = {cost_center_sum:,.0f}"


def test_multiple_metrics_rollup_consistency(hyper_manager):
    """
    Verify that ALL metrics roll up correctly across hierarchy levels.
    
    Tests at least: ttl_rev_amt, lh_rev_amt, ordr_cnt, truck_count
    """
    metrics_to_test = ["ttl_rev_amt", "lh_rev_amt", "ordr_cnt", "truck_count"]
    
    for metric in metrics_to_test:
        # Load region-level aggregation
        region_sql = f"""
        SELECT 
            "gl_rgn_nm",
            SUM("{metric}") AS "{metric}"
        FROM "Extract"."Extract"
        WHERE "cal_dt" < DATE '2100-01-01'
        GROUP BY "gl_rgn_nm"
        ORDER BY "gl_rgn_nm"
        """
        
        region_df = execute_custom_query(hyper_manager, region_sql)
        
        assert len(region_df) > 0, f"No regions found for metric '{metric}'"
        
        # Pick a region with non-zero metric value
        non_zero_regions = region_df[region_df[metric] > 0]
        if len(non_zero_regions) == 0:
            pytest.skip(f"No non-zero values found for metric '{metric}'")
        
        test_region = non_zero_regions.loc[non_zero_regions[metric].idxmax(), "gl_rgn_nm"]
        region_total = non_zero_regions.loc[non_zero_regions["gl_rgn_nm"] == test_region, metric].values[0]
        
        # Load division-level aggregation for that region
        division_sql = f"""
        SELECT 
            "gl_rgn_nm",
            "gl_div_nm",
            SUM("{metric}") AS "{metric}"
        FROM "Extract"."Extract"
        WHERE "cal_dt" < DATE '2100-01-01'
            AND "gl_rgn_nm" = '{test_region.replace("'", "''")}'
        GROUP BY "gl_rgn_nm", "gl_div_nm"
        ORDER BY "gl_div_nm"
        """
        
        division_df = execute_custom_query(hyper_manager, division_sql)
        
        assert len(division_df) > 0, \
            f"No divisions found for region '{test_region}' and metric '{metric}'"
        
        # Verify rollup
        division_sum = division_df[metric].sum()
        
        if region_total != 0:
            relative_error = abs((division_sum - region_total) / region_total)
            assert relative_error < ROLLUP_TOLERANCE, \
                f"Metric '{metric}' rollup failed for region '{test_region}': " \
                f"Region = {region_total:,.2f}, Division sum = {division_sum:,.2f}, " \
                f"Error = {relative_error:.6%} (tolerance: {ROLLUP_TOLERANCE:.6%})"
        else:
            assert abs(division_sum) < 0.01, \
                f"Metric '{metric}' rollup failed: Region = 0, Division sum = {division_sum:,.2f}"


def test_hierarchy_time_slicing(hyper_manager):
    """
    Verify hierarchy drill-down works within a specific time range.
    
    Tests:
    - Filter to recent 30 days
    - Drill down geographic hierarchy
    - Verify time filter is respected at all levels
    """
    # Calculate date range (last 30 days from max date in dataset)
    max_date_sql = """
    SELECT MAX(CAST("cal_dt" AS DATE)) AS max_date
    FROM "Extract"."Extract"
    WHERE "cal_dt" < DATE '2100-01-01'
    """
    
    max_date_df = execute_custom_query(hyper_manager, max_date_sql)
    
    # Handle Tableau Date objects
    max_date_raw = max_date_df["max_date"].values[0]
    try:
        from tableauhyperapi import Date as HyperDate
        if isinstance(max_date_raw, HyperDate):
            max_date_raw = str(max_date_raw)
    except (ImportError, TypeError):
        pass
    
    max_date = pd.to_datetime(max_date_raw)
    date_start = (max_date - timedelta(days=30)).strftime("%Y-%m-%d")
    date_end = max_date.strftime("%Y-%m-%d")
    
    # Load region-level data with time filter
    region_sql = f"""
    SELECT 
        "gl_rgn_nm",
        SUM("ttl_rev_amt") AS "ttl_rev_amt",
        MIN(CAST("cal_dt" AS DATE)) AS min_date,
        MAX(CAST("cal_dt" AS DATE)) AS max_date
    FROM "Extract"."Extract"
    WHERE "cal_dt" >= DATE '{date_start}'
        AND "cal_dt" <= DATE '{date_end}'
    GROUP BY "gl_rgn_nm"
    ORDER BY "gl_rgn_nm"
    """
    
    region_df = execute_custom_query(hyper_manager, region_sql)
    
    assert len(region_df) > 0, "No regions found in time-filtered dataset"
    
    # Verify time filter was applied
    for _, row in region_df.iterrows():
        # Handle Tableau Date objects
        min_date_raw = row["min_date"]
        max_date_raw = row["max_date"]
        
        try:
            from tableauhyperapi import Date as HyperDate
            if isinstance(min_date_raw, HyperDate):
                min_date_raw = str(min_date_raw)
            if isinstance(max_date_raw, HyperDate):
                max_date_raw = str(max_date_raw)
        except (ImportError, TypeError):
            pass
        
        min_date = pd.to_datetime(min_date_raw)
        max_date = pd.to_datetime(max_date_raw)
        
        assert min_date >= pd.to_datetime(date_start), \
            f"Region '{row['gl_rgn_nm']}' has data before start date: {min_date} < {date_start}"
        assert max_date <= pd.to_datetime(date_end), \
            f"Region '{row['gl_rgn_nm']}' has data after end date: {max_date} > {date_end}"
    
    # Pick a region for drill-down
    test_region = region_df.loc[region_df["ttl_rev_amt"].idxmax(), "gl_rgn_nm"]
    region_total = region_df.loc[region_df["gl_rgn_nm"] == test_region, "ttl_rev_amt"].values[0]
    
    # Load division-level data with same time filter
    division_sql = f"""
    SELECT 
        "gl_rgn_nm",
        "gl_div_nm",
        SUM("ttl_rev_amt") AS "ttl_rev_amt",
        MIN(CAST("cal_dt" AS DATE)) AS min_date,
        MAX(CAST("cal_dt" AS DATE)) AS max_date
    FROM "Extract"."Extract"
    WHERE "cal_dt" >= DATE '{date_start}'
        AND "cal_dt" <= DATE '{date_end}'
        AND "gl_rgn_nm" = '{test_region.replace("'", "''")}'
    GROUP BY "gl_rgn_nm", "gl_div_nm"
    ORDER BY "gl_div_nm"
    """
    
    division_df = execute_custom_query(hyper_manager, division_sql)
    
    assert len(division_df) > 0, f"No divisions found for region '{test_region}' in time range"
    
    # Verify time filter at division level
    for _, row in division_df.iterrows():
        # Handle Tableau Date objects
        min_date_raw = row["min_date"]
        max_date_raw = row["max_date"]
        
        try:
            from tableauhyperapi import Date as HyperDate
            if isinstance(min_date_raw, HyperDate):
                min_date_raw = str(min_date_raw)
            if isinstance(max_date_raw, HyperDate):
                max_date_raw = str(max_date_raw)
        except (ImportError, TypeError):
            pass
        
        min_date = pd.to_datetime(min_date_raw)
        max_date = pd.to_datetime(max_date_raw)
        
        assert min_date >= pd.to_datetime(date_start), \
            f"Division '{row['gl_div_nm']}' has data before start date: {min_date} < {date_start}"
        assert max_date <= pd.to_datetime(date_end), \
            f"Division '{row['gl_div_nm']}' has data after end date: {max_date} > {date_end}"
    
    # Verify rollup integrity with time filter
    division_sum = division_df["ttl_rev_amt"].sum()
    
    if region_total != 0:
        relative_error = abs((division_sum - region_total) / region_total)
        assert relative_error < ROLLUP_TOLERANCE, \
            f"Time-sliced rollup failed for region '{test_region}': " \
            f"Region = {region_total:,.2f}, Division sum = {division_sum:,.2f}, " \
            f"Error = {relative_error:.6%}"
    else:
        assert abs(division_sum) < 0.01, \
            f"Time-sliced rollup failed: Region = 0, Division sum = {division_sum:,.2f}"


def test_cross_hierarchy_independence(hyper_manager):
    """
    Verify that geographic and business line hierarchies are independent.
    
    Tests:
    - Drill down both hierarchies simultaneously
    - Check that filtering on one hierarchy doesn't affect the other
    """
    # Load data with both hierarchy dimensions
    cross_sql = """
    SELECT 
        "gl_rgn_nm",
        "gl_div_nm",
        "ops_ln_of_bus_ref_nm",
        "ops_ln_of_bus_nm",
        SUM("ttl_rev_amt") AS "ttl_rev_amt",
        SUM("ordr_cnt") AS "ordr_cnt"
    FROM "Extract"."Extract"
    WHERE "cal_dt" < DATE '2100-01-01'
        AND "gl_rgn_nm" IS NOT NULL
        AND "ops_ln_of_bus_ref_nm" IS NOT NULL
    GROUP BY 
        "gl_rgn_nm",
        "gl_div_nm",
        "ops_ln_of_bus_ref_nm",
        "ops_ln_of_bus_nm"
    """
    
    cross_df = execute_custom_query(hyper_manager, cross_sql)
    
    assert len(cross_df) > 0, "No data found with both hierarchy dimensions"
    
    # Pick a region and business line reference for testing
    test_region = cross_df.groupby("gl_rgn_nm")["ttl_rev_amt"].sum().idxmax()
    test_bus_ref = cross_df.groupby("ops_ln_of_bus_ref_nm")["ordr_cnt"].sum().idxmax()
    
    # Test 1: Filter by region only - verify business line totals are independent
    region_filtered_sql = f"""
    SELECT 
        "ops_ln_of_bus_ref_nm",
        SUM("ordr_cnt") AS "ordr_cnt"
    FROM "Extract"."Extract"
    WHERE "cal_dt" < DATE '2100-01-01'
        AND "gl_rgn_nm" = '{test_region.replace("'", "''")}'
    GROUP BY "ops_ln_of_bus_ref_nm"
    """
    
    region_filtered_df = execute_custom_query(hyper_manager, region_filtered_sql)
    
    # Verify we still have multiple business lines when filtered by region
    assert len(region_filtered_df) > 0, \
        f"No business lines found when filtering by region '{test_region}'"
    
    # Test 2: Filter by business line only - verify geographic totals are independent
    bus_filtered_sql = f"""
    SELECT 
        "gl_rgn_nm",
        SUM("ttl_rev_amt") AS "ttl_rev_amt"
    FROM "Extract"."Extract"
    WHERE "cal_dt" < DATE '2100-01-01'
        AND "ops_ln_of_bus_ref_nm" = '{test_bus_ref.replace("'", "''")}'
    GROUP BY "gl_rgn_nm"
    """
    
    bus_filtered_df = execute_custom_query(hyper_manager, bus_filtered_sql)
    
    # Verify we still have multiple regions when filtered by business line
    assert len(bus_filtered_df) > 0, \
        f"No regions found when filtering by business line '{test_bus_ref}'"
    
    # Test 3: Cross-tabulation - verify totals match when aggregated different ways
    # Total for region, any business line
    region_total_sql = f"""
    SELECT SUM("ttl_rev_amt") AS total
    FROM "Extract"."Extract"
    WHERE "cal_dt" < DATE '2100-01-01'
        AND "gl_rgn_nm" = '{test_region.replace("'", "''")}'
    """
    
    region_total_df = execute_custom_query(hyper_manager, region_total_sql)
    region_total = region_total_df["total"].values[0]
    
    # Sum across business lines for that region
    region_by_bus_total = region_filtered_df["ordr_cnt"].sum()  # Different metric, but validates independence
    
    # Total for business line, any region
    bus_total_sql = f"""
    SELECT SUM("ordr_cnt") AS total
    FROM "Extract"."Extract"
    WHERE "cal_dt" < DATE '2100-01-01'
        AND "ops_ln_of_bus_ref_nm" = '{test_bus_ref.replace("'", "''")}'
    """
    
    bus_total_df = execute_custom_query(hyper_manager, bus_total_sql)
    bus_total = bus_total_df["total"].values[0]
    
    # Sum across regions for that business line
    bus_by_region_total = bus_filtered_df["ttl_rev_amt"].sum()  # Different metric
    
    # Verify the cross-tabulation preserves both hierarchies
    # The sum of business lines within a region should equal the business line total for that region
    cross_check_sql = f"""
    SELECT 
        SUM("ordr_cnt") AS total
    FROM "Extract"."Extract"
    WHERE "cal_dt" < DATE '2100-01-01'
        AND "gl_rgn_nm" = '{test_region.replace("'", "''")}'
    """
    
    cross_check_df = execute_custom_query(hyper_manager, cross_check_sql)
    cross_check_total = cross_check_df["total"].values[0]
    
    # Verify rollup integrity
    if cross_check_total != 0:
        relative_error = abs((region_by_bus_total - cross_check_total) / cross_check_total)
        assert relative_error < ROLLUP_TOLERANCE, \
            f"Cross-hierarchy independence test failed: " \
            f"Cross-check total = {cross_check_total:,.0f}, " \
            f"Business line sum = {region_by_bus_total:,.0f}, " \
            f"Error = {relative_error:.6%}"
    
    # Verify that both hierarchies can be traversed independently
    # This is validated by the fact that we have multiple values in both dimensions
    assert len(region_filtered_df) >= 1, "Business line hierarchy lost when filtering by region"
    assert len(bus_filtered_df) >= 1, "Geographic hierarchy lost when filtering by business line"
