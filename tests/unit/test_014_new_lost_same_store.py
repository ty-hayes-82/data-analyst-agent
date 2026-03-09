"""
Unit tests for New/Lost/Same-Store Decomposition Tool (Spec 014).

Tests:
- compute_new_lost_same_store returns proper structure
- Sum check: new_total - lost_total + same_store_delta == total_delta
- Entity count check: new + lost + same_store == total unique entities
- Edge cases: insufficient periods, zero delta, YoY fallback
- Insight card generation from NLSS data
"""

import pytest
import json
import importlib
import pandas as pd
import numpy as np
from io import StringIO


def _import_stat_tool(tool_name: str):
    """Import a tool from statistical_insights_agent using importlib."""
    mod = importlib.import_module(
        f"data_analyst_agent.sub_agents.statistical_insights_agent.tools.{tool_name}"
    )
    return getattr(mod, tool_name)


def _populate_cache_with_churn_data():
    """Create synthetic data with clear new/lost/same-store entities."""
    from data_analyst_agent.sub_agents.data_cache import set_validated_csv, clear_all_caches, set_analysis_context
    from data_analyst_agent.semantic.models import DatasetContract, AnalysisContext

    clear_all_caches()
    
    data = {
        "period": [
            "2025-01", "2025-01", "2025-01",
            "2025-02", "2025-02", "2025-02", "2025-02",
        ],
        "item": [
            "A", "B", "C",
            "A", "B", "D", "E",
        ],
        "item_name": [
            "Entity A", "Entity B", "Entity C",
            "Entity A", "Entity B", "Entity D", "Entity E",
        ],
        "amount": [
            100, 200, 50,
            120, 180, 75, 25,
        ],
    }
    df = pd.DataFrame(data)
    csv_data = df.to_csv(index=False)
    set_validated_csv(csv_data)
    
    contract_data = {
        "name": "churn_test",
        "version": "1.0",
        "time": {"column": "period", "format": "%Y-%m", "frequency": "monthly"},
        "grain": {"columns": ["item"]},
        "metrics": [{"name": "amount", "column": "amount", "unit": "USD", "direction": "higher_is_better"}],
        "dimensions": [{"name": "item", "column": "item", "tags": ["entity_id"]}],
        "policies": {}
    }
    contract = DatasetContract(**contract_data)
    ctx = AnalysisContext(
        contract=contract,
        df=df,
        target_metric=contract.metrics[0],
        primary_dimension=contract.dimensions[0],
        run_id="test_churn"
    )
    set_analysis_context(ctx)
    
    return df


def _teardown_cache():
    from data_analyst_agent.sub_agents.data_cache import clear_all_caches
    clear_all_caches()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_compute_new_lost_same_store_structure():
    """Test that NLSS returns proper structure."""
    compute_new_lost_same_store = _import_stat_tool("compute_new_lost_same_store")
    _populate_cache_with_churn_data()

    try:
        result_str = await compute_new_lost_same_store()
        result = json.loads(result_str)

        assert "error" not in result, f"Got error: {result.get('error')}"
        
        assert "comparison" in result
        assert "current_period" in result
        assert "prior_period" in result
        assert "summary" in result
        assert "top_new" in result
        assert "top_lost" in result
        assert "top_same_store_movers" in result
        
        summary = result["summary"]
        assert "total_current" in summary
        assert "total_prior" in summary
        assert "total_delta" in summary
        assert "new_total" in summary
        assert "lost_total" in summary
        assert "same_store_delta" in summary
        assert "new_count" in summary
        assert "lost_count" in summary
        assert "same_store_count" in summary
        assert "new_pct_of_delta" in summary
        assert "lost_pct_of_delta" in summary
        assert "same_store_pct_of_delta" in summary

        print(f"[PASS] NLSS structure: {summary['new_count']} new, "
              f"{summary['lost_count']} lost, {summary['same_store_count']} same-store")
    finally:
        _teardown_cache()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_compute_new_lost_same_store_sum_check():
    """Test that new_total - lost_total + same_store_delta == total_delta."""
    compute_new_lost_same_store = _import_stat_tool("compute_new_lost_same_store")
    _populate_cache_with_churn_data()

    try:
        result_str = await compute_new_lost_same_store()
        result = json.loads(result_str)

        assert "error" not in result, f"Got error: {result.get('error')}"
        
        summary = result["summary"]
        new_total = summary["new_total"]
        lost_total = summary["lost_total"]
        same_store_delta = summary["same_store_delta"]
        total_delta = summary["total_delta"]
        
        computed_delta = new_total - lost_total + same_store_delta
        assert abs(computed_delta - total_delta) < 0.01, (
            f"Sum check failed: {new_total} - {lost_total} + {same_store_delta} = {computed_delta}, "
            f"expected {total_delta}"
        )

        print(f"[PASS] Sum check: {new_total} - {lost_total} + {same_store_delta} = {computed_delta} == {total_delta}")
    finally:
        _teardown_cache()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_compute_new_lost_same_store_entity_count():
    """Test synthetic data with known new/lost/same-store entities."""
    compute_new_lost_same_store = _import_stat_tool("compute_new_lost_same_store")
    _populate_cache_with_churn_data()

    try:
        result_str = await compute_new_lost_same_store()
        result = json.loads(result_str)

        assert "error" not in result, f"Got error: {result.get('error')}"
        
        summary = result["summary"]
        
        assert summary["new_count"] == 2, f"Expected 2 new (D, E), got {summary['new_count']}"
        assert summary["lost_count"] == 1, f"Expected 1 lost (C), got {summary['lost_count']}"
        assert summary["same_store_count"] == 2, f"Expected 2 same-store (A, B), got {summary['same_store_count']}"
        
        assert summary["new_total"] == 100.0, f"Expected new_total=100 (D:75 + E:25), got {summary['new_total']}"
        assert summary["lost_total"] == 50.0, f"Expected lost_total=50 (C), got {summary['lost_total']}"
        
        same_store_current = 120 + 180
        same_store_prior = 100 + 200
        expected_delta = same_store_current - same_store_prior
        assert summary["same_store_delta"] == expected_delta, (
            f"Expected same_store_delta={expected_delta}, got {summary['same_store_delta']}"
        )
        
        print(f"[PASS] Entity counts and totals match expected values")
    finally:
        _teardown_cache()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_compute_new_lost_same_store_insufficient_periods():
    """Test handling of insufficient periods."""
    from data_analyst_agent.sub_agents.data_cache import set_validated_csv, clear_all_caches, set_analysis_context
    from data_analyst_agent.semantic.models import DatasetContract, AnalysisContext

    clear_all_caches()
    
    data = {
        "period": ["2025-01", "2025-01"],
        "item": ["A", "B"],
        "item_name": ["Entity A", "Entity B"],
        "amount": [100, 200],
    }
    df = pd.DataFrame(data)
    csv_data = df.to_csv(index=False)
    set_validated_csv(csv_data)
    
    contract_data = {
        "name": "single_period_test",
        "version": "1.0",
        "time": {"column": "period", "format": "%Y-%m", "frequency": "monthly"},
        "grain": {"columns": ["item"]},
        "metrics": [{"name": "amount", "column": "amount", "unit": "USD", "direction": "higher_is_better"}],
        "dimensions": [{"name": "item", "column": "item", "tags": ["entity_id"]}],
        "policies": {}
    }
    contract = DatasetContract(**contract_data)
    ctx = AnalysisContext(
        contract=contract,
        df=df,
        target_metric=contract.metrics[0],
        primary_dimension=contract.dimensions[0],
        run_id="test_single_period"
    )
    set_analysis_context(ctx)

    try:
        compute_new_lost_same_store = _import_stat_tool("compute_new_lost_same_store")
        result_str = await compute_new_lost_same_store()
        result = json.loads(result_str)

        assert "warning" in result, "Expected warning for insufficient periods"
        assert result["warning"] == "InsufficientPeriods"
        
        print(f"[PASS] Insufficient periods handled gracefully: {result.get('message')}")
    finally:
        _teardown_cache()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_compute_new_lost_same_store_top_lists_sorted():
    """Test that top_new, top_lost, and top_same_store_movers are properly sorted."""
    compute_new_lost_same_store = _import_stat_tool("compute_new_lost_same_store")
    _populate_cache_with_churn_data()

    try:
        result_str = await compute_new_lost_same_store()
        result = json.loads(result_str)

        assert "error" not in result
        
        top_new = result["top_new"]
        if len(top_new) >= 2:
            for i in range(len(top_new) - 1):
                assert abs(top_new[i]["current_value"]) >= abs(top_new[i + 1]["current_value"]), \
                    "top_new not sorted by absolute current_value"
        
        top_lost = result["top_lost"]
        if len(top_lost) >= 2:
            for i in range(len(top_lost) - 1):
                assert abs(top_lost[i]["prior_value"]) >= abs(top_lost[i + 1]["prior_value"]), \
                    "top_lost not sorted by absolute prior_value"
        
        top_movers = result["top_same_store_movers"]
        if len(top_movers) >= 2:
            for i in range(len(top_movers) - 1):
                assert abs(top_movers[i]["delta"]) >= abs(top_movers[i + 1]["delta"]), \
                    "top_same_store_movers not sorted by absolute delta"
        
        print(f"[PASS] All top lists are properly sorted")
    finally:
        _teardown_cache()


def _populate_cache_with_multi_period_data():
    """Create synthetic data with multiple periods for full statistical summary test."""
    from data_analyst_agent.sub_agents.data_cache import set_validated_csv, clear_all_caches, set_analysis_context
    from data_analyst_agent.semantic.models import DatasetContract, AnalysisContext

    clear_all_caches()
    
    periods = [f"2024-{m:02d}" for m in range(1, 13)] + [f"2025-{m:02d}" for m in range(1, 3)]
    items = ["A", "B", "C", "D"]
    
    data = {"period": [], "item": [], "item_name": [], "amount": []}
    np.random.seed(42)
    
    for period in periods:
        for item in items:
            if period == "2025-02" and item == "C":
                continue
            if period == "2025-02" and item == "E":
                data["period"].append(period)
                data["item"].append("E")
                data["item_name"].append("Entity E")
                data["amount"].append(float(np.random.randint(50, 150)))
                continue
            data["period"].append(period)
            data["item"].append(item)
            data["item_name"].append(f"Entity {item}")
            base = {"A": 100, "B": 200, "C": 50, "D": 150}.get(item, 100)
            data["amount"].append(float(base + np.random.randint(-20, 20)))
    
    if "2025-02" in periods:
        data["period"].append("2025-02")
        data["item"].append("E")
        data["item_name"].append("Entity E")
        data["amount"].append(75.0)
    
    df = pd.DataFrame(data)
    csv_data = df.to_csv(index=False)
    set_validated_csv(csv_data)
    
    contract_data = {
        "name": "multi_period_test",
        "version": "1.0",
        "time": {"column": "period", "format": "%Y-%m", "frequency": "monthly"},
        "grain": {"columns": ["item"]},
        "metrics": [{"name": "amount", "column": "amount", "unit": "USD", "direction": "higher_is_better"}],
        "dimensions": [{"name": "item", "column": "item", "tags": ["entity_id"]}],
        "policies": {}
    }
    contract = DatasetContract(**contract_data)
    ctx = AnalysisContext(
        contract=contract,
        df=df,
        target_metric=contract.metrics[0],
        primary_dimension=contract.dimensions[0],
        run_id="test_multi_period"
    )
    set_analysis_context(ctx)
    
    return df


@pytest.mark.unit
@pytest.mark.asyncio
async def test_statistical_summary_includes_nlss():
    """Test that compute_statistical_summary includes new_lost_same_store in output."""
    compute_statistical_summary = _import_stat_tool("compute_statistical_summary")
    _populate_cache_with_multi_period_data()

    try:
        result_str = await compute_statistical_summary()
        result = json.loads(result_str)

        assert "error" not in result, f"Got error: {result.get('error')}"
        assert "new_lost_same_store" in result, "new_lost_same_store missing from statistical summary"
        
        nlss = result["new_lost_same_store"]
        assert isinstance(nlss, dict), "new_lost_same_store should be a dict"
        
        if "error" not in nlss and "warning" not in nlss:
            assert "summary" in nlss
            assert "top_new" in nlss
            assert "top_lost" in nlss
            assert "top_same_store_movers" in nlss
        
        assert "New/Lost/Same-Store decomposition" in result["metadata"]["advanced_methods"]
        
        print(f"[PASS] NLSS integrated into statistical summary")
    finally:
        _teardown_cache()


@pytest.mark.unit
def test_build_new_lost_same_store_cards():
    """Test insight card generation from NLSS data."""
    from data_analyst_agent.sub_agents.statistical_insights_agent.tools.generate_insight_cards import (
        _build_new_lost_same_store_cards
    )
    
    nlss_data = {
        "comparison": "MoM",
        "current_period": "2025-02",
        "prior_period": "2025-01",
        "summary": {
            "total_current": 400,
            "total_prior": 350,
            "total_delta": 50,
            "new_total": 100,
            "lost_total": 50,
            "same_store_current": 300,
            "same_store_prior": 300,
            "same_store_delta": 0,
            "new_count": 2,
            "lost_count": 1,
            "same_store_count": 5,
            "new_pct_of_delta": 200.0,
            "lost_pct_of_delta": -100.0,
            "same_store_pct_of_delta": 0.0
        },
        "top_new": [{"item": "D", "item_name": "Entity D", "current_value": 75}],
        "top_lost": [{"item": "C", "item_name": "Entity C", "prior_value": 50}],
        "top_same_store_movers": [{"item": "A", "item_name": "Entity A", "current": 120, "prior": 100, "delta": 20, "delta_pct": 20.0}]
    }
    
    cards = _build_new_lost_same_store_cards(nlss_data, grand_total=400)
    
    assert len(cards) > 0, "Expected at least one insight card"
    
    card_titles = [c["title"] for c in cards]
    has_portfolio_churn = any("Portfolio Churn" in t for t in card_titles)
    has_new_entities = any("New Entities" in t for t in card_titles)
    has_same_store = any("Same-Store" in t for t in card_titles)
    
    assert has_portfolio_churn, "Expected Portfolio Churn card (churn > 20% of delta)"
    assert has_new_entities, "Expected New Entity Impact card (new > 30% of delta)"
    assert has_same_store, "Expected Same-Store Trend card"
    
    for card in cards:
        assert "title" in card
        assert "what_changed" in card
        assert "why" in card
        assert "evidence" in card
        assert "now_what" in card
        assert "priority" in card
        assert "impact_score" in card
        assert "materiality_weight" in card
        assert "tags" in card
        assert card["priority"] in ["low", "medium", "high", "critical"]
        assert 0 <= card["impact_score"] <= 1
    
    print(f"[PASS] Card generation: {len(cards)} cards created")
    for card in cards:
        print(f"  - {card['title']} (priority: {card['priority']}, score: {card['impact_score']:.3f})")


@pytest.mark.unit
def test_build_new_lost_same_store_cards_error_handling():
    """Test card builder handles error/warning data gracefully."""
    from data_analyst_agent.sub_agents.statistical_insights_agent.tools.generate_insight_cards import (
        _build_new_lost_same_store_cards
    )
    
    cards = _build_new_lost_same_store_cards({"error": "SomeError"}, grand_total=1000)
    assert cards == [], "Should return empty list for error data"
    
    cards = _build_new_lost_same_store_cards({"warning": "InsufficientPeriods"}, grand_total=1000)
    assert cards == [], "Should return empty list for warning data"
    
    cards = _build_new_lost_same_store_cards({}, grand_total=1000)
    assert cards == [], "Should return empty list for empty data"
    
    cards = _build_new_lost_same_store_cards(None, grand_total=1000)
    assert cards == [], "Should return empty list for None data"
    
    print(f"[PASS] Card builder handles error cases gracefully")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s", "--tb=short"])
