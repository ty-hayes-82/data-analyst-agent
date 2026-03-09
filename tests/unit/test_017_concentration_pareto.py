"""
Unit tests for Concentration / Pareto Analysis Tool (Spec 017).

Tests:
- HHI calculation correctness (known distributions)
- Gini coefficient correctness (perfect equality vs monopoly)
- Pareto ratio calculation
- Concentration trend analysis
- Variance concentration and persistent movers
- Insight card generation
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


def _teardown_cache():
    from data_analyst_agent.sub_agents.data_cache import clear_all_caches
    clear_all_caches()


def _populate_cache_with_known_distribution():
    """Create data with known concentration characteristics for validation."""
    from data_analyst_agent.sub_agents.data_cache import set_validated_csv, clear_all_caches, set_analysis_context
    from data_analyst_agent.semantic.models import DatasetContract, AnalysisContext

    clear_all_caches()
    
    data = {
        "period": ["2025-01"] * 10 + ["2025-02"] * 10,
        "item": ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"] * 2,
        "item_name": ["Entity A", "Entity B", "Entity C", "Entity D", "Entity E",
                      "Entity F", "Entity G", "Entity H", "Entity I", "Entity J"] * 2,
        "amount": [
            500, 250, 100, 50, 30, 25, 20, 15, 5, 5,
            510, 240, 110, 45, 35, 20, 25, 10, 3, 2,
        ],
    }
    df = pd.DataFrame(data)
    csv_data = df.to_csv(index=False)
    set_validated_csv(csv_data)
    
    contract_data = {
        "name": "concentration_test",
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
        run_id="test_concentration"
    )
    set_analysis_context(ctx)
    
    return df


def _populate_cache_with_equal_distribution():
    """Create data where all entities have equal values (Gini ~ 0)."""
    from data_analyst_agent.sub_agents.data_cache import set_validated_csv, clear_all_caches, set_analysis_context
    from data_analyst_agent.semantic.models import DatasetContract, AnalysisContext

    clear_all_caches()
    
    data = {
        "period": ["2025-01"] * 5 + ["2025-02"] * 5,
        "item": ["A", "B", "C", "D", "E"] * 2,
        "item_name": ["Entity A", "Entity B", "Entity C", "Entity D", "Entity E"] * 2,
        "amount": [100, 100, 100, 100, 100, 100, 100, 100, 100, 100],
    }
    df = pd.DataFrame(data)
    csv_data = df.to_csv(index=False)
    set_validated_csv(csv_data)
    
    contract_data = {
        "name": "equal_test",
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
        run_id="test_equal"
    )
    set_analysis_context(ctx)
    
    return df


def _populate_cache_with_duopoly():
    """Create data where 2 entities each have 50% (HHI = 5000)."""
    from data_analyst_agent.sub_agents.data_cache import set_validated_csv, clear_all_caches, set_analysis_context
    from data_analyst_agent.semantic.models import DatasetContract, AnalysisContext

    clear_all_caches()
    
    data = {
        "period": ["2025-01", "2025-01", "2025-02", "2025-02"],
        "item": ["A", "B", "A", "B"],
        "item_name": ["Entity A", "Entity B", "Entity A", "Entity B"],
        "amount": [500, 500, 500, 500],
    }
    df = pd.DataFrame(data)
    csv_data = df.to_csv(index=False)
    set_validated_csv(csv_data)
    
    contract_data = {
        "name": "duopoly_test",
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
        run_id="test_duopoly"
    )
    set_analysis_context(ctx)
    
    return df


def _populate_cache_with_multi_period():
    """Create data with multiple periods for trend analysis."""
    from data_analyst_agent.sub_agents.data_cache import set_validated_csv, clear_all_caches, set_analysis_context
    from data_analyst_agent.semantic.models import DatasetContract, AnalysisContext

    clear_all_caches()
    
    periods = [f"2024-{m:02d}" for m in range(1, 13)]
    items = ["A", "B", "C", "D", "E"]
    
    data = {"period": [], "item": [], "item_name": [], "amount": []}
    np.random.seed(42)
    
    for period in periods:
        for item in items:
            data["period"].append(period)
            data["item"].append(item)
            data["item_name"].append(f"Entity {item}")
            base = {"A": 100, "B": 80, "C": 60, "D": 40, "E": 20}.get(item, 50)
            data["amount"].append(float(base + np.random.randint(-10, 10)))
    
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
async def test_compute_concentration_analysis_structure():
    """Test that concentration analysis returns proper structure."""
    compute_concentration_analysis = _import_stat_tool("compute_concentration_analysis")
    _populate_cache_with_known_distribution()

    try:
        result_str = await compute_concentration_analysis()
        result = json.loads(result_str)

        assert "error" not in result, f"Got error: {result.get('error')}"
        
        assert "latest_period" in result
        assert "concentration_trend" in result
        assert "variance_concentration" in result
        assert "summary" in result
        
        lp = result["latest_period"]
        assert "period" in lp
        assert "total_entities" in lp
        assert "pareto_count" in lp
        assert "pareto_ratio" in lp
        assert "hhi" in lp
        assert "hhi_label" in lp
        assert "gini" in lp
        assert "top_5_share" in lp
        assert "top_10_share" in lp
        assert "top_entities" in lp
        
        print(f"[PASS] Structure: HHI={lp['hhi']:.0f}, Gini={lp['gini']:.3f}, "
              f"Pareto={lp['pareto_count']}/{lp['total_entities']}")
    finally:
        _teardown_cache()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_hhi_duopoly():
    """Test HHI for a duopoly (2 entities with 50% each = HHI 5000)."""
    compute_concentration_analysis = _import_stat_tool("compute_concentration_analysis")
    _populate_cache_with_duopoly()

    try:
        result_str = await compute_concentration_analysis()
        result = json.loads(result_str)

        assert "error" not in result
        
        hhi = result["latest_period"]["hhi"]
        assert 4900 <= hhi <= 5100, f"Expected HHI ~5000 for duopoly, got {hhi}"
        
        print(f"[PASS] Duopoly HHI = {hhi:.0f} (expected ~5000)")
    finally:
        _teardown_cache()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_gini_equal_distribution():
    """Test Gini coefficient for equal distribution (should be ~0)."""
    compute_concentration_analysis = _import_stat_tool("compute_concentration_analysis")
    _populate_cache_with_equal_distribution()

    try:
        result_str = await compute_concentration_analysis()
        result = json.loads(result_str)

        assert "error" not in result
        
        gini = result["latest_period"]["gini"]
        assert gini < 0.1, f"Expected Gini ~0 for equal distribution, got {gini}"
        
        print(f"[PASS] Equal distribution Gini = {gini:.3f} (expected ~0)")
    finally:
        _teardown_cache()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pareto_ratio():
    """Test Pareto ratio calculation."""
    compute_concentration_analysis = _import_stat_tool("compute_concentration_analysis")
    _populate_cache_with_known_distribution()

    try:
        result_str = await compute_concentration_analysis()
        result = json.loads(result_str)

        assert "error" not in result
        
        lp = result["latest_period"]
        pareto_count = lp["pareto_count"]
        pareto_ratio = lp["pareto_ratio"]
        total = lp["total_entities"]
        
        assert pareto_count <= total, "Pareto count should not exceed total entities"
        assert pareto_ratio == pareto_count / total, "Pareto ratio should equal count / total"
        
        top_entities = lp["top_entities"]
        if pareto_count <= len(top_entities):
            cumsum_at_pareto = top_entities[pareto_count - 1]["cumulative_share"]
            assert cumsum_at_pareto >= 0.8 or pareto_count == total, (
                f"Cumulative share at pareto_count should be >= 0.8, got {cumsum_at_pareto}"
            )
        
        print(f"[PASS] Pareto: {pareto_count} of {total} entities ({pareto_ratio*100:.0f}%) reach 80%")
    finally:
        _teardown_cache()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_concentration_trend():
    """Test concentration trend analysis with multi-period data."""
    compute_concentration_analysis = _import_stat_tool("compute_concentration_analysis")
    _populate_cache_with_multi_period()

    try:
        result_str = await compute_concentration_analysis()
        result = json.loads(result_str)

        assert "error" not in result
        
        trend = result["concentration_trend"]
        assert "hhi_values" in trend
        assert "gini_values" in trend
        assert len(trend["hhi_values"]) == 12, f"Expected 12 periods, got {len(trend['hhi_values'])}"
        
        assert "hhi_slope" in trend
        assert "hhi_slope_p_value" in trend
        assert "hhi_direction" in trend
        assert trend["hhi_direction"] in ["increasing", "decreasing", "stable"]
        
        print(f"[PASS] Trend: HHI slope={trend['hhi_slope']:.2f}, "
              f"p={trend['hhi_slope_p_value']:.4f}, direction={trend['hhi_direction']}")
    finally:
        _teardown_cache()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_variance_concentration():
    """Test variance concentration analysis."""
    compute_concentration_analysis = _import_stat_tool("compute_concentration_analysis")
    _populate_cache_with_multi_period()

    try:
        result_str = await compute_concentration_analysis()
        result = json.loads(result_str)

        assert "error" not in result
        
        variance = result["variance_concentration"]
        assert "pareto_count" in variance
        assert "pareto_ratio" in variance
        assert "top_5_variance_share" in variance
        assert "persistent_top_movers" in variance
        
        print(f"[PASS] Variance: Pareto={variance['pareto_count']}, "
              f"Top-5 share={variance['top_5_variance_share']:.1%}, "
              f"Persistent movers={len(variance['persistent_top_movers'])}")
    finally:
        _teardown_cache()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_insufficient_entities():
    """Test handling of insufficient entities."""
    from data_analyst_agent.sub_agents.data_cache import set_validated_csv, clear_all_caches, set_analysis_context
    from data_analyst_agent.semantic.models import DatasetContract, AnalysisContext

    clear_all_caches()
    
    data = {
        "period": ["2025-01", "2025-02"],
        "item": ["A", "A"],
        "item_name": ["Entity A", "Entity A"],
        "amount": [100, 100],
    }
    df = pd.DataFrame(data)
    csv_data = df.to_csv(index=False)
    set_validated_csv(csv_data)
    
    contract_data = {
        "name": "single_entity_test",
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
        run_id="test_single_entity"
    )
    set_analysis_context(ctx)

    try:
        compute_concentration_analysis = _import_stat_tool("compute_concentration_analysis")
        result_str = await compute_concentration_analysis()
        result = json.loads(result_str)

        assert "warning" in result, "Expected warning for insufficient entities"
        assert result["warning"] == "TooFewEntities"
        
        print(f"[PASS] Insufficient entities handled: {result.get('message')}")
    finally:
        _teardown_cache()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_statistical_summary_includes_concentration():
    """Test that compute_statistical_summary includes concentration_analysis."""
    compute_statistical_summary = _import_stat_tool("compute_statistical_summary")
    _populate_cache_with_multi_period()

    try:
        result_str = await compute_statistical_summary()
        result = json.loads(result_str)

        assert "error" not in result, f"Got error: {result.get('error')}"
        assert "concentration_analysis" in result, "concentration_analysis missing from statistical summary"
        
        ca = result["concentration_analysis"]
        assert isinstance(ca, dict), "concentration_analysis should be a dict"
        
        if "error" not in ca and "warning" not in ca:
            assert "latest_period" in ca
            assert "concentration_trend" in ca
            assert "variance_concentration" in ca
        
        assert "Concentration / Pareto analysis (HHI, Gini)" in result["metadata"]["advanced_methods"]
        
        print(f"[PASS] Concentration analysis integrated into statistical summary")
    finally:
        _teardown_cache()


@pytest.mark.unit
def test_build_concentration_cards():
    """Test insight card generation from concentration data."""
    from data_analyst_agent.sub_agents.statistical_insights_agent.tools.generate_insight_cards import (
        _build_concentration_cards
    )
    
    concentration_data = {
        "latest_period": {
            "period": "2025-02",
            "total_entities": 10,
            "pareto_count": 3,
            "pareto_ratio": 0.3,
            "pareto_label": "3 of 10 entities (30%) account for 80% of total",
            "top_5_share": 0.85,
            "top_10_share": 1.0,
            "hhi": 2100,
            "hhi_label": "Moderately concentrated (1500-2500)",
            "gini": 0.65,
            "top_entities": []
        },
        "concentration_trend": {
            "hhi_values": [{"period": f"2024-{m:02d}", "hhi": 2000 + m * 10} for m in range(1, 13)],
            "gini_values": [{"period": f"2024-{m:02d}", "gini": 0.60 + m * 0.005} for m in range(1, 13)],
            "hhi_slope": 10.0,
            "hhi_slope_p_value": 0.05,
            "hhi_direction": "increasing",
            "gini_slope": 0.005,
            "gini_direction": "increasing"
        },
        "variance_concentration": {
            "pareto_count": 2,
            "pareto_ratio": 0.2,
            "pareto_label": "2 of 10 entities (20%) drive 80% of variance",
            "top_5_variance_share": 0.90,
            "persistent_top_movers": [
                {"item": "A", "item_name": "Entity A", "times_in_top_5": 10, "out_of_periods": 11},
                {"item": "B", "item_name": "Entity B", "times_in_top_5": 8, "out_of_periods": 11}
            ]
        },
        "summary": {
            "entities_analyzed": 10,
            "periods_analyzed": 12,
            "concentration_level": "moderate",
            "concentration_trending": "increasing"
        }
    }
    
    cards = _build_concentration_cards(concentration_data)
    
    assert len(cards) >= 1, "Expected at least one insight card"
    
    card_titles = [c["title"] for c in cards]
    has_portfolio = any("Portfolio Concentration" in t for t in card_titles)
    has_trending = any("Concentration" in t and "trending" in t.lower() for t in card_titles)
    has_variance = any("Variance" in t for t in card_titles)
    
    assert has_portfolio, "Expected Portfolio Concentration card"
    assert has_trending, "Expected Concentration Trending card (p < 0.10)"
    assert has_variance, "Expected Variance Concentration card (persistent movers exist)"
    
    for card in cards:
        assert "title" in card
        assert "what_changed" in card
        assert "evidence" in card
        assert "priority" in card
        assert "impact_score" in card
        assert card["priority"] in ["low", "medium", "high", "critical"]
        assert 0 <= card["impact_score"] <= 1
    
    print(f"[PASS] Card generation: {len(cards)} cards created")
    for card in cards:
        print(f"  - {card['title']} (priority: {card['priority']}, score: {card['impact_score']:.3f})")


@pytest.mark.unit
def test_build_concentration_cards_error_handling():
    """Test card builder handles error/warning data gracefully."""
    from data_analyst_agent.sub_agents.statistical_insights_agent.tools.generate_insight_cards import (
        _build_concentration_cards
    )
    
    cards = _build_concentration_cards({"error": "SomeError"})
    assert cards == [], "Should return empty list for error data"
    
    cards = _build_concentration_cards({"warning": "TooFewEntities"})
    assert cards == [], "Should return empty list for warning data"
    
    cards = _build_concentration_cards({})
    assert cards == [], "Should return empty list for empty data"
    
    cards = _build_concentration_cards(None)
    assert cards == [], "Should return empty list for None data"
    
    print(f"[PASS] Card builder handles error cases gracefully")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s", "--tb=short"])
