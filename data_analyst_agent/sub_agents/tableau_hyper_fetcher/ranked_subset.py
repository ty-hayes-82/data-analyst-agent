"""Resolve contract ranked_subset_fetch into physical Hyper columns for SQL generation."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional

from data_analyst_agent.semantic.models import DatasetContract


@dataclass(frozen=True)
class RankedSubsetSpec:
    """Physical column names and per-level caps for ranked Hyper subset CTEs."""

    rank_col: str
    column_level_0: str
    column_level_1: str
    top_level_0: int
    top_level_1_per_level_0: int
    column_level_2: Optional[str] = None
    top_level_2_per_level_1: Optional[int] = None

    @property
    def is_three_level(self) -> bool:
        return self.column_level_2 is not None


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _resolve_level_dimension_names(contract: DatasetContract, cfg) -> List[str]:
    """Return ordered contract dimension names for ranked_subset (2 or 3 levels)."""
    if cfg.level_0_dimension and cfg.level_1_dimension:
        names = [cfg.level_0_dimension.strip(), cfg.level_1_dimension.strip()]
        if cfg.level_2_dimension:
            names.append(cfg.level_2_dimension.strip())
        return names
    hier_name = (cfg.hierarchy_name or "").strip()
    if not hier_name:
        raise ValueError(
            "ranked_subset_fetch: set hierarchy_name or level_0_dimension and level_1_dimension."
        )
    hier = next((h for h in contract.hierarchies if h.name == hier_name), None)
    if hier is None:
        raise ValueError(
            f"ranked_subset_fetch: hierarchy '{hier_name}' not found on contract '{contract.name}'."
        )
    levels = list(hier.children or [])
    if len(levels) not in (2, 3):
        raise ValueError(
            f"ranked_subset_fetch: hierarchy '{hier_name}' needs 2 or 3 levels; got {len(levels)}."
        )
    return levels


def resolve_ranked_subset_spec(contract: DatasetContract) -> Optional[RankedSubsetSpec]:
    """Build a RankedSubsetSpec from the contract, or None if disabled / missing."""
    cfg = getattr(contract, "ranked_subset_fetch", None)
    if cfg is None or not cfg.enabled:
        return None

    level_names = _resolve_level_dimension_names(contract, cfg)
    cols = [contract.get_dimension(n).column for n in level_names]

    m = contract.get_metric(cfg.ranking_metric)
    if m.type == "derived" or not m.column:
        raise ValueError(
            f"ranked_subset_fetch.ranking_metric '{cfg.ranking_metric}' must be a non-derived "
            f"metric with a physical column (got type={m.type!r}, column={m.column!r})."
        )

    top0 = _env_int("DATA_ANALYST_RANKED_TOP_LEVEL_0", cfg.top_level_0)
    top0 = _env_int("DATA_ANALYST_RANKED_TOP_PARENTS", top0)
    top1 = _env_int("DATA_ANALYST_RANKED_TOP_LEVEL_1_PER_LEVEL_0", cfg.top_level_1_per_level_0)
    top1 = _env_int("DATA_ANALYST_RANKED_TOP_CHILDREN", top1)
    if top0 < 1:
        top0 = cfg.top_level_0
    if top1 < 1:
        top1 = cfg.top_level_1_per_level_0

    if len(cols) == 2:
        return RankedSubsetSpec(
            rank_col=m.column,
            column_level_0=cols[0],
            column_level_1=cols[1],
            top_level_0=top0,
            top_level_1_per_level_0=top1,
        )

    top2 = _env_int(
        "DATA_ANALYST_RANKED_TOP_LEVEL_2_PER_LEVEL_1",
        cfg.top_level_2_per_level_1 if cfg.top_level_2_per_level_1 is not None else 30,
    )
    if top2 < 1:
        top2 = cfg.top_level_2_per_level_1 or 30

    return RankedSubsetSpec(
        rank_col=m.column,
        column_level_0=cols[0],
        column_level_1=cols[1],
        column_level_2=cols[2],
        top_level_0=top0,
        top_level_1_per_level_0=top1,
        top_level_2_per_level_1=top2,
    )
