"""Monthly total computations (aggregate then derive)."""

from __future__ import annotations

import os
from typing import Optional

import pandas as pd

from ..stat_summary.state import SummaryState


def compute_monthly_totals(state: SummaryState) -> None:
    ctx = state.ctx
    df = state.df
    pivot = state.pivot
    monthly_totals: dict[str, float] = {}
    ratio_config: Optional[dict] = None

    if ctx and ctx.contract and state.current_metric_name:
        from ..ratio_metrics_config import get_ratio_config_for_metric

        ratio_config = get_ratio_config_for_metric(ctx.contract, state.current_metric_name)

    if ratio_config:
        totals = _compute_ratio_totals(df, pivot, ctx, ratio_config, state)
        if totals is None:
            ratio_config = None
        else:
            monthly_totals = totals

    if not ratio_config:
        for period in pivot.columns:
            total = float(pivot[period].sum())
            monthly_totals[str(period)] = round(total, 2)

    state.monthly_totals = monthly_totals

    if state.prev_period is not None and monthly_totals:
        latest_mt = monthly_totals.get(state.latest_period, 0)
        prev_mt = monthly_totals.get(state.prev_period, 0)
        correct_total_change = latest_mt - prev_mt
        total_change_denom = correct_total_change if correct_total_change != 0 else 1e-9
        if state.latest_period_value is not None and state.prev_period_value is not None:
            period_delta = pivot[state.latest_period_value] - pivot[state.prev_period_value]
            for account in pivot.index:
                state.contribution_share[account] = float(period_delta.loc[account] / total_change_denom)


def _compute_ratio_totals(df, pivot, ctx, ratio_config, state: SummaryState) -> dict[str, float] | None:
    num_metric = ratio_config.get("numerator_metric")
    denom_metric = ratio_config.get("denominator_metric")
    min_share = ratio_config.get("materiality_min_share")

    try:
        from .....tools.validation_data_loader import load_validation_data

        is_tableau = (
            ctx.contract
            and getattr(ctx.contract, "data_source", None)
            and getattr(ctx.contract.data_source, "type", None) == "tableau_hyper"
        )

        if num_metric in df.columns and denom_metric in df.columns:
            nd_df = df.copy()
            nd_df["metric"] = "mock"
        elif is_tableau:
            return None
        else:
            _exclude_partial = os.environ.get("DATA_ANALYST_EXCLUDE_PARTIAL_WEEK", "false").lower() == "true"
            nd_df = load_validation_data(metric_filter=[num_metric, denom_metric], exclude_partial_week=_exclude_partial)

        if nd_df.empty:
            return None

        tcol = state.time_col if state.time_col in nd_df.columns else "week_ending"
        gcol = state.grain_col if state.grain_col in nd_df.columns else "terminal"

        if num_metric in nd_df.columns and denom_metric in nd_df.columns:
            num_agg = nd_df.groupby(tcol)[num_metric].sum()
            if denom_metric == "Truck Count" and "truck_count" in nd_df.columns and "days_in_period" in nd_df.columns:
                period_totals = nd_df.groupby(tcol).agg(
                    truck_total=("truck_count", "sum"),
                    days_max=("days_in_period", "max"),
                )
                net_denom = period_totals["truck_total"] / period_totals["days_max"].replace(0, float("nan"))
                denom_agg = net_denom
            else:
                denom_agg = nd_df.groupby(tcol)[denom_metric].sum()
        else:
            nd_df["value"] = pd.to_numeric(nd_df["value"], errors="coerce").fillna(0)
            num_agg = nd_df[nd_df["metric"].str.strip() == num_metric].groupby(tcol)["value"].sum()
            denom_agg = nd_df[nd_df["metric"].str.strip() == denom_metric].groupby(tcol)["value"].sum()

        monthly_totals: dict[str, float] = {}
        for period in pivot.columns:
            p = str(period)
            denom = float(denom_agg.get(p, 0)) or 1e-9
            total = float(num_agg.get(p, 0)) / denom
            monthly_totals[p] = round(total, 2)
        return monthly_totals
    except Exception:
        return None
