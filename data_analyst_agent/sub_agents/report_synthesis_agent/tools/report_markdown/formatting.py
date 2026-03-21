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
_METRIC_UNITS_DATASET: Optional[str] = None
_CURRENCY_TOKENS = {"usd", "currency", "dollars", "dollar", "us$", "us dollars"}


def load_metric_units() -> Dict[str, Dict[str, str]]:
    global _METRIC_UNITS_CACHE, _METRIC_UNITS_DATASET

    dataset_name: Optional[str] = None
    try:
        from config.dataset_resolver import get_active_dataset, get_dataset_path_optional

        dataset_name = get_active_dataset()
        if _METRIC_UNITS_CACHE is not None and dataset_name == _METRIC_UNITS_DATASET:
            return _METRIC_UNITS_CACHE

        path = get_dataset_path_optional("metric_units.yaml")
        if path and path.exists():
            import yaml

            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            # Support both flat mapping (metric: unit) and nested (metrics: {metric: {unit: ...}})
            _METRIC_UNITS_CACHE = data.get("metrics", None) or data or {}
        else:
            _METRIC_UNITS_CACHE = {}
        _METRIC_UNITS_DATASET = dataset_name
    except Exception:  # pragma: no cover
        _METRIC_UNITS_CACHE = {}
        _METRIC_UNITS_DATASET = dataset_name
    return _METRIC_UNITS_CACHE


def clear_metric_units_cache() -> None:
    global _METRIC_UNITS_CACHE, _METRIC_UNITS_DATASET
    _METRIC_UNITS_CACHE = None
    _METRIC_UNITS_DATASET = None


def normalize_unit(unit: Optional[str]) -> str:
    if unit is None:
        return "currency"
    text = str(unit).strip()
    return text or "currency"


def is_currency_unit(unit: str) -> bool:
    if not unit:
        return True
    normalized = unit.strip().lower()
    if "$" in unit:
        return True
    return normalized in _CURRENCY_TOKENS


def format_value(value: float, unit: str) -> str:
    normalized = normalize_unit(unit)
    if is_currency_unit(normalized):
        return f"${value:,.0f}"
    if normalized.lower() in {"count", "units", "unit"}:
        return f"{value:,.0f}"
    return f"{value:,.0f} {normalized}"


def unit_display_label(unit: str) -> str:
    normalized = normalize_unit(unit)
    if is_currency_unit(normalized):
        return "$"
    return normalized


def resolve_unit(analysis_target: Optional[str], contract_unit: Optional[str] = None) -> str:
    key = (analysis_target or "").strip()
    if key:
        units = load_metric_units()
        cfg = units.get(key) or units.get(key.strip())
        if isinstance(cfg, dict):
            value = str(cfg.get("unit", "currency"))
            normalized = value.strip()
            if normalized:
                return normalized
        elif isinstance(cfg, str):
            normalized = cfg.strip()
            if normalized:
                return normalized

    if contract_unit is not None:
        text_value = str(contract_unit).strip()
        if text_value:
            return text_value

    return "currency"


def format_variance(value: float, unit: str, analysis_target: Optional[str] = None) -> str:
    normalized = normalize_unit(unit)
    return format_value(value, normalized)


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
    "normalize_unit",
    "is_currency_unit",
    "format_value",
    "unit_display_label",
    "clear_metric_units_cache",
]
