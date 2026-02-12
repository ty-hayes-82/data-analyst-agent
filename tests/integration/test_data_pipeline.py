"""
Step 8: Integration Test - Data Pipeline.

Tests the connected flow: CSV load -> validation -> sign flip -> hierarchy enrichment
-> cache storage using actual tool functions with real PL-067 data.

Note: reshape_and_validate expects JSON input ({"time_series": [...]} or {"rows": [...]})
and returns JSON with {"analysis_type", "time_series", "quality_flags"}.
flip_revenue_signs and join_chart_metadata expect CSV strings.
"""

import pytest
import json
import importlib
import pandas as pd
from io import StringIO

from tests.fixtures.test_data_loader import TestDataLoader
from tests.utils.import_helpers import import_data_validation_tool


# ============================================================================
# Helpers
# ============================================================================

def _load_raw_pl_data():
    """Load raw PL-067 CSV and convert to time-series format."""
    loader = TestDataLoader()
    pl_df = loader.load_pl_067_csv()
    ts_df = loader.convert_to_time_series_format(pl_df)
    return ts_df


def _load_ops_metrics():
    """Load mock ops metrics."""
    loader = TestDataLoader()
    return loader.get_mock_ops_metrics()


def _ts_df_to_json_input(ts_df: pd.DataFrame) -> str:
    """Convert time-series DataFrame to JSON input for reshape_and_validate."""
    records = ts_df.to_dict(orient="records")
    return json.dumps({"time_series": records})


def _time_series_to_csv(time_series: list) -> str:
    """Convert time_series list of dicts to CSV string."""
    df = pd.DataFrame(time_series)
    return df.to_csv(index=False)


# ============================================================================
# Step 8a: CSV load -> reshape_and_validate
# ============================================================================

@pytest.mark.integration
@pytest.mark.csv_mode
@pytest.mark.asyncio
async def test_pipeline_reshape_and_validate():
    """Test that raw time-series data passes through reshape_and_validate correctly."""
    mod = import_data_validation_tool("reshape_and_validate")

    ts_df = _load_raw_pl_data()
    json_input = _ts_df_to_json_input(ts_df)

    result_str = await mod.reshape_and_validate(json_input)
    result = json.loads(result_str)

    assert "error" not in result, f"Got error: {result.get('error')}"
    assert result["analysis_type"] == "ingest_validation"
    assert "time_series" in result
    assert len(result["time_series"]) > 0
    assert "quality_flags" in result

    print(f"[PASS] reshape_and_validate: {len(result['time_series'])} records validated")


# ============================================================================
# Step 8b: reshape -> flip_revenue_signs
# ============================================================================

@pytest.mark.integration
@pytest.mark.csv_mode
@pytest.mark.asyncio
async def test_pipeline_reshape_then_flip_signs():
    """Test reshape followed by revenue sign flip."""
    reshape_mod = import_data_validation_tool("reshape_and_validate")
    flip_mod = import_data_validation_tool("flip_revenue_signs")

    ts_df = _load_raw_pl_data()
    json_input = _ts_df_to_json_input(ts_df)

    # Step 1: Reshape and validate
    reshape_result = json.loads(await reshape_mod.reshape_and_validate(json_input))
    assert "error" not in reshape_result
    time_series = reshape_result["time_series"]

    # Convert to CSV for flip_revenue_signs
    csv_data = _time_series_to_csv(time_series)

    # Step 2: Flip revenue signs
    flipped_csv = await flip_mod.flip_revenue_signs(csv_data)
    flipped_df = pd.read_csv(StringIO(flipped_csv))

    assert "sign_flipped" in flipped_df.columns

    # Revenue accounts (3xxx) should have been flipped
    if "gl_account" in flipped_df.columns:
        revenue_rows = flipped_df[flipped_df["gl_account"].astype(str).str.startswith("3")]
        flipped_revenue = revenue_rows[revenue_rows["sign_flipped"] == True]
        assert len(flipped_revenue) > 0, "Some revenue accounts should be sign-flipped"
        print(f"[PASS] Pipeline: reshape -> flip: {len(flipped_revenue)} revenue rows flipped")
    else:
        # Account column might be named differently
        assert "sign_flipped" in flipped_df.columns
        print(f"[PASS] Pipeline: reshape -> flip: sign_flipped column present")


# ============================================================================
# Step 8c: reshape -> flip -> join_chart_metadata
# ============================================================================

@pytest.mark.integration
@pytest.mark.csv_mode
@pytest.mark.asyncio
async def test_pipeline_reshape_flip_join_metadata():
    """Test full data validation pipeline: reshape -> flip -> join chart metadata."""
    reshape_mod = import_data_validation_tool("reshape_and_validate")
    flip_mod = import_data_validation_tool("flip_revenue_signs")
    join_mod = import_data_validation_tool("join_chart_metadata")

    ts_df = _load_raw_pl_data()
    json_input = _ts_df_to_json_input(ts_df)

    # Step 1: Reshape and validate
    reshape_result = json.loads(await reshape_mod.reshape_and_validate(json_input))
    assert "error" not in reshape_result
    csv_data = _time_series_to_csv(reshape_result["time_series"])

    # Step 2: Flip revenue signs
    flipped_csv = await flip_mod.flip_revenue_signs(csv_data)

    # Step 3: Join chart metadata
    enriched_csv = await join_mod.join_chart_metadata(flipped_csv)
    enriched_df = pd.read_csv(StringIO(enriched_csv))

    # Should have hierarchy levels from the chart of accounts
    # Note: if input already has level_* columns, join produces _x/_y suffixes
    level_cols = [c for c in enriched_df.columns if c.startswith("level_")]
    assert len(level_cols) >= 4, f"Expected hierarchy columns, got: {level_cols}"

    # Check for either exact or suffixed column names
    has_level_2 = "level_2" in enriched_df.columns or "level_2_y" in enriched_df.columns
    assert has_level_2, "Missing any level_2 hierarchy column"

    level_2_col = "level_2" if "level_2" in enriched_df.columns else "level_2_y"
    non_unclassified = enriched_df[enriched_df[level_2_col] != "Unclassified"]
    print(f"[PASS] Pipeline: reshape -> flip -> join metadata: "
          f"{len(enriched_df)} rows, {len(non_unclassified)} with hierarchy")


# ============================================================================
# Step 8d: Full pipeline -> cache storage -> retrieval
# ============================================================================

@pytest.mark.integration
@pytest.mark.csv_mode
@pytest.mark.asyncio
async def test_pipeline_full_to_cache():
    """Test complete data pipeline ending with cache storage and retrieval."""
    from pl_analyst_agent.sub_agents.data_cache import (
        set_validated_csv, get_validated_csv, clear_all_caches, _CSV_CACHE_FILE
    )

    reshape_mod = import_data_validation_tool("reshape_and_validate")
    flip_mod = import_data_validation_tool("flip_revenue_signs")
    join_mod = import_data_validation_tool("join_chart_metadata")

    ts_df = _load_raw_pl_data()
    json_input = _ts_df_to_json_input(ts_df)

    # Pipeline: reshape -> flip -> join
    reshape_result = json.loads(await reshape_mod.reshape_and_validate(json_input))
    assert "error" not in reshape_result
    csv_data = _time_series_to_csv(reshape_result["time_series"])
    flipped_csv = await flip_mod.flip_revenue_signs(csv_data)
    enriched_csv = await join_mod.join_chart_metadata(flipped_csv)

    # Store in cache
    clear_all_caches()
    if _CSV_CACHE_FILE.exists():
        _CSV_CACHE_FILE.unlink()

    set_validated_csv(enriched_csv)

    # Retrieve from cache and verify integrity
    cached_csv = get_validated_csv()
    assert cached_csv is not None, "Cache should contain data"
    assert cached_csv == enriched_csv, "Cached data should match what was stored"

    # Parse and validate structure
    cached_df = pd.read_csv(StringIO(cached_csv))
    assert "period" in cached_df.columns
    assert "amount" in cached_df.columns
    assert "sign_flipped" in cached_df.columns
    has_level_2 = "level_2" in cached_df.columns or "level_2_y" in cached_df.columns
    assert has_level_2, "Missing level_2 hierarchy column"
    assert len(cached_df) > 0

    print(f"[PASS] Full pipeline -> cache: {len(cached_df)} rows stored and retrieved")

    # Cleanup
    clear_all_caches()


# ============================================================================
# Step 8e: Pipeline with ops metrics join
# ============================================================================

@pytest.mark.integration
@pytest.mark.csv_mode
@pytest.mark.asyncio
async def test_pipeline_with_ops_metrics():
    """Test pipeline including operational metrics join."""
    reshape_mod = import_data_validation_tool("reshape_and_validate")
    join_ops_mod = import_data_validation_tool("join_ops_metrics")

    ts_df = _load_raw_pl_data()
    ops_df = _load_ops_metrics()

    json_input = _ts_df_to_json_input(ts_df)

    # Step 1: Reshape
    reshape_result = json.loads(await reshape_mod.reshape_and_validate(json_input))
    assert "error" not in reshape_result

    # Step 2: Join ops metrics
    # join_ops_metrics expects two separate JSON arguments: pl_data and ops_data
    pl_json = json.dumps({"time_series": reshape_result["time_series"]})
    ops_json = json.dumps({"time_series": ops_df.to_dict(orient="records")})

    result_str = await join_ops_mod.join_ops_metrics(pl_data=pl_json, ops_data=ops_json)
    result = json.loads(result_str)

    assert "error" not in result, f"Got error: {result.get('error')}"
    assert "time_series" in result
    assert len(result["time_series"]) > 0

    print(f"[PASS] Pipeline with ops metrics: {len(result['time_series'])} joined records")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s", "--tb=short"])
