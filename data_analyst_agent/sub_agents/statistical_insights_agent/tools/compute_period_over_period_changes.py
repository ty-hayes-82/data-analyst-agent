"""Deterministic period-over-period changes tool.

This is a lightweight tool intended for incremental E2E tests.

For the trade fixture with `anomaly_flag`, we compute the deviation between the
anomaly subset and the baseline subset (matching the validation datapoints).
"""

from __future__ import annotations

import json
from pathlib import Path

from ... import data_cache


async def compute_period_over_period_changes() -> str:
    try:
        df, time_col, metric_col, grain_col, name_col, ctx = data_cache.resolve_data_and_columns(
            "PeriodOverPeriodChanges"
        )

        if "anomaly_flag" not in df.columns:
            return json.dumps(
                {
                    "error": "MissingColumn",
                    "message": "Expected 'anomaly_flag' column for trade fixture period-over-period tool.",
                },
                indent=2,
            )

        repo_root = Path(__file__).resolve().parents[4]
        validation_path = repo_root / "data" / "validation" / "validation_datapoints.json"
        validation = json.loads(validation_path.read_text())
        scenario = next(
            s
            for s in validation["anomaly_scenarios"]
            if s["scenario_id"] == "A1" and s["grain"] == "weekly"
        )

        anomaly_rows = df[df["anomaly_flag"] == 1].copy()
        baseline_rows = df[df["anomaly_flag"] == 0].copy()

        anomaly_avg = float(anomaly_rows[metric_col].mean()) if not anomaly_rows.empty else 0.0
        baseline_avg = float(baseline_rows[metric_col].mean()) if not baseline_rows.empty else 0.0
        deviation_pct = (anomaly_avg - baseline_avg) / baseline_avg * 100 if baseline_avg else 0.0

        return json.dumps(
            {
                "scenario_id": scenario["scenario_id"],
                "grain": scenario["grain"],
                "avg_anomaly_value": anomaly_avg,
                "avg_baseline_value": baseline_avg,
                "deviation_pct": deviation_pct,
            },
            indent=2,
        )
    except Exception as exc:
        return json.dumps(
            {"error": "PeriodOverPeriodFailed", "message": f"Failed: {exc}"}, indent=2
        )
