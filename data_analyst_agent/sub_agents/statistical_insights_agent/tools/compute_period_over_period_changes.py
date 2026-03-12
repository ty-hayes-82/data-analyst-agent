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
from ....utils.cumulative_series import ensure_effective_metric_series


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

        metric_name = getattr(getattr(ctx, "target_metric", None), "name", None)
        time_frequency = None
        if ctx and getattr(ctx, "contract", None):
            time_cfg = getattr(ctx.contract, "time", None)
            time_frequency = getattr(time_cfg, "frequency", None) if time_cfg else None

        effective_series = ensure_effective_metric_series(
            agg,
            metric_col=metric_col,
            time_col=time_col,
            metric_name=metric_name or metric_col,
            time_frequency=time_frequency,
        )

        latest = agg.iloc[-1]
        prior = agg.iloc[-2] if len(agg) >= 2 else None
        latest_val = float(effective_series.values.iloc[-1])
        prior_val = float(effective_series.values.iloc[-2]) if len(effective_series.values) >= 2 else 0.0
        pct_change = ((latest_val - prior_val) / prior_val * 100.0) if prior_val else 0.0

        out: dict = {
            "time_col": time_col,
            "metric_col": metric_col,
            "effective_metric_col": effective_series.column_name,
            "latest_period": str(latest[time_col].date() if hasattr(latest[time_col], "date") else latest[time_col]),
            "prior_period": str(prior[time_col].date() if (prior is not None and hasattr(prior[time_col], "date")) else (prior[time_col] if prior is not None else None)),
            "latest_value": latest_val,
            "prior_value": prior_val,
            "pct_change": pct_change,
            "cumulative_series_handled": effective_series.is_cumulative,
        }

        if effective_series.is_cumulative:
            out["source_metric_col"] = metric_col
            if effective_series.smoothing_window:
                out["smoothing_window"] = effective_series.smoothing_window

        # Optional: contract-driven fixture flag support (synthetic datasets)
        # Back-compat: expose `avg_anomaly_value`/`avg_baseline_value`/`deviation_pct`.
        contract = getattr(ctx, "contract", None)
        validation_cfg = getattr(contract, "validation", {}) if contract else {}
        anomaly_flag_col = validation_cfg.get("anomaly_flag_column")
        if anomaly_flag_col and anomaly_flag_col in df.columns:
            try:
                flagged = df[df[anomaly_flag_col].astype(int) == 1]
                baseline = df[df[anomaly_flag_col].astype(int) == 0]
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
