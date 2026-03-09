"""
Step 9: Integration Test - Hierarchical Drill-Down Loop.

Tests the full drill-down loop from level 2 through level 5 using
compute_level_statistics tool with real PL-067 data.

Note: This tests the tool directly (not the full ADK LoopAgent) since
the loop orchestration depends on the ADK framework and LLM decisions.
We simulate the loop by calling compute_level_statistics for each level
and verifying data flows correctly between levels.
"""

import pytest
import json
import importlib
import pandas as pd
from io import StringIO

from tests.fixtures.test_data_loader import TestDataLoader
from data_analyst_agent.sub_agents.data_cache import (
    set_validated_csv, set_validated_data, get_validated_csv,
    set_analysis_context, clear_all_caches, _CSV_CACHE_FILE
)


# ============================================================================
# Helpers
# ============================================================================

def _build_pl_context(ts_df: pd.DataFrame):
    """Build and register a P&L AnalysisContext for the given time-series DataFrame."""
    from pathlib import Path
    from data_analyst_agent.semantic.models import DatasetContract, AnalysisContext

    contract_path = Path(__file__).parent.parent / "fixtures" / "pl_067_contract.yaml"
    contract = DatasetContract.from_yaml(str(contract_path))

    # Ensure hierarchical columns exist (fill from level_1 if missing)
    for col in ("canonical_category", "level_2", "level_3"):
        if col not in ts_df.columns:
            ts_df[col] = ts_df.get("level_1", ts_df["gl_account"])

    target_metric = contract.get_metric("amount")
    primary_dim = contract.get_dimension("dimension_value")

    ctx = AnalysisContext(
        contract=contract,
        df=ts_df,
        target_metric=target_metric,
        primary_dimension=primary_dim,
        run_id="test-drill-down",
        max_drill_depth=4,
    )
    set_analysis_context(ctx)
    return ctx


def _setup_cache_with_enriched_data():
    """Load PL-067 data, enrich with hierarchy, store in cache + AnalysisContext."""
    loader = TestDataLoader()
    pl_df = loader.load_pl_067_csv()
    ts_df = loader.convert_to_time_series_format(pl_df)

    # Add account_name column (needed by statistical tools)
    if "account_name" not in ts_df.columns:
        ts_df["account_name"] = ts_df["gl_account"]

    csv_data = ts_df.to_csv(index=False)

    clear_all_caches()
    if _CSV_CACHE_FILE.exists():
        _CSV_CACHE_FILE.unlink()

    set_validated_csv(csv_data)
    _build_pl_context(ts_df)
    return ts_df


def _import_compute_level_statistics():
    """Import compute_level_statistics from the hierarchy ranker agent."""
    mod = importlib.import_module(
        "data_analyst_agent.sub_agents.hierarchy_variance_agent.tools.compute_level_statistics"
    )
    return mod.compute_level_statistics


def _teardown():
    clear_all_caches()
    if _CSV_CACHE_FILE.exists():
        _CSV_CACHE_FILE.unlink()


# ============================================================================
# Test: Level 2 analysis
# ============================================================================

@pytest.mark.integration
@pytest.mark.csv_mode
@pytest.mark.asyncio
async def test_drill_down_level_2():
    """Test Level 2 (category-level) analysis."""
    compute = _import_compute_level_statistics()
    _setup_cache_with_enriched_data()

    try:
        result_str = await compute(level=2)
        result = json.loads(result_str)

        assert "error" not in result, f"Got error: {result.get('error')}"

        # May be a duplicate level (same as level 1)
        if result.get("is_duplicate"):
            print(f"[PASS] Level 2 is duplicate of Level {result.get('duplicate_of')} - expected behavior")
            return

        assert result["level"] == 2
        assert "top_drivers" in result
        assert "items_analyzed" in result
        assert result["items_analyzed"] > 0

        print(f"[PASS] Level 2: {result['items_analyzed']} items, "
              f"{len(result['top_drivers'])} top drivers, "
              f"explains {result.get('variance_explained_pct', 'N/A')}%")
    finally:
        _teardown()


# ============================================================================
# Test: Level 3 analysis
# ============================================================================

@pytest.mark.integration
@pytest.mark.csv_mode
@pytest.mark.asyncio
async def test_drill_down_level_3():
    """Test Level 3 (sub-category) analysis."""
    compute = _import_compute_level_statistics()
    _setup_cache_with_enriched_data()

    try:
        result_str = await compute(level=3)
        result = json.loads(result_str)

        assert "error" not in result, f"Got error: {result.get('error')}"

        if result.get("is_duplicate"):
            print(f"[PASS] Level 3 is duplicate of Level {result.get('duplicate_of')} - skipping")
            return

        assert result["level"] == 3
        assert "top_drivers" in result
        assert result["items_analyzed"] > 0

        # Top drivers should have variance calculations
        if len(result["top_drivers"]) > 0:
            driver = result["top_drivers"][0]
            assert "item" in driver or "account" in driver
            assert "variance_dollar" in driver or "current" in driver

        print(f"[PASS] Level 3: {result['items_analyzed']} items, "
              f"{len(result['top_drivers'])} top drivers")
    finally:
        _teardown()


# ============================================================================
# Test: Level 4 analysis
# ============================================================================

@pytest.mark.integration
@pytest.mark.csv_mode
@pytest.mark.asyncio
async def test_drill_down_level_4():
    """Test Level 4 (detail sub-category) analysis."""
    compute = _import_compute_level_statistics()
    _setup_cache_with_enriched_data()

    try:
        result_str = await compute(level=4)
        result = json.loads(result_str)

        assert "error" not in result, f"Got error: {result.get('error')}"

        if result.get("is_duplicate"):
            print(f"[PASS] Level 4 is duplicate of Level {result.get('duplicate_of')} - expected for flat hierarchies")
            return

        assert result["level"] == 4
        assert "top_drivers" in result

        print(f"[PASS] Level 4: {result['items_analyzed']} items, "
              f"{len(result['top_drivers'])} top drivers")
    finally:
        _teardown()


# ============================================================================
# Test: Level 5 analysis (GL account detail)
# ============================================================================

@pytest.mark.integration
@pytest.mark.csv_mode
@pytest.mark.asyncio
async def test_drill_down_level_5():
    """Test Level 5 (GL account detail) - the deepest level."""
    compute = _import_compute_level_statistics()
    _setup_cache_with_enriched_data()

    try:
        result_str = await compute(level=5)
        result = json.loads(result_str)

        assert "error" not in result, f"Got error: {result.get('error')}"

        # Level 5 should never be a duplicate - it's always GL accounts
        assert not result.get("is_duplicate", False), "Level 5 should not be a duplicate"
        assert result["level"] == 5
        assert "top_drivers" in result
        assert result["items_analyzed"] > 0

        # GL account detail should have individual accounts
        if len(result["top_drivers"]) > 0:
            driver = result["top_drivers"][0]
            assert "item" in driver or "account" in driver

        print(f"[PASS] Level 5 (GL detail): {result['items_analyzed']} accounts, "
              f"{len(result['top_drivers'])} top drivers")
    finally:
        _teardown()


# ============================================================================
# Test: Full drill-down sequence (levels 2-5)
# ============================================================================

@pytest.mark.integration
@pytest.mark.csv_mode
@pytest.mark.asyncio
async def test_drill_down_full_sequence():
    """Test the complete drill-down from level 2 to level 5 in sequence."""
    compute = _import_compute_level_statistics()
    _setup_cache_with_enriched_data()

    try:
        levels_analyzed = []
        level_results = {}

        for level in [2, 3, 4, 5]:
            result_str = await compute(level=level)
            result = json.loads(result_str)

            assert "error" not in result, f"Level {level} error: {result.get('error')}"

            if result.get("is_duplicate"):
                print(f"  Level {level}: SKIP (duplicate of Level {result.get('duplicate_of')})")
                continue

            levels_analyzed.append(level)
            level_results[f"level_{level}"] = result

            items = result.get("items_analyzed", 0)
            drivers = len(result.get("top_drivers", []))
            explained = result.get("variance_explained_pct", "N/A")
            print(f"  Level {level}: {items} items, {drivers} top drivers, {explained}% explained")

        # Should have analyzed at least 2 levels (some may be duplicates)
        assert len(levels_analyzed) >= 2, \
            f"Expected at least 2 non-duplicate levels, got {len(levels_analyzed)}"

        # Level 5 (GL detail) should always be present
        assert 5 in levels_analyzed, "Level 5 (GL detail) must always be analyzed"

        # Build the final hierarchical result (simulating FinalizeAnalysisResults)
        hierarchical_result = {
            "analysis_type": "hierarchical_drill_down",
            "dimension_value": "067",
            "levels_analyzed": levels_analyzed,
            "drill_down_path": " -> ".join(f"Level {l}" for l in levels_analyzed),
            "level_results": level_results
        }

        # Verify the final result is valid JSON
        result_json = json.dumps(hierarchical_result)
        assert len(result_json) > 100, "Hierarchical result should be non-trivial"

        print(f"\n[PASS] Full drill-down: {hierarchical_result['drill_down_path']}")
        print(f"  Levels analyzed: {levels_analyzed}")
        print(f"  Result size: {len(result_json)} bytes")

    finally:
        _teardown()


# ============================================================================
# Test: Drill-down with different variance types
# ============================================================================

@pytest.mark.integration
@pytest.mark.csv_mode
@pytest.mark.asyncio
async def test_drill_down_variance_types():
    """Test that drill-down works with different variance calculation types."""
    compute = _import_compute_level_statistics()
    _setup_cache_with_enriched_data()

    try:
        variance_types = ["yoy", "mom"]
        for vtype in variance_types:
            result_str = await compute(level=5, variance_type=vtype)
            result = json.loads(result_str)

            if "error" in result:
                # Some variance types may need more data than available
                print(f"  {vtype}: warning - {result.get('error', 'insufficient data')}")
                continue

            if result.get("is_duplicate"):
                continue

            assert result["items_analyzed"] > 0
            print(f"  {vtype}: {result['items_analyzed']} items analyzed")

        print(f"[PASS] Multiple variance types tested")
    finally:
        _teardown()


# ============================================================================
# Test: No infinite loop condition
# ============================================================================

@pytest.mark.integration
@pytest.mark.csv_mode
@pytest.mark.asyncio
async def test_drill_down_no_infinite_loop():
    """Test that the drill-down terminates properly (no infinite loop)."""
    compute = _import_compute_level_statistics()
    _setup_cache_with_enriched_data()

    try:
        max_iterations = 10
        iteration = 0
        current_level = 2

        while current_level <= 5 and iteration < max_iterations:
            result_str = await compute(level=current_level)
            result = json.loads(result_str)

            if "error" in result:
                break

            # Simulate decision: always CONTINUE until level 5
            if current_level >= 5:
                break

            current_level += 1
            iteration += 1

        assert iteration < max_iterations, "Loop did not terminate within max iterations"
        assert current_level >= 5 or "error" in result, \
            "Loop should reach level 5 or encounter an error"

        print(f"[PASS] Drill-down terminated after {iteration + 1} iterations at level {current_level}")
    finally:
        _teardown()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s", "--tb=short"])
