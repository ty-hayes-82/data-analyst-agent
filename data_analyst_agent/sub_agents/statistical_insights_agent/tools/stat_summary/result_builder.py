"""Final result assembly for statistical summary."""

from __future__ import annotations

import json
from typing import Any

from ..stat_summary.state import SummaryState


def build_result(state: SummaryState, advanced_results: dict[str, Any]) -> str:
    result = {
        "top_drivers": state.top_drivers,
        "most_volatile": state.most_volatile,
        "anomalies": state.anomalies_sorted,
        "correlations": state.correlations,
        "monthly_totals": state.monthly_totals,
        "period_totals": state.monthly_totals,
        "summary_stats": state.summary_stats,
        "enhanced_top_drivers": state.enhanced_top_drivers,
        "normalization_unavailable": True,
        "normalization_readiness": {"ready": False, "missing_metrics": ["miles", "loads", "stops"]},
        "delta_attribution": state.delta_attribution,
        "dq_flags": {"suspected_uniform_growth": state.suspected_uniform_growth},
        "lag_metadata": (
            {
                "lag_periods": state.lag,
                "effective_latest": state.latest_period,
                "lag_window": state.lag_window,
            }
            if state.lag > 0
            else None
        ),
    }

    # Map advanced results to legacy keys
    result.update({
        "seasonal_analysis": advanced_results.get("SeasonalDecomposition"),
        "change_points": advanced_results.get("ChangePoints"),
        "mad_outliers": advanced_results.get("MADOutliers"),
        "forecasts": advanced_results.get("ForecastBaseline"),
        "operational_ratios": advanced_results.get("DerivedMetrics"),
        "new_lost_same_store": advanced_results.get("NewLostSameStore"),
        "concentration_analysis": advanced_results.get("ConcentrationAnalysis"),
        "cross_metric_correlations": advanced_results.get("CrossMetricCorrelation"),
        "lagged_correlations": advanced_results.get("LaggedCorrelation"),
        "variance_decomposition": advanced_results.get("VarianceDecomposition"),
        "outlier_impact": advanced_results.get("OutlierImpact"),
        "distribution_analysis": advanced_results.get("DistributionAnalysis"),
        "cross_dimension_analysis": _collect_cross_dim(advanced_results),
    })

    focus_context = {
        "analysis_focus": state.analysis_focus,
        "custom_focus": state.custom_focus,
        **(state.focus_settings or {}),
    }

    z_threshold = focus_context.get("z_threshold", 2.0)

    result["metadata"] = {
        "computation_method": "pandas/numpy statistical analysis + advanced methods",
        "anomaly_threshold": f"z-score >= {z_threshold}",
        "slope_method": f"last 3 {state.period_unit}s linear regression",
        "temporal_grain": state.temporal_grain,
        "time_frequency": state.time_frequency,
        "period_unit": state.period_unit,
        "focus_context": focus_context,
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
    }

    return json.dumps(result, indent=2, default=_json_default)


def _collect_cross_dim(advanced_results: dict[str, Any]) -> dict[str, Any] | None:
    cross_dim = {
        name: payload
        for name, payload in advanced_results.items()
        if name.startswith("CrossDimension_")
    }
    return cross_dim or None


def _json_default(value):
    try:
        import numpy as np

        if isinstance(value, np.generic):
            return value.item()
    except Exception:
        pass
    return str(value)
