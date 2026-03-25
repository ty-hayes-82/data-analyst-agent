"""Tests for contract-driven ranked_subset_fetch resolution."""

from pathlib import Path

import pytest

from data_analyst_agent.sub_agents.tableau_hyper_fetcher.ranked_subset import (
    resolve_ranked_subset_spec,
)
from data_analyst_agent.utils.contract_cache import load_contract_cached

ROOT = Path(__file__).resolve().parent.parent.parent
TOLLS_WL_CONTRACT = (
    ROOT / "config" / "datasets" / "tableau" / "tolls_expense_weekly_lane_ds" / "contract.yaml"
)


def _clear_ranked_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "DATA_ANALYST_RANKED_TOP_PARENTS",
        "DATA_ANALYST_RANKED_TOP_CHILDREN",
        "DATA_ANALYST_RANKED_TOP_LEVEL_0",
        "DATA_ANALYST_RANKED_TOP_LEVEL_1_PER_LEVEL_0",
        "DATA_ANALYST_RANKED_TOP_LEVEL_2_PER_LEVEL_1",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.skipif(not TOLLS_WL_CONTRACT.is_file(), reason="tolls weekly lane contract not present")
def test_resolve_tolls_weekly_lane_contract_maps_columns(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_ranked_env(monkeypatch)
    contract = load_contract_cached(str(TOLLS_WL_CONTRACT))
    spec = resolve_ranked_subset_spec(contract)
    assert spec is not None
    assert spec.is_three_level
    assert spec.column_level_0 == "shpr_prnt_nm"
    assert spec.column_level_1 == "shpr_nm"
    assert spec.column_level_2 == "stop_location_w_cust"
    assert spec.rank_col == "toll_expense"
    assert spec.top_level_0 == 20
    assert spec.top_level_1_per_level_0 == 20
    assert spec.top_level_2_per_level_1 == 30


@pytest.mark.skipif(not TOLLS_WL_CONTRACT.is_file(), reason="tolls weekly lane contract not present")
def test_resolve_env_overrides_top_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_ranked_env(monkeypatch)
    monkeypatch.setenv("DATA_ANALYST_RANKED_TOP_LEVEL_0", "10")
    monkeypatch.setenv("DATA_ANALYST_RANKED_TOP_LEVEL_1_PER_LEVEL_0", "15")
    monkeypatch.setenv("DATA_ANALYST_RANKED_TOP_LEVEL_2_PER_LEVEL_1", "25")
    contract = load_contract_cached(str(TOLLS_WL_CONTRACT))
    spec = resolve_ranked_subset_spec(contract)
    assert spec is not None
    assert spec.top_level_0 == 10
    assert spec.top_level_1_per_level_0 == 15
    assert spec.top_level_2_per_level_1 == 25


@pytest.mark.skipif(not TOLLS_WL_CONTRACT.is_file(), reason="tolls weekly lane contract not present")
def test_resolve_legacy_env_aliases(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_ranked_env(monkeypatch)
    monkeypatch.setenv("DATA_ANALYST_RANKED_TOP_PARENTS", "11")
    monkeypatch.setenv("DATA_ANALYST_RANKED_TOP_CHILDREN", "12")
    contract = load_contract_cached(str(TOLLS_WL_CONTRACT))
    spec = resolve_ranked_subset_spec(contract)
    assert spec is not None
    assert spec.top_level_0 == 11
    assert spec.top_level_1_per_level_0 == 12


@pytest.mark.skipif(not TOLLS_WL_CONTRACT.is_file(), reason="tolls weekly lane contract not present")
def test_resolve_disabled_returns_none() -> None:
    contract = load_contract_cached(str(TOLLS_WL_CONTRACT))
    assert contract.ranked_subset_fetch is not None
    disabled = contract.ranked_subset_fetch.model_copy(update={"enabled": False})
    c2 = contract.model_copy(update={"ranked_subset_fetch": disabled})
    assert resolve_ranked_subset_spec(c2) is None
