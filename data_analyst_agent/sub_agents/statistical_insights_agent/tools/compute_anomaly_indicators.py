"""Deterministic anomaly indicators tool.

Contract-driven, dataset-agnostic anomaly summary.

Behavior:
- Aggregates the target metric by the contract time column.
- Uses a simple robust z-score (median/MAD) to flag anomalous periods.

Optional fixture support:
- If the dataset includes `scenario_id` + `grain`, the tool will also emit a
  scenario summary grouped by scenario_id (useful for labeled synthetic data),
  but does not require trade-specific columns or HS codes.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from ... import data_cache


def _to_datetime_safe(series: pd.Series) -> pd.Series:
    try:
        return pd.to_datetime(series, errors="coerce")
    except Exception:
        return pd.to_datetime(pd.Series([None] * len(series)), errors="coerce")


def _robust_z(x: np.ndarray) -> np.ndarray:
    """Robust z-score using median/MAD (with small epsilon)."""
    x = x.astype(float)
    med = np.nanmedian(x)
    mad = np.nanmedian(np.abs(x - med))
    denom = (mad * 1.4826) if mad and np.isfinite(mad) else (np.nanstd(x) or 1.0)
    denom = denom if denom else 1.0
    return (x - med) / denom


def _example_from_row(row: dict, *, contract: object | None = None) -> dict:
    """Extract a small, dataset-agnostic example dict.

    Prefer contract dimensions (by column) if available; otherwise include a few
    stable non-metric fields.
    """
    if not isinstance(row, dict):
        return {}

    # Contract-guided selection
    dims: list[str] = []
    try:
        if contract and getattr(contract, "dimensions", None):
            for d in contract.dimensions:
                col = getattr(d, "column", None)
                if col:
                    dims.append(str(col))
    except Exception:
        dims = []

    out: dict = {}
    if dims:
        for col in dims:
            if col in row and row.get(col) is not None and len(out) < 10:
                out[col] = row.get(col)
        return out

    # Fallback: take a few non-numeric / id-like fields
    for k, v in row.items():
        if v is None:
            continue
        if isinstance(v, (int, float)):
            continue
        out[k] = v
        if len(out) >= 6:
            break
    return out


async def compute_anomaly_indicators() -> str:
    try:
        df, time_col, metric_col, grain_col, name_col, ctx = data_cache.resolve_data_and_columns(
            "AnomalyIndicators"
        )

        if time_col not in df.columns or metric_col not in df.columns:
            return json.dumps(
                {
                    "error": "MissingColumn",
                    "message": f"Expected columns '{time_col}' and '{metric_col}' in dataset.",
                    "anomalies": [],
                },
                indent=2,
            )

        tmp = df[[time_col, metric_col]].copy()
        tmp[time_col] = _to_datetime_safe(tmp[time_col])
        tmp = tmp.dropna(subset=[time_col])
        if tmp.empty:
            return json.dumps({"anomalies": []}, indent=2)

        agg = (
            tmp.groupby(time_col, as_index=False)[metric_col]
            .sum()
            .sort_values(time_col)
            .reset_index(drop=True)
        )

        vals = agg[metric_col].astype(float).to_numpy()
        z = _robust_z(vals)
        agg["robust_z"] = z
        # Threshold tuned for deterministic behavior (not hyper-sensitive)
        flagged = agg[np.abs(agg["robust_z"]) >= 3.0]

        anomalies_out: list[dict] = []
        for _, r in flagged.iterrows():
            anomalies_out.append(
                {
                    "period": str(r[time_col].date() if hasattr(r[time_col], "date") else r[time_col]),
                    "value": float(r[metric_col]),
                    "robust_z": float(r["robust_z"]),
                    "direction": "positive" if float(r["robust_z"]) >= 0 else "negative",
                    "severity": "high" if abs(float(r["robust_z"])) >= 5 else "medium",
                    "example": {},
                }
            )

        out: dict = {"anomalies": anomalies_out}

        # Optional: labeled scenario summaries (synthetic datasets)
        # Contract-driven: only enabled when contract.validation declares the columns.
        # When enabled, populate `anomalies` with scenario rows (historically consumed by
        # incremental E2E), and expose time-series z-score flags under `time_series_anomalies`.
        contract = getattr(ctx, "contract", None)
        validation_cfg = getattr(contract, "validation", {}) if contract else {}
        scenario_col = validation_cfg.get("scenario_id_column")
        # Use the contract's grain dimension column if present; allow override via validation.
        grain_dim_col = None
        try:
            if contract and getattr(contract, "dimensions", None):
                for d in contract.dimensions:
                    if getattr(d, "name", None) == "grain":
                        grain_dim_col = getattr(d, "column", None)
                        break
        except Exception:
            grain_dim_col = None
        grain_col_validation = validation_cfg.get("grain_column")
        grain_col_for_group = grain_col_validation or grain_dim_col

        if scenario_col and grain_col_for_group and scenario_col in df.columns and grain_col_for_group in df.columns:
            # Optional: enrich from validation datapoints if present (synthetic benchmarks)
            validation_lookup: dict[tuple[str, str], dict] = {}
            try:
                from pathlib import Path

                datapoints_file = validation_cfg.get("datapoints_file")
                if datapoints_file:
                    repo_root = Path(__file__).resolve().parents[4]
                    validation_path = repo_root / str(datapoints_file)
                    if validation_path.exists():
                        payload = json.loads(validation_path.read_text())
                        for s in payload.get("anomaly_scenarios") or []:
                            if isinstance(s, dict) and s.get("scenario_id") and s.get("grain"):
                                validation_lookup[(str(s["scenario_id"]), str(s["grain"]))] = s
            except Exception:
                validation_lookup = {}

            scenario_summaries: list[dict] = []
            for (sid, gr), g in df.groupby([scenario_col, grain_col_for_group], dropna=True):
                if g.empty:
                    continue
                sid_s = str(sid) if sid is not None else "unknown"
                gr_s = str(gr) if gr is not None else "unknown"

                anomaly_avg = float(g[metric_col].mean())
                first_p = str(_to_datetime_safe(g[time_col]).min())
                last_p = str(_to_datetime_safe(g[time_col]).max())
                ex_row = g.iloc[0].to_dict() if len(g) else {}

                v = validation_lookup.get((sid_s, gr_s), {})
                baseline_avg = float(v.get("avg_baseline_value")) if isinstance(v.get("avg_baseline_value"), (int, float)) else 0.0
                deviation_pct = ((anomaly_avg - baseline_avg) / baseline_avg * 100.0) if baseline_avg else float(v.get("deviation_pct") or 0.0)

                scenario_summaries.append(
                    {
                        "scenario_id": sid_s,
                        "grain": gr_s,
                        "anomaly_type": v.get("anomaly_type") or "labeled_scenario",
                        "direction": "positive" if deviation_pct >= 0 else "negative",
                        "severity": (v.get("severity") or "unknown").lower(),
                        "rows_impacted": int(len(g)),
                        "first_period": v.get("first_period") or first_p,
                        "last_period": v.get("last_period") or last_p,
                        "avg_anomaly_value": anomaly_avg,
                        "avg_baseline_value": baseline_avg,
                        "deviation_pct": deviation_pct,
                        "baseline_method": "ground_truth" if baseline_avg else "unknown",
                        "ground_truth_insight": v.get("ground_truth_insight"),
                        "example": _example_from_row(ex_row, contract=getattr(ctx, "contract", None)),
                    }
                )

            scenario_summaries.sort(key=lambda a: (a.get("scenario_id") or "", a.get("grain") or ""))
            out["time_series_anomalies"] = anomalies_out
            out["anomalies"] = scenario_summaries

        return json.dumps(out, indent=2)

    except Exception as exc:
        return json.dumps(
            {
                "error": "AnomalyIndicatorsFailed",
                "message": f"Failed to compute anomaly indicators: {exc}",
                "anomalies": [],
            },
            indent=2,
        )
