import pandas as pd

from data_analyst_agent.utils.temporal_grain import detect_temporal_grain


def test_detect_temporal_grain_weekly():
    dates = pd.date_range("2025-01-03", periods=16, freq="W-FRI")
    result = detect_temporal_grain(dates)
    assert result.temporal_grain == "weekly"
    assert result.detected_anchor == "week_end"
    assert result.detection_confidence >= 0.75


def test_detect_temporal_grain_monthly():
    dates = pd.date_range("2024-01-31", periods=14, freq="ME")
    result = detect_temporal_grain(dates)
    assert result.temporal_grain == "monthly"
    assert result.detected_anchor == "month_end"
    assert result.detection_confidence >= 0.75


def test_detect_temporal_grain_unknown_on_short_series():
    dates = pd.date_range("2025-01-31", periods=5, freq="ME")
    result = detect_temporal_grain(dates)
    assert result.temporal_grain == "unknown"
    assert result.periods_analyzed == 5


def test_detect_temporal_grain_unknown_on_ambiguous_cadence():
    # Mixed 7/14/21-day spacing should not confidently map to weekly or monthly.
    dates = pd.to_datetime(
        [
            "2025-01-03",
            "2025-01-10",
            "2025-01-24",
            "2025-02-14",
            "2025-02-21",
            "2025-03-14",
            "2025-03-21",
            "2025-04-11",
            "2025-04-18",
        ]
    )
    result = detect_temporal_grain(dates)
    assert result.temporal_grain == "unknown"
