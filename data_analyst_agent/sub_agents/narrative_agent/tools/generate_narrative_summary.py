"""Deterministic narrative summary tool.

The production narrative agent is LLM-based. For incremental E2E validation we
need a fast, deterministic narrative renderer that can be executed without an
LLM runtime.

This tool turns already-computed analysis artifacts into a concise narrative
string for assertions.
"""

from __future__ import annotations

from typing import Any, Mapping


def _get_first(mapping: Any, key: str, default=None):
    if isinstance(mapping, Mapping):
        return mapping.get(key, default)
    return default


async def generate_narrative_summary(
    *,
    hierarchy_variance: dict | None = None,
    anomaly_indicators: dict | None = None,
    seasonal_decomposition: dict | None = None,
) -> str:
    """Render a deterministic narrative string from prior level outputs."""

    parts: list[str] = []

    # Variance
    if isinstance(hierarchy_variance, dict):
        drivers = hierarchy_variance.get("top_drivers") or []
        if drivers:
            d0 = drivers[0]
            item = d0.get("item")
            pct = d0.get("variance_pct")
            parts.append(f"Top variance driver: {item} (YoY {pct:+.1f}%).")

    # Anomaly
    if isinstance(anomaly_indicators, dict):
        anomalies = anomaly_indicators.get("anomalies") or []
        if anomalies:
            a1 = anomalies[0]
            insight = a1.get("ground_truth_insight") or ""
            deviation = a1.get("deviation_pct")
            parts.append(f"Anomaly detected: {insight} (deviation {deviation:+.1f}%).")

    # Seasonality
    if isinstance(seasonal_decomposition, dict):
        s = seasonal_decomposition.get("seasonality_summary") or {}
        if s:
            peak = s.get("peak_month")
            trough = s.get("trough_month")
            amp = s.get("seasonal_amplitude_pct")
            parts.append(
                f"Seasonality: peak month={peak}, trough month={trough}, amplitude={amp:.1f}%."
            )

    if not parts:
        return "No narrative available: missing analysis inputs."

    return " ".join(parts)
