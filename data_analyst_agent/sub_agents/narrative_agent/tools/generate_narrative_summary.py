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

import json
from collections.abc import Mapping
from typing import Any


def _safe_lower(x) -> str:
    return str(x).lower() if x is not None else ""


def _coerce_contract_dict(contract: Any) -> dict:
    if contract is None:
        return {}
    if isinstance(contract, str):
        try:
            return json.loads(contract)
        except json.JSONDecodeError:
            return {}
    if isinstance(contract, Mapping):
        return dict(contract)
    if hasattr(contract, "model_dump"):
        try:
            return contract.model_dump()
        except Exception:
            pass
    if hasattr(contract, "dict"):
        try:
            return contract.dict()
        except Exception:
            pass
    return {}


def _extract_dimension_aliases(contract_dict: Mapping | None) -> tuple[list[str], dict[str, int]]:
    if not isinstance(contract_dict, Mapping):
        return [], {}

    dims = contract_dict.get("dimensions") or []
    aliases: list[str] = []

    def _get(obj, key, default=None):
        if isinstance(obj, Mapping):
            return obj.get(key, default)
        return getattr(obj, key, default)

    for dim in dims:
        name = _get(dim, "name")
        column = _get(dim, "column")
        display = _get(dim, "display_name")
        for candidate in (name, column, display):
            if candidate and str(candidate) not in aliases:
                aliases.append(str(candidate))
                aliases.append(f"{candidate}_name")
                aliases.append(f"{candidate}_id")

    # Preserve insertion order but remove duplicates
    seen = set()
    ordered_aliases = []
    for alias in aliases:
        alias_str = str(alias)
        if alias_str and alias_str not in seen:
            seen.add(alias_str)
            ordered_aliases.append(alias_str)

    # Build priority map using hierarchy definition first, fall back to dimension order
    priority: dict[str, int] = {}
    hierarchy_children: list[str] = []
    for hierarchy in contract_dict.get("hierarchies", []) or []:
        children = hierarchy.get("children") if isinstance(hierarchy, Mapping) else getattr(hierarchy, "children", None)
        if children:
            for child in children:
                if child:
                    hierarchy_children.append(str(child))
    if not hierarchy_children:
        for dim in dims:
            key = _get(dim, "name") or _get(dim, "column")
            if key:
                hierarchy_children.append(str(key))

    for idx, child in enumerate(hierarchy_children):
        priority[child.lower()] = idx

    return ordered_aliases, priority


def _generic_key_priority(key: str, dimension_priority: dict[str, int] | None = None) -> tuple[int, str]:
    """Assign priority to dimension keys for narrative display.
    
    Args:
        key: Dimension key to prioritize
        dimension_priority: Contract-derived priority map (from hierarchy order)
        
    Returns:
        Tuple of (priority_rank, normalized_key) for sorting
        
    Priority order:
        - If dimension_priority provided, use contract hierarchy order (0-based)
        - Otherwise fall back to heuristic patterns:
            0: Geographic (region, country, market, geo, state, province, city)
            1: Categorical (segment, category, product, line, channel, type)
            2: Identifier (code, id, key)
            3: Label (name, label, description)
            4: Other
    """
    kl = key.lower()
    
    # Contract-driven priority takes precedence
    if dimension_priority and kl in dimension_priority:
        return (dimension_priority[kl], kl)
    
    # Fallback to heuristic patterns for datasets without explicit hierarchy
    if any(token in kl for token in ("region", "country", "market", "geo", "state", "province", "city", "location")):
        return (0, kl)
    if any(token in kl for token in ("segment", "category", "product", "line", "channel", "type", "class")):
        return (1, kl)
    if any(token in kl for token in ("code", "id", "key")):
        return (2, kl)
    if "name" in kl or "label" in kl or "description" in kl:
        return (3, kl)
    return (4, kl)


async def generate_narrative_summary(
    *,
    hierarchy_variance: dict | None = None,
    anomaly_indicators: dict | None = None,
    seasonal_decomposition: dict | None = None,
    contract: dict | None = None,
    **_kwargs,
) -> str:
    parts: list[str] = []
    contract_dict = _coerce_contract_dict(contract)
    dimension_aliases, dimension_priority = _extract_dimension_aliases(contract_dict)

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
                    picked: list[str] = []
                    example_key_lookup = {str(k).lower(): k for k in ex.keys()}

                    if dimension_aliases:
                        ordered_alias_keys: list[str] = []
                        for alias in dimension_aliases:
                            actual_key = example_key_lookup.get(alias.lower())
                            if actual_key and actual_key not in ordered_alias_keys:
                                ordered_alias_keys.append(actual_key)
                        if not ordered_alias_keys and example_key_lookup:
                            ordered_alias_keys = sorted(
                                example_key_lookup.values(),
                                key=lambda key: (
                                    dimension_priority.get(str(key).lower(), 10_000),
                                    str(key).lower(),
                                ),
                            )
                        for key in ordered_alias_keys:
                            value = ex.get(key)
                            if value not in (None, ""):
                                picked.append(f"{key}={value}")
                            if len(picked) >= 8:
                                break

                    if not picked:
                        ordered_generic = sorted(ex.keys(), key=lambda k: _generic_key_priority(str(k), dimension_priority))
                        for key in ordered_generic:
                            value = ex.get(key)
                            if value not in (None, ""):
                                picked.append(f"{key}={value}")
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
