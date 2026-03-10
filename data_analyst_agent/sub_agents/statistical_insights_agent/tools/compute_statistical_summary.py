"""Orchestrates the statistical summary pipeline."""

from __future__ import annotations

import json

from ... import data_cache
from .stat_summary import (
    advanced_tools,
    anomaly_signals,
    data_prep,
    period_totals,
    per_item_metrics,
    result_builder,
    summary_enhancements,
)


async def compute_statistical_summary(
    analysis_focus: list[str] | None = None,
    custom_focus: str | None = None,
) -> str:
    try:
        state, _ = data_prep.prepare_state(
            data_cache.resolve_data_and_columns,
            analysis_focus=analysis_focus,
            custom_focus=custom_focus,
        )
        per_item_metrics.compute_account_metrics(state)
        anomaly_signals.compute_anomalies_and_correlations(state)
        period_totals.compute_monthly_totals(state)
        summary_enhancements.build_summary_stats(state)
        summary_enhancements.build_enhanced_drivers(state)
        resolved_bundle = advanced_tools.build_resolved_bundle_for_tools(state)
        advanced_results = await advanced_tools.run_advanced_tools(state, resolved_bundle)
        return result_builder.build_result(state, advanced_results)
    except Exception as exc:
        return json.dumps(
            {"error": f"Failed to compute statistical summary: {exc}", "traceback": str(exc)},
            indent=2,
        )
