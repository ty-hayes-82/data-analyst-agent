"""Deterministic period-over-period changes tool.

Contract-driven, dataset-agnostic period-over-period summary.

Behavior:
- Aggregates the target metric by the contract time column.
- Computes change between the most recent period and the prior period.

Optional validation overlays (contract-driven):
- If the dataset declares an anomaly-flag column, compute flagged vs baseline
  averages without assuming specific column names or value encodings.
- If the dataset declares scenario metadata (ID column + datapoints file),
  attach scenario-level summaries enriched from the contract's validation file.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Iterable, Optional

import pandas as pd

from ... import data_cache
from ....utils.cumulative_series import ensure_effective_metric_series


LOGGER = logging.getLogger(__name__)


_DEFAULT_FLAG_TRUTHY_VALUES = {True, 1, "1", "true", "yes", "y", "t"}
_SCENARIO_METADATA_FIELDS = {
    "scenario_id",
    "grain",
    "anomaly_type",
    "direction",
    "severity",
    "rows_impacted",
    "first_period",
    "last_period",
    "ground_truth_insight",
}
_VALIDATION_METADATA_CACHE: dict[str, dict[str, Any]] = {}


def _to_datetime_safe(series: pd.Series) -> pd.Series:
    try:
        return pd.to_datetime(series, errors="coerce")
    except Exception:
        return pd.to_datetime(pd.Series([None] * len(series)), errors="coerce")


def _normalize_flag_value(value: Any) -> Optional[Any]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return 1 if float(value) != 0 else 0
    if isinstance(value, str):
        stripped = value.strip().lower()
        if not stripped:
            return None
        return stripped
    return None


def _normalize_truthy_tokens(tokens: Iterable[Any] | None) -> set[Any]:
    source = tokens or _DEFAULT_FLAG_TRUTHY_VALUES
    normalized: set[Any] = set()
    for token in source:
        norm = _normalize_flag_value(token)
        if norm is not None:
            normalized.add(norm)
    if not normalized:
        normalized = {True, 1, "1"}
    return normalized


def _build_flag_mask(series: pd.Series, truthy_tokens: Iterable[Any] | None = None) -> pd.Series:
    normalized_truthy = _normalize_truthy_tokens(truthy_tokens)
    normalized_series = series.apply(_normalize_flag_value)
    return normalized_series.isin(normalized_truthy)


def _detect_repo_root(contract_path: Optional[str]) -> Optional[Path]:
    if not contract_path:
        return None
    path = Path(contract_path).resolve()
    search_path = path if path.is_dir() else path.parent
    for candidate in [search_path] + list(search_path.parents):
        marker = candidate / "pyproject.toml"
        if marker.exists():
            return candidate
    return search_path


def _load_validation_metadata(contract, datapoints_file: Optional[str]) -> Optional[dict[str, Any]]:
    if not datapoints_file:
        return None
    try:
        path = Path(datapoints_file)
        if not path.is_absolute():
            repo_root = _detect_repo_root(getattr(contract, "_source_path", None))
            if repo_root:
                path = (repo_root / datapoints_file).resolve()
            else:
                path = path.resolve()
        cache_key = str(path)
        if cache_key in _VALIDATION_METADATA_CACHE:
            return _VALIDATION_METADATA_CACHE[cache_key]
        if not path.exists():
            LOGGER.debug("Validation datapoints file not found at %s", path)
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        _VALIDATION_METADATA_CACHE[cache_key] = data
        return data
    except Exception as exc:
        LOGGER.warning("Failed to load validation metadata: %s", exc)
        return None


def _scenario_metadata_lookup(metadata: Optional[dict[str, Any]], *, time_frequency: Optional[str]) -> dict[str, dict[str, Any]]:
    if not metadata:
        return {}
    scenarios = metadata.get("anomaly_scenarios")
    if not isinstance(scenarios, list):
        return {}
    freq = (time_frequency or "").lower()
    lookup: dict[str, dict[str, Any]] = {}
    for entry in scenarios:
        if not isinstance(entry, dict):
            continue
        scenario_id = entry.get("scenario_id")
        if not scenario_id:
            continue
        entry_freq = str(entry.get("grain", "")).lower()
        if freq and entry_freq and entry_freq != freq:
            continue
        scenario_key = str(scenario_id)
        if scenario_key in lookup:
            continue
        filtered = {k: entry[k] for k in _SCENARIO_METADATA_FIELDS if k in entry}
        lookup[scenario_key] = filtered
    return lookup


def _attach_validation_overlays(
    *,
    df: pd.DataFrame,
    agg: pd.DataFrame,
    metric_col: str,
    validation_cfg: dict[str, Any],
    time_frequency: Optional[str],
    contract: Any,
    out: dict,
):
    anomaly_flag_col = validation_cfg.get("anomaly_flag_column")
    truthy_tokens = validation_cfg.get("anomaly_flag_truthy_values")
    if anomaly_flag_col and anomaly_flag_col in df.columns:
        try:
            flag_mask = _build_flag_mask(df[anomaly_flag_col], truthy_tokens)
            if flag_mask.any():
                flagged = df[flag_mask]
                baseline = df[~flag_mask]
                f_avg = float(flagged[metric_col].mean()) if not flagged.empty else 0.0
                b_avg = float(baseline[metric_col].mean()) if not baseline.empty else 0.0
                f_pct = ((f_avg - b_avg) / b_avg * 100.0) if b_avg else 0.0

                out["avg_anomaly_value"] = f_avg
                out["avg_baseline_value"] = b_avg
                out["deviation_pct"] = f_pct

                out["fixture_flagged_avg"] = f_avg
                out["fixture_baseline_avg"] = b_avg
                out["fixture_deviation_pct"] = f_pct
        except Exception as exc:
            LOGGER.debug("Anomaly flag summary failed: %s", exc)

    scenario_col = validation_cfg.get("scenario_id_column")
    datapoints_file = validation_cfg.get("datapoints_file")
    scenario_metadata = _scenario_metadata_lookup(
        _load_validation_metadata(contract, datapoints_file),
        time_frequency=time_frequency,
    )

    if scenario_col and scenario_col in df.columns:
        try:
            scenario_subset = df[[scenario_col, metric_col]].dropna(subset=[scenario_col])
            if not scenario_subset.empty:
                scenario_totals = []
                total_metric = float(agg[metric_col].sum()) or 0.0

                for scenario_id, group in scenario_subset.groupby(scenario_col):
                    metric_sum = float(group[metric_col].sum())
                    avg_val = float(group[metric_col].mean()) if not group.empty else 0.0
                    share_pct = (metric_sum / total_metric * 100.0) if total_metric else 0.0
                    record = {
                        "scenario_id": str(scenario_id),
                        "row_count": int(len(group)),
                        "total_metric_value": metric_sum,
                        "avg_metric_value": avg_val,
                        "share_of_metric_pct": share_pct,
                    }
                    metadata = scenario_metadata.get(str(scenario_id))
                    if metadata:
                        record["metadata"] = metadata
                    scenario_totals.append(record)

                if scenario_totals:
                    scenario_totals.sort(key=lambda item: item["scenario_id"])
                    overlays = out.setdefault("validation_overlays", {})
                    overlays["scenario_summaries"] = scenario_totals
        except Exception as exc:
            LOGGER.debug("Scenario summary failed: %s", exc)

    if "validation_overlays" in out and not out["validation_overlays"]:
        out.pop("validation_overlays", None)


async def compute_period_over_period_changes() -> str:
    """Compute period-over-period changes for the target metric.
    
    Aggregates the target metric by the contract's time column and computes
    the change between the most recent period and the prior period. Provides
    both absolute and percentage changes.
    
    Optional validation overlays (contract-driven):
    - If dataset declares an anomaly-flag column: computes flagged vs baseline averages
    - If dataset declares scenario metadata: attaches scenario-level summaries
    
    Returns:
        JSON string containing:
        - current_period: Most recent period timestamp
        - prior_period: Previous period timestamp
        - current_value: Metric value in current period
        - prior_value: Metric value in prior period
        - absolute_change: current_value - prior_value
        - percent_change: (absolute_change / prior_value) * 100
        - validation_overlay: Optional anomaly/scenario metadata
        
    Example Response:
        {
            "current_period": "2025-02-28",
            "prior_period": "2025-01-31",
            "current_value": 1500000.0,
            "prior_value": 1400000.0,
            "absolute_change": 100000.0,
            "percent_change": 7.14,
            "validation_overlay": {...}
        }
        
    Raises:
        Returns error JSON if required columns missing or data empty after parsing
    """
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
        
        # Focus-aware period filtering
        from ....utils.focus_directives import get_focus_modes
        focus_modes = get_focus_modes(ctx.session.state if ctx and hasattr(ctx, 'session') else None)
        if "recent_weekly_trends" in focus_modes and len(agg) > 8:
            agg = agg.tail(8)  # last 8 weeks
            print("[PeriodOverPeriod] Focus mode 'recent_weekly_trends': filtering to last 8 periods")
        elif "recent_monthly_trends" in focus_modes and len(agg) > 6:
            agg = agg.tail(6)  # last 6 months
            print("[PeriodOverPeriod] Focus mode 'recent_monthly_trends': filtering to last 6 periods")

        metric_name = getattr(getattr(ctx, "target_metric", None), "name", None)
        time_frequency = None
        contract = getattr(ctx, "contract", None)
        if ctx and contract:
            time_cfg = getattr(contract, "time", None)
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

        validation_cfg = getattr(contract, "validation", {}) if contract else {}
        _attach_validation_overlays(
            df=df,
            agg=agg,
            metric_col=metric_col,
            validation_cfg=validation_cfg,
            time_frequency=time_frequency,
            contract=contract,
            out=out,
        )

        return json.dumps(out, indent=2)

    except Exception as exc:
        return json.dumps(
            {"error": "PeriodOverPeriodFailed", "message": f"Failed: {exc}"}, indent=2
        )
