"""Per-drill-level entity filtering (top %% or top N) for hierarchy statistics."""

from __future__ import annotations

import os
from typing import List, Optional, Tuple

import pandas as pd

from data_analyst_agent.semantic.models import (
    DatasetContract,
    HierarchyEntityFilterConfig,
    TierFilterRule,
)


def parse_tier_filter_env(raw: str) -> List[TierFilterRule]:
    """Parse DATA_ANALYST_TIER_FILTER: ``level:mode:value`` or ``level:mode:value@partition_dim`` per segment.

    Example: ``1:top_pct:100,2:top_pct:95,3:top_n:20@gl_div_nm``
    """
    rules: List[TierFilterRule] = []
    for segment in raw.split(","):
        segment = segment.strip()
        if not segment:
            continue
        partition_by: Optional[str] = None
        if "@" in segment:
            segment, _, dim = segment.partition("@")
            partition_by = dim.strip() or None
        parts = segment.split(":")
        if len(parts) != 3:
            raise ValueError(
                f"Invalid tier filter segment {segment!r}; expected level:mode:value or level:mode:value@dim"
            )
        level_s, mode, val_s = parts[0].strip(), parts[1].strip().lower(), parts[2].strip()
        if mode not in ("top_pct", "top_n"):
            raise ValueError(f"Invalid tier filter mode {mode!r}; use top_pct or top_n")
        rules.append(
            TierFilterRule(
                level=int(level_s),
                mode=mode,  # type: ignore[arg-type]
                value=float(val_s),
                partition_by_dimension=partition_by,
            )
        )
    return rules


def resolve_effective_filter_config(
    contract: DatasetContract,
    hierarchy_name: Optional[str],
) -> Optional[HierarchyEntityFilterConfig]:
    """Merge contract hierarchy_entity_filters with optional env override of levels."""
    base = getattr(contract, "hierarchy_entity_filters", None)
    env_raw = (os.environ.get("DATA_ANALYST_TIER_FILTER") or "").strip()
    parsed_override: Optional[List[TierFilterRule]] = None

    if env_raw:
        try:
            parsed_override = parse_tier_filter_env(env_raw)
        except ValueError as exc:
            print(f"[TierFilter] Invalid DATA_ANALYST_TIER_FILTER: {exc}")

    if parsed_override is not None:
        if not base:
            print(
                "[TierFilter] DATA_ANALYST_TIER_FILTER set but contract has no hierarchy_entity_filters; "
                "define ranking_metric and hierarchy_name in contract to use tier filters."
            )
            return None
        base = base.model_copy(update={"levels": parsed_override})

    if not base or not base.levels:
        return None

    if base.hierarchy_name and hierarchy_name and base.hierarchy_name != hierarchy_name:
        return None

    return base


def _ranking_metric_column(contract: DatasetContract, metric_name: str) -> Optional[str]:
    try:
        m = contract.get_metric(metric_name)
    except KeyError:
        print(f"[TierFilter] Unknown ranking_metric {metric_name!r} on contract")
        return None
    if m.type == "derived" or not m.column:
        print(
            f"[TierFilter] ranking_metric {metric_name!r} must be non-derived with a physical column "
            f"(got type={m.type!r}, column={m.column!r})"
        )
        return None
    return m.column


def _entities_to_keep_from_totals(
    entity_totals: pd.Series,
    rule: TierFilterRule,
) -> List:
    """entity_totals: index = entity id, values = sum(rank metric), sorted descending by value."""
    if entity_totals.empty:
        return []
    entity_totals = entity_totals.sort_values(ascending=False)
    if rule.mode == "top_n":
        n = max(1, int(rule.value))
        return list(entity_totals.head(n).index)

    pct = min(100.0, float(rule.value))
    total = float(entity_totals.sum())
    if total == 0 or pd.isna(total):
        return list(entity_totals.index)

    threshold = total * (pct / 100.0)
    cum = entity_totals.cumsum()
    kept: List = []
    for ent, csum in cum.items():
        kept.append(ent)
        if float(csum) >= threshold:
            break
    return kept


def filter_entities_for_level(
    df: pd.DataFrame,
    level_col: str,
    rank_col: str,
    rule: TierFilterRule,
    contract: DatasetContract,
) -> pd.DataFrame:
    """Return rows whose ``level_col`` values pass the tier rule (global or partitioned)."""
    if df.empty or level_col not in df.columns:
        return df
    if rank_col not in df.columns:
        print(f"[TierFilter] Ranking column {rank_col!r} missing; skipping level filter.")
        return df

    parent_col: Optional[str] = None
    if rule.partition_by_dimension:
        try:
            dim = contract.get_dimension(rule.partition_by_dimension)
            parent_col = dim.column
        except KeyError:
            print(
                f"[TierFilter] Unknown partition_by_dimension {rule.partition_by_dimension!r}; skipping."
            )
            return df
        if parent_col not in df.columns:
            print(f"[TierFilter] Partition column {parent_col!r} missing; skipping.")
            return df

    if parent_col:
        keep_rows: List[Tuple[object, object]] = []
        grouped = df.groupby([parent_col, level_col], dropna=False)[rank_col].sum()
        for parent_val, sub in grouped.groupby(level=0):
            flat = sub.droplevel(0) if isinstance(sub.index, pd.MultiIndex) else sub
            for ent in _entities_to_keep_from_totals(flat, rule):
                keep_rows.append((parent_val, ent))
        if not keep_rows:
            return df.iloc[0:0].copy()
        keys_df = pd.DataFrame(keep_rows, columns=[parent_col, level_col])
        out = df.merge(keys_df, on=[parent_col, level_col], how="inner")
        print(
            f"[TierFilter] level_col={level_col!r} partition={parent_col!r} "
            f"mode={rule.mode} value={rule.value} -> {len(out)} rows (from {len(df)})"
        )
        return out

    totals = df.groupby(level_col, dropna=False)[rank_col].sum()
    keep_entities = _entities_to_keep_from_totals(totals, rule)
    out = df[df[level_col].isin(keep_entities)].copy()
    print(
        f"[TierFilter] level_col={level_col!r} mode={rule.mode} value={rule.value} "
        f"-> {len(out)} rows (from {len(df)}), {len(keep_entities)} entities kept"
    )
    return out


def apply_tier_filter_to_dataframe(
    df: pd.DataFrame,
    contract: DatasetContract,
    level: int,
    level_col: str,
    hierarchy_name: Optional[str],
    cfg: HierarchyEntityFilterConfig,
) -> pd.DataFrame:
    """Apply the rule matching ``level`` if configured."""
    if level <= 0 or level_col == "_total_agg":
        return df

    if cfg.hierarchy_name and hierarchy_name and cfg.hierarchy_name != hierarchy_name:
        return df

    rule = next((r for r in cfg.levels if r.level == level), None)
    if rule is None:
        return df

    rank_col = _ranking_metric_column(contract, cfg.ranking_metric)
    if not rank_col:
        return df

    return filter_entities_for_level(df, level_col, rank_col, rule, contract)
