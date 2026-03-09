"""Trade dataset end-to-end smoke tests.

Validates that the synthetic trade fixtures align with the published
validation datapoints so we know anomaly detection math is still wired
correctly for the Semiconductors (scenario A1) shock.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import pandas as pd
import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
TRADE_DATA_PATH = REPO_ROOT / "data" / "synthetic" / "synthetic_hierarchical_trade_dataset_250k.csv"
FIXTURE_A_PATH = REPO_ROOT / "data" / "validation" / "fixture_a_lax_imports_weekly.csv"
FIXTURE_C_PATH = REPO_ROOT / "data" / "validation" / "fixture_c_minimal_lax_8542.csv"
VALIDATION_PATH = REPO_ROOT / "data" / "validation" / "validation_datapoints.json"


@lru_cache(maxsize=1)
def _load_trade_dataset() -> pd.DataFrame:
    return pd.read_csv(TRADE_DATA_PATH)


@lru_cache(maxsize=1)
def _load_validation() -> dict:
    return json.loads(VALIDATION_PATH.read_text())


@pytest.mark.e2e
@pytest.mark.trade_data
def test_total_yoy_variance_matches_validation() -> None:
    df = _load_trade_dataset()
    validation = _load_validation()["total_yoy_variance"]
    weekly = df[df["grain"] == "weekly"].copy()
    yearly_totals = weekly.groupby("year")["trade_value_usd"].sum()

    y2024 = yearly_totals.loc[2024]
    y2023 = yearly_totals.loc[2023]
    variance_pct = (y2024 - y2023) / y2023 * 100

    assert y2024 == pytest.approx(validation["y2024_total"], rel=1e-3)
    assert y2023 == pytest.approx(validation["y2023_total"], rel=1e-3)
    assert variance_pct == pytest.approx(validation["variance_pct"], abs=0.05)


@pytest.mark.e2e
@pytest.mark.trade_data
def test_region_variance_ranking_matches_validation() -> None:
    df = _load_trade_dataset()
    validation = _load_validation()["region_variance_ranking"]
    weekly = df[df["grain"] == "weekly"].copy()

    region_year = (
        weekly.groupby(["region", "year"])["trade_value_usd"].sum().unstack().fillna(0.0)
    )
    ranking = []
    for region, row in region_year.iterrows():
        y2024 = float(row.get(2024, 0.0))
        y2023 = float(row.get(2023, 0.0))
        diff = y2024 - y2023
        variance_pct = (diff / y2023 * 100) if y2023 else 0.0
        ranking.append({
            "region": region,
            "y2024": y2024,
            "y2023": y2023,
            "abs_variance": diff,
            "variance_pct": variance_pct,
        })

    # Sort by absolute variance descending to match validation order
    ranking.sort(key=lambda r: r["abs_variance"], reverse=True)

    for produced, expected in zip(ranking, validation):
        assert produced["region"] == expected["region"]
        assert produced["y2024"] == pytest.approx(expected["y2024"], rel=1e-3)
        assert produced["y2023"] == pytest.approx(expected["y2023"], rel=1e-3)
        assert produced["abs_variance"] == pytest.approx(expected["abs_variance"], rel=1e-3)
        assert produced["variance_pct"] == pytest.approx(expected["variance_pct"], abs=0.05)


@pytest.mark.e2e
@pytest.mark.trade_data
def test_seasonal_patterns_match_validation() -> None:
    df = _load_trade_dataset()
    validation = _load_validation()["seasonal_pattern"]
    monthly = df[df["grain"] == "monthly"].copy()

    monthly_avgs = monthly.groupby("month")["trade_value_usd"].mean()
    peak_month = int(monthly_avgs.idxmax())
    trough_month = int(monthly_avgs.idxmin())
    amplitude_pct = (monthly_avgs.max() - monthly_avgs.min()) / monthly_avgs.mean() * 100

    assert peak_month == validation["peak_month"]
    assert trough_month == validation["trough_month"]
    assert amplitude_pct == pytest.approx(validation["seasonal_amplitude_pct"], abs=0.5)


@pytest.mark.e2e
@pytest.mark.trade_data
def test_fixture_a_contains_a1_anomaly_rows() -> None:
    df = pd.read_csv(FIXTURE_A_PATH)
    validation = next(
        s for s in _load_validation()["anomaly_scenarios"]
        if s["scenario_id"] == "A1" and s["grain"] == "weekly"
    )

    anomaly_rows = df[df["scenario_id"] == "A1"].copy()
    assert len(anomaly_rows) == validation["rows_impacted"]
    assert anomaly_rows["period_end"].min() == validation["first_period"]
    assert anomaly_rows["period_end"].max() == validation["last_period"]


@pytest.mark.e2e
@pytest.mark.trade_data
@pytest.mark.csv_mode
def test_fixture_c_anomaly_matches_ground_truth() -> None:
    """Fixture C should reproduce the weekly A1 anomaly summary."""
    df = pd.read_csv(FIXTURE_C_PATH)
    validation = _load_validation()

    scenario = next(
        s for s in validation["anomaly_scenarios"]
        if s["scenario_id"] == "A1" and s["grain"] == "weekly"
    )

    anomaly_rows = df[df["anomaly_flag"] == 1].copy()
    baseline_rows = df[df["anomaly_flag"] == 0].copy()

    assert not anomaly_rows.empty, "Fixture C must contain labeled anomaly rows"
    assert len(anomaly_rows) == scenario["rows_impacted"]

    anomaly_avg = anomaly_rows["trade_value_usd"].mean()
    baseline_avg = baseline_rows["trade_value_usd"].mean()
    deviation_pct = (anomaly_avg - baseline_avg) / baseline_avg * 100

    assert anomaly_avg == pytest.approx(scenario["avg_anomaly_value"], rel=0.01)
    # Fixture C is a minimal slice, so its baseline average can drift slightly
    # from the canonical validation datapoint. Keep it within five percent.
    assert baseline_avg == pytest.approx(scenario["avg_baseline_value"], rel=0.05)
    assert deviation_pct == pytest.approx(scenario["deviation_pct"], abs=3)

    assert anomaly_rows["period_end"].min() == scenario["first_period"]
    assert anomaly_rows["period_end"].max() == scenario["last_period"]
    assert scenario["ground_truth_insight"] in anomaly_rows["ground_truth_insight"].iat[0]
