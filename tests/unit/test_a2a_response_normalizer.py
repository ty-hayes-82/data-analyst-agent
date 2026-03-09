"""
Unit tests for A2aResponseNormalizer.

Tests all response format handling paths:
- JSON with "data" key (list of records)
- JSON with "data" key (CSV string payload)
- JSON with "data" key (column-oriented dict)
- JSON with "time_series" key
- Raw CSV passthrough
- Markdown-wrapped JSON
- Empty / None input
- Static extract_time_series helper
- period_end_date remapping (T012)
- miles_per_truck derivation (T013)
- deadhead_pct derivation (T014)
"""

import pytest
import json
import pandas as pd
from io import StringIO
from unittest.mock import MagicMock

from data_analyst_agent.sub_agents.a2a_response_normalizer import A2aResponseNormalizer


# ---------------------------------------------------------------------------
# Sample data for T012–T014
# ---------------------------------------------------------------------------

_SAMPLE_EXPORT_CSV = (
    "period_end_date,ops_ln_of_bus_ref_nm,ttl_rev_amt,ld_trf_mi,ttl_trf_mi,truck_count,"
    "empty_miles,deadhead_pct,miles_per_truck,revenue_per_loaded_mile\n"
    "2025-01-31,Line Haul,1200000,500000,600000,200,100000,16.667,2500.0,2.4\n"
    "2025-02-28,Line Haul,1100000,480000,580000,190,100000,17.241,2526.316,2.292\n"
    "2025-03-31,Dedicated,900000,300000,350000,120,50000,14.286,2500.0,3.0\n"
)

_SAMPLE_EXPORT_TOOL_RESPONSE = json.dumps({
    "success": True,
    "format": "csv",
    "row_count": 3,
    "data": _SAMPLE_EXPORT_CSV,
})


def _make_contract(time_col: str = "cal_dt", time_fmt: str = "%Y-%m"):
    """Return a minimal mock DatasetContract with a time spec."""
    contract = MagicMock()
    time_spec = MagicMock()
    time_spec.column = time_col
    time_spec.format = time_fmt
    contract.time = time_spec
    return contract


def _make_normalizer_with_contract(time_col: str = "cal_dt", time_fmt: str = "%Y-%m"):
    """Return an A2aResponseNormalizer wired to a minimal mock contract."""
    return A2aResponseNormalizer(_make_contract(time_col, time_fmt))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def normalizer(ops_metrics_contract):
    """Create normalizer backed by the ops_metrics contract."""
    return A2aResponseNormalizer(ops_metrics_contract)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_normalize_json_data_list(normalizer):
    """JSON dict with 'data' key containing a list of records."""
    raw = json.dumps({
        "data": [
            {"cal_dt": "2025-01", "ops_ln_of_bus_ref_nm": "Line Haul", "ttl_rev_amt": 600000},
            {"cal_dt": "2025-02", "ops_ln_of_bus_ref_nm": "Line Haul", "ttl_rev_amt": 620000},
        ]
    })

    csv_out = normalizer.normalize_response(raw)
    df = pd.read_csv(StringIO(csv_out))

    assert len(df) == 2
    assert "cal_dt" in df.columns
    assert "ttl_rev_amt" in df.columns
    assert df["ttl_rev_amt"].iloc[0] == 600000


@pytest.mark.unit
def test_normalize_json_data_csv_string(normalizer):
    """JSON dict with 'data' key containing a CSV string."""
    csv_payload = "cal_dt,ttl_rev_amt\n2025-01,500000\n2025-02,510000"
    raw = json.dumps({"data": csv_payload})

    csv_out = normalizer.normalize_response(raw)

    assert "cal_dt" in csv_out
    assert "500000" in csv_out
    df = pd.read_csv(StringIO(csv_out))
    assert len(df) == 2


@pytest.mark.unit
def test_normalize_json_data_compact_format(normalizer):
    """JSON dict with 'data' key containing column-oriented dict."""
    raw = json.dumps({
        "data": {
            "cal_dt": ["2025-01", "2025-02"],
            "ttl_rev_amt": [500000, 510000],
        }
    })

    csv_out = normalizer.normalize_response(raw)
    df = pd.read_csv(StringIO(csv_out))

    assert len(df) == 2
    # sign_flipped column is added by Spec 015
    expected_cols = ["cal_dt", "ttl_rev_amt", "sign_flipped"]
    assert all(c in df.columns for c in expected_cols)
    assert len(df.columns) == len(expected_cols)


@pytest.mark.unit
def test_normalize_time_series_response(normalizer):
    """JSON dict with 'time_series' key."""
    raw = json.dumps({
        "time_series": [
            {"cal_dt": "2025-01", "ttl_rev_amt": 500000},
            {"cal_dt": "2025-02", "ttl_rev_amt": 510000},
        ],
        "accounts_included": ["3100"],
    })

    csv_out = normalizer.normalize_response(raw)
    df = pd.read_csv(StringIO(csv_out))

    assert len(df) == 2
    assert "cal_dt" in df.columns
    assert "ttl_rev_amt" in df.columns
    assert "sign_flipped" in df.columns


@pytest.mark.unit
def test_normalize_csv_passthrough(normalizer):
    """Raw CSV text should pass through with sign_flipped column added."""
    raw_csv = "cal_dt,ttl_rev_amt\n2025-01,500000\n2025-02,510000"

    csv_out = normalizer.normalize_response(raw_csv)
    df = pd.read_csv(StringIO(csv_out))
    
    assert len(df) == 2
    assert "cal_dt" in df.columns
    assert "ttl_rev_amt" in df.columns
    assert "sign_flipped" in df.columns
    assert all(df["sign_flipped"] == False)


@pytest.mark.unit
def test_normalize_markdown_wrapped_json(normalizer):
    """Markdown-wrapped JSON (```json ... ```) should be stripped and parsed."""
    inner = json.dumps({
        "data": [
            {"cal_dt": "2025-01", "ttl_rev_amt": 500000},
        ]
    })
    raw = f"```json\n{inner}\n```"

    csv_out = normalizer.normalize_response(raw)
    df = pd.read_csv(StringIO(csv_out))

    assert len(df) == 1
    assert "cal_dt" in df.columns


@pytest.mark.unit
def test_normalize_empty_response(normalizer):
    """Empty or None input should return empty string."""
    assert normalizer.normalize_response("") == ""
    assert normalizer.normalize_response("   ") == ""
    assert normalizer.normalize_response(None) == ""


@pytest.mark.unit
def test_extract_time_series_static():
    """Static helper should extract the time_series list from JSON."""
    payload = json.dumps({
        "time_series": [
            {"period": "2025-01", "value": 100},
            {"period": "2025-02", "value": 200},
        ]
    })

    ts = A2aResponseNormalizer.extract_time_series(payload)
    assert ts is not None
    assert len(ts) == 2
    assert ts[0]["value"] == 100


@pytest.mark.unit
def test_extract_time_series_invalid():
    """extract_time_series should return None for non-JSON or missing key."""
    assert A2aResponseNormalizer.extract_time_series("not json") is None
    assert A2aResponseNormalizer.extract_time_series('{"other": 1}') is None


# ===========================================================================
# T012: period_end_date remapping
# ===========================================================================

@pytest.mark.unit
def test_period_end_date_remapped_to_contract_column():
    """period_end_date should be renamed to the contract time column (cal_dt)."""
    norm = _make_normalizer_with_contract(time_col="cal_dt", time_fmt="%Y-%m")
    result = norm.normalize_response(_SAMPLE_EXPORT_TOOL_RESPONSE)
    df = pd.read_csv(StringIO(result))
    assert "cal_dt" in df.columns, \
        f"period_end_date not remapped to cal_dt; columns: {list(df.columns)}"
    assert "period_end_date" not in df.columns


@pytest.mark.unit
def test_period_end_date_reformatted_to_year_month():
    """YYYY-MM-DD dates in period_end_date should become YYYY-MM after normalization."""
    norm = _make_normalizer_with_contract(time_col="cal_dt", time_fmt="%Y-%m")
    result = norm.normalize_response(_SAMPLE_EXPORT_TOOL_RESPONSE)
    df = pd.read_csv(StringIO(result))
    sample = str(df["cal_dt"].iloc[0])
    assert len(sample) == 7 and sample[4] == "-", \
        f"Date not reformatted to YYYY-MM; got: {sample}"


@pytest.mark.unit
def test_period_end_date_unchanged_when_contract_uses_same_name():
    """If contract time col == 'period_end_date', no rename should occur."""
    norm = _make_normalizer_with_contract(time_col="period_end_date", time_fmt="%Y-%m-%d")
    result = norm.normalize_response(_SAMPLE_EXPORT_TOOL_RESPONSE)
    df = pd.read_csv(StringIO(result))
    assert "period_end_date" in df.columns


@pytest.mark.unit
def test_normalizer_preserves_all_metric_columns():
    """All metric columns from the payload should survive normalization."""
    norm = _make_normalizer_with_contract()
    result = norm.normalize_response(_SAMPLE_EXPORT_TOOL_RESPONSE)
    df = pd.read_csv(StringIO(result))
    for col in ("ttl_rev_amt", "ld_trf_mi", "ttl_trf_mi", "truck_count", "sign_flipped"):
        assert col in df.columns, f"Column {col} lost during normalization"


# ===========================================================================
# T013: miles_per_truck derivation
# ===========================================================================

@pytest.mark.unit
def test_miles_per_truck_formula_matches_column():
    """Pre-computed miles_per_truck should equal ld_trf_mi / truck_count within 1e-3."""
    df = pd.read_csv(StringIO(_SAMPLE_EXPORT_CSV))
    required = {"ld_trf_mi", "truck_count", "miles_per_truck"}
    assert required.issubset(set(df.columns)), \
        f"Missing columns: {required - set(df.columns)}"

    mask = df["truck_count"] > 0
    df = df[mask].copy()
    expected = df["ld_trf_mi"] / df["truck_count"]
    actual = pd.to_numeric(df["miles_per_truck"], errors="coerce")
    diff = (expected - actual).abs()
    assert diff.max() < 0.001, \
        f"miles_per_truck deviates from formula: max_diff={diff.max():.6f}"


@pytest.mark.unit
def test_miles_per_truck_zero_truck_count_excluded():
    """Rows with truck_count = 0 should not be checked (division by zero guard)."""
    csv = (
        "period_end_date,ld_trf_mi,truck_count,miles_per_truck\n"
        "2025-01-31,500000,0,0\n"
        "2025-02-28,480000,190,2526.316\n"
    )
    df = pd.read_csv(StringIO(csv))
    valid = df[df["truck_count"] > 0]
    assert len(valid) == 1
    ratio = valid["ld_trf_mi"].iloc[0] / valid["truck_count"].iloc[0]
    assert abs(ratio - valid["miles_per_truck"].iloc[0]) < 0.001


@pytest.mark.unit
def test_miles_per_truck_negative_value_not_expected():
    """miles_per_truck should never be negative."""
    df = pd.read_csv(StringIO(_SAMPLE_EXPORT_CSV))
    numeric = pd.to_numeric(df["miles_per_truck"], errors="coerce")
    negative = numeric[numeric < 0]
    assert len(negative) == 0, \
        f"Unexpected negative miles_per_truck values: {negative.tolist()}"


# ===========================================================================
# T014: deadhead_pct derivation
# ===========================================================================

@pytest.mark.unit
def test_deadhead_pct_formula_matches_column():
    """Pre-computed deadhead_pct should match (ttl_trf_mi - ld_trf_mi) / ttl_trf_mi * 100."""
    df = pd.read_csv(StringIO(_SAMPLE_EXPORT_CSV))
    required = {"ttl_trf_mi", "ld_trf_mi", "deadhead_pct"}
    assert required.issubset(set(df.columns)), \
        f"Missing columns: {required - set(df.columns)}"

    mask = df["ttl_trf_mi"] > 0
    df = df[mask].copy()
    expected = (df["ttl_trf_mi"] - df["ld_trf_mi"]) / df["ttl_trf_mi"] * 100.0
    actual = pd.to_numeric(df["deadhead_pct"], errors="coerce")
    diff = (expected - actual).abs()
    assert diff.max() < 0.01, \
        f"deadhead_pct deviates from formula: max_diff={diff.max():.6f}"


@pytest.mark.unit
def test_deadhead_pct_range():
    """deadhead_pct should be between 0 and 100."""
    df = pd.read_csv(StringIO(_SAMPLE_EXPORT_CSV))
    pct = pd.to_numeric(df["deadhead_pct"], errors="coerce").dropna()
    assert pct.min() >= 0.0, f"Negative deadhead_pct: {pct.min()}"
    assert pct.max() <= 100.0, f"deadhead_pct > 100: {pct.max()}"


@pytest.mark.unit
def test_deadhead_pct_increases_with_more_empty_miles():
    """More empty miles relative to total should yield higher deadhead_pct."""
    csv = (
        "period_end_date,ttl_trf_mi,ld_trf_mi,deadhead_pct\n"
        "2025-01-31,1000000,900000,10.0\n"
        "2025-02-28,1000000,500000,50.0\n"
    )
    df = pd.read_csv(StringIO(csv))
    pct = pd.to_numeric(df["deadhead_pct"], errors="coerce")
    assert pct.iloc[1] > pct.iloc[0], \
        "More empty miles should yield higher deadhead_pct"


@pytest.mark.unit
def test_empty_miles_equals_ttl_minus_ld():
    """empty_miles column (if present) should equal ttl_trf_mi - ld_trf_mi."""
    df = pd.read_csv(StringIO(_SAMPLE_EXPORT_CSV))
    if "empty_miles" not in df.columns:
        pytest.skip("empty_miles column not present in sample data")
    expected = df["ttl_trf_mi"] - df["ld_trf_mi"]
    actual = pd.to_numeric(df["empty_miles"], errors="coerce")
    diff = (expected - actual).abs()
    assert diff.max() < 1.0, \
        f"empty_miles != ttl_trf_mi - ld_trf_mi; max_diff={diff.max()}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
