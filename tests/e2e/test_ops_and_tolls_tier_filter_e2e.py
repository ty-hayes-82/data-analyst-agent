"""
End-to-end integration: real Hyper fetch + compute_level_statistics with hierarchy_entity_filters.

Skips automatically if TDSX / extract is missing or Hyper API unavailable.
Compares items_analyzed with contract tier filters vs without (fewer entities when filters apply).
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import pandas as pd
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

OPS_CONTRACT = REPO_ROOT / "config" / "datasets" / "tableau" / "ops_metrics_ds" / "contract.yaml"
OPS_TDSX = REPO_ROOT / "data" / "tableau" / "Ops Metrics DS.tdsx"
OPS_LOADER = REPO_ROOT / "config" / "datasets" / "tableau" / "ops_metrics_ds" / "loader.yaml"

TOLLS_CONTRACT = REPO_ROOT / "config" / "datasets" / "tableau" / "tolls_expense_weekly_lane_ds" / "contract.yaml"
TOLLS_TDSX = REPO_ROOT / "data" / "tableau" / "Tolls Expense.tdsx"
TOLLS_LOADER = REPO_ROOT / "config" / "datasets" / "tableau" / "tolls_expense_weekly_lane_ds" / "loader.yaml"


def _load_hyper_df(
    dataset_folder: str,
    loader_path: Path,
    project_root: Path,
    date_start: str,
    date_end: str,
    physical_filters: Dict[str, list],
) -> pd.DataFrame:
    from data_analyst_agent.sub_agents.tableau_hyper_fetcher.loader_config import HyperLoaderConfig
    from data_analyst_agent.sub_agents.tableau_hyper_fetcher.hyper_connection import get_or_create_manager
    from data_analyst_agent.sub_agents.tableau_hyper_fetcher.query_builder import HyperQueryBuilder
    from data_analyst_agent.sub_agents.tableau_hyper_fetcher.ranked_subset import resolve_ranked_subset_spec

    with open(loader_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    cfg = HyperLoaderConfig(**raw)
    mgr = get_or_create_manager(dataset_folder, cfg)
    mgr.ensure_extracted(project_root)
    from data_analyst_agent.semantic.models import DatasetContract

    contract_path = loader_path.parent / "contract.yaml"
    contract = DatasetContract.from_yaml(str(contract_path))
    ranked = resolve_ranked_subset_spec(contract)
    builder = HyperQueryBuilder(cfg)
    sql = builder.build_query(
        date_start=date_start,
        date_end=date_end,
        filters=physical_filters,
        ranked_spec=ranked,
    )
    return mgr.execute_query(sql)


def _primary_dimension(contract):
    prim = next((d for d in contract.dimensions if getattr(d, "role", None) == "primary"), None)
    return prim or contract.dimensions[0]


async def _level_stats_items(
    contract,
    df: pd.DataFrame,
    target_metric_name: str,
    level: int,
    hierarchy_name: str,
    session_suffix: str,
) -> Tuple[int, Dict[str, Any]]:
    from data_analyst_agent.semantic.models import AnalysisContext
    from data_analyst_agent.sub_agents.data_cache import current_session_id, set_analysis_context
    from data_analyst_agent.sub_agents.hierarchy_variance_agent.tools.level_stats.core import (
        compute_level_statistics_impl,
    )

    target = contract.get_metric(target_metric_name)
    primary = _primary_dimension(contract)
    ctx = AnalysisContext(
        contract=contract,
        df=df,
        target_metric=target,
        primary_dimension=primary,
        run_id=f"e2e_{session_suffix}",
        max_drill_depth=getattr(contract.reporting, "max_drill_depth", 4),
        temporal_grain="weekly",
        temporal_grain_confidence=1.0,
        period_end_column=contract.time.column,
        time_frequency="weekly",
    )
    sid = f"e2e_tier_{session_suffix}"
    token = current_session_id.set(sid)
    try:
        set_analysis_context(ctx, session_id=sid)
        raw = await compute_level_statistics_impl(
            level=level,
            analysis_period="latest",
            variance_type="wow",
            top_n=500,
            hierarchy_name=hierarchy_name,
        )
    finally:
        current_session_id.reset(token)

    payload = json.loads(raw)
    if "error" in payload:
        pytest.fail(f"level_stats error: {payload}")
    return int(payload.get("items_analyzed", 0)), payload


@pytest.fixture
def hyper_available_ops():
    if not OPS_TDSX.exists():
        pytest.skip(f"Missing TDSX: {OPS_TDSX}")
    if not OPS_LOADER.exists():
        pytest.skip(f"Missing loader: {OPS_LOADER}")


@pytest.fixture
def hyper_available_tolls():
    if not TOLLS_TDSX.exists():
        pytest.skip(f"Missing TDSX: {TOLLS_TDSX}")
    if not TOLLS_LOADER.exists():
        pytest.skip(f"Missing loader: {TOLLS_LOADER}")


def test_ops_metrics_ds_line_haul_tier_filter_reduces_entities(hyper_available_ops, monkeypatch):
    """Line Haul + date window: tier filters should reduce terminal/DM counts vs no filters."""
    monkeypatch.delenv("DATA_ANALYST_TIER_FILTER", raising=False)

    from data_analyst_agent.semantic.models import DatasetContract

    contract = DatasetContract.from_yaml(str(OPS_CONTRACT))
    setattr(contract, "_source_path", str(OPS_CONTRACT))

    df = _load_hyper_df(
        "ops_metrics_ds",
        OPS_LOADER,
        REPO_ROOT,
        "2025-12-14",
        "2026-03-14",
        {"ops_ln_of_bus_ref_nm": ["Line Haul"]},
    )
    assert not df.empty, "Expected non-empty Hyper result for Line Haul"
    assert "truck_count" in df.columns, df.columns.tolist()

    async def _run():
        # Without tier filters
        c_plain = contract.model_copy(update={"hierarchy_entity_filters": None})
        n2_plain, _ = await _level_stats_items(
            c_plain, df, "ttl_rev_amt", 2, "geographic", "ops_l2_plain"
        )
        n3_plain, _ = await _level_stats_items(
            c_plain, df, "ttl_rev_amt", 3, "geographic", "ops_l3_plain"
        )
        # With contract tier filters (95% terminals, top 20 DM per terminal)
        n2_filt, p2 = await _level_stats_items(
            contract, df, "ttl_rev_amt", 2, "geographic", "ops_l2_filt"
        )
        n3_filt, p3 = await _level_stats_items(
            contract, df, "ttl_rev_amt", 3, "geographic", "ops_l3_filt"
        )
        return (n2_plain, n3_plain, n2_filt, n3_filt, p2, p3)

    n2p, n3p, n2f, n3f, p2, p3 = asyncio.run(_run())

    print(
        f"\n[ops_metrics_ds Line Haul] items_analyzed level2 plain={n2p} filtered={n2f} | "
        f"level3 plain={n3p} filtered={n3f}"
    )
    assert n2f <= n2p, "Tier filter should not increase terminal count"
    assert n3f <= n3p, "Tier filter should not increase driver-manager count"
    assert n2f >= 1 and n3f >= 1
    assert "top_drivers" in p2 and "top_drivers" in p3


def test_tolls_weekly_lane_dedicated_tier_filter_reduces_entities(hyper_available_tolls, monkeypatch):
    """Dedicated LOB: tier filters reduce shipper/lane counts vs no filters."""
    monkeypatch.delenv("DATA_ANALYST_TIER_FILTER", raising=False)

    from data_analyst_agent.semantic.models import DatasetContract

    contract = DatasetContract.from_yaml(str(TOLLS_CONTRACT))
    setattr(contract, "_source_path", str(TOLLS_CONTRACT))

    df = _load_hyper_df(
        "tolls_expense_weekly_lane_ds",
        TOLLS_LOADER,
        REPO_ROOT,
        "2025-12-28",
        "2026-03-21",
        {"ops_ln_of_bus_ref_nm": ["Dedicated"]},
    )
    assert not df.empty, "Expected non-empty Hyper result for Dedicated"
    assert "toll_expense" in df.columns, df.columns.tolist()

    async def _run():
        c_plain = contract.model_copy(update={"hierarchy_entity_filters": None})
        n1p, _ = await _level_stats_items(
            c_plain, df, "toll_expense", 1, "shipper_parent_shipper_stop_lane", "tolls_l1_plain"
        )
        n2p, _ = await _level_stats_items(
            c_plain, df, "toll_expense", 2, "shipper_parent_shipper_stop_lane", "tolls_l2_plain"
        )
        n3p, _ = await _level_stats_items(
            c_plain, df, "toll_expense", 3, "shipper_parent_shipper_stop_lane", "tolls_l3_plain"
        )
        n1f, p1 = await _level_stats_items(
            contract, df, "toll_expense", 1, "shipper_parent_shipper_stop_lane", "tolls_l1_filt"
        )
        n2f, p2 = await _level_stats_items(
            contract, df, "toll_expense", 2, "shipper_parent_shipper_stop_lane", "tolls_l2_filt"
        )
        n3f, p3 = await _level_stats_items(
            contract, df, "toll_expense", 3, "shipper_parent_shipper_stop_lane", "tolls_l3_filt"
        )
        return (n1p, n2p, n3p, n1f, n2f, n3f, p1, p2, p3)

    n1p, n2p, n3p, n1f, n2f, n3f, p1, p2, p3 = asyncio.run(_run())

    print(
        f"\n[tolls_expense_weekly_lane_ds Dedicated] L1 {n1p}->{n1f} | L2 {n2p}->{n2f} | L3 {n3p}->{n3f}"
    )
    assert n1f <= n1p
    assert n2f <= n2p
    assert n3f <= n3p
    assert n1f >= 1
    assert "top_drivers" in p1
