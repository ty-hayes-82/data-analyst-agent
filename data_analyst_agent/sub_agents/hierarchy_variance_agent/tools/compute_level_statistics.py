"""Public entry point for hierarchy level statistics."""

from __future__ import annotations

from typing import Optional

from data_analyst_agent.sub_agents.data_cache import resolve_data_and_columns  # re-export for legacy patch sites

from .level_stats import core as _core


async def compute_level_statistics(
    level: int,
    analysis_period: str = "latest",
    variance_type: str = "yoy",
    top_n: int = 10,
    cumulative_threshold: float = 80.0,
    hierarchy_name: Optional[str] = None,
) -> str:
    """Delegate to the split-out core implementation."""
    _core.resolve_data_and_columns = resolve_data_and_columns
    return await _core.compute_level_statistics_impl(
        level=level,
        analysis_period=analysis_period,
        variance_type=variance_type,
        top_n=top_n,
        cumulative_threshold=cumulative_threshold,
        hierarchy_name=hierarchy_name,
    )
