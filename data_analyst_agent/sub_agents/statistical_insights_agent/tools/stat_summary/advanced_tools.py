"""Advanced analysis orchestration for statistical summary."""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any

from config.statistical_analysis_config import get_analysis_toggle_summary, get_skip_tools

from .._resolved_data import build_resolved_bundle
from ..stat_summary.state import SummaryState
from ..compute_concentration_analysis import compute_concentration_analysis
from ..compute_cross_dimension_analysis import compute_cross_dimension_analysis
from ..compute_cross_metric_correlation import compute_cross_metric_correlation
from ..compute_distribution_analysis import compute_distribution_analysis
from ..compute_derived_metrics import compute_derived_metrics
from ..compute_forecast_baseline import compute_forecast_baseline
from ..compute_lagged_correlation import compute_lagged_correlation
from ..compute_new_lost_same_store import compute_new_lost_same_store
from ..compute_outlier_impact import compute_outlier_impact
from ..compute_seasonal_decomposition import compute_seasonal_decomposition
from ..compute_variance_decomposition import compute_variance_decomposition
from ..detect_change_points import detect_change_points
from ..detect_mad_outliers import detect_mad_outliers


def build_resolved_bundle_for_tools(state: SummaryState) -> dict[str, Any]:
    lag_meta = (
        {
            "lag_periods": state.lag,
            "effective_latest": state.latest_period,
            "lag_window": state.lag_window,
        }
        if state.lag > 0
        else None
    )
    return build_resolved_bundle(
        df=state.df,
        pivot=state.pivot,
        time_col=state.time_col,
        metric_col=state.metric_col,
        grain_col=state.grain_col,
        name_col=state.name_col,
        ctx=state.ctx,
        names_map=state.names_map,
        monthly_totals=state.monthly_totals,
        lag_metadata=lag_meta,
    )


async def run_advanced_tools(state: SummaryState, resolved_bundle: dict[str, Any]) -> dict[str, Any]:
    skip_tools = get_skip_tools()
    toggle_summary = get_analysis_toggle_summary()
    _log_toggle_info(toggle_summary, skip_tools)

    tools = _build_tool_definitions(resolved_bundle, skip_tools, state)
    concurrency = int(os.environ.get("STATISTICAL_ADVANCED_CONCURRENCY", "3"))
    sem = asyncio.Semaphore(concurrency)

    async def _run_with_sem(name: str, coro):
        async with sem:
            return await _timed_tool(name, coro)

    tasks = []
    for env_name, display_name, coro_fn in tools:
        if env_name in skip_tools:
            tasks.append(_run_with_sem(display_name, _skipped_placeholder(display_name)))
        else:
            tasks.append(_run_with_sem(display_name, coro_fn()))

    results = await asyncio.gather(*tasks, return_exceptions=True)
    parsed_results = {}
    for idx, res in enumerate(results):
        name = tools[idx][1]
        parsed_results[name] = _parse_result(res, name)
    return parsed_results


def _build_tool_definitions(resolved_bundle, skip_tools, state: SummaryState):
    defs = [
        ("seasonal_decomposition", "SeasonalDecomposition", lambda: compute_seasonal_decomposition(pre_resolved=resolved_bundle)),
        ("change_points", "ChangePoints", lambda: detect_change_points(pre_resolved=resolved_bundle)),
        ("mad_outliers", "MADOutliers", lambda: detect_mad_outliers(pre_resolved=resolved_bundle)),
        ("forecast_baseline", "ForecastBaseline", lambda: compute_forecast_baseline(pre_resolved=resolved_bundle)),
        ("derived_metrics", "DerivedMetrics", lambda: compute_derived_metrics(pre_resolved=resolved_bundle)),
        ("new_lost_same_store", "NewLostSameStore", lambda: compute_new_lost_same_store(pre_resolved=resolved_bundle)),
        ("concentration_analysis", "ConcentrationAnalysis", lambda: compute_concentration_analysis(pre_resolved=resolved_bundle)),
        ("cross_metric_correlation", "CrossMetricCorrelation", lambda: compute_cross_metric_correlation(pre_resolved=resolved_bundle)),
        ("lagged_correlation", "LaggedCorrelation", lambda: compute_lagged_correlation(pre_resolved=resolved_bundle)),
        ("variance_decomposition", "VarianceDecomposition", lambda: compute_variance_decomposition(pre_resolved=resolved_bundle)),
        ("outlier_impact", "OutlierImpact", lambda: compute_outlier_impact(pre_resolved=resolved_bundle)),
        ("distribution_analysis", "DistributionAnalysis", lambda: compute_distribution_analysis(pre_resolved=resolved_bundle)),
    ]

    cross_dims = (
        state.ctx.contract.cross_dimensions
        if state.ctx and state.ctx.contract and isinstance(getattr(state.ctx.contract, "cross_dimensions", None), (list, tuple))
        else []
    )
    if cross_dims and "cross_dimension_analysis" not in skip_tools:
        for cfg in cross_dims:
            defs.append(
                (
                    "cross_dimension_analysis",
                    f"CrossDimension_{cfg.name}",
                    lambda _cfg=cfg: compute_cross_dimension_analysis(
                        hierarchy_level=0,
                        auxiliary_dimension=_cfg.name,
                        min_sample_size=_cfg.min_sample_size,
                        max_cardinality=_cfg.max_cardinality,
                        pre_resolved=resolved_bundle,
                    ),
                )
            )
    return defs


async def _skipped_placeholder(name: str):
    t0 = time.perf_counter()
    res = json.dumps({"skipped": True, "reason": "disabled"})
    elapsed = time.perf_counter() - t0
    print(f"[StatisticalSummary] [TIMER] {name}: {elapsed:.2f}s (skipped)", flush=True)
    return res


async def _timed_tool(name: str, coro):
    t0 = time.perf_counter()
    try:
        result = await coro
        elapsed = time.perf_counter() - t0
        print(f"[StatisticalSummary] [TIMER] {name}: {elapsed:.2f}s", flush=True)
        return result
    except Exception as exc:
        elapsed = time.perf_counter() - t0
        print(f"[StatisticalSummary] [TIMER] {name}: {elapsed:.2f}s FAILED: {exc}", flush=True)
        raise


def _parse_result(res, name: str):
    if isinstance(res, Exception):
        print(f"[StatisticalSummary] Warning: {name} failed: {res}")
        return {"error": str(res)}
    try:
        return json.loads(res)
    except Exception as exc:
        print(f"[StatisticalSummary] Warning: {name} returned invalid JSON: {exc}")
        return {"error": "Invalid JSON"}


def _log_toggle_info(toggle_summary, skip_tools):
    print(
        f"[StatisticalSummary] Profile: {toggle_summary.get('profile', 'unknown')} "
        f"(source={toggle_summary.get('source', 'unknown')})"
    )
    if toggle_summary.get("enabled_tools"):
        print(f"[StatisticalSummary] Enabled: {toggle_summary.get('enabled_tools')}")
    if skip_tools:
        print(f"[StatisticalSummary] Disabled: {sorted(skip_tools)}")
    if toggle_summary.get("overrides"):
        print(f"[StatisticalSummary] Overrides: {toggle_summary.get('overrides')}")
    print("[StatisticalSummary] Running advanced analysis...")
