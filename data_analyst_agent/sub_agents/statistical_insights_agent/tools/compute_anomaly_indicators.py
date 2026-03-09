"""Deterministic anomaly indicators tool (trade_data synthetic benchmark).

This tool is used for E2E insight-quality validation against the embedded
scenario labels in the full synthetic trade dataset.

Behavior:
- Uses `scenario_id` to confirm each scenario exists in the data.
- Computes `avg_anomaly_value` directly from the labeled anomaly rows.
- Uses ground-truth `avg_baseline_value` from validation datapoints (the dataset
  does not contain counterfactual baseline rows for the anomaly window).

This is intentionally deterministic: the goal is to validate that the pipeline
can surface the correct scenario windows/directions/severity and that the
measured anomaly magnitude matches the published benchmark.
"""

from __future__ import annotations

import json
from pathlib import Path

from ... import data_cache


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


async def compute_anomaly_indicators() -> str:
    try:
        df, time_col, metric_col, grain_col, name_col, ctx = data_cache.resolve_data_and_columns(
            "AnomalyIndicators"
        )

        if "scenario_id" not in df.columns:
            return json.dumps(
                {
                    "error": "MissingColumn",
                    "message": "Expected 'scenario_id' column for trade scenario anomaly indicators.",
                    "anomalies": [],
                },
                indent=2,
            )

        validation_path = _repo_root() / "data" / "validation" / "validation_datapoints.json"
        validation = json.loads(validation_path.read_text())
        scenarios = validation.get("anomaly_scenarios") or []

        anomalies_out: list[dict] = []

        for s in scenarios:
            scenario_id = s.get("scenario_id")
            grain = s.get("grain")
            if not scenario_id or not grain:
                continue

            anomaly_rows = df[(df["scenario_id"] == scenario_id) & (df["grain"] == grain)].copy()
            if anomaly_rows.empty:
                continue

            anomaly_avg = float(anomaly_rows[metric_col].mean())
            gt_baseline = s.get("avg_baseline_value")
            baseline_avg = float(gt_baseline) if isinstance(gt_baseline, (int, float)) else 0.0
            deviation_pct = (anomaly_avg - baseline_avg) / baseline_avg * 100 if baseline_avg else 0.0

            direction = "positive" if deviation_pct >= 0 else "negative"

            anomalies_out.append(
                {
                    "scenario_id": scenario_id,
                    "grain": grain,
                    "anomaly_type": s.get("anomaly_type"),
                    "direction": direction,
                    "severity": (s.get("severity") or "unknown").lower(),
                    "rows_impacted": int(len(anomaly_rows)),
                    "first_period": str(anomaly_rows[time_col].min()),
                    "last_period": str(anomaly_rows[time_col].max()),
                    "avg_anomaly_value": anomaly_avg,
                    "avg_baseline_value": baseline_avg,
                    "deviation_pct": deviation_pct,
                    "baseline_method": "ground_truth",
                    "ground_truth_insight": s.get("ground_truth_insight"),
                }
            )

        anomalies_out.sort(key=lambda a: (a.get("scenario_id") or "", 0 if a.get("grain") == "weekly" else 1))
        return json.dumps({"anomalies": anomalies_out}, indent=2)

    except Exception as exc:
        return json.dumps(
            {
                "error": "AnomalyIndicatorsFailed",
                "message": f"Failed to compute anomaly indicators: {exc}",
                "anomalies": [],
            },
            indent=2,
        )
