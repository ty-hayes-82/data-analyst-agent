"""Ratio metric helpers for level statistics."""
from __future__ import annotations

import os
from typing import Any, Optional, Tuple

import pandas as pd

from data_analyst_agent.tools.validation_data_loader import load_validation_data


class RatioAggregationResult(Tuple[pd.DataFrame, pd.DataFrame, Optional[float]]):
    """Typed tuple wrapper for ratio aggregation outputs."""


def compute_ratio_aggregations(
    df: pd.DataFrame,
    ctx: Any,
    level_col: str,
    time_col: str,
    grain_col: str,
    metric_col: str,
    current_period: str,
    prior_period_str: str,
):
    """Return (ratio_config, current_agg, prior_agg, network_variance, network_ratio_totals).

    network_ratio_totals is (network_current, network_prior) for ratio metrics, else None.
    """
    ratio_config = None
    current_metric_name = _resolve_metric_name(df, ctx)

    if current_metric_name and "metric" in df.columns and df["metric"].nunique() > 1:
        if current_metric_name in [str(m).strip() for m in df["metric"].unique()]:
            df = df[df["metric"].str.strip() == current_metric_name].copy()

    if current_metric_name:
        ratio_config = _fetch_ratio_config(ctx, current_metric_name)

    if not ratio_config or level_col not in df.columns:
        return None, _default_agg(df, level_col, metric_col, current_period, time_col, "current"), _default_agg(
            df, level_col, metric_col, prior_period_str, time_col, "prior"
        ), None, None

    current_df = df[df[time_col] == str(current_period)].copy()

    result = _aggregate_ratio_values(
        df,
        current_df,
        ctx,
        level_col,
        time_col,
        grain_col,
        current_period,
        prior_period_str,
        ratio_config,
    )
    if result is None:
        return None, _default_agg(df, level_col, metric_col, current_period, time_col, "current"), _default_agg(
            df, level_col, metric_col, prior_period_str, time_col, "prior"
        ), None, None
    # result: (current_agg, prior_agg, network_variance, network_current, network_prior)
    return ratio_config, result[0], result[1], result[2], (result[3], result[4])


def _resolve_metric_name(df: pd.DataFrame, ctx: Any) -> Optional[str]:
    if "metric" not in df.columns:
        return getattr(getattr(ctx, "target_metric", None), "name", None)

    unique_metrics = [str(m).strip() for m in df["metric"].unique() if m]
    if len(unique_metrics) == 1:
        return unique_metrics[0]

    if ctx and ctx.target_metric and ctx.target_metric.name in unique_metrics:
        return ctx.target_metric.name

    try:
        from data_analyst_agent.semantic.ratio_metrics_config import get_ratio_config_for_metric

        for metric in unique_metrics:
            if get_ratio_config_for_metric(ctx.contract, metric):
                return metric
    except Exception:
        pass

    return getattr(getattr(ctx, "target_metric", None), "name", None)


def _fetch_ratio_config(ctx: Any, metric_name: str):
    try:
        from data_analyst_agent.semantic.ratio_metrics_config import get_ratio_config_for_metric

        return get_ratio_config_for_metric(ctx.contract, metric_name)
    except Exception:
        return None


def _default_agg(df, level_col, metric_col, period_str, time_col, value_label):
    # Normalize period comparison: strip time components from both sides
    clean_period = str(period_str).split(" ")[0].split("T")[0]
    subset = df[df[time_col].astype(str).str[:10] == clean_period].copy()
    if subset.empty:
        return pd.DataFrame({"item": [], value_label: []})
    # Fill null dimension values to avoid dropping rows during groupby
    subset[level_col] = subset[level_col].fillna("(Unassigned)")
    return (
        subset.groupby(level_col, dropna=False)[metric_col]
        .sum()
        .reset_index()
        .rename(columns={level_col: "item", metric_col: value_label})
    )


def _aggregate_ratio_values(
    df,
    current_df,
    ctx,
    level_col: str,
    time_col: str,
    grain_col: str,
    current_period: str,
    prior_period_str: str,
    ratio_config,
):
    if ratio_config.get("numerator_expr") is not None and ratio_config.get("denominator_expr") is not None:
        return _aggregate_wide_dataframe_exprs(
            df,
            level_col,
            time_col,
            grain_col,
            current_period,
            prior_period_str,
            ratio_config,
        )

    num_metric = ratio_config.get("numerator_metric")
    denom_metric = ratio_config.get("denominator_metric")
    is_tableau = (
        ctx.contract
        and getattr(ctx.contract, "data_source", None)
        and getattr(ctx.contract.data_source, "type", None) == "tableau_hyper"
    )

    if num_metric in df.columns and denom_metric in df.columns:
        return _aggregate_wide_dataframe(
            df,
            level_col,
            time_col,
            grain_col,
            current_period,
            prior_period_str,
            ratio_config,
        )

    if is_tableau:
        print(
            f"[compute_level_statistics] Tableau dataset but missing ratio columns "
            f"({num_metric!r}, {denom_metric!r}). Skipping ratio aggregation."
        )
        return None

    return _aggregate_from_validation_data(
        current_df,
        level_col,
        time_col,
        grain_col,
        current_period,
        prior_period_str,
        ratio_config,
    )


def _aggregate_wide_dataframe_exprs(
    df,
    level_col,
    time_col,
    grain_col,
    current_period,
    prior_period_str,
    ratio_config,
):
    """Aggregate-then-divide using contract-derived numerator/denominator pandas expressions."""
    from data_analyst_agent.semantic.derived_kpi_formula import column_refs_in_expr

    num_expr = ratio_config.get("numerator_expr")
    den_expr = ratio_config.get("denominator_expr")
    mult = float(ratio_config.get("multiply", 1.0))
    if not num_expr or not den_expr or level_col not in df.columns:
        return None

    nd_df = df.copy()
    nd_df[time_col] = nd_df[time_col].astype(str)
    available = set(nd_df.columns)
    cols_needed = column_refs_in_expr(num_expr, available) | column_refs_in_expr(den_expr, available)
    if not cols_needed:
        print("[ratio_exprs] No column refs resolved for ratio expressions; skipping.")
        return None

    if ratio_config.get("materiality_min_share"):
        print("[ratio_exprs] materiality_min_share is not supported for expr-based ratios; ignoring.")

    if level_col == "_total_agg":
        nd_df["_total_agg"] = "Total"

    def _subset_for_period(period_str: str):
        clean = str(period_str).split(" ")[0].split("T")[0]
        mask = nd_df[time_col].str[:10] == clean
        sub = nd_df.loc[mask]
        if sub.empty and period_str is not None:
            sub = nd_df.loc[nd_df[time_col] == str(period_str)]
        return sub

    def _ratio_agg_period(period_str: str) -> pd.DataFrame:
        sub = _subset_for_period(period_str)
        if sub.empty:
            return pd.DataFrame(columns=["item", "val"])
        work = sub[list(cols_needed | {level_col})].copy()
        work[level_col] = work[level_col].fillna("(Unassigned)")
        for c in cols_needed:
            work[c] = pd.to_numeric(work[c], errors="coerce").fillna(0)
        g = work.groupby(level_col, dropna=False)[sorted(cols_needed)].sum()
        try:
            g["_n"] = g.eval(num_expr)
            g["_d"] = g.eval(den_expr)
        except Exception as exc:
            print(f"[ratio_exprs] group eval failed ({exc}); num_expr={num_expr!r} den_expr={den_expr!r}")
            return pd.DataFrame(columns=["item", "val"])
        d_safe = g["_d"].replace(0, float("nan"))
        g["val"] = mult * g["_n"] / d_safe
        out = g["val"].reset_index()
        out.columns = ["item", "val"]
        return out

    def _eval_agg_scalar(frame: pd.DataFrame, expr: str) -> float:
        """DataFrame.eval may return a Series (use .iloc[0]) or a scalar float."""
        raw = frame.eval(expr)
        if hasattr(raw, "iloc"):
            return float(raw.iloc[0])
        return float(raw)

    def _network_ratio_period(period_str: str) -> float:
        sub = _subset_for_period(period_str)
        if sub.empty:
            return 0.0
        srows = sub[list(cols_needed)].copy()
        for c in cols_needed:
            srows[c] = pd.to_numeric(srows[c], errors="coerce").fillna(0)
        agg = srows.sum(numeric_only=True).to_frame().T
        try:
            n_v = _eval_agg_scalar(agg, num_expr)
            d_v = _eval_agg_scalar(agg, den_expr)
        except Exception as exc:
            print(f"[ratio_exprs] network eval failed ({exc})")
            return 0.0
        if d_v == 0:
            return 0.0
        return float(mult * n_v / d_v)

    current_agg = _ratio_agg_period(str(current_period))
    current_agg.columns = ["item", "current"]
    prior_agg = _ratio_agg_period(str(prior_period_str))
    prior_agg.columns = ["item", "prior"]

    net_cur = _network_ratio_period(str(current_period))
    if _subset_for_period(str(prior_period_str)).empty:
        net_pri = net_cur
    else:
        net_pri = _network_ratio_period(str(prior_period_str))

    return current_agg, prior_agg, net_cur - net_pri, net_cur, net_pri


def _aggregate_wide_dataframe(
    df,
    level_col,
    time_col,
    grain_col,
    current_period,
    prior_period_str,
    ratio_config,
):
    nd_df = df.copy()
    nd_df[time_col] = nd_df[time_col].astype(str)

    numeric_cols = [ratio_config.get("numerator_metric"), ratio_config.get("denominator_metric")]
    
    # =====================================================================
    # HARDCODED TRADE-SPECIFIC LOGIC — NEEDS CONTRACT-DRIVEN REPLACEMENT
    # =====================================================================
    # Current: Hardcoded auxiliary columns for trade datasets with vehicle-based denominators
    # 
    # CONTRACT-DRIVEN REPLACEMENT PLAN:
    # 1. Add to ratio config schema (contract.yaml metrics section):
    #    auxiliary_columns: ["truck_count", "days_in_period"]
    #    denominator_aggregation_strategy: "network_level_resource" | "sum"
    # 
    # 2. Replace this loop with:
    #    auxiliary_cols = ratio_config.get("auxiliary_columns", [])
    #    for col in auxiliary_cols:
    #        if col in nd_df.columns:
    #            numeric_cols.append(col)
    # =====================================================================
    for extra_col in ["truck_count", "days_in_period"]:
        if extra_col in nd_df.columns:
            numeric_cols.append(extra_col)
    for col in sorted(set(filter(None, numeric_cols))):
        nd_df[col] = pd.to_numeric(nd_df[col], errors="coerce").fillna(0)

    # =====================================================================
    # HARDCODED TRADE-SPECIFIC LOGIC — NEEDS CONTRACT-DRIVEN REPLACEMENT
    # =====================================================================
    # Current: Hardcoded check for "Truck Count" denominator metric name
    # 
    # Problem: Prevents ratio metrics from working with other datasets that have
    # network-level resource denominators (e.g., "Server Count", "Agent Count")
    # 
    # CONTRACT-DRIVEN REPLACEMENT PLAN:
    # Replace this boolean with:
    #    use_network_level_aggregation = (
    #        ratio_config.get("denominator_aggregation_strategy") == "network_level_resource"
    #    )
    # Then check auxiliary_columns from config instead of hardcoded column names.
    # =====================================================================
    use_network_truck_denominator = (
        ratio_config.get("denominator_metric") == "Truck Count"
        and "truck_count" in nd_df.columns
        and "days_in_period" in nd_df.columns
    )

    def _effective_denom_by_group(sub_df, group_key):
        if use_network_truck_denominator:
            # Use contract-provided grain_col instead of hardcoded "terminal"
            # This allows the logic to work for any dataset with network-level resource denominators
            if grain_col in sub_df.columns:
                if group_key == grain_col:
                    dedup = sub_df.groupby([group_key], dropna=False).agg(
                        truck_total=("truck_count", "max"),
                        days_max=("days_in_period", "max"),
                    ).reset_index()
                else:
                    dedup = sub_df.groupby([group_key, grain_col], dropna=False).agg(
                        truck_total=("truck_count", "max"),
                        days_max=("days_in_period", "max"),
                    ).reset_index()
                truck_s = dedup.groupby(group_key)["truck_total"].sum()
                days_s = dedup.groupby(group_key)["days_max"].max().replace(0, float("nan"))
                return truck_s / days_s
            truck_s = sub_df.groupby(group_key)["truck_count"].sum()
            days_s = sub_df.groupby(group_key)["days_in_period"].max().replace(0, float("nan"))
            return truck_s / days_s
        return sub_df.groupby(group_key)[ratio_config.get("denominator_metric")].sum()

    def _effective_denom_total(sub_df):
        if use_network_truck_denominator:
            # Use contract-provided grain_col instead of hardcoded "terminal"
            if grain_col in sub_df.columns:
                dedup = sub_df.groupby(grain_col, dropna=False).agg(
                    truck_total=("truck_count", "max"),
                    days_max=("days_in_period", "max"),
                )
                days = float(dedup["days_max"].max()) if not dedup.empty else 0.0
                return (float(dedup["truck_total"].sum()) / days) if days > 0 else 0.0
            days = float(sub_df["days_in_period"].max()) if not sub_df.empty else 0.0
            return (float(sub_df["truck_count"].sum()) / days) if days > 0 else 0.0
        return float(sub_df[ratio_config.get("denominator_metric")].sum())

    def _ratio_agg(period_str):
        sub = nd_df[nd_df[time_col] == period_str]
        if sub.empty:
            return pd.DataFrame(columns=["item", "val"])
        num_s = sub.groupby(level_col)[ratio_config.get("numerator_metric")].sum()
        den_s = _effective_denom_by_group(sub, level_col)
        r = (num_s / den_s.replace(0, float("nan"))).reset_index()
        r.columns = ["item", "val"]
        return r

    def _network_ratio(period_str):
        sub = nd_df[nd_df[time_col] == period_str]
        if sub.empty:
            return 0.0
        num_total = sub[ratio_config.get("numerator_metric")].sum()
        den_total = _effective_denom_total(sub)
        return float(num_total / den_total) if den_total > 0 else 0.0

    if ratio_config.get("materiality_min_share"):
        nd_df = _apply_share_materiality(
            nd_df,
            level_col,
            grain_col,
            ratio_config,
            time_col,
            use_network_truck_denominator,
        )

    if level_col == "_total_agg":
        nd_df["_total_agg"] = "Total"

    current_agg = _ratio_agg(str(current_period))
    current_agg.columns = ["item", "current"]
    prior_agg = _ratio_agg(prior_period_str)
    prior_agg.columns = ["item", "prior"]

    net_cur = _network_ratio(str(current_period))
    sub_pri = nd_df[nd_df[time_col] == str(prior_period_str)]
    if sub_pri.empty:
        net_pri = net_cur
    else:
        net_pri = _network_ratio(prior_period_str)

    return current_agg, prior_agg, net_cur - net_pri, net_cur, net_pri


def _aggregate_from_validation_data(
    current_df,
    level_col,
    time_col,
    grain_col,
    current_period,
    prior_period_str,
    ratio_config,
):
    _exclude_partial = os.environ.get("DATA_ANALYST_EXCLUDE_PARTIAL_WEEK", "false").lower() == "true"
    nd_df = load_validation_data(
        metric_filter=[ratio_config.get("numerator_metric"), ratio_config.get("denominator_metric")],
        exclude_partial_week=_exclude_partial,
    )
    if nd_df.empty or "metric" not in nd_df.columns or "value" not in nd_df.columns:
        return None

    # Use contract-provided time_col and grain_col; no hardcoded fallbacks to dataset-specific columns
    tcol = time_col if time_col in nd_df.columns else time_col
    gcol = grain_col if grain_col in nd_df.columns else grain_col
    nd_df[tcol] = nd_df[tcol].astype(str)
    nd_df["value"] = pd.to_numeric(nd_df["value"], errors="coerce").fillna(0)

    net_denom = nd_df[nd_df["metric"].str.strip() == ratio_config.get("denominator_metric")].groupby(tcol)["value"].sum()
    grain_vals = set(current_df[grain_col].unique()) if grain_col in current_df.columns else set()
    if grain_vals:
        nd_df = nd_df[nd_df[gcol].isin(grain_vals)]

    min_share = ratio_config.get("materiality_min_share")
    if min_share:
        m_col = level_col if level_col != "_total_agg" else gcol
        grain_denom = (
            nd_df[nd_df["metric"].str.strip() == ratio_config.get("denominator_metric")]
            .groupby([tcol, m_col])["value"].sum()
        )
        share = grain_denom / net_denom.reindex(grain_denom.index, level=0)
        material_idx = share[share >= min_share].reset_index()[[tcol, m_col]]
        nd_df = nd_df.merge(material_idx, on=[tcol, m_col], how="inner")

    if level_col == "_total_agg":
        nd_df["_total_agg"] = "Total"
    elif level_col not in nd_df.columns:
        return None

    def _ratio_agg(period_str):
        sub = nd_df[nd_df[tcol] == period_str]
        if sub.empty:
            return pd.DataFrame(columns=["item", "val"])
        num_s = (
            sub[sub["metric"].str.strip() == ratio_config.get("numerator_metric")]
            .groupby(level_col)["value"]
            .sum()
        )
        den_s = (
            sub[sub["metric"].str.strip() == ratio_config.get("denominator_metric")]
            .groupby(level_col)["value"]
            .sum()
        )
        r = (num_s / den_s.replace(0, float("nan"))).reset_index()
        r.columns = ["item", "val"]
        return r

    def _network_ratio(period_str):
        sub = nd_df[nd_df[tcol] == period_str]
        if sub.empty:
            return 0.0
        num_total = sub[sub["metric"].str.strip() == ratio_config.get("numerator_metric")]["value"].sum()
        den_total = sub[sub["metric"].str.strip() == ratio_config.get("denominator_metric")]["value"].sum()
        return float(num_total / den_total) if den_total > 0 else 0.0

    current_agg = _ratio_agg(str(current_period))
    current_agg.columns = ["item", "current"]
    prior_agg = _ratio_agg(prior_period_str)
    prior_agg.columns = ["item", "prior"]

    net_cur = _network_ratio(str(current_period))
    sub_pri = nd_df[nd_df[tcol] == str(prior_period_str)]
    if sub_pri.empty:
        net_pri = net_cur
    else:
        net_pri = _network_ratio(prior_period_str)

    return current_agg, prior_agg, net_cur - net_pri, net_cur, net_pri


def _apply_share_materiality(
    nd_df,
    level_col,
    grain_col,
    ratio_config,
    time_col,
    use_network_truck_denominator,
):
    min_share = ratio_config.get("materiality_min_share")
    if not min_share:
        return nd_df

    m_col = level_col if level_col != "_total_agg" else grain_col
    if use_network_truck_denominator and grain_col in nd_df.columns:
        _grain_terminal = nd_df.groupby([time_col, m_col, grain_col], dropna=False).agg(
            truck_total=("truck_count", "max"),
            days_max=("days_in_period", "max"),
        ).reset_index()
        _grain_totals = _grain_terminal.groupby([time_col, m_col]).agg(
            truck_total=("truck_total", "sum"),
            days_max=("days_max", "max"),
        )
        grain_denom = _grain_totals["truck_total"] / _grain_totals["days_max"].replace(0, float("nan"))
        net = grain_denom.groupby(level=0).sum()
    elif use_network_truck_denominator:
        _grain_totals = nd_df.groupby([time_col, m_col]).agg(
            truck_total=("truck_count", "sum"),
            days_max=("days_in_period", "max"),
        )
        grain_denom = _grain_totals["truck_total"] / _grain_totals["days_max"].replace(0, float("nan"))
        net = grain_denom.groupby(level=0).sum()
    else:
        grain_denom = nd_df.groupby([time_col, m_col])[ratio_config.get("denominator_metric")].sum()
        net = grain_denom.groupby(level=0).sum()

    share = grain_denom / net.reindex(grain_denom.index, level=0)
    material_idx = share[share >= min_share].reset_index()[[time_col, m_col]]
    return nd_df.merge(material_idx, on=[time_col, m_col], how="inner")
