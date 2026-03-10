"""Utility helpers for translating request metadata into contract-aware filters."""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

from ..semantic.models import DatasetContract, DimensionDefinition

# Values that indicate the caller wants the full dataset (no filter applied).
GENERIC_UNFILTERED_TOKENS = frozenset(
    {
        "",
        "all",
        "all entities",
        "all regions",
        "all terminals",
        "entire network",
        "entire scope",
        "none",
        "total",
    }
)


def _normalize_key(key: str) -> str:
    return str(key).strip().lower()


def _normalize_value(value: Any) -> str:
    return str(value).strip().lower()


def _build_alias_map(contract: DatasetContract) -> Dict[str, DimensionDefinition]:
    alias_map: Dict[str, DimensionDefinition] = {}
    for dim in contract.dimensions:
        alias_map[_normalize_key(dim.name)] = dim
        alias_map[_normalize_key(dim.column)] = dim
        for tag in dim.tags:
            alias_map[_normalize_key(tag)] = dim
    return alias_map


def extract_dimension_filters(
    contract: DatasetContract,
    *,
    request_analysis: Optional[Dict[str, Any]] = None,
    candidates: Optional[Iterable[Tuple[Optional[str], Any]]] = None,
) -> Dict[str, Any]:
    """Return a mapping of physical column -> filter value derived from the contract.

    Args:
        contract: DatasetContract describing available dimensions.
        request_analysis: Parsed request_analysis payload stored in session state.
        candidates: Additional (dimension_key, value) tuples to evaluate in order.

    Returns:
        Dict mapping DataFrame column names to the desired filter value.
    """

    alias_map = _build_alias_map(contract)
    filters: Dict[str, Any] = {}

    def _maybe_add(key: Optional[str], value: Any) -> None:
        if key is None or value is None:
            return
        normalized_value = _normalize_value(value)
        if normalized_value in GENERIC_UNFILTERED_TOKENS:
            return
        normalized_key = _normalize_key(key)
        if normalized_key.endswith("_value"):
            normalized_key = normalized_key[:-6]
        dim = alias_map.get(normalized_key)
        if not dim:
            return
        filters[dim.column] = value

    if candidates:
        for key, value in candidates:
            _maybe_add(key, value)

    if isinstance(request_analysis, dict):
        _maybe_add(
            request_analysis.get("primary_dimension"),
            request_analysis.get("primary_dimension_value"),
        )
        _maybe_add(
            request_analysis.get("dimension"), request_analysis.get("dimension_value")
        )
        for key, value in request_analysis.items():
            _maybe_add(key, value)

    return filters


def describe_dimension_filters(
    contract: DatasetContract, filters: Dict[str, Any]
) -> str:
    """Human-readable summary of the applied dimension filters."""
    if not filters:
        return "(none)"

    parts: List[str] = []
    dim_by_column = {d.column: d for d in contract.dimensions}
    for column, value in filters.items():
        dim = dim_by_column.get(column)
        label = dim.name if dim else column
        parts.append(f"{label}={value}")
    return ", ".join(parts)
