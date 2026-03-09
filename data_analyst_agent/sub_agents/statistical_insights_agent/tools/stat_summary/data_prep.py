"""Input preparation helpers for statistical summary."""

from __future__ import annotations

import os
from typing import Any, Tuple

import numpy as np
import pandas as pd

from .....semantic.lag_utils import get_effective_lag_or_default, resolve_effective_latest_period
from ..stat_summary.state import SummaryState


def prepare_state(resolve_data_and_columns) -> Tuple[SummaryState, dict[str, Any]]:
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
    latest_period = str(effective_latest) if effective_latest else "N/A"

    temporal_grain = "monthly"
    ctx_temporal_grain = getattr(ctx, "temporal_grain", None) if ctx else None
    if isinstance(ctx_temporal_grain, str) and ctx_temporal_grain:
        temporal_grain = ctx_temporal_grain
    period_unit = "week" if temporal_grain == "weekly" else "month"

    try:
        latest_idx = list(pivot.columns).index(effective_latest)
        prev_period = str(pivot.columns[latest_idx - 1]) if latest_idx > 0 else None
    except ValueError:
        prev_period = None

    change_series = None
    contribution_share: dict[str, float] = {}
    if prev_period is not None:
        change_series = pivot[latest_period] - pivot[prev_period]

    pattern_label_by_account = _compute_pattern_labels(pivot, latest_period)

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
        latest_period=latest_period,
        prev_period=prev_period,
        lag=lag,
        lag_window=[str(p) for p in lag_window],
        pattern_label_by_account=pattern_label_by_account,
        change_series=change_series,
        contribution_share=contribution_share,
    )

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
                from ..ratio_metrics_config import get_ratio_config_for_metric as _get_rc

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
        from ..ratio_metrics_config import get_ratio_config_for_metric as _get_rc
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
        _gcol = grain_col if grain_col in denom_df.columns else "terminal"
        _tcol = time_col if time_col in denom_df.columns else "week_ending"
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


def _compute_pattern_labels(pivot: pd.DataFrame, latest_period: str) -> dict[str, str]:
    labels: dict[str, str] = {}
    if pivot.shape[1] >= 3:
        mean3 = pivot.iloc[:, -3:].mean(axis=1)
        std3 = pivot.iloc[:, -3:].std(axis=1)
        for account in pivot.index:
            latest_val = float(pivot.loc[account, latest_period])
            m3 = float(mean3.loc[account])
            s3 = float(std3.loc[account])
            is_spike = abs(latest_val - m3) > 2.0 * s3 if s3 > 0 else False
            labels[account] = "spike" if is_spike else "run_rate_change"
    else:
        for account in pivot.index:
            labels[account] = "run_rate_change"
    return labels
