"""Shared helpers for determining hierarchy analysis depth from state/contract."""

from __future__ import annotations

from typing import Iterable, Mapping, Any


def _level_indices_from_state(state: Mapping[str, Any], prefix: str) -> list[int]:
    """Return sorted level indices detected in session state for a prefix."""
    levels: list[int] = []
    for key, value in state.items():
        if not isinstance(key, str) or not key.startswith(prefix) or not value:
            continue
        remainder = key[len(prefix) :]
        try:
            level = int(remainder.split("_", 1)[0])
        except (ValueError, IndexError):
            continue
        levels.append(level)
    return sorted(set(levels))


def _contract_depth(contract) -> int:
    max_depth = 0
    if not contract:
        return max_depth
    hierarchies: Iterable[Any] = getattr(contract, "hierarchies", None) or []
    for hierarchy in hierarchies:
        children = getattr(hierarchy, "children", None)
        if children is None and isinstance(hierarchy, dict):
            children = hierarchy.get("children")
        depth = len(children or [])
        if depth > max_depth:
            max_depth = depth
    return max_depth


def hierarchy_level_range(
    state: Mapping[str, Any],
    contract,
    *,
    max_cap: int = 6,
    default_levels: int = 3,
) -> range:
    """Infer the range of hierarchy levels that should be materialized."""
    state_levels = _level_indices_from_state(state, "level_")
    contract_depth = _contract_depth(contract)
    observed_max = state_levels[-1] if state_levels else 0
    inferred_max = max(observed_max, contract_depth, default_levels)
    capped = min(max_cap, max(0, inferred_max))
    return range(0, capped + 1)


def independent_level_range(
    state: Mapping[str, Any],
    contract,
    *,
    max_cap: int = 4,
    default_levels: int = 2,
) -> range:
    """Infer range of independent (net-new) levels present in session state."""
    state_levels = _level_indices_from_state(state, "independent_level_")
    contract_depth = _contract_depth(contract)
    observed_max = state_levels[-1] if state_levels else 1
    inferred_max = max(observed_max, min(contract_depth, max_cap), default_levels)
    start_level = 1 if inferred_max >= 1 else 0
    capped = min(max_cap, max(start_level, inferred_max))
    return range(start_level, capped + 1)
