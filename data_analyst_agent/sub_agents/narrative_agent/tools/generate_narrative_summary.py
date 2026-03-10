"""Deterministic narrative summary tool.

The production narrative agent is LLM-based. For E2E insight-quality validation
we need a fast, deterministic narrative renderer.

This tool builds a narrative from structured analysis artifacts, focusing on:
- top variance drivers
- anomaly descriptions (generic; supports optional labeled scenarios)
- quantitative deviation claims (percentages)
- actionable recommendations derived from available dimensions in the artifacts
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
    contract: dict | None = None,
    **_kwargs,
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

                # Dataset-agnostic dimension hints
                dims_txt = ""
                if isinstance(ex, Mapping) and ex:
                    # Prefer contract dimensions if provided (by name/column), else fall back to a few example keys.
                    dim_keys: list[str] = []
                    if isinstance(contract, dict):
                        for d in contract.get("dimensions", []) or []:
                            if isinstance(d, dict):
                                dim_keys.extend([x for x in (d.get("name"), d.get("column")) if x])
                    dim_keys = [str(k) for k in dim_keys if k]

                    picked = []

                    def _prefer(k: str) -> int:
                        kl = str(k).lower()
                        # Dataset-agnostic heuristic ordering:
                        # 0 = product/code identifiers
                        # 1 = geo/context fields
                        # 2 = human-readable names
                        # 3 = everything else
                        if any(tok in kl for tok in ("hs", "sku", "product", "item", "code")):
                            return 0
                        if any(tok in kl for tok in ("region", "state", "country", "city", "port", "terminal", "location")):
                            return 1
                        if "name" in kl:
                            return 2
                        return 3

                    if dim_keys:
                        ordered = sorted([k for k in dim_keys if k in ex], key=_prefer)
                        for k in ordered:
                            if ex.get(k) not in (None, ""):
                                v = ex.get(k)
                                kl = str(k).lower()
                                if kl.startswith("hs") and str(v).strip():
                                    picked.append(f"{k} {v}")
                                else:
                                    picked.append(f"{k}={v}")
                            if len(picked) >= 8:
                                break
                    if not picked:
                        ordered2 = sorted(list(ex.keys()), key=_prefer)
                        for k in ordered2:
                            v = ex.get(k)
                            if v not in (None, ""):
                                kl = str(k).lower()
                                if kl.startswith("hs") and str(v).strip():
                                    picked.append(f"{k} {v}")
                                else:
                                    picked.append(f"{k}={v}")
                            if len(picked) >= 8:
                                break
                    if picked:
                        dims_txt = " (" + ", ".join(picked) + ")"

                parts.append(
                    f"- {sid} [{atype}]: deviation {dev:+.1f}% (severity={sev}).{dims_txt}"
                )

                # Scenario-specific actionable recommendation seed (dataset-agnostic)
                if sid:
                    recommendations.append(
                        f"Investigate {sid} root causes and validate the magnitude ({dev:+.1f}%) using the relevant contract dimensions." 
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
                "Validate the highest-impact variance drivers with drill-down using the contract hierarchy levels.",
                "Cross-check anomalies against known events and shipment timing before escalation.",
                "Create monitoring rules per scenario type (drop/surge/shutdown) with clear escalation thresholds.",
            ]
        )

    parts.append("Recommended actions:")
    for i, r in enumerate(recommendations[:5], start=1):
        parts.append(f"{i}. {r}")

    return "\n".join(parts).strip() if parts else "No narrative available."
