"""
Unit tests for the shared data cache module.

Tests:
- CSV round-trip (set / get)
- Ops metrics CSV round-trip
- AnalysisContext set / get
- resolve_data_and_columns helper
- Structured data cache (time series)
- Cache isolation (clear_all_caches)
"""

import pytest
import json
import pandas as pd
from io import StringIO

from data_analyst_agent.sub_agents.data_cache import (
    set_validated_csv,
    get_validated_csv,
    clear_validated_csv,
    set_supplementary_data_csv,
    get_supplementary_data_csv,
    clear_supplementary_data_csv,
    set_analysis_context,
    get_analysis_context,
    resolve_data_and_columns,
    set_validated_data,
    get_validated_data,
    get_validated_records,
    get_validated_metadata,
    clear_all_caches,
    _CSV_CACHE_FILE,
    _OPS_CACHE_FILE,
    _CONTEXT_CACHE_FILE,
)


# ---------------------------------------------------------------------------
# Setup / teardown
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_caches():
    """Ensure every test starts and ends with a clean cache."""
    clear_all_caches()
    # Also remove file artefacts
    for f in (_CSV_CACHE_FILE, _OPS_CACHE_FILE, _CONTEXT_CACHE_FILE):
        if f.exists():
            f.unlink()
    yield
    clear_all_caches()
    for f in (_CSV_CACHE_FILE, _OPS_CACHE_FILE, _CONTEXT_CACHE_FILE):
        if f.exists():
            f.unlink()


# ---------------------------------------------------------------------------
# Tests: Validated CSV cache
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_set_and_get_validated_csv():
    """Round-trip CSV storage and retrieval."""
    csv = "period,amount\n2025-01,100\n2025-02,200"
    set_validated_csv(csv)

    result = get_validated_csv()
    assert result is not None
    df = pd.read_csv(StringIO(result))
    assert len(df) == 2
    assert list(df.columns) == ["period", "amount"]


@pytest.mark.unit
def test_validated_csv_file_persistence():
    """CSV should survive memory-cache clear if file persists."""
    csv = "period,amount\n2025-01,100"
    set_validated_csv(csv)

    # Clear only the in-memory dict (not the file)
    import data_analyst_agent.sub_agents.data_cache as dc
    if isinstance(dc._validated_csv_cache, dict):
        dc._validated_csv_cache.clear()
    else:
        dc._validated_csv_cache = {}

    # Should still be readable from file
    result = get_validated_csv()
    assert result is not None
    assert "2025-01" in result


@pytest.mark.unit
def test_clear_validated_csv():
    """After clearing, get should return None (when file also removed)."""
    set_validated_csv("x,y\n1,2")
    clear_validated_csv()
    if _CSV_CACHE_FILE.exists():
        _CSV_CACHE_FILE.unlink()

    assert get_validated_csv() is None


# ---------------------------------------------------------------------------
# Tests: Ops metrics CSV cache
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_set_and_get_supplementary_data_csv():
    """Round-trip ops metrics CSV."""
    csv = "cal_dt,ttl_rev_amt\n2025-01,500000"
    set_supplementary_data_csv(csv)

    result = get_supplementary_data_csv()
    assert result is not None
    assert "500000" in result


@pytest.mark.unit
def test_clear_supplementary_data_csv():
    """After clearing, get should return None."""
    set_supplementary_data_csv("a,b\n1,2")
    clear_supplementary_data_csv()

    assert get_supplementary_data_csv() is None


# ---------------------------------------------------------------------------
# Tests: AnalysisContext cache
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_set_and_get_analysis_context(ops_metrics_analysis_context):
    """Round-trip AnalysisContext storage and retrieval."""
    ctx = ops_metrics_analysis_context
    set_analysis_context(ctx)

    retrieved = get_analysis_context()
    assert retrieved is not None
    assert retrieved.run_id == ctx.run_id
    assert retrieved.contract.name == ctx.contract.name
    assert retrieved.target_metric.name == ctx.target_metric.name


# ---------------------------------------------------------------------------
# Tests: resolve_data_and_columns
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_resolve_data_and_columns(ops_metrics_context_with_cache):
    """resolve_data_and_columns should return correct tuple from cached context."""
    df, time_col, metric_col, grain_col, name_col, ctx = resolve_data_and_columns("test")

    assert df is not None
    assert len(df) > 0
    assert time_col == "cal_dt"
    assert metric_col == "total_revenue"
    assert ctx is not None


@pytest.mark.unit
def test_resolve_data_and_columns_raises_when_empty():
    """Should raise ValueError when no context is set."""
    with pytest.raises(ValueError, match="AnalysisContext not found"):
        resolve_data_and_columns("test")


# ---------------------------------------------------------------------------
# Tests: Structured data cache (time series)
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_set_and_get_validated_data():
    """Round-trip structured data (time_series dict)."""
    data = {
        "time_series": [
            {"period": "2025-01", "gl_account": "3100", "amount": 100},
            {"period": "2025-02", "gl_account": "3100", "amount": 200},
        ],
        "metadata": {"source": "test"},
    }
    set_validated_data(data)

    result = get_validated_data()
    assert result is not None
    assert len(result["time_series"]) == 2


@pytest.mark.unit
def test_get_validated_records():
    """get_validated_records returns just the time_series list."""
    data = {
        "time_series": [
            {"period": "2025-01", "amount": 100},
        ]
    }
    set_validated_data(data)

    records = get_validated_records()
    assert len(records) == 1
    assert records[0]["amount"] == 100


@pytest.mark.unit
def test_get_validated_metadata():
    """get_validated_metadata returns summary statistics."""
    data = {
        "time_series": [
            {"period": "2025-01", "gl_account": "3100", "amount": 100},
            {"period": "2025-02", "gl_account": "3100", "amount": 200},
            {"period": "2025-01", "gl_account": "3200", "amount": 50},
        ]
    }
    set_validated_data(data)

    meta = get_validated_metadata()
    assert meta["total_records"] == 3
    assert meta["gl_accounts"] == 2
    assert meta["period_count"] == 2


# ---------------------------------------------------------------------------
# Tests: Cache isolation
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_clear_all_caches():
    """clear_all_caches should wipe CSV, structured, ops, and context caches."""
    set_validated_csv("a,b\n1,2")
    set_supplementary_data_csv("x,y\n3,4")
    set_validated_data({"time_series": [{"a": 1}]})

    clear_all_caches()

    # In-memory dicts should be empty; structured caches should be None
    import data_analyst_agent.sub_agents.data_cache as dc
    assert dc._validated_csv_cache == {}
    assert dc._ops_metrics_csv_cache == {}
    assert dc._analysis_context_cache == {}
    assert dc._get_validated_data_cache() is None


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
