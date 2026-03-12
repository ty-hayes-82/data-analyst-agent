from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, Dict, Any

import pandas as pd


@dataclass(frozen=True)
class TemporalGrainResult:
    temporal_grain: str
    detection_confidence: float
    detected_anchor: str
    periods_analyzed: int
    weekly_cadence_ratio: float
    monthly_cadence_ratio: float
    month_end_ratio: float
    dominant_weekday_ratio: float
    dominant_weekday: Optional[int]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "temporal_grain": self.temporal_grain,
            "detection_confidence": self.detection_confidence,
            "detected_anchor": self.detected_anchor,
            "periods_analyzed": self.periods_analyzed,
            "weekly_cadence_ratio": self.weekly_cadence_ratio,
            "monthly_cadence_ratio": self.monthly_cadence_ratio,
            "month_end_ratio": self.month_end_ratio,
            "dominant_weekday_ratio": self.dominant_weekday_ratio,
            "dominant_weekday": self.dominant_weekday,
        }


_CANONICAL_GRAIN_ALIASES = {
    "d": "daily",
    "day": "daily",
    "daily": "daily",
    "w": "weekly",
    "wk": "weekly",
    "week": "weekly",
    "weekly": "weekly",
    "m": "monthly",
    "mo": "monthly",
    "mon": "monthly",
    "month": "monthly",
    "monthly": "monthly",
    "q": "quarterly",
    "qr": "quarterly",
    "quarter": "quarterly",
    "quarterly": "quarterly",
    "y": "yearly",
    "yr": "yearly",
    "year": "yearly",
    "annual": "yearly",
    "annually": "yearly",
    "yearly": "yearly",
}

_PERIOD_UNIT_BY_GRAIN = {
    "daily": "day",
    "weekly": "week",
    "monthly": "month",
    "quarterly": "quarter",
    "yearly": "year",
}

_SHORT_DELTA_BY_GRAIN = {
    "daily": "DoD",
    "weekly": "WoW",
    "monthly": "MoM",
    "quarterly": "QoQ",
    "yearly": "YoY",
}

_PERIOD_PHRASE_TEMPLATE = {
    "daily": "the day ending {period_end}",
    "weekly": "the week ending {period_end}",
    "monthly": "the month ending {period_end}",
    "quarterly": "the quarter ending {period_end}",
    "yearly": "the year ending {period_end}",
}


def normalize_temporal_grain(value: Optional[str]) -> str:
    """Map arbitrary frequency/grain labels to canonical values."""
    if value is None:
        return "unknown"
    normalized = str(value).strip().lower()
    if not normalized:
        return "unknown"
    return _CANONICAL_GRAIN_ALIASES.get(
        normalized,
        normalized if normalized in _PERIOD_UNIT_BY_GRAIN else "unknown",
    )


def temporal_grain_to_period_unit(grain: Optional[str]) -> str:
    """Return the singular period unit for a canonical grain."""
    return _PERIOD_UNIT_BY_GRAIN.get(normalize_temporal_grain(grain), "period")


def temporal_grain_to_short_delta_label(grain: Optional[str]) -> str:
    """Return the short comparison label (WoW, MoM, etc.) for the grain."""
    return _SHORT_DELTA_BY_GRAIN.get(normalize_temporal_grain(grain), "PoP")


def _empty_result(periods: int = 0) -> TemporalGrainResult:
    return TemporalGrainResult(
        temporal_grain="unknown",
        detection_confidence=0.0,
        detected_anchor="unknown",
        periods_analyzed=periods,
        weekly_cadence_ratio=0.0,
        monthly_cadence_ratio=0.0,
        month_end_ratio=0.0,
        dominant_weekday_ratio=0.0,
        dominant_weekday=None,
    )


def detect_temporal_grain(
    dates: Iterable[Any],
    cadence_threshold: float = 0.75,
    anchor_threshold: float = 0.70,
    minimum_periods: int = 8,
) -> TemporalGrainResult:
    """Detect weekly vs monthly period-end grain from a sequence of dates."""
    series = pd.to_datetime(pd.Series(list(dates)), errors="coerce").dropna()
    if series.empty:
        return _empty_result(0)

    unique_periods = pd.Series(sorted(series.dt.normalize().unique()))
    periods = int(len(unique_periods))
    if periods < minimum_periods:
        return _empty_result(periods)

    deltas = unique_periods.diff().dt.days.dropna()
    if deltas.empty:
        return _empty_result(periods)

    weekly_cadence_ratio = float(((deltas >= 6) & (deltas <= 8)).mean())
    monthly_cadence_ratio = float(((deltas >= 27) & (deltas <= 32)).mean())
    month_end_ratio = float(unique_periods.dt.is_month_end.mean())

    weekday_counts = unique_periods.dt.weekday.value_counts(normalize=True)
    if weekday_counts.empty:
        dominant_weekday = None
        dominant_weekday_ratio = 0.0
    else:
        dominant_weekday = int(weekday_counts.index[0])
        dominant_weekday_ratio = float(weekday_counts.iloc[0])

    weekly_score = min(weekly_cadence_ratio, dominant_weekday_ratio)
    monthly_score = min(monthly_cadence_ratio, month_end_ratio)

    if weekly_cadence_ratio >= cadence_threshold and dominant_weekday_ratio >= anchor_threshold:
        return TemporalGrainResult(
            temporal_grain="weekly",
            detection_confidence=round(weekly_score, 4),
            detected_anchor="week_end",
            periods_analyzed=periods,
            weekly_cadence_ratio=round(weekly_cadence_ratio, 4),
            monthly_cadence_ratio=round(monthly_cadence_ratio, 4),
            month_end_ratio=round(month_end_ratio, 4),
            dominant_weekday_ratio=round(dominant_weekday_ratio, 4),
            dominant_weekday=dominant_weekday,
        )

    if monthly_cadence_ratio >= cadence_threshold and month_end_ratio >= anchor_threshold:
        return TemporalGrainResult(
            temporal_grain="monthly",
            detection_confidence=round(monthly_score, 4),
            detected_anchor="month_end",
            periods_analyzed=periods,
            weekly_cadence_ratio=round(weekly_cadence_ratio, 4),
            monthly_cadence_ratio=round(monthly_cadence_ratio, 4),
            month_end_ratio=round(month_end_ratio, 4),
            dominant_weekday_ratio=round(dominant_weekday_ratio, 4),
            dominant_weekday=dominant_weekday,
        )

    return TemporalGrainResult(
        temporal_grain="unknown",
        detection_confidence=round(max(weekly_score, monthly_score), 4),
        detected_anchor="unknown",
        periods_analyzed=periods,
        weekly_cadence_ratio=round(weekly_cadence_ratio, 4),
        monthly_cadence_ratio=round(monthly_cadence_ratio, 4),
        month_end_ratio=round(month_end_ratio, 4),
        dominant_weekday_ratio=round(dominant_weekday_ratio, 4),
        dominant_weekday=dominant_weekday,
    )


def describe_analysis_period(
    period_end: str,
    frequency: Optional[str] = None,
    temporal_grain: Optional[str] = None,
) -> str:
    """Human-readable label for the analysis period."""

    if not period_end:
        return "the most recent period"

    preferred = normalize_temporal_grain(frequency or temporal_grain)
    template = _PERIOD_PHRASE_TEMPLATE.get(preferred, "the period ending {period_end}")
    return template.format(period_end=period_end)
