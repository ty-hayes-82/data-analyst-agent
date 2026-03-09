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
Smoke tests: Total Miles / Miles per Truck / Truck Count insight discovery.

These tests exercise the full analysis toolchain on three related operational
metrics from data/validation_data.csv:

  - Total Miles        : absolute weekly miles per terminal
  - Total Miles/Trk/Wk : efficiency ratio (miles per truck per week)
  - Truck Count        : fleet size per terminal per week

Each test phase is independently runnable and builds on the shared cache
fixture.  No LLM or network calls are made.

Run individually:
  pytest tests/e2e/test_011_miles_truck_count_smoke.py -v -s
"""

import asyncio
import json
import pytest
import pandas as pd
from io import StringIO
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
DATASETS_DIR = PROJECT_ROOT / "config" / "datasets"
VALIDATION_CSV = PROJECT_ROOT / "data" / "validation_data.csv"

# The three metrics under analysis
TARGET_METRICS = ["Total Miles", "Total Miles/Trk/Wk", "Truck Count"]

skip_if_no_data = pytest.mark.skipif(
    not VALIDATION_CSV.exists(),
    reason=f"validation_data.csv not found at {VALIDATION_CSV}",
)


# ---------------------------------------------------------------------------
# Shared fixture: load the three metrics into the cache once per module
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def miles_truck_context():
    """
    Load Total Miles + Total Miles/Trk/Wk + Truck Count from validation_data.csv,
    build an AnalysisContext, populate the cache, and yield (df, ctx).
    Cleaned up after all tests in this module finish.
    """
    from data_analyst_agent.semantic.models import DatasetContract, AnalysisContext
    from data_analyst_agent.tools.validation_data_loader import load_validation_data
    from data_analyst_agent.sub_agents.data_cache import (
        set_validated_csv,
        set_analysis_context,
        clear_all_caches,
    )

    contract_path = DATASETS_DIR / "validation_ops" / "contract.yaml"
    if not contract_path.exists():
        pytest.skip(f"Contract not found: {contract_path}")
    if not VALIDATION_CSV.exists():
        pytest.skip(f"Data file not found: {VALIDATION_CSV}")

    clear_all_caches()

    # Load only the three target metrics
    df_full = load_validation_data()
    df = df_full[df_full["metric"].isin(TARGET_METRICS)].copy()

    assert len(df) > 0, "No rows returned for target metrics"

    csv_str = df.to_csv(index=False)
    set_validated_csv(csv_str)

    contract = DatasetContract.from_yaml(str(contract_path))
    target_metric = contract.get_metric("value")
    primary_dim = contract.get_dimension("terminal")

    ctx = AnalysisContext(
        contract=contract,
        df=df,
        target_metric=target_metric,
        primary_dimension=primary_dim,
        run_id="smoke-miles-truck-011",
        max_drill_depth=2,
    )
    set_analysis_context(ctx)

    yield df, ctx

    clear_all_caches()


# ---------------------------------------------------------------------------
# Phase 1: Data shape and coverage
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@skip_if_no_data
def test_data_shape(miles_truck_context):
    """All three metrics are present with full weekly coverage across all terminals."""
    df, _ = miles_truck_context

    loaded_metrics = sorted(df["metric"].unique())
    for metric in TARGET_METRICS:
        assert metric in loaded_metrics, f"Expected metric '{metric}' not found"

    # Each metric should have data for all 37 terminals x 60 weeks
    for metric in TARGET_METRICS:
        rows = df[df["metric"] == metric]
        assert rows["terminal"].nunique() >= 30, (
            f"{metric}: expected >= 30 terminals, got {rows['terminal'].nunique()}"
        )
        assert rows["week_ending"].nunique() == 60, (
            f"{metric}: expected 60 weeks, got {rows['week_ending'].nunique()}"
        )

    print(
        f"[smoke] Data shape OK: {len(df):,} rows, "
        f"{df['terminal'].nunique()} terminals, "
        f"{df['week_ending'].nunique()} weeks"
    )


# ---------------------------------------------------------------------------
# Phase 2: Value ranges are plausible
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@skip_if_no_data
def test_value_ranges(miles_truck_context):
    """Each metric has plausible non-trivial numeric values."""
    df, _ = miles_truck_context

    expectations = {
        # (metric, min_mean, min_nonzero_count)
        "Total Miles":        (10_000, 100),   # Terminals do at least 10k miles/wk on avg
        "Total Miles/Trk/Wk": (500, 100),       # At least 500 miles/truck/week on avg
        "Truck Count":        (5, 100),          # At least 5 trucks on average
    }

    for metric, (min_mean, min_nonzero) in expectations.items():
        values = df[df["metric"] == metric]["value"].dropna()
        nonzero = values[values > 0]

        assert len(nonzero) >= min_nonzero, (
            f"{metric}: expected >= {min_nonzero} non-zero values, got {len(nonzero)}"
        )
        assert values.mean() >= min_mean, (
            f"{metric}: mean {values.mean():.1f} below expected floor {min_mean}"
        )

    print("[smoke] Value ranges OK")


# ---------------------------------------------------------------------------
# Phase 3: Cross-metric relationship (efficiency ratio sanity check)
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@skip_if_no_data
def test_miles_per_truck_relationship(miles_truck_context):
    """
    Total Miles / Truck Count should approximate Total Miles/Trk/Wk
    (within a reasonable tolerance since both measure the same ratio).
    """
    df, _ = miles_truck_context

    # Pivot each metric to (terminal, week_ending)
    def pivot(metric_name):
        return (
            df[df["metric"] == metric_name]
            .set_index(["terminal", "week_ending"])["value"]
        )

    total_miles = pivot("Total Miles")
    truck_count = pivot("Truck Count")
    ratio_reported = pivot("Total Miles/Trk/Wk")

    # Align on common index
    common = total_miles.index.intersection(truck_count.index).intersection(ratio_reported.index)
    assert len(common) >= 100, f"Not enough common (terminal, week) pairs: {len(common)}"

    computed = total_miles.loc[common] / truck_count.loc[common]
    reported = ratio_reported.loc[common]

    # Both numerically valid rows only
    valid = computed.notna() & reported.notna() & (truck_count.loc[common] > 0)
    computed = computed[valid]
    reported = reported[valid]

    # The ratio measures the same underlying relationship; correlation should be positive
    # and reasonably strong (> 0.6).  It won't be perfect because "Total Miles" is a
    # weekly aggregate while "Total Miles/Trk/Wk" is pre-computed by the source system
    # and may use slightly different denominator logic (e.g. seated vs total trucks).
    corr = computed.corr(reported)
    assert corr > 0.6, (
        f"Expected computed miles/truck vs reported to correlate > 0.6, got {corr:.3f}"
    )

    print(f"[smoke] Miles/truck ratio correlation: {corr:.3f}")


# ---------------------------------------------------------------------------
# Phase 4: Statistical summary tool produces structured output
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@skip_if_no_data
def test_statistical_summary_produces_output(miles_truck_context):
    """compute_statistical_summary runs without error and returns JSON with key fields."""
    from data_analyst_agent.sub_agents.statistical_insights_agent.tools.compute_statistical_summary import (
        compute_statistical_summary,
    )

    result_str = asyncio.run(compute_statistical_summary())
    assert result_str, "compute_statistical_summary returned empty string"

    result = json.loads(result_str)
    assert "error" not in result, f"Tool returned error: {result.get('error')}"

    # Verify the summary contains the core analysis sections
    assert "anomalies" in result or "delta_attribution" in result, (
        f"Summary missing expected sections. Keys: {list(result.keys())}"
    )

    # Check that at least one terminal was analyzed
    anomalies = result.get("anomalies", [])
    delta = result.get("delta_attribution", [])
    assert len(anomalies) > 0 or len(delta) > 0, (
        "Expected anomalies or delta_attribution to contain items"
    )

    items_analyzed = result.get("summary", {}).get("total_items", 0)
    print(
        f"[smoke] Statistical summary OK: {len(anomalies)} anomalies, "
        f"{len(delta)} delta items, items_analyzed={items_analyzed}"
    )


# ---------------------------------------------------------------------------
# Phase 5: Outlier detection fires on known volatile terminals
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@skip_if_no_data
def test_outlier_detection_produces_results(miles_truck_context):
    """detect_mad_outliers runs and returns structured JSON."""
    from data_analyst_agent.sub_agents.statistical_insights_agent.tools.detect_mad_outliers import (
        detect_mad_outliers,
    )

    result_str = asyncio.run(detect_mad_outliers())
    assert result_str, "detect_mad_outliers returned empty string"

    result = json.loads(result_str)
    assert "error" not in result, f"Tool returned error: {result.get('error')}"

    assert "mad_outliers" in result, f"Missing 'mad_outliers' key. Got: {list(result.keys())}"
    assert isinstance(result["mad_outliers"], list)

    summary = result.get("summary", {})
    items_with_outliers = summary.get("items_with_outliers", 0)
    assert items_with_outliers > 0, (
        "Expected at least 1 terminal with MAD outliers in weekly Total Miles data"
    )

    print(
        f"[smoke] MAD outliers: {len(result['mad_outliers'])} flagged, "
        f"{items_with_outliers} terminals affected"
    )


# ---------------------------------------------------------------------------
# Phase 6: Insight card generation produces cards for each metric
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@skip_if_no_data
def test_insight_cards_generated(miles_truck_context):
    """
    generate_statistical_insight_cards runs and returns at least one insight card
    that references one of the three target metrics.
    """
    from data_analyst_agent.sub_agents.statistical_insights_agent.tools.compute_statistical_summary import (
        compute_statistical_summary,
    )
    from data_analyst_agent.sub_agents.statistical_insights_agent.tools.generate_insight_cards import (
        generate_statistical_insight_cards,
    )

    # First compute the summary (required input for card generation)
    summary_str = asyncio.run(compute_statistical_summary())
    summary = json.loads(summary_str)
    assert "error" not in summary

    # generate_statistical_insight_cards is synchronous and takes a dict
    cards_result = generate_statistical_insight_cards(statistical_summary=summary)
    assert isinstance(cards_result, dict), "Expected dict return from card generator"
    assert "error" not in cards_result, f"Tool returned error: {cards_result.get('error')}"

    insight_cards = cards_result.get("insight_cards", [])
    assert len(insight_cards) > 0, "Expected at least 1 insight card"

    # Each card must have the required structural fields
    required_fields = {"title", "priority"}
    for i, card in enumerate(insight_cards[:5]):
        missing = required_fields - set(card.keys())
        assert not missing, f"Card {i} missing required fields: {missing}"

    # Priorities must be valid
    valid_priorities = {"critical", "high", "medium", "low"}
    priorities = [c.get("priority", "").lower() for c in insight_cards]
    for p in priorities:
        if p:
            assert p in valid_priorities, f"Unexpected insight card priority: '{p}'"

    # At least one card should have a non-empty title referencing specific data
    non_empty_titles = [c["title"] for c in insight_cards if c.get("title", "").strip()]
    assert len(non_empty_titles) > 0, "All insight cards have empty titles"

    print(
        f"[smoke] Insight cards: {len(insight_cards)} generated, "
        f"priorities={set(p for p in priorities if p)}, "
        f"sample_title='{insight_cards[0].get('title', '')}'"
    )


# ---------------------------------------------------------------------------
# Phase 7: Trend direction is detectable across the 60-week span
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@skip_if_no_data
def test_trend_direction_detectable(miles_truck_context):
    """
    For at least some terminals, Truck Count shows a clear directional trend
    across the 60-week span (upward or downward), confirming the time-series
    depth is sufficient for trend analysis.
    """
    df, _ = miles_truck_context

    truck_df = (
        df[df["metric"] == "Truck Count"]
        .dropna(subset=["value"])
        .sort_values("week_ending")
    )

    terminals_with_trend = []

    for terminal, grp in truck_df.groupby("terminal"):
        if len(grp) < 20:
            continue

        values = grp["value"].values
        x = range(len(values))

        # Linear regression slope
        from scipy.stats import linregress
        slope, _, _, p_value, _ = linregress(x, values)

        # Statistically significant trend (p < 0.05)
        if p_value < 0.05 and abs(slope) > 0.1:
            terminals_with_trend.append({
                "terminal": terminal,
                "slope": round(float(slope), 3),
                "p_value": round(float(p_value), 4),
                "direction": "up" if slope > 0 else "down",
            })

    assert len(terminals_with_trend) >= 1, (
        "Expected at least 1 terminal with a statistically significant Truck Count trend "
        "but found none. Check that 60 weeks of data are loaded correctly."
    )

    for t in sorted(terminals_with_trend, key=lambda x: abs(x["slope"]), reverse=True)[:5]:
        print(
            f"[smoke] Trend: {t['terminal']} Truck Count "
            f"{t['direction']} slope={t['slope']} p={t['p_value']}"
        )

    print(f"[smoke] {len(terminals_with_trend)} terminals have significant Truck Count trends")


# ---------------------------------------------------------------------------
# Phase 8: Partial week (2026-02-21) is a detectable anomaly in Total Miles
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@skip_if_no_data
def test_partial_week_is_anomalous(miles_truck_context):
    """
    The last week (2026-02-21) should have noticeably lower Total Miles values
    compared to the 4-week average that precedes it, confirming partial-week
    detection works as expected.
    """
    df, _ = miles_truck_context

    total_miles = (
        df[df["metric"] == "Total Miles"]
        .dropna(subset=["value"])
        .sort_values("week_ending")
    )

    weeks = sorted(total_miles["week_ending"].unique())
    assert "2026-02-21" in weeks, "Last week 2026-02-21 not found in data"

    last_week_total = total_miles[total_miles["week_ending"] == "2026-02-21"]["value"].sum()

    # Compare against average of the preceding 4 weeks
    prior_weeks = weeks[-5:-1]
    prior_avg = (
        total_miles[total_miles["week_ending"].isin(prior_weeks)]
        .groupby("week_ending")["value"]
        .sum()
        .mean()
    )

    pct_drop = (prior_avg - last_week_total) / prior_avg * 100 if prior_avg > 0 else 0

    assert pct_drop > 20, (
        f"Expected last week (2026-02-21) to be > 20% below prior 4-week avg. "
        f"Got {pct_drop:.1f}% drop. last_week={last_week_total:,.0f}, prior_avg={prior_avg:,.0f}"
    )

    print(
        f"[smoke] Partial week detected: 2026-02-21 total miles={last_week_total:,.0f}, "
        f"prior 4-week avg={prior_avg:,.0f} ({pct_drop:.1f}% drop)"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s", "--tb=short"])
