"""Unit tests for hierarchy tier filtering (top %% / top N)."""

from __future__ import annotations

import os

import pandas as pd
import pytest

from data_analyst_agent.semantic.models import (
    DatasetContract,
    DimensionDefinition,
    GrainConfig,
    HierarchyEntityFilterConfig,
    HierarchyNode,
    MetricDefinition,
    TierFilterRule,
    TimeConfig,
)
from data_analyst_agent.sub_agents.hierarchy_variance_agent.tools.level_stats.tier_filter import (
    filter_entities_for_level,
    parse_tier_filter_env,
    resolve_effective_filter_config,
)


def _minimal_contract() -> DatasetContract:
    return DatasetContract(
        name="test_ds",
        version="1",
        time=TimeConfig(column="dt", frequency="weekly", format="%Y-%m-%d"),
        grain=GrainConfig(columns=["dt", "region", "terminal"]),
        metrics=[
            MetricDefinition(name="amt", column="amt", type="additive", format="float"),
            MetricDefinition(name="vol", column="vol", type="additive", format="float"),
        ],
        dimensions=[
            DimensionDefinition(name="region", column="region", role="primary"),
            DimensionDefinition(name="terminal", column="terminal", role="primary"),
        ],
        hierarchies=[
            HierarchyNode(name="geo", levels=["region", "terminal"]),
        ],
    )


def test_top_pct_global_keeps_cumulative_share():
    contract = _minimal_contract()
    df = pd.DataFrame(
        {
            "region": ["A", "A", "B", "B", "C", "C"],
            "terminal": ["t1", "t2", "t3", "t4", "t5", "t6"],
            "amt": [50, 0, 30, 0, 20, 0],
            "vol": [1, 1, 1, 1, 1, 1],
            "dt": ["2025-01-01"] * 6,
        }
    )
    rule = TierFilterRule(level=1, mode="top_pct", value=80.0)
    out = filter_entities_for_level(df, "region", "amt", rule, contract)
    assert set(out["region"].unique()) == {"A", "B"}
    assert len(out) == 4


def test_top_pct_100_keeps_all():
    contract = _minimal_contract()
    df = pd.DataFrame(
        {
            "region": ["A", "B"],
            "terminal": ["t1", "t2"],
            "amt": [10, 90],
            "vol": [1, 1],
            "dt": ["2025-01-01"] * 2,
        }
    )
    rule = TierFilterRule(level=1, mode="top_pct", value=100.0)
    out = filter_entities_for_level(df, "region", "amt", rule, contract)
    assert len(out) == 2


def test_top_n_global():
    contract = _minimal_contract()
    df = pd.DataFrame(
        {
            "region": ["A", "B", "C", "D"],
            "terminal": ["t"] * 4,
            "amt": [100, 50, 25, 1],
            "vol": [1, 1, 1, 1],
            "dt": ["2025-01-01"] * 4,
        }
    )
    rule = TierFilterRule(level=1, mode="top_n", value=2.0)
    out = filter_entities_for_level(df, "region", "amt", rule, contract)
    assert set(out["region"].unique()) == {"A", "B"}


def test_top_n_per_partition():
    contract = _minimal_contract()
    df = pd.DataFrame(
        {
            "region": ["R1", "R1", "R1", "R2", "R2", "R2"],
            "terminal": ["a", "b", "c", "d", "e", "f"],
            "amt": [10, 5, 1, 8, 7, 1],
            "vol": [1, 1, 1, 1, 1, 1],
            "dt": ["2025-01-01"] * 6,
        }
    )
    rule = TierFilterRule(level=2, mode="top_n", value=2.0, partition_by_dimension="region")
    out = filter_entities_for_level(df, "terminal", "amt", rule, contract)
    assert set(out["terminal"]) == {"a", "b", "d", "e"}
    assert len(out) == 4


def test_empty_dataframe_unchanged():
    contract = _minimal_contract()
    df = pd.DataFrame(columns=["region", "terminal", "amt", "vol", "dt"])
    rule = TierFilterRule(level=1, mode="top_pct", value=50.0)
    out = filter_entities_for_level(df, "region", "amt", rule, contract)
    assert len(out) == 0


def test_zero_total_keeps_all_entities():
    contract = _minimal_contract()
    df = pd.DataFrame(
        {
            "region": ["A", "B"],
            "terminal": ["t1", "t2"],
            "amt": [0, 0],
            "vol": [1, 1],
            "dt": ["2025-01-01"] * 2,
        }
    )
    rule = TierFilterRule(level=1, mode="top_pct", value=50.0)
    out = filter_entities_for_level(df, "region", "amt", rule, contract)
    assert len(out) == 2


def test_parse_tier_filter_env_with_partition():
    rules = parse_tier_filter_env("1:top_pct:100,3:top_n:20@gl_div_nm")
    assert len(rules) == 2
    assert rules[0].level == 1 and rules[0].mode == "top_pct" and rules[0].value == 100
    assert rules[1].level == 3 and rules[1].partition_by_dimension == "gl_div_nm"


def test_parse_tier_filter_env_invalid_mode():
    with pytest.raises(ValueError):
        parse_tier_filter_env("1:bad:10")


def test_resolve_effective_filter_config_hierarchy_mismatch():
    contract = _minimal_contract()
    contract.hierarchy_entity_filters = HierarchyEntityFilterConfig(
        hierarchy_name="geo",
        ranking_metric="amt",
        levels=[TierFilterRule(level=1, mode="top_pct", value=100.0)],
    )
    assert resolve_effective_filter_config(contract, "other") is None
    cfg = resolve_effective_filter_config(contract, "geo")
    assert cfg is not None
    assert cfg.ranking_metric == "amt"


def test_env_overrides_levels(monkeypatch):
    contract = _minimal_contract()
    contract.hierarchy_entity_filters = HierarchyEntityFilterConfig(
        hierarchy_name="geo",
        ranking_metric="amt",
        levels=[TierFilterRule(level=1, mode="top_pct", value=100.0)],
    )
    monkeypatch.setenv("DATA_ANALYST_TIER_FILTER", "1:top_n:1")
    cfg = resolve_effective_filter_config(contract, "geo")
    assert cfg is not None
    assert len(cfg.levels) == 1
    assert cfg.levels[0].mode == "top_n"
    assert cfg.levels[0].value == 1
    monkeypatch.delenv("DATA_ANALYST_TIER_FILTER", raising=False)
