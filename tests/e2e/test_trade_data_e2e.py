"""Trade dataset end-to-end smoke tests.

Validates that the synthetic trade fixtures align with the published
validation datapoints so we know anomaly detection math is still wired
correctly for the Semiconductors (scenario A1) shock.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_C_PATH = REPO_ROOT / "data" / "validation" / "fixture_c_minimal_lax_8542.csv"
VALIDATION_PATH = REPO_ROOT / "data" / "validation" / "validation_datapoints.json"


def _load_validation() -> dict:
    return json.loads(VALIDATION_PATH.read_text())


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
