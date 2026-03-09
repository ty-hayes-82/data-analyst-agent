# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Integration tests for Spec 011: Validation Data Local Cache & Insight Discovery.

Tests cover:
  - Wide-to-long ETL output shape and dtypes
  - Value cleaning (currency, percentages, nulls)
  - Data cache round-trip via the loader
  - DatasetContract loading and semantic-layer compatibility
  - TestingDataAgent integration (Validation Ops path)
  - New/Lost/Same-Store and Concentration tools against validation data (Spec 014, 017)

All tests run without network access or LLM calls.
"""

import json
import importlib
import pytest
import pandas as pd
from io import StringIO
from pathlib import Path

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
VALIDATION_CSV = DATA_DIR / "validation_data.csv"
DATASETS_DIR = PROJECT_ROOT / "config" / "datasets"


# ---------------------------------------------------------------------------
# Skip guard
# ---------------------------------------------------------------------------

def _validation_data_available() -> bool:
    return VALIDATION_CSV.exists()


skip_if_no_data = pytest.mark.skipif(
    not _validation_data_available(),
    reason=f"validation_data.csv not found at {VALIDATION_CSV}",
)


# ---------------------------------------------------------------------------
# Test 1: ETL output shape
# ---------------------------------------------------------------------------

@pytest.mark.integration
@skip_if_no_data
def test_validation_data_loader_output_shape():
    """Loader must produce > 120k rows with the 5 expected columns."""
    from data_analyst_agent.tools.validation_data_loader import load_validation_data

    df = load_validation_data()

    assert isinstance(df, pd.DataFrame), "Expected a DataFrame"
    assert len(df) > 120_000, f"Expected > 120,000 rows, got {len(df):,}"

    expected_cols = {"region", "terminal", "metric", "week_ending", "value"}
    assert expected_cols.issubset(set(df.columns)), (
        f"Missing columns: {expected_cols - set(df.columns)}"
    )

    # At least one region and 50+ terminals
    assert df["region"].nunique() >= 1
    assert df["terminal"].nunique() >= 30, (
        f"Expected >= 30 terminals, found {df['terminal'].nunique()}"
    )

    # At least 30 distinct metrics
    assert df["metric"].nunique() >= 30, (
        f"Expected >= 30 metrics, found {df['metric'].nunique()}"
    )

    # 60 weeks expected
    assert df["week_ending"].nunique() == 60, (
        f"Expected 60 weeks, found {df['week_ending'].nunique()}"
    )


# ---------------------------------------------------------------------------
# Test 2: Value cleaning
# ---------------------------------------------------------------------------

@pytest.mark.integration
@skip_if_no_data
def test_value_cleaning_currency_and_percentages():
    """Currency strings, quoted numbers, percentages, and dashes all become float."""
    from data_analyst_agent.tools.validation_data_loader import load_validation_data

    df = load_validation_data()

    assert pd.api.types.is_float_dtype(df["value"]), (
        f"Expected float dtype for 'value', got {df['value'].dtype}"
    )

    non_null = df["value"].dropna()
    assert len(non_null) > 0, "All values are NaN"

    # Revenue metrics should be numeric, not string artefacts
    rev_rows = df[df["metric"].str.contains("Rev/Trk/Wk", na=False)]
    assert len(rev_rows) > 0, "No Rev/Trk/Wk rows found"
    assert rev_rows["value"].notna().sum() > 0, "Rev/Trk/Wk values are all NaN"

    # Percentage metric (Turnover %) should yield raw float, not string
    pct_rows = df[df["metric"].str.contains("Turnover", na=False)]
    if len(pct_rows) > 0:
        valid = pct_rows["value"].dropna()
        assert len(valid) > 0, "Turnover % values all NaN"
        assert (valid > 0).any(), "Expected some positive Turnover % values"


@pytest.mark.integration
@skip_if_no_data
def test_dash_values_become_nan():
    """Rows with dash ('-') source values must be NaN, not zero or string."""
    from data_analyst_agent.tools.validation_data_loader import load_validation_data

    df = load_validation_data()

    # The value column must not contain string dashes
    str_values = df["value"].dropna().astype(str)
    assert not str_values.str.contains(r"^\s*-\s*$", regex=True).any(), (
        "Found raw '-' strings in value column"
    )


# ---------------------------------------------------------------------------
# Test 3: Date parsing
# ---------------------------------------------------------------------------

@pytest.mark.integration
@skip_if_no_data
def test_week_ending_date_format():
    """week_ending column must be YYYY-MM-DD strings, earliest 2025-01-04."""
    from data_analyst_agent.tools.validation_data_loader import load_validation_data

    df = load_validation_data()

    dates = pd.to_datetime(df["week_ending"], errors="coerce")
    assert dates.isna().sum() == 0, (
        f"{dates.isna().sum()} week_ending values could not be parsed"
    )

    assert dates.min().strftime("%Y-%m-%d") == "2025-01-04", (
        f"Expected earliest date 2025-01-04, got {dates.min().strftime('%Y-%m-%d')}"
    )
    assert dates.max().strftime("%Y-%m-%d") == "2026-02-21", (
        f"Expected latest date 2026-02-21, got {dates.max().strftime('%Y-%m-%d')}"
    )


# ---------------------------------------------------------------------------
# Test 4: Filtering parameters
# ---------------------------------------------------------------------------

@pytest.mark.integration
@skip_if_no_data
def test_region_filter():
    """region_filter keeps only matching rows."""
    from data_analyst_agent.tools.validation_data_loader import load_validation_data

    df_full = load_validation_data()
    df_central = load_validation_data(region_filter="Central")

    assert len(df_central) > 0, "No rows returned for region=Central"
    assert len(df_central) < len(df_full), "Filter should reduce row count"
    assert df_central["region"].str.lower().unique().tolist() == ["central"]


@pytest.mark.integration
@skip_if_no_data
def test_metric_filter():
    """metric_filter keeps only rows whose metric name contains the substring."""
    from data_analyst_agent.tools.validation_data_loader import load_validation_data

    df = load_validation_data(metric_filter="Truck Count")

    assert len(df) > 0, "No rows returned for metric_filter='Truck Count'"
    assert df["metric"].str.contains("Truck Count", na=False).all()


@pytest.mark.integration
@skip_if_no_data
def test_exclude_partial_week():
    """exclude_partial_week=True drops the 2/21/2026 column."""
    from data_analyst_agent.tools.validation_data_loader import load_validation_data

    df_with = load_validation_data()
    df_without = load_validation_data(exclude_partial_week=True)

    assert "2026-02-21" in df_with["week_ending"].values
    assert "2026-02-21" not in df_without["week_ending"].values
    assert df_without["week_ending"].nunique() == 59


# ---------------------------------------------------------------------------
# Test 5: Cache round-trip
# ---------------------------------------------------------------------------

@pytest.mark.integration
@skip_if_no_data
def test_cache_roundtrip():
    """Load data -> store in cache -> retrieve -> parse back to DataFrame."""
    from data_analyst_agent.tools.validation_data_loader import load_validation_data
    from data_analyst_agent.sub_agents.data_cache import (
        set_validated_csv,
        get_validated_csv,
        clear_all_caches,
    )

    clear_all_caches()
    try:
        df = load_validation_data()
        csv_str = df.to_csv(index=False)
        set_validated_csv(csv_str)

        retrieved = get_validated_csv()
        assert retrieved is not None, "Cache returned None after set"

        df2 = pd.read_csv(StringIO(retrieved))
        assert len(df2) == len(df), (
            f"Round-trip row count mismatch: {len(df)} -> {len(df2)}"
        )
        assert set(df2.columns) == set(df.columns), "Column mismatch after round-trip"
    finally:
        clear_all_caches()


# ---------------------------------------------------------------------------
# Test 6: DatasetContract loads and is compatible with semantic layer
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_validation_ops_contract_loads():
    """validation_ops contract.yaml must load without errors."""
    from data_analyst_agent.semantic.models import DatasetContract

    contract_path = DATASETS_DIR / "validation_ops" / "contract.yaml"
    assert contract_path.exists(), f"Contract not found: {contract_path}"

    contract = DatasetContract.from_yaml(str(contract_path))

    assert contract.name == "Validation Ops"
    assert contract.time.column == "week_ending"
    assert contract.time.frequency == "weekly"


@pytest.mark.integration
def test_validation_ops_contract_has_required_fields():
    """Contract must expose the metric, terminal dimension, and hierarchy."""
    from data_analyst_agent.semantic.models import DatasetContract

    contract_path = DATASETS_DIR / "validation_ops" / "contract.yaml"
    contract = DatasetContract.from_yaml(str(contract_path))

    # Metric
    value_metric = contract.get_metric("value")
    assert value_metric is not None
    assert value_metric.column == "value"

    # Primary dimension
    terminal_dim = contract.get_dimension("terminal")
    assert terminal_dim is not None
    assert terminal_dim.role == "primary", f"Expected role 'primary', got '{terminal_dim.role}'"

    # Hierarchy
    assert len(contract.hierarchies) >= 1
    hierarchy = contract.hierarchies[0]
    assert "terminal" in hierarchy.children


# ---------------------------------------------------------------------------
# Test 7: AnalysisContext construction from validation_ops data
# ---------------------------------------------------------------------------

@pytest.mark.integration
@skip_if_no_data
def test_analysis_context_construction():
    """AnalysisContext can be built from the loader output + validation_ops contract."""
    from data_analyst_agent.semantic.models import DatasetContract, AnalysisContext
    from data_analyst_agent.tools.validation_data_loader import load_validation_data

    contract_path = DATASETS_DIR / "validation_ops" / "contract.yaml"
    contract = DatasetContract.from_yaml(str(contract_path))

    df = load_validation_data(metric_filter="Truck Count")

    target_metric = contract.get_metric("value")
    primary_dim = contract.get_dimension("terminal")

    ctx = AnalysisContext(
        contract=contract,
        df=df,
        target_metric=target_metric,
        primary_dimension=primary_dim,
        run_id="test-validation-011",
        max_drill_depth=2,
    )

    assert ctx is not None
    assert len(ctx.df) > 0
    assert ctx.target_metric.column == "value"
    assert ctx.primary_dimension.column == "terminal"


# ---------------------------------------------------------------------------
# Test 8: DatasetResolver recognizes validation_ops
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_dataset_resolver_finds_validation_ops(monkeypatch):
    """get_active_dataset() returns 'validation_ops' when env var is set."""
    import importlib
    import data_analyst_agent.sub_agents.data_cache  # noqa: ensure cache module loaded

    monkeypatch.setenv("ACTIVE_DATASET", "validation_ops")

    # Force reload of cache
    from config import dataset_resolver
    dataset_resolver.clear_dataset_cache()

    dataset = dataset_resolver.get_active_dataset()
    assert dataset == "validation_ops"

    contract_path = dataset_resolver.get_dataset_path("contract.yaml")
    assert contract_path.exists()

    dataset_resolver.clear_dataset_cache()


# ---------------------------------------------------------------------------
# Helpers: Populate cache with validation_ops data for agent tool tests
# ---------------------------------------------------------------------------

def _populate_cache_with_validation_ops(metric_filter: str = "Truck Count", exclude_partial: bool = True):
    """Load validation data, set cache and AnalysisContext for statistical tools."""
    from data_analyst_agent.tools.validation_data_loader import load_validation_data
    from data_analyst_agent.sub_agents.data_cache import set_validated_csv, set_analysis_context, clear_all_caches
    from data_analyst_agent.semantic.models import DatasetContract, AnalysisContext

    clear_all_caches()

    df = load_validation_data(
        metric_filter=metric_filter,
        exclude_partial_week=exclude_partial,
    )
    csv_str = df.to_csv(index=False)
    set_validated_csv(csv_str)

    contract_path = DATASETS_DIR / "validation_ops" / "contract.yaml"
    contract = DatasetContract.from_yaml(str(contract_path))
    setattr(contract, "_source_path", str(contract_path))
    target_metric = contract.get_metric("value")
    primary_dim = contract.get_dimension("terminal")

    ctx = AnalysisContext(
        contract=contract,
        df=df,
        target_metric=target_metric,
        primary_dimension=primary_dim,
        run_id="test-validation-011-tools",
        max_drill_depth=2,
    )
    set_analysis_context(ctx)
    return df


def _teardown_cache():
    from data_analyst_agent.sub_agents.data_cache import clear_all_caches
    clear_all_caches()


# ---------------------------------------------------------------------------
# Test 9: New/Lost/Same-Store tool on validation data (Spec 014)
# ---------------------------------------------------------------------------

@pytest.mark.integration
@skip_if_no_data
@pytest.mark.asyncio
async def test_new_lost_same_store_on_validation_data():
    """New/Lost/Same-Store decomposition runs on validation data and passes sum check."""
    _populate_cache_with_validation_ops()

    try:
        mod = importlib.import_module(
            "data_analyst_agent.sub_agents.statistical_insights_agent.tools.compute_new_lost_same_store"
        )
        compute_nlss = getattr(mod, "compute_new_lost_same_store")

        result_str = await compute_nlss()
        result = json.loads(result_str)

        assert "error" not in result, f"New/Lost/Same-Store failed: {result.get('error')}"
        if result.get("warning") == "InsufficientPeriods":
            pytest.skip("Validation data had insufficient periods for NLSS")

        summary = result.get("summary", {})
        new_total = summary.get("new_total", 0)
        lost_total = summary.get("lost_total", 0)
        same_store_delta = summary.get("same_store_delta", 0)
        total_delta = summary.get("total_delta", 0)

        computed = new_total - lost_total + same_store_delta
        assert abs(computed - total_delta) < 0.01, (
            f"Sum check failed: new_total - lost_total + same_store_delta = {computed}, total_delta = {total_delta}"
        )

        assert "current_period" in result
        assert "prior_period" in result
        assert "top_new" in result
        assert "top_lost" in result
        assert "top_same_store_movers" in result
    finally:
        _teardown_cache()


@pytest.mark.integration
@skip_if_no_data
@pytest.mark.asyncio
async def test_concentration_analysis_on_validation_data():
    """Concentration/Pareto analysis runs on validation data and returns valid metrics."""
    _populate_cache_with_validation_ops()

    try:
        mod = importlib.import_module(
            "data_analyst_agent.sub_agents.statistical_insights_agent.tools.compute_concentration_analysis"
        )
        compute_conc = getattr(mod, "compute_concentration_analysis")

        result_str = await compute_conc()
        result = json.loads(result_str)

        assert "error" not in result, f"Concentration analysis failed: {result.get('error')}"
        if result.get("warning") in ("TooFewEntities", "InsufficientPeriods"):
            pytest.skip(f"Validation data triggered warning: {result.get('warning')}")

        lp = result.get("latest_period", {})
        assert lp, "latest_period section missing"
        assert "hhi" in lp
        assert "gini" in lp
        assert "pareto_count" in lp
        assert "pareto_ratio" in lp
        assert "total_entities" in lp
        assert 0 <= lp["gini"] <= 1, f"Gini out of range: {lp['gini']}"
        assert lp["hhi"] >= 0, f"HHI negative: {lp['hhi']}"

        summary = result.get("summary", {})
        assert summary.get("entities_analyzed", 0) >= 2
        assert "concentration_level" in summary

        variance = result.get("variance_concentration", {})
        assert "pareto_ratio" in variance
        assert "persistent_top_movers" in variance
    finally:
        _teardown_cache()


# ---------------------------------------------------------------------------
# Test 10: Full statistical summary includes new tools on validation data
# ---------------------------------------------------------------------------

@pytest.mark.integration
@skip_if_no_data
@pytest.mark.asyncio
async def test_statistical_summary_includes_new_tools_on_validation_data():
    """compute_statistical_summary run on validation data includes new_lost_same_store and concentration_analysis."""
    _populate_cache_with_validation_ops()

    try:
        mod = importlib.import_module(
            "data_analyst_agent.sub_agents.statistical_insights_agent.tools.compute_statistical_summary"
        )
        compute_summary = getattr(mod, "compute_statistical_summary")

        result_str = await compute_summary()
        result = json.loads(result_str)

        assert "error" not in result, f"Statistical summary failed: {result.get('error')}"

        assert "new_lost_same_store" in result
        nlss = result["new_lost_same_store"]
        assert isinstance(nlss, dict)
        if "error" not in nlss and "warning" not in nlss:
            assert "summary" in nlss
            assert "top_new" in nlss
            assert "top_same_store_movers" in nlss

        assert "concentration_analysis" in result
        ca = result["concentration_analysis"]
        assert isinstance(ca, dict)
        if "error" not in ca and "warning" not in ca:
            assert "latest_period" in ca
            assert "summary" in ca
            assert ca["latest_period"].get("total_entities", 0) >= 1

        advanced = result.get("metadata", {}).get("advanced_methods", [])
        assert "New/Lost/Same-Store decomposition" in advanced
        assert "Concentration / Pareto analysis (HHI, Gini)" in advanced
    finally:
        _teardown_cache()


# ---------------------------------------------------------------------------
# Test 11b: Rev/Trk/Wk aggregate-then-derive (Spec 025)
# ---------------------------------------------------------------------------

@pytest.mark.integration
@skip_if_no_data
@pytest.mark.asyncio
async def test_rev_trk_wk_aggregate_then_derive():
    """Rev/Trk/Wk period totals must be sum(revenue)/sum(truck_count), not sum(ratio). Plausible range 2k-6k."""
    # Use list for exact match so we get only "Rev/Trk/Wk" (not Solo/Teams/Mentor Rev/Trk/Wk)
    _populate_cache_with_validation_ops(metric_filter=["Rev/Trk/Wk"])

    try:
        mod = importlib.import_module(
            "data_analyst_agent.sub_agents.statistical_insights_agent.tools.compute_statistical_summary"
        )
        compute_summary = getattr(mod, "compute_statistical_summary")

        result_str = await compute_summary()
        result = json.loads(result_str)

        assert "error" not in result, f"Statistical summary failed: {result.get('error')}"
        monthly_totals = result.get("monthly_totals") or {}
        assert monthly_totals, "monthly_totals should be present"

        for period, total in monthly_totals.items():
            # Rev/Trk/Wk in $/truck/week: network total should be 2k-6k (not 122k+ from summing ratios)
            assert 500 <= total <= 10000, (
                f"Rev/Trk/Wk total for {period} should be plausible (500-10k), got {total}. "
                "If 122k+, aggregate-then-derive is not applied."
            )
    finally:
        _teardown_cache()


# ---------------------------------------------------------------------------
# Test 11: Insight cards from new tools on validation data
# ---------------------------------------------------------------------------

@pytest.mark.integration
@skip_if_no_data
def test_insight_cards_include_new_tools_on_validation_data():
    """generate_statistical_insight_cards produces cards from NLSS and concentration when summary contains them."""
    from data_analyst_agent.sub_agents.statistical_insights_agent.tools.generate_insight_cards import (
        generate_statistical_insight_cards,
        _build_new_lost_same_store_cards,
        _build_concentration_cards,
    )

    nlss_sample = {
        "summary": {"new_count": 2, "lost_count": 1, "same_store_count": 10, "total_delta": 50,
                    "new_total": 60, "lost_total": 10, "same_store_delta": 0,
                    "new_pct_of_delta": 120, "lost_pct_of_delta": -20},
        "top_new": [{"item": "T1", "item_name": "Terminal 1", "current_value": 40}],
        "top_lost": [{"item": "T0", "item_name": "Terminal 0", "prior_value": 10}],
        "top_same_store_movers": [],
    }
    conc_sample = {
        "latest_period": {"total_entities": 30, "pareto_count": 6, "pareto_ratio": 0.2,
                          "hhi": 1200, "hhi_label": "Unconcentrated (<1500)", "gini": 0.5,
                          "top_5_share": 0.6, "top_10_share": 0.8},
        "concentration_trend": {"hhi_slope": 5, "hhi_slope_p_value": 0.08, "hhi_direction": "increasing"},
        "variance_concentration": {"persistent_top_movers": []},
        "summary": {},
    }

    cards_nlss = _build_new_lost_same_store_cards(nlss_sample, grand_total=1000)
    cards_conc = _build_concentration_cards(conc_sample)

    assert isinstance(cards_nlss, list)
    assert isinstance(cards_conc, list)
    assert len(cards_conc) >= 1, "Concentration should produce at least Portfolio Concentration card"
    for card in cards_nlss + cards_conc:
        assert "title" in card
        assert "impact_score" in card
        assert "priority" in card
        assert card["priority"] in ("low", "medium", "high", "critical")

    fake_summary = {
        "new_lost_same_store": nlss_sample,
        "concentration_analysis": conc_sample,
        "summary_stats": {},
        "monthly_totals": {},
    }
    out = generate_statistical_insight_cards(fake_summary)
    assert "insight_cards" in out
    assert len(out["insight_cards"]) >= 1, "Should produce at least one insight card"
    titles = [c["title"] for c in out["insight_cards"]]
    has_conc = any("Concentration" in t for t in titles)
    assert has_conc, "Ranked cards should include at least one concentration card from concentration_analysis"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
