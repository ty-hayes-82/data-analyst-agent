"""Advanced analysis orchestration for the statistical summary tool."""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any, Dict, List, Tuple

from config.statistical_analysis_config import (
    get_analysis_toggle_summary,
    get_skip_tools,
)

from .._resolved_data import build_resolved_bundle
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
from .data_prep import SummaryPrepResult
from .utils import json_default


async def run_advanced_analysis(prep: SummaryPrepResult) -> Dict[str, Any]:
    """Execute the advanced async tools with concurrency controls."""

    skip_tools = get_skip_tools()
    toggle_summary = get_analysis_toggle_summary()

    print(
        f"[StatisticalSummary] Profile: {toggle_summary.get('profile', 'unknown')} "
        f"(source={toggle_summary.get('source', 'unknown')})"
    )
    if toggle_summary.get("enabled_tools"):
        print(
            f"[StatisticalSummary] Enabled: {toggle_summary.get('enabled_tools')}"
        )
    if skip_tools:
        print(f"[StatisticalSummary] Disabled: {sorted(skip_tools)}")
    if toggle_summary.get("overrides"):
        print(
            f"[StatisticalSummary] Overrides: {toggle_summary.get('overrides')}"
        )
    print("[StatisticalSummary] Running advanced analysis...")

    lag_meta = (
        {
            "lag_periods": prep.lag,
            "effective_latest": prep.latest_period,
            "lag_window": prep.lag_window,
        }
        if prep.lag > 0
        else None
    )

    resolved_bundle = build_resolved_bundle(
        df=prep.df,
        pivot=prep.pivot,
        time_col=prep.time_col,
        metric_col=prep.metric_col,
        grain_col=prep.grain_col,
        name_col=prep.name_col,
        ctx=prep.ctx,
        names_map=prep.names_map,
        monthly_totals=prep.monthly_totals,
        lag_metadata=lag_meta,
    )

    concurrency = int(os.environ.get("STATISTICAL_ADVANCED_CONCURRENCY", "3"))
    sem = asyncio.Semaphore(concurrency)

    async def _run_with_sem(coro):
        async with sem:
            return await coro

    async def _timed_tool(name: str, coro):
        t0 = time.perf_counter()
        try:
            result = await coro
            elapsed = time.perf_counter() - t0
            print(
                f"[StatisticalSummary] [TIMER] {name}: {elapsed:.2f}s", flush=True
            )
            return result
        except Exception as exc:
            elapsed = time.perf_counter() - t0
            print(
                f"[StatisticalSummary] [TIMER] {name}: {elapsed:.2f}s FAILED: {exc}",
                flush=True,
            )
            raise

    async def _skipped_placeholder(name: str):
        t0 = time.perf_counter()
        payload = json.dumps(
            {"skipped": True, "reason": "disabled"}, default=json_default
        )
        elapsed = time.perf_counter() - t0
        print(
            f"[StatisticalSummary] [TIMER] {name}: {elapsed:.2f}s (skipped)",
            flush=True,
        )
        return payload

    tool_defs: List[Tuple[str, str, Any]] = [
        (
            "seasonal_decomposition",
            "SeasonalDecomposition",
            lambda: compute_seasonal_decomposition(pre_resolved=resolved_bundle),
        ),
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

    cross_dim_enabled = "cross_dimension_analysis" not in skip_tools
    cross_dims = (
        prep.ctx.contract.cross_dimensions
        if (
            cross_dim_enabled
            and prep.ctx
            and getattr(prep.ctx, "contract", None)
            and isinstance(getattr(prep.ctx.contract, "cross_dimensions", None), (list, tuple))
        )
        else []
    )

    for cd_cfg in cross_dims:
        name = cd_cfg.name
        min_sample = cd_cfg.min_sample_size
        max_cardinality = cd_cfg.max_cardinality

        def _make_cd_lambda(
            dim_name: str,
            sample_size: int,
            cardinality: int,
        ):
            return lambda: compute_cross_dimension_analysis(
                hierarchy_level=0,
                auxiliary_dimension=dim_name,
                min_sample_size=sample_size,
                max_cardinality=cardinality,
                pre_resolved=resolved_bundle,
            )

        tool_defs.append(
            (
                "cross_dimension_analysis",
                f"CrossDimension_{name}",
                _make_cd_lambda(name, min_sample, max_cardinality),
            )
        )

    tasks = []
    for env_name, display_name, coro_fn in tool_defs:
        if env_name in skip_tools:
            tasks.append(_run_with_sem(_skipped_placeholder(display_name)))
        else:
            tasks.append(_run_with_sem(_timed_tool(display_name, coro_fn())))

    start = time.perf_counter()
    results = await asyncio.gather(*tasks, return_exceptions=True)
    total_elapsed = time.perf_counter() - start
    print(
        f"[StatisticalSummary] [TIMER] Advanced analysis total: {total_elapsed:.2f}s",
        flush=True,
    )

    def _parse_result(payload, name: str):
        if isinstance(payload, Exception):
            print(f"[StatisticalSummary] Warning: {name} failed: {payload}")
            return {"error": str(payload)}
        try:
            return json.loads(payload)
        except Exception as exc:
            print(
                f"[StatisticalSummary] Warning: {name} returned invalid JSON: {exc}"
            )
            return {"error": "Invalid JSON"}

    fixed_count = 12
    parsed_fixed = [
        _parse_result(result, tool_defs[idx][1]) for idx, result in enumerate(results[:fixed_count])
    ]

    cross_dim_data: Dict[str, Any] = {}
    for idx in range(fixed_count, len(results)):
        display_name = tool_defs[idx][1]
        cross_dim_data[display_name] = _parse_result(results[idx], display_name)

    print("[StatisticalSummary] Advanced analysis complete")

    return {
        "seasonal_data": parsed_fixed[0],
        "changepoint_data": parsed_fixed[1],
        "mad_data": parsed_fixed[2],
        "forecast_data": parsed_fixed[3],
        "ratio_data": parsed_fixed[4],
        "nlss_data": parsed_fixed[5],
        "concentration_data": parsed_fixed[6],
        "cross_metric_data": parsed_fixed[7],
        "lagged_data": parsed_fixed[8],
        "variance_data": parsed_fixed[9],
        "outlier_impact_data": parsed_fixed[10],
        "distribution_data": parsed_fixed[11],
        "cross_dim_data": cross_dim_data if cross_dim_data else None,
    }
