"""Comprehensive Statistical Summary Tool (modular orchestrator)."""

from __future__ import annotations

import json
from typing import Any, Dict

from .stat_summary.advanced_analysis import run_advanced_analysis
from .stat_summary.core_metrics import (
    build_summary_sections,
    compute_correlations,
    detect_anomalies,
    generate_account_statistics,
)
from .stat_summary.data_prep import prepare_summary_inputs
from .stat_summary.utils import json_default


def _error_payload(message: str) -> str:
    return json.dumps({"error": message}, indent=2, default=json_default)


async def compute_statistical_summary() -> str:
    """Compute comprehensive statistical summary from validated data."""

    try:
        try:
            prep = prepare_summary_inputs()
        except ValueError as exc:
            return _error_payload(str(exc))

        (
            account_stats,
            top_drivers,
            most_volatile,
            total_avg_mag,
        ) = generate_account_statistics(prep.pivot, prep.names_map)

        anomalies_sorted, anomaly_latest_flag = detect_anomalies(
            pivot=prep.pivot,
            names_map=prep.names_map,
            latest_period=prep.latest_period,
            recent_periods=prep.recent_periods,
        )

        correlations, suspected_uniform_growth = compute_correlations(
            pivot=prep.pivot,
            names_map=prep.names_map,
            ctx=prep.ctx,
        )

        (
            summary_stats,
            enhanced_top_drivers,
            delta_attribution,
        ) = build_summary_sections(
            pivot=prep.pivot,
            monthly_totals=prep.monthly_totals,
            latest_period=prep.latest_period,
            prev_period=prep.prev_period,
            temporal_grain=prep.temporal_grain,
            period_unit=prep.period_unit,
            account_stats=account_stats,
            top_drivers=top_drivers,
            most_volatile=most_volatile,
            total_avg_mag=total_avg_mag,
            contribution_share=prep.contribution_share,
            pattern_label_by_account=prep.pattern_label_by_account,
            anomalies_sorted=anomalies_sorted,
            change_series=prep.change_series,
            names_map=prep.names_map,
            anomaly_latest_flag=anomaly_latest_flag,
            lag=prep.lag,
            lag_window=prep.lag_window,
        )

        advanced_results = await run_advanced_analysis(prep)

        result: Dict[str, Any] = {
            "top_drivers": top_drivers,
            "most_volatile": most_volatile,
            "anomalies": anomalies_sorted,
            "correlations": correlations,
            "monthly_totals": prep.monthly_totals,
            "period_totals": prep.monthly_totals,
            "summary_stats": summary_stats,
            "enhanced_top_drivers": enhanced_top_drivers,
            "normalization_unavailable": True,
            "normalization_readiness": {
                "ready": False,
                "missing_metrics": ["miles", "loads", "stops"],
            },
            "delta_attribution": delta_attribution,
            "dq_flags": {
                "suspected_uniform_growth": suspected_uniform_growth,
            },
            "lag_metadata": summary_stats.get("lag_metadata")
            if summary_stats.get("lag_metadata")
            else (
                {
                    "lag_periods": prep.lag,
                    "effective_latest": prep.latest_period,
                    "lag_window": prep.lag_window,
                }
                if prep.lag > 0
                else None
            ),
            "seasonal_analysis": advanced_results["seasonal_data"],
            "change_points": advanced_results["changepoint_data"],
            "mad_outliers": advanced_results["mad_data"],
            "forecasts": advanced_results["forecast_data"],
            "operational_ratios": advanced_results["ratio_data"],
            "new_lost_same_store": advanced_results["nlss_data"],
            "concentration_analysis": advanced_results["concentration_data"],
            "cross_metric_correlations": advanced_results["cross_metric_data"],
            "lagged_correlations": advanced_results["lagged_data"],
            "variance_decomposition": advanced_results["variance_data"],
            "outlier_impact": advanced_results["outlier_impact_data"],
            "distribution_analysis": advanced_results["distribution_data"],
            "cross_dimension_analysis": advanced_results["cross_dim_data"],
            "metadata": {
                "computation_method": "pandas/numpy statistical analysis + advanced methods",
                "anomaly_threshold": "z-score >= 2.0",
                "slope_method": f"last 3 {prep.period_unit}s linear regression",
                "temporal_grain": prep.temporal_grain,
                "period_unit": prep.period_unit,
                "advanced_methods": [
                    "STL seasonal decomposition",
                    "PELT change point detection",
                    "MAD robust outlier detection",
                    "ARIMA forecasting",
                    "Operational ratio analysis",
                    "New/Lost/Same-Store decomposition",
                    "Concentration / Pareto analysis (HHI, Gini)",
                    "Cross-metric correlation matrix",
                    "Lagged cross-correlation (leading indicators)",
                    "Variance decomposition (ANOVA)",
                    "Outlier impact quantification",
                    "Distribution shape analysis",
                    "Cross-dimension analysis (auxiliary dimension interaction)",
                ],
            },
        }

        return json.dumps(result, indent=2, default=json_default)

    except Exception as exc:  # pragma: no cover - defensive guardrail
        return json.dumps(
            {
                "error": f"Failed to compute statistical summary: {exc}",
                "traceback": str(exc),
            },
            indent=2,
            default=json_default,
        )
