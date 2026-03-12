"""Helpers for detecting cumulative metrics and deriving incremental series."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class EffectiveMetricSeries:
    """Represents the effective (possibly derived) metric series to analyze."""

    values: pd.Series
    column_name: str
    is_cumulative: bool
    smoothing_applied: bool
    smoothing_window: Optional[int] = None

    def metadata(self) -> dict:
        return {
            "column_name": self.column_name,
            "is_cumulative": self.is_cumulative,
            "smoothing_applied": self.smoothing_applied,
            "smoothing_window": self.smoothing_window,
        }


def _sanitize_metric_name(name: str) -> str:
    slug = re.sub(r"[^0-9a-zA-Z]+", "_", str(name or "metric")).strip("_")
    return slug or "metric"


def _non_decreasing_share(diffs: np.ndarray) -> float:
    if diffs.size == 0:
        return 0.0
    finite_diffs = diffs[np.isfinite(diffs)]
    if finite_diffs.size == 0:
        return 0.0
    abs_diffs = np.abs(finite_diffs)
    percentile = np.percentile(abs_diffs, 10) if abs_diffs.size else 0.0
    tolerance = max(1e-6, percentile * 0.5)
    return float(np.mean(finite_diffs >= -tolerance))


def _is_cumulative(values: pd.Series, min_points: int = 6, monotonic_threshold: float = 0.85) -> bool:
    arr = values.dropna().to_numpy(dtype=float)
    if arr.size < min_points:
        return False
    diffs = np.diff(arr)
    if diffs.size == 0:
        return False
    positive_share = float(np.mean(diffs > 0)) if diffs.size else 0.0
    if positive_share < 0.6:
        return False
    if (np.nanmax(arr) - np.nanmin(arr)) <= 0:
        return False
    share = _non_decreasing_share(diffs)
    return share >= monotonic_threshold


def _apply_smoothing(series: pd.Series, window: int) -> tuple[pd.Series, bool]:
    if window <= 1 or len(series) < 2:
        return series, False
    min_periods = max(1, window // 2)
    smoothed = series.rolling(window=window, min_periods=min_periods).mean()
    smoothed = smoothed.bfill().ffill().fillna(0.0)
    return smoothed, True


def ensure_effective_metric_series(
    agg: pd.DataFrame,
    *,
    metric_col: str,
    time_col: str,
    metric_name: Optional[str] = None,
    time_frequency: Optional[str] = None,
    smoothing_window: int = 7,
) -> EffectiveMetricSeries:
    """Return the effective metric series, deriving new_<metric> when cumulative."""

    if metric_col not in agg.columns:
        raise KeyError(f"Column '{metric_col}' not present in aggregate frame")
    if time_col not in agg.columns:
        raise KeyError(f"Column '{time_col}' not present in aggregate frame")

    agg.sort_values(time_col, inplace=True)
    agg.reset_index(drop=True, inplace=True)
    working = agg.copy()
    series = pd.Series(pd.to_numeric(working[metric_col], errors="coerce"), index=working.index).fillna(0.0)

    if not _is_cumulative(series):
        return EffectiveMetricSeries(series, metric_col, False, False, None)

    derived = series.diff().fillna(series.iloc[0])
    derived = derived.clip(lower=0.0)

    smoothing_applied = False
    smoothing_win = None
    if (time_frequency or "").lower() == "daily" and smoothing_window > 1:
        derived, smoothing_applied = _apply_smoothing(derived, smoothing_window)
        smoothing_win = smoothing_window if smoothing_applied else None

    derived = derived.clip(lower=0.0)

    base_name = metric_name or metric_col
    slug = _sanitize_metric_name(base_name)
    new_col = f"new_{slug}"
    counter = 1
    while new_col in working.columns:
        counter += 1
        new_col = f"new_{slug}_{counter}"

    agg[new_col] = derived.values

    return EffectiveMetricSeries(derived, new_col, True, smoothing_applied, smoothing_win)
