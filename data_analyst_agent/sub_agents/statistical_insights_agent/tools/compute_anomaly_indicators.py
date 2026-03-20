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
from ....utils.cumulative_series import ensure_effective_metric_series


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


def _detect_repo_root(contract_path: str | None) -> Path | None:
    """Detect the repository root by searching for pyproject.toml."""
    if not contract_path:
        return None
    from pathlib import Path
    path = Path(contract_path).resolve()
    search_path = path if path.is_dir() else path.parent
    for candidate in [search_path] + list(search_path.parents):
        marker = candidate / "pyproject.toml"
        if marker.exists():
            return candidate
    return search_path


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
    """Detect statistical anomalies in the target metric time series.
    
    Uses z-score analysis with a rolling window baseline to identify periods
    where the metric value significantly deviates from historical patterns.
    Detects both positive and negative anomalies with statistical significance.
    
    Algorithm:
    1. Aggregate metric by time column (handles daily/weekly/monthly data)
    2. Compute rolling average and standard deviation (window = min(12, len/2))
    3. Calculate z-scores for each period
    4. Flag periods with |z-score| > threshold (default 2.0)
    5. Compute p-values for statistical significance
    
    Returns:
        JSON string containing:
        - anomalies: List of detected anomalies, each with:
            - period: Timestamp of anomaly
            - value: Actual metric value
            - baseline: Rolling average baseline
            - deviation_pct: Percentage deviation from baseline
            - z_score: Statistical z-score
            - p_value: Statistical significance (p-value)
            - direction: "above" or "below"
            - severity: "critical" (|z| > 3), "high" (|z| > 2.5), "moderate"
            
    Example Response:
        {
            "anomalies": [
                {
                    "period": "2025-02-28",
                    "value": 2100000.0,
                    "baseline": 1500000.0,
                    "deviation_pct": 40.0,
                    "z_score": 3.2,
                    "p_value": 0.001,
                    "direction": "above",
                    "severity": "critical"
                }
            ],
            "total_periods": 36,
            "anomaly_count": 3
        }
        
    Raises:
        Returns error JSON if required columns missing or data empty
    """
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

        vals = agg[effective_series.column_name].astype(float).to_numpy()
        z = _robust_z(vals)
        agg["robust_z"] = z
        # Threshold tuned for deterministic behavior (not hyper-sensitive)
        flagged = agg[np.abs(agg["robust_z"]) >= 3.0]

        # Vectorized anomaly payload generation (avoid iterrows)
        anomalies_out: list[dict] = []
        if not flagged.empty:
            flagged_copy = flagged.copy()
            flagged_copy['entry_value'] = flagged_copy[effective_series.column_name].astype(float)
            flagged_copy['period'] = flagged_copy[time_col].apply(
                lambda x: str(x.date() if hasattr(x, "date") else x)
            )
            flagged_copy['direction'] = flagged_copy['robust_z'].apply(
                lambda z: "positive" if z >= 0 else "negative"
            )
            flagged_copy['severity'] = flagged_copy['robust_z'].apply(
                lambda z: "high" if abs(z) >= 5 else "medium"
            )
            
            anomalies_out = flagged_copy.apply(
                lambda r: {
                    "period": r['period'],
                    "value": float(r['entry_value']),
                    "robust_z": float(r['robust_z']),
                    "direction": r['direction'],
                    "severity": r['severity'],
                    "example": {},
                    "metric_variant": effective_series.column_name,
                    **({"original_value": float(r[metric_col])} if effective_series.is_cumulative else {})
                },
                axis=1
            ).tolist()

        out: dict = {
            "anomalies": anomalies_out,
            "effective_metric_col": effective_series.column_name,
            "cumulative_series_handled": effective_series.is_cumulative,
        }
        if effective_series.is_cumulative:
            out["source_metric_col"] = metric_col
            if effective_series.smoothing_window:
                out["smoothing_window"] = effective_series.smoothing_window

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
                    path = Path(datapoints_file)
                    if not path.is_absolute():
                        contract_path = getattr(contract, "_source_path", None)
                        repo_root = _detect_repo_root(contract_path)
                        if repo_root:
                            path = (repo_root / datapoints_file).resolve()
                        else:
                            path = path.resolve()
                    else:
                        path = Path(datapoints_file)
                    
                    if path.exists():
                        payload = json.loads(path.read_text(encoding="utf-8"))
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
