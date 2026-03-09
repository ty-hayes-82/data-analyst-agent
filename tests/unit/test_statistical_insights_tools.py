"""
Step 4: Unit tests for Statistical Insights Agent tools.

Tests each tool in isolation using the data_cache to inject test data.
Tools tested:
- detect_mad_outliers
- detect_change_points
- compute_statistical_summary (comprehensive, calls the others internally)

Note: These tools use relative imports from data_cache, so we must import
them via importlib.import_module (supports numeric-prefix directory names).
"""

import pytest
import json
import importlib
import pandas as pd
import numpy as np
from io import StringIO


# ============================================================================
# Dynamic import helper for numeric-prefix package directories
# ============================================================================

def _import_stat_tool(tool_name: str):
    """Import a tool from statistical_insights_agent using importlib."""
    mod = importlib.import_module(
        f"data_analyst_agent.sub_agents.statistical_insights_agent.tools.{tool_name}"
    )
    return getattr(mod, tool_name)


# ============================================================================
# Helper: populate the data cache with test data
# ============================================================================

def _populate_cache_with_test_data():
    """Load PL-067 validated data into the data cache and set up AnalysisContext."""
    from tests.fixtures.test_data_loader import TestDataLoader
    from data_analyst_agent.sub_agents.data_cache import set_validated_csv, clear_all_caches, set_analysis_context
    from data_analyst_agent.semantic.models import DatasetContract, AnalysisContext

    # Clear any prior state
    clear_all_caches()

    loader = TestDataLoader()
    pl_df = loader.load_pl_067_csv()
    ts_df = loader.convert_to_time_series_format(pl_df)

    # Statistical tools expect consistent naming
    if "item_name" not in ts_df.columns:
        ts_df["item_name"] = ts_df["gl_account"]
    if "account_name" not in ts_df.columns:
        ts_df["account_name"] = ts_df["gl_account"]
    if "item" not in ts_df.columns:
        ts_df["item"] = ts_df["gl_account"]

    csv_data = ts_df.to_csv(index=False)
    set_validated_csv(csv_data)
    
    print(f"DEBUG: ts_df columns: {ts_df.columns.tolist()}")
    
    # Set up mock AnalysisContext (now mandatory)
    contract_data = {
        "name": "pl_contract",
        "version": "1.0",
        "time": {"column": "period", "format": "%Y-%m", "frequency": "monthly"},
        "grain": {"columns": ["gl_account"]},
        "metrics": [{"name": "amount", "column": "amount", "unit": "USD", "direction": "lower_is_better"}],
        "dimensions": [{"name": "gl_account", "column": "gl_account", "tags": ["account_id"]}],
        "policies": {
            "item_classification": {
                "revenue": {"starts_with": ["3"]}
            }
        }
    }
    contract = DatasetContract(**contract_data)
    ctx = AnalysisContext(
        contract=contract,
        df=ts_df,
        target_metric=contract.metrics[0],
        primary_dimension=contract.dimensions[0],
        cost_center="067",
        run_id="test_run"
    )
    
    set_analysis_context(ctx)
    
    return ts_df


def _teardown_cache():
    from data_analyst_agent.sub_agents.data_cache import clear_all_caches
    clear_all_caches()


# ============================================================================
# Tests for detect_mad_outliers
# ============================================================================

@pytest.mark.unit
@pytest.mark.csv_mode
@pytest.mark.asyncio
async def test_detect_mad_outliers_structure():
    """Test that MAD outlier detection returns proper structure."""
    detect_mad_outliers = _import_stat_tool("detect_mad_outliers")
    _populate_cache_with_test_data()

    try:
        result_str = await detect_mad_outliers()
        result = json.loads(result_str)

        assert "summary" in result
        assert "items_analyzed" in result["summary"]
        assert result["summary"]["items_analyzed"] > 0
        assert "total_outliers_detected" in result["summary"]

        # mad_outliers list should exist (even if empty)
        assert "mad_outliers" in result
        assert isinstance(result["mad_outliers"], list)

        # top_outliers is a subset
        assert "top_outliers" in result
        assert len(result["top_outliers"]) <= 15

        print(f"[PASS] MAD outliers: {result['summary']['total_outliers_detected']} detected "
              f"across {result['summary']['items_analyzed']} items")
    finally:
        _teardown_cache()


@pytest.mark.unit
@pytest.mark.csv_mode
@pytest.mark.asyncio
async def test_detect_mad_outliers_no_nan():
    """Test that MAD results contain no NaN values."""
    detect_mad_outliers = _import_stat_tool("detect_mad_outliers")
    _populate_cache_with_test_data()

    try:
        result_str = await detect_mad_outliers()
        result = json.loads(result_str)

        for outlier in result.get("mad_outliers", []):
            assert not np.isnan(outlier["modified_z_score"]), "Modified z-score is NaN"
            assert not np.isnan(outlier["amount"]), "Amount is NaN"
            assert not np.isnan(outlier["median"]), "Median is NaN"
            assert not np.isinf(outlier["modified_z_score"]), "Modified z-score is Inf"

        print("[PASS] No NaN/Inf values in MAD outlier results")
    finally:
        _teardown_cache()


@pytest.mark.unit
@pytest.mark.csv_mode
@pytest.mark.asyncio
async def test_detect_mad_outliers_empty_cache():
    """Test MAD outlier detection when cache is empty."""
    from data_analyst_agent.sub_agents.data_cache import clear_all_caches, _CSV_CACHE_FILE
    clear_all_caches()
    # Also remove the file-based cache so get_validated_csv returns None
    if _CSV_CACHE_FILE.exists():
        _CSV_CACHE_FILE.unlink()

    detect_mad_outliers = _import_stat_tool("detect_mad_outliers")
    result_str = await detect_mad_outliers()
    result = json.loads(result_str)

    assert "error" in result
    print("[PASS] Empty cache handled gracefully")


# ============================================================================
# Tests for detect_change_points
# ============================================================================

@pytest.mark.unit
@pytest.mark.csv_mode
@pytest.mark.asyncio
async def test_detect_change_points_structure():
    """Test that change point detection returns proper structure."""
    detect_change_points = _import_stat_tool("detect_change_points")
    _populate_cache_with_test_data()

    try:
        result_str = await detect_change_points()
        result = json.loads(result_str)

        assert "summary" in result
        # The tool uses 'items_analyzed' in success case
        if "warning" not in result:
            assert "items_analyzed" in result["summary"]
            assert result["summary"]["items_analyzed"] > 0
            assert "total_change_points" in result["summary"]
            assert "change_points" in result
            assert isinstance(result["change_points"], list)
            print(f"[PASS] Change points: {result['summary']['total_change_points']} detected")
        else:
            print(f"[PASS] Change point detection returned warning: {result.get('message', 'insufficient data')}")
    finally:
        _teardown_cache()


@pytest.mark.unit
@pytest.mark.csv_mode
@pytest.mark.asyncio
async def test_detect_change_points_no_nan():
    """Test that change point results contain no NaN/Inf values."""
    detect_change_points = _import_stat_tool("detect_change_points")
    _populate_cache_with_test_data()

    try:
        result_str = await detect_change_points()
        result = json.loads(result_str)

        for cp in result.get("change_points", []):
            assert not np.isnan(cp["before_mean"]), "before_mean is NaN"
            assert not np.isnan(cp["after_mean"]), "after_mean is NaN"
            assert not np.isnan(cp["magnitude_dollar"]), "magnitude_dollar is NaN"
            assert not np.isinf(cp["magnitude_pct"]), "magnitude_pct is Inf"

        print("[PASS] No NaN/Inf values in change point results")
    finally:
        _teardown_cache()


# ============================================================================
# Tests for compute_statistical_summary (comprehensive)
# ============================================================================

@pytest.mark.unit
@pytest.mark.csv_mode
@pytest.mark.asyncio
async def test_compute_statistical_summary_structure():
    """Test that statistical summary returns all expected sections."""
    compute_statistical_summary = _import_stat_tool("compute_statistical_summary")
    _populate_cache_with_test_data()

    try:
        result_str = await compute_statistical_summary()
        result = json.loads(result_str)

        # Should not contain an error
        assert "error" not in result, f"Got error: {result.get('error')}"

        # Core sections
        assert "top_drivers" in result
        assert "most_volatile" in result
        assert "anomalies" in result
        assert "monthly_totals" in result
        assert "summary_stats" in result

        # Enhanced sections
        assert "enhanced_top_drivers" in result
        assert "seasonal_analysis" in result
        assert "change_points" in result
        assert "mad_outliers" in result
        assert "forecasts" in result
        assert "operational_ratios" in result

        # Validate top_drivers structure
        assert len(result["top_drivers"]) > 0
        driver = result["top_drivers"][0]
        assert "item" in driver
        assert "avg" in driver
        assert "std" in driver
        assert "cv" in driver
        assert "slope_3mo" in driver

        # Validate summary_stats
        stats = result["summary_stats"]
        assert stats["total_items"] > 0
        assert stats["total_periods"] > 0

        print(f"[PASS] Statistical summary: {stats['total_items']} items, "
              f"{stats['total_periods']} periods, "
              f"{len(result['anomalies'])} anomalies")
    finally:
        _teardown_cache()


@pytest.mark.unit
@pytest.mark.csv_mode
@pytest.mark.asyncio
async def test_statistical_summary_no_nan_in_drivers():
    """Test that top_drivers contain no NaN values."""
    compute_statistical_summary = _import_stat_tool("compute_statistical_summary")
    _populate_cache_with_test_data()

    try:
        result_str = await compute_statistical_summary()
        result = json.loads(result_str)

        for driver in result.get("top_drivers", []):
            assert not np.isnan(driver["avg"]), f"NaN avg for {driver.get('item')}"
            assert not np.isnan(driver["std"]), f"NaN std for {driver.get('item')}"
            assert not np.isnan(driver["cv"]), f"NaN cv for {driver.get('item')}"
            assert not np.isinf(driver["cv"]), f"Inf cv for {driver.get('item')}"

        print("[PASS] No NaN/Inf in statistical drivers")
    finally:
        _teardown_cache()


@pytest.mark.unit
@pytest.mark.csv_mode
@pytest.mark.asyncio
async def test_statistical_summary_empty_cache():
    """Test statistical summary when cache is empty."""
    from data_analyst_agent.sub_agents.data_cache import clear_all_caches, _CSV_CACHE_FILE
    clear_all_caches()
    # Also remove the file-based cache so get_validated_csv returns None
    if _CSV_CACHE_FILE.exists():
        _CSV_CACHE_FILE.unlink()

    compute_statistical_summary = _import_stat_tool("compute_statistical_summary")
    result_str = await compute_statistical_summary()
    result = json.loads(result_str)

    assert "error" in result
    print("[PASS] Empty cache handled gracefully")


# ============================================================================
# Ops Metrics statistical insights tests (Spec 001 + 002)
# ============================================================================

def _populate_cache_with_ops_metrics_data():
    """Load ops_metrics sample data into the data cache and set up AnalysisContext."""
    from tests.fixtures.ops_metrics_contract_fixture import (
        load_ops_contract,
        load_ops_line_haul_df,
    )
    from data_analyst_agent.sub_agents.data_cache import (
        set_validated_csv,
        clear_all_caches,
        set_analysis_context,
    )
    from data_analyst_agent.semantic.models import AnalysisContext

    clear_all_caches()

    contract = load_ops_contract()
    df = load_ops_line_haul_df()

    csv_data = df.to_csv(index=False)
    set_validated_csv(csv_data)

    ctx = AnalysisContext(
        contract=contract,
        df=df,
        target_metric=contract.get_metric("total_revenue"),
        primary_dimension=contract.get_dimension("lob"),
        run_id="test_ops_stats",
        max_drill_depth=3,
    )
    set_analysis_context(ctx)
    return df


@pytest.mark.unit
@pytest.mark.ops_metrics
@pytest.mark.asyncio
async def test_compute_statistical_summary_ops_metrics():
    """Statistical summary should work with ops metrics data (multi-metric)."""
    compute_statistical_summary = _import_stat_tool("compute_statistical_summary")
    _populate_cache_with_ops_metrics_data()

    try:
        result_str = await compute_statistical_summary()
        result = json.loads(result_str)

        assert "error" not in result, f"Got error: {result.get('error')}"
        assert "top_drivers" in result
        assert "summary_stats" in result

        stats = result["summary_stats"]
        assert stats["total_items"] > 0
        assert stats["total_periods"] > 0

        print(
            f"[PASS] Ops metrics stats: {stats['total_items']} items, "
            f"{stats['total_periods']} periods"
        )
    finally:
        _teardown_cache()


@pytest.mark.unit
@pytest.mark.ops_metrics
@pytest.mark.asyncio
async def test_detect_mad_outliers_ops_metrics():
    """MAD outlier detection should work with ops metrics data."""
    detect_mad_outliers = _import_stat_tool("detect_mad_outliers")
    _populate_cache_with_ops_metrics_data()

    try:
        result_str = await detect_mad_outliers()
        result = json.loads(result_str)

        assert "error" not in result, f"Got error: {result.get('error')}"
        assert "summary" in result
        # The tool uses 'items_analyzed' in success case
        assert "items_analyzed" in result["summary"]
        assert result["summary"]["items_analyzed"] > 0
        print(f"[PASS] Ops MAD outliers: {result['summary']['total_outliers_detected']} detected")
    finally:
        _teardown_cache()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s", "--tb=short"])
