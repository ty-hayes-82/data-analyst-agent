"""Formatting helpers for markdown report generation."""

from __future__ import annotations

from typing import Dict, Optional, Set

_DERIVED_TAGS: Set[str] = frozenset(
    {
        "correlation",
        "leading_indicator",
        "mix_shift",
        "hierarchy",
        "cross_metric",
        "concentration",
        "operational_link",
        "anova",
        "variance",
        "regional_analysis",
        "market_share",
        "drill_down",
    }
)

_ZERO_VARIANCE_PATTERNS = (
    "Variance of $0",
    "Variance of $0.00",
    "Variance of 0",
    "Variance of +0",
    "Variance of -0",
    "Variance of +0.00",
    "Variance of -0.00",
)

_METRIC_UNITS_CACHE: Optional[Dict[str, Dict[str, str]]] = None


def load_metric_units() -> Dict[str, Dict[str, str]]:
    global _METRIC_UNITS_CACHE
    if _METRIC_UNITS_CACHE is not None:
        return _METRIC_UNITS_CACHE

    try:
        from config.dataset_resolver import get_dataset_path_optional

        path = get_dataset_path_optional("metric_units.yaml")
        if path and path.exists():
            import yaml

            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            _METRIC_UNITS_CACHE = data.get("metrics", {}) or {}
        else:
            _METRIC_UNITS_CACHE = {}
    except Exception:  # pragma: no cover
        _METRIC_UNITS_CACHE = {}
    return _METRIC_UNITS_CACHE


def resolve_unit(analysis_target: str) -> str:
    units = load_metric_units()
    cfg = units.get(analysis_target) or units.get(analysis_target.strip())
    if cfg and isinstance(cfg, dict):
        return str(cfg.get("unit", "currency"))
    return "currency"


def format_variance(value: float, unit: str, analysis_target: Optional[str] = None) -> str:
    if analysis_target:
        units = load_metric_units()
        cfg = units.get(analysis_target) or {}
        if isinstance(cfg, dict):
            unit_type = cfg.get("unit", unit)
            suffix = cfg.get("suffix", "")
            if unit_type == "currency":
                return f"${value:,.0f}"
            if unit_type in ("miles", "count", "ratio") and suffix:
                return f"{value:,.0f} {suffix}"
            if unit_type in ("miles", "count"):
                return f"{value:,.0f}"
    if unit == "currency":
        return f"${value:,.0f}"
    return f"{value:,.0f}"


def is_skip_card(card: dict) -> bool:
    if not card or not isinstance(card, dict):
        return True
    what = str(card.get("what_changed", "")).strip()
    if any(pattern in what for pattern in _ZERO_VARIANCE_PATTERNS):
        return True

    evidence = card.get("evidence", {})
    if isinstance(evidence, dict):
        for key in ("variance_dollar", "variance", "variance_amount"):
            value = evidence.get(key)
            if value is None:
                continue
            try:
                if abs(float(value)) < 0.001:
                    return True
            except (TypeError, ValueError):
                continue
    return False


def card_tags(card: dict) -> Set[str]:
    tags = card.get("tags") or []
    return {str(tag).lower() for tag in tags}


__all__ = [
    "_DERIVED_TAGS",
    "format_variance",
    "resolve_unit",
    "card_tags",
    "is_skip_card",
]
