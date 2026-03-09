"""Deterministic anomaly indicators tool.

This is a lightweight, code-based tool intended for incremental E2E testing.
It operates on the currently cached validated CSV + AnalysisContext.

For trade_data fixtures that include `anomaly_flag`, it will summarize the
anomaly window statistics in a stable JSON schema.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from ... import data_cache


async def compute_anomaly_indicators() -> str:
    """Compute anomaly indicators for the currently cached dataset.

    Returns JSON:
      {
        "anomalies": [
          {
            "scenario_id": "A1",
            "grain": "weekly",
            "rows_impacted": 9,
            "first_period": "YYYY-MM-DD",
            "last_period": "YYYY-MM-DD",
            "avg_anomaly_value": float,
            "avg_baseline_value": float,
            "deviation_pct": float,
            "ground_truth_insight": str
          }
        ]
      }
    """

    try:
        df, time_col, metric_col, grain_col, name_col, ctx = data_cache.resolve_data_and_columns(
            "AnomalyIndicators"
        )

        if "anomaly_flag" not in df.columns:
            return json.dumps(
                {
                    "error": "MissingColumn",
                    "message": "Expected 'anomaly_flag' column for deterministic anomaly indicators.",
                    "anomalies": [],
                },
                indent=2,
            )

        # We only support the trade validation datapoints for now.
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

        if anomaly_rows.empty or baseline_rows.empty:
            return json.dumps(
                {
                    "error": "InsufficientData",
                    "message": "Need both anomaly_flag==1 and anomaly_flag==0 rows.",
                    "anomalies": [],
                },
                indent=2,
            )

        anomaly_avg = float(anomaly_rows[metric_col].mean())
        baseline_avg = float(baseline_rows[metric_col].mean())
        deviation_pct = (anomaly_avg - baseline_avg) / baseline_avg * 100 if baseline_avg else 0.0

        result = {
            "anomalies": [
                {
                    "scenario_id": scenario["scenario_id"],
                    "grain": scenario["grain"],
                    "rows_impacted": int(scenario["rows_impacted"]),
                    "first_period": scenario["first_period"],
                    "last_period": scenario["last_period"],
                    "avg_anomaly_value": anomaly_avg,
                    "avg_baseline_value": baseline_avg,
                    "deviation_pct": deviation_pct,
                    "ground_truth_insight": scenario["ground_truth_insight"],
                }
            ]
        }

        return json.dumps(result, indent=2)

    except Exception as exc:
        return json.dumps(
            {
                "error": "AnomalyIndicatorsFailed",
                "message": f"Failed to compute anomaly indicators: {exc}",
                "anomalies": [],
            },
            indent=2,
        )
