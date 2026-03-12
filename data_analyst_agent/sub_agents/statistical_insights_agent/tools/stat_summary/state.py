"""Shared SummaryState dataclass for statistical summary pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass
class SummaryState:
    df: pd.DataFrame
    pivot: pd.DataFrame
    ctx: Any
    time_col: str
    metric_col: str
    grain_col: str
    name_col: str
    names_map: dict[str, str]
    current_metric_name: str | None
    temporal_grain: str
    period_unit: str
    latest_period: str
    prev_period: str | None
    lag: int
    lag_window: list[str]
    time_frequency: str | None = None
    latest_period_value: Any | None = None
    prev_period_value: Any | None = None
    pattern_label_by_account: dict[str, str] = field(default_factory=dict)
    change_series: pd.Series | None = None
    contribution_share: dict[str, float] = field(default_factory=dict)

    # Buckets populated by downstream stages
    account_stats: list[dict] = field(default_factory=list)
    top_drivers: list[dict] = field(default_factory=list)
    most_volatile: list[dict] = field(default_factory=list)
    anomalies: list[dict] = field(default_factory=list)
    anomalies_sorted: list[dict] = field(default_factory=list)
    anomaly_latest_flag: dict[str, bool] = field(default_factory=dict)
    correlations: dict[str, dict] = field(default_factory=dict)
    suspected_uniform_growth: bool = False
    monthly_totals: dict[str, float] = field(default_factory=dict)
    summary_stats: dict[str, Any] = field(default_factory=dict)
    enhanced_top_drivers: list[dict] = field(default_factory=list)
    delta_attribution: list[dict] = field(default_factory=list)

    # Advanced tool payloads
    advanced_results: dict[str, Any] = field(default_factory=dict)

    # Focus directives
    analysis_focus: list[str] = field(default_factory=list)
    custom_focus: str = ""
    focus_settings: dict[str, Any] = field(default_factory=dict)
