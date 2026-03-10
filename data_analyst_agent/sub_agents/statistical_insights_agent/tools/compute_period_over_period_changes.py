"""Deterministic period-over-period changes tool.

Contract-driven, dataset-agnostic period-over-period summary.

Behavior:
- Aggregates the target metric by the contract time column.
- Computes change between the most recent period and the prior period.

Optional fixture support:
- If the dataset includes a boolean-ish `anomaly_flag` column, also computes the
  deviation between flagged vs non-flagged subsets (useful for synthetic/fixture
  datasets), but this is never required.
"""

from __future__ import annotations

import json

import pandas as pd

from ... import data_cache


def _to_datetime_safe(series: pd.Series) -> pd.Series:
    try:
        return pd.to_datetime(series, errors="coerce")
    except Exception:
        return pd.to_datetime(pd.Series([None] * len(series)), errors="coerce")


async def compute_period_over_period_changes() -> str:
    try:
        df, time_col, metric_col, grain_col, name_col, ctx = data_cache.resolve_data_and_columns(
            "PeriodOverPeriodChanges"
        )

        if time_col not in df.columns or metric_col not in df.columns:
            return json.dumps(
                {
                    "error": "MissingColumn",
                    "message": f"Expected columns '{time_col}' and '{metric_col}' in dataset.",
                },
                indent=2,
            )

        # Aggregate by time
        tmp = df[[time_col, metric_col]].copy()
        tmp[time_col] = _to_datetime_safe(tmp[time_col])
        tmp = tmp.dropna(subset=[time_col])
        if tmp.empty:
            return json.dumps(
                {"error": "EmptyData", "message": "No usable rows after time parsing."}, indent=2
            )

        agg = (
            tmp.groupby(time_col, as_index=False)[metric_col]
            .sum()
            .sort_values(time_col)
            .reset_index(drop=True)
        )

        latest = agg.iloc[-1]
        prior = agg.iloc[-2] if len(agg) >= 2 else None
        latest_val = float(latest[metric_col])
        prior_val = float(prior[metric_col]) if prior is not None else 0.0
        pct_change = ((latest_val - prior_val) / prior_val * 100.0) if prior_val else 0.0

        out: dict = {
            "time_col": time_col,
            "metric_col": metric_col,
            "latest_period": str(latest[time_col].date() if hasattr(latest[time_col], "date") else latest[time_col]),
            "prior_period": str(prior[time_col].date() if (prior is not None and hasattr(prior[time_col], "date")) else (prior[time_col] if prior is not None else None)),
            "latest_value": latest_val,
            "prior_value": prior_val,
            "pct_change": pct_change,
        }

        # Optional: if anomaly_flag exists, compute flagged vs baseline deltas.
        # Back-compat: expose `avg_anomaly_value`/`avg_baseline_value`/`deviation_pct`.
        if "anomaly_flag" in df.columns:
            try:
                flagged = df[df["anomaly_flag"].astype(int) == 1]
                baseline = df[df["anomaly_flag"].astype(int) == 0]
                f_avg = float(flagged[metric_col].mean()) if not flagged.empty else 0.0
                b_avg = float(baseline[metric_col].mean()) if not baseline.empty else 0.0
                f_pct = ((f_avg - b_avg) / b_avg * 100.0) if b_avg else 0.0

                out["avg_anomaly_value"] = f_avg
                out["avg_baseline_value"] = b_avg
                out["deviation_pct"] = f_pct

                # Keep the more explicit fixture-prefixed fields too
                out["fixture_flagged_avg"] = f_avg
                out["fixture_baseline_avg"] = b_avg
                out["fixture_deviation_pct"] = f_pct
            except Exception:
                pass

        return json.dumps(out, indent=2)

    except Exception as exc:
        return json.dumps(
            {"error": "PeriodOverPeriodFailed", "message": f"Failed: {exc}"}, indent=2
        )
