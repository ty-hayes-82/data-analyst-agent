import pandas as pd

from data_analyst_agent.utils.temporal_grain import (
    detect_temporal_grain,
    describe_analysis_period,
    temporal_grain_to_period_unit,
    temporal_grain_to_short_delta_label,
)


from data_analyst_agent.sub_agents.report_synthesis_agent.tools.generate_markdown_report import _detect_temporal_labels


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


def test_describe_analysis_period_respects_yearly_frequency():
    phrase = describe_analysis_period("2024-12-31", frequency="yearly")
    assert phrase == "the year ending 2024-12-31"
    assert temporal_grain_to_period_unit("yearly") == "year"
    assert temporal_grain_to_short_delta_label("yearly") == "YoY"


def test_detect_temporal_labels_fall_back_to_contract_frequency():
    stats_data = {
        "summary_stats": {},
        "metadata": {"time_frequency": "yearly"},
    }
    temporal_grain, short_label, period_label = _detect_temporal_labels(stats_data)
    assert temporal_grain == "yearly"
    assert short_label == "YoY"
    assert period_label == "year"
