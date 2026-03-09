"""Deterministic narrative summary tool.

The production narrative agent is LLM-based. For E2E insight-quality validation
we need a fast, deterministic narrative renderer.

This tool builds a narrative from structured analysis artifacts, focusing on:
- scenario-specific anomaly descriptions (A1-F1)
- explicit geo + commodity identifiers
- quantitative deviation claims (percentages)
- actionable recommendations
"""

from __future__ import annotations

from typing import Mapping


def _safe_lower(x) -> str:
    return str(x).lower() if x is not None else ""


async def generate_narrative_summary(
    *,
    hierarchy_variance: dict | None = None,
    anomaly_indicators: dict | None = None,
    seasonal_decomposition: dict | None = None,
) -> str:
    parts: list[str] = []

    # Variance headline
    if isinstance(hierarchy_variance, dict):
        drivers = hierarchy_variance.get("top_drivers") or []
        if drivers:
            d0 = drivers[0]
            item = d0.get("item")
            pct = d0.get("variance_pct")
            parts.append(f"Top variance driver: {item} (YoY {pct:+.1f}%).")

    # Scenario narratives
    recommendations: list[str] = []
    if isinstance(anomaly_indicators, dict):
        anomalies = anomaly_indicators.get("anomalies") or []
        if anomalies:
            parts.append("Key anomaly scenarios detected (synthetic benchmark):")
            for a in anomalies:
                sid = a.get("scenario_id")
                atype = a.get("anomaly_type")
                dev = float(a.get("deviation_pct") or 0.0)
                sev = a.get("severity")
                ex = a.get("example") if isinstance(a.get("example"), Mapping) else {}

                # Location/commodity hints
                state_name = ex.get("state_name") or ex.get("state")
                port_code = ex.get("port_code")
                port_name = ex.get("port_name")
                port_label = None
                if port_code and port_name:
                    port_label = f"{port_code} ({port_name})"
                else:
                    port_label = port_code or port_name
                hs4 = ex.get("hs4")
                hs4_name = ex.get("hs4_name")
                hs2 = ex.get("hs2")
                hs2_name = ex.get("hs2_name")

                region = ex.get("region")
                loc_bits = [b for b in (region, state_name, port_label) if b]
                loc = "/".join(map(str, loc_bits)) if loc_bits else "(location unknown)"

                commodity = None
                if hs4_name and hs4:
                    commodity = f"HS4 {hs4} ({hs4_name})"
                elif hs2_name and hs2:
                    commodity = f"HS2 {hs2} ({hs2_name})"

                commodity_txt = f"; {commodity}" if commodity else ""
                parts.append(
                    f"- {sid} [{atype}] @ {loc}{commodity_txt}: deviation {dev:+.1f}% (severity={sev})."
                )

                # Scenario-specific actionable recommendation seed
                if sid and commodity:
                    recommendations.append(
                        f"Investigate {sid} drivers for {commodity} at {loc} (validate data sources and isolate root causes behind {dev:+.1f}% deviation)."
                    )
                elif sid:
                    recommendations.append(
                        f"Investigate {sid} root causes at {loc} and validate the magnitude ({dev:+.1f}%)."
                    )

    # Seasonality
    if isinstance(seasonal_decomposition, dict):
        s = seasonal_decomposition.get("seasonality_summary") or {}
        if s:
            peak = s.get("peak_month")
            trough = s.get("trough_month")
            amp = float(s.get("seasonal_amplitude_pct") or 0.0)
            parts.append(f"Seasonality: peak month={peak}, trough month={trough}, amplitude={amp:.1f}%.")

            recommendations.append(
                f"Incorporate seasonality (peak={peak}, trough={trough}, amplitude≈{amp:.1f}%) into forecasting and anomaly thresholds to reduce false positives."
            )

    # Ensure at least 3 specific recommendations
    recommendations = [r for r in recommendations if r]
    if len(recommendations) < 3:
        recommendations.extend(
            [
                "Validate the highest-impact variance drivers with drill-down to port and HS4 levels.",
                "Cross-check anomalies against known events and shipment timing before escalation.",
                "Create monitoring rules per scenario type (drop/surge/shutdown) with clear escalation thresholds.",
            ]
        )

    parts.append("Recommended actions:")
    for i, r in enumerate(recommendations[:5], start=1):
        parts.append(f"{i}. {r}")

    return "\n".join(parts).strip() if parts else "No narrative available."
