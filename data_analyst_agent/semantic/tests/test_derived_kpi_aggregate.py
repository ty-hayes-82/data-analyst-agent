"""Tests for aggregate-then-divide semantics for contract derived KPIs."""

from __future__ import annotations

import importlib.util
import os
import sys
from types import SimpleNamespace

import pandas as pd
import pytest

from data_analyst_agent.semantic.derived_kpi_formula import (
    column_refs_in_expr,
    kpi_to_aggregate_ratio_parts,
)
from data_analyst_agent.semantic.models import DatasetContract
from data_analyst_agent.semantic.ratio_metrics_config import (
    get_ratio_config_for_metric,
    get_ratio_config_from_contract_derived_kpis,
)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
OPS_CONTRACT = os.path.join(REPO_ROOT, "config", "datasets", "tableau", "ops_metrics_ds", "contract.yaml")

_RATIO_METRICS_PATH = os.path.join(
    REPO_ROOT,
    "data_analyst_agent",
    "sub_agents",
    "hierarchy_variance_agent",
    "tools",
    "level_stats",
    "ratio_metrics.py",
)


def _load_ratio_metrics_compute():
    spec = importlib.util.spec_from_file_location(
        "_semantic_test_level_stats_ratio_metrics",
        _RATIO_METRICS_PATH,
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod.compute_ratio_aggregations


compute_ratio_aggregations = _load_ratio_metrics_compute()


@pytest.fixture(scope="module")
def ops_contract() -> DatasetContract:
    return DatasetContract.from_yaml(OPS_CONTRACT)


def test_column_refs_in_expr():
    available = {"ttl_rev_amt", "fuel_srchrg_rev_amt", "other"}
    refs = column_refs_in_expr("(ttl_rev_amt - fuel_srchrg_rev_amt)", available)
    assert refs == {"ttl_rev_amt", "fuel_srchrg_rev_amt"}


def test_kpi_to_aggregate_ratio_parts_trpm(ops_contract: DatasetContract):
    derived = ops_contract.derived_kpis
    by_name = {k["name"]: k for k in derived if k.get("name")}
    base = {m.name for m in ops_contract.metrics if m.column}
    parts = kpi_to_aggregate_ratio_parts(by_name["trpm"], by_name, base)
    assert parts is not None
    num_expr, den_expr, mult = parts
    assert mult == 1.0
    assert "ttl_rev_amt" in num_expr and "fuel_srchrg_rev_amt" in num_expr
    assert "ld_mi_less_swift_billto" in den_expr and "dh_miles" in den_expr


def test_additive_derived_has_no_ratio_config(ops_contract: DatasetContract):
    assert get_ratio_config_from_contract_derived_kpis(ops_contract, "total_miles_rpt") is None


def test_get_ratio_config_for_metric_trpm(ops_contract: DatasetContract):
    cfg = get_ratio_config_for_metric(ops_contract, "trpm")
    assert cfg is not None
    assert "numerator_expr" in cfg and "denominator_expr" in cfg


def test_aggregate_then_divide_trpm_not_sum_of_row_ratios(ops_contract: DatasetContract):
    """Two child rows with identical per-row TRPM: network TRPM must match that ratio, not 2x."""
    m = ops_contract.get_metric("trpm")
    ctx = SimpleNamespace(contract=ops_contract, target_metric=m)

    df = pd.DataFrame(
        {
            "_total_agg": ["Total", "Total"],
            "cal_dt": ["2026-03-14", "2026-03-14"],
            "gl_rgn_nm": ["East", "East"],
            "ttl_rev_amt": [100.0, 200.0],
            "fuel_srchrg_rev_amt": [10.0, 20.0],
            "ld_mi_less_swift_billto": [50.0, 100.0],
            "dh_miles": [10.0, 20.0],
        }
    )
    ratio_cfg, cur, pri, _net, _nr = compute_ratio_aggregations(
        df,
        ctx,
        "_total_agg",
        "cal_dt",
        "gl_rgn_nm",
        "trpm",
        "2026-03-14",
        "2026-03-07",
    )
    assert ratio_cfg is not None
    assert "numerator_expr" in ratio_cfg
    assert not cur.empty
    total = float(cur.loc[cur["item"] == "Total", "current"].iloc[0])
    assert total == pytest.approx(1.5, rel=1e-9)
