"""Input preparation helpers for statistical summary."""

from __future__ import annotations

import os
from typing import Any, Tuple

import numpy as np
import pandas as pd

from .....semantic.lag_utils import get_effective_lag_or_default, resolve_effective_latest_period
from ..stat_summary.state import SummaryState


from .....utils.temporal_grain import normalize_temporal_grain, temporal_grain_to_period_unit


def prepare_state(resolve_data_and_columns, analysis_focus=None, custom_focus: str | None = None) -> Tuple[SummaryState, dict[str, Any]]:
    df, time_col, metric_col, grain_col, name_col, ctx = resolve_data_and_columns("StatisticalSummary")
    df[metric_col] = pd.to_numeric(df[metric_col], errors="coerce").fillna(0)

    current_metric_name = _resolve_target_metric(df, ctx)
    if current_metric_name and "metric" in df.columns and df["metric"].nunique() > 1:
        metric_matches = df["metric"].str.strip() == current_metric_name
        if metric_matches.any():
            df = df[metric_matches].copy()

    names_map = dict(zip(df[grain_col], df[name_col]))
    pivot = df.pivot_table(
        index=grain_col,
        columns=time_col,
        values=metric_col,
        aggfunc="sum",
        fill_value=0,
    )
    pivot = pivot.reindex(sorted(pivot.columns), axis=1)

    _apply_materiality_filter(df, pivot, ctx, current_metric_name, grain_col, time_col)

    periods = sorted(pivot.columns)
    lag = get_effective_lag_or_default(ctx.contract, ctx.target_metric) if ctx and ctx.contract and ctx.target_metric else 0
    effective_latest, lag_window = resolve_effective_latest_period(periods, lag)
    latest_period_label = _format_period_label(effective_latest)

    time_cfg = getattr(ctx.contract, "time", None) if ctx and getattr(ctx, "contract", None) else None
    time_frequency = getattr(time_cfg, "frequency", None) if time_cfg else None

    ctx_temporal_grain = getattr(ctx, "temporal_grain", None) if ctx else None
    temporal_grain = normalize_temporal_grain(ctx_temporal_grain)
    if temporal_grain == "unknown":
        temporal_grain = "monthly"
    period_unit = temporal_grain_to_period_unit(temporal_grain)

    latest_idx = None
    prev_period_value = None
    try:
        latest_idx = list(pivot.columns).index(effective_latest)
        if latest_idx > 0:
            prev_period_value = list(pivot.columns)[latest_idx - 1]
    except ValueError:
        pass

    prev_period_label = _format_period_label(prev_period_value) if prev_period_value is not None else None

    change_series = None
    contribution_share: dict[str, float] = {}
    if prev_period_value is not None and effective_latest is not None:
        change_series = pivot[effective_latest] - pivot[prev_period_value]

    pattern_label_by_account = _compute_pattern_labels(pivot, effective_latest)

    state = SummaryState(
        df=df,
        pivot=pivot,
        ctx=ctx,
        time_col=time_col,
        metric_col=metric_col,
        grain_col=grain_col,
        name_col=name_col,
        names_map=names_map,
        current_metric_name=current_metric_name,
        temporal_grain=temporal_grain,
        period_unit=period_unit,
        time_frequency=time_frequency,
        latest_period=latest_period_label,
        prev_period=prev_period_label,
        lag=lag,
        lag_window=[str(p) for p in lag_window],
        latest_period_value=effective_latest,
        prev_period_value=prev_period_value,
        pattern_label_by_account=pattern_label_by_account,
        change_series=change_series,
        contribution_share=contribution_share,
    )

    normalized_focus = _normalize_focus_list(analysis_focus)
    focus_settings = _derive_focus_settings(normalized_focus, temporal_grain)
    state.analysis_focus = normalized_focus
    state.custom_focus = (custom_focus or "").strip()
    state.focus_settings = focus_settings

    return state, {"names_map": names_map}


def _resolve_target_metric(df: pd.DataFrame, ctx) -> str | None:
    current_metric_name = None
    if "metric" in df.columns:
        u_metrics = [str(m).strip() for m in df["metric"].unique() if m]
        if len(u_metrics) == 1:
            current_metric_name = u_metrics[0]
        elif ctx and ctx.target_metric and ctx.target_metric.name in u_metrics:
            current_metric_name = ctx.target_metric.name
        else:
            try:
                from data_analyst_agent.semantic.ratio_metrics_config import (
                    get_ratio_config_for_metric as _get_rc,
                )

                for m in u_metrics:
                    if _get_rc(ctx.contract, m):
                        current_metric_name = m
                        break
            except Exception:
                pass
    if not current_metric_name and ctx and ctx.target_metric:
        current_metric_name = ctx.target_metric.name
    return current_metric_name


def _apply_materiality_filter(df, pivot, ctx, metric_name, grain_col, time_col):
    if not (ctx and ctx.contract and metric_name and "metric" in df.columns):
        return
    try:
        from data_analyst_agent.semantic.ratio_metrics_config import (
            get_ratio_config_for_metric as _get_rc,
        )
        from .....tools.validation_data_loader import load_validation_data

        ratio_cfg = _get_rc(ctx.contract, metric_name)
        if not ratio_cfg:
            return
        min_share = ratio_cfg.get("materiality_min_share")
        denom_metric = ratio_cfg.get("denominator_metric")
        if not min_share or not denom_metric:
            return
        _exclude_partial = os.environ.get("DATA_ANALYST_EXCLUDE_PARTIAL_WEEK", "false").lower() == "true"
        denom_df = load_validation_data(metric_filter=[denom_metric], exclude_partial_week=_exclude_partial)
        if denom_df.empty:
            return
        if grain_col not in denom_df.columns:
            raise ValueError(f"Materiality filter: grain column '{grain_col}' not found in denominator data (available: {list(denom_df.columns)})")
        _gcol = grain_col
        # Use contract-defined time column
        contract_time_col = ctx.contract.time.column if ctx.contract.time else None
        if not contract_time_col or contract_time_col not in denom_df.columns:
            raise ValueError(f"Materiality filter: time column '{contract_time_col or time_col}' not found in denominator data (available: {list(denom_df.columns)})")
        _tcol = contract_time_col
        denom_df["value"] = pd.to_numeric(denom_df["value"], errors="coerce").fillna(0)
        net_denom = denom_df.groupby(_tcol)["value"].sum()
        grain_vals = set(df[_gcol].astype(str).unique())
        filtered = denom_df[denom_df[_gcol].astype(str).isin(grain_vals)]
        grain_denom = filtered.groupby([_tcol, _gcol])["value"].sum()
        denom_share = grain_denom / net_denom.reindex(grain_denom.index, level=0)
        low_pairs = denom_share[denom_share < min_share].reset_index()
        low_set = set(zip(low_pairs[_gcol].astype(str), low_pairs[_tcol].astype(str)))
        if not low_set:
            return
        for col in list(pivot.columns):
            col_str = str(col)
            for term in pivot.index:
                if (str(term), col_str) in low_set:
                    pivot.at[term, col] = float("nan")
    except Exception:
        pass


def _format_period_label(period) -> str:
    if period is None:
        return "N/A"
    if hasattr(period, "isoformat"):
        try:
            return period.isoformat()
        except Exception:
            pass
    return str(period)


def _compute_pattern_labels(pivot: pd.DataFrame, latest_period_value) -> dict[str, str]:
    labels: dict[str, str] = {}
    if latest_period_value is None or latest_period_value not in pivot.columns:
        for account in pivot.index:
            labels[account] = "run_rate_change"
        return labels

    if pivot.shape[1] >= 3:
        mean3 = pivot.iloc[:, -3:].mean(axis=1)
        std3 = pivot.iloc[:, -3:].std(axis=1)
        for account in pivot.index:
            latest_val = float(pivot.loc[account, latest_period_value])
            m3 = float(mean3.loc[account])
            s3 = float(std3.loc[account])
            is_spike = abs(latest_val - m3) > 2.0 * s3 if s3 > 0 else False
            labels[account] = "spike" if is_spike else "run_rate_change"
    else:
        for account in pivot.index:
            labels[account] = "run_rate_change"
    return labels


def _normalize_focus_list(focus) -> list[str]:
    if not focus:
        return []
    if isinstance(focus, str):
        focus = [focus]
    seen = set()
    normalized: list[str] = []
    for item in focus:
        value = str(item).strip().lower()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized


def _derive_focus_settings(focus_modes: list[str], temporal_grain: str) -> dict[str, Any]:
    focus_defaults = {
        "daily": 14,
        "weekly": 8,
        "monthly": 4,
        "quarterly": 4,
        "yearly": 3,
    }
    settings: dict[str, Any] = {
        "z_threshold": 2.0,
        "focus_periods": focus_defaults.get(temporal_grain, 4),
    }
    if "recent_weekly_trends" in focus_modes:
        settings["focus_periods"] = 8
    if "recent_monthly_trends" in focus_modes:
        settings["focus_periods"] = 6
    if "anomaly_detection" in focus_modes or "outlier_investigation" in focus_modes:
        settings["z_threshold"] = 1.5
    if "yoy_comparison" in focus_modes:
        settings["emphasize_yoy"] = True
    if "forecasting" in focus_modes:
        settings["emphasize_forecast"] = True
    if "revenue_gap_analysis" in focus_modes:
        settings["highlight_revenue_gaps"] = True
    settings["analysis_focus"] = focus_modes
    return settings
