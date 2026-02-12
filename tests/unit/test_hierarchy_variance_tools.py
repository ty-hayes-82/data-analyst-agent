"""
Step 3: Unit tests for Hierarchy Variance Ranker Agent tools.

Tests:
- aggregate_by_level
- rank_level_items_by_variance
- identify_top_level_drivers
"""

import pytest
import json
import pandas as pd
from io import StringIO
from tests.utils.import_helpers import import_hierarchy_ranker_tool


# ============================================================================
# Helper: build validated CSV test data for hierarchy tools
# ============================================================================

def _make_validated_csv() -> str:
    """Build a minimal validated CSV with hierarchy levels and multiple periods."""
    rows = []
    accounts = [
        ("3100-00", "Total Operating Revenue", "Freight Revenue", "Mileage Revenue", "Mileage Revenue"),
        ("3200-00", "Total Operating Revenue", "Fuel Surcharge Revenue", "Fuel Surcharge Revenue", "Fuel Surcharge Revenue"),
        ("3115-00", "Total Operating Revenue", "Freight Revenue", "Accessorial Revenue", "Load/Unload"),
    ]
    # 15 months from 2024-07 to 2025-09
    periods = [f"2024-{m:02d}" for m in range(7, 13)] + [f"2025-{m:02d}" for m in range(1, 10)]

    for period in periods:
        for gl, l1, l2, l3, l4 in accounts:
            base = -600000 if gl == "3100-00" else -100000
            # Add a slight YoY shift: amounts are ~10% higher in 2025 vs 2024
            multiplier = 1.10 if period >= "2025-01" else 1.0
            amount = round(base * multiplier + hash((gl, period)) % 5000, 2)
            rows.append({
                "period": period,
                "gl_account": gl,
                "amount": amount,
                "cost_center": "67",
                "level_1": l1,
                "level_2": l2,
                "level_3": l3,
                "level_4": l4,
            })

    df = pd.DataFrame(rows)
    return df.to_csv(index=False)


# ============================================================================
# Tests for aggregate_by_level
# ============================================================================

@pytest.mark.unit
@pytest.mark.csv_mode
@pytest.mark.asyncio
async def test_aggregate_by_level_2():
    """Test aggregation at Level 2."""
    mod = import_hierarchy_ranker_tool("aggregate_by_level")
    csv_data = _make_validated_csv()

    result_str = await mod.aggregate_by_level(csv_data, 2)
    result = json.loads(result_str)

    assert result["analysis_type"] == "level_aggregation"
    assert result["level_number"] == 2
    assert result["level_items_count"] >= 1
    assert len(result["level_items"]) >= 1

    # Each item should have a time_series dict
    for item in result["level_items"]:
        assert "level_item" in item
        assert "time_series" in item
        assert isinstance(item["time_series"], dict)
        assert len(item["time_series"]) > 0

    print(f"[PASS] Level 2 aggregation: {result['level_items_count']} items")


@pytest.mark.unit
@pytest.mark.csv_mode
@pytest.mark.asyncio
async def test_aggregate_by_level_3():
    """Test aggregation at Level 3."""
    mod = import_hierarchy_ranker_tool("aggregate_by_level")
    csv_data = _make_validated_csv()

    result_str = await mod.aggregate_by_level(csv_data, 3)
    result = json.loads(result_str)

    assert result["level_number"] == 3
    assert result["level_items_count"] >= 1

    print(f"[PASS] Level 3 aggregation: {result['level_items_count']} items")


@pytest.mark.unit
@pytest.mark.csv_mode
@pytest.mark.asyncio
async def test_aggregate_by_level_missing_column():
    """Test error when level column is missing."""
    mod = import_hierarchy_ranker_tool("aggregate_by_level")
    df = pd.DataFrame({"period": ["2024-01"], "amount": [100], "gl_account": ["3100-00"]})
    csv_data = df.to_csv(index=False)

    result_str = await mod.aggregate_by_level(csv_data, 2)
    result = json.loads(result_str)

    assert "error" in result
    print("[PASS] Missing column handled gracefully")


# ============================================================================
# Tests for rank_level_items_by_variance
# ============================================================================

@pytest.mark.unit
@pytest.mark.csv_mode
@pytest.mark.asyncio
async def test_rank_level_items_yoy():
    """Test YoY ranking of level items."""
    mod_agg = import_hierarchy_ranker_tool("aggregate_by_level")
    mod_rank = import_hierarchy_ranker_tool("rank_level_items_by_variance")
    csv_data = _make_validated_csv()

    # Aggregate first
    agg_str = await mod_agg.aggregate_by_level(csv_data, 2)

    # Rank
    rank_str = await mod_rank.rank_level_items_by_variance(agg_str, "yoy")
    result = json.loads(rank_str)

    assert result["analysis_type"] == "level_item_variance_ranking"
    assert result["variance_type"] == "yoy"
    assert len(result["ranked_items"]) >= 1

    # Items should be sorted by absolute variance descending
    abs_vars = [item["abs_variance_dollar"] for item in result["ranked_items"]]
    assert abs_vars == sorted(abs_vars, reverse=True)

    # Cumulative percentage should reach 100%
    last_item = result["ranked_items"][-1]
    assert last_item["cumulative_pct"] == pytest.approx(100.0, abs=0.5)

    print(f"[PASS] YoY ranking: {len(result['ranked_items'])} items ranked")


@pytest.mark.unit
@pytest.mark.csv_mode
@pytest.mark.asyncio
async def test_rank_level_items_mom():
    """Test MoM ranking."""
    mod_agg = import_hierarchy_ranker_tool("aggregate_by_level")
    mod_rank = import_hierarchy_ranker_tool("rank_level_items_by_variance")
    csv_data = _make_validated_csv()

    agg_str = await mod_agg.aggregate_by_level(csv_data, 2)
    rank_str = await mod_rank.rank_level_items_by_variance(agg_str, "mom")
    result = json.loads(rank_str)

    assert result["variance_type"] == "mom"
    assert len(result["ranked_items"]) >= 1

    print(f"[PASS] MoM ranking: {len(result['ranked_items'])} items")


@pytest.mark.unit
@pytest.mark.csv_mode
@pytest.mark.asyncio
async def test_rank_insufficient_periods():
    """Test error when less than 2 periods."""
    mod_rank = import_hierarchy_ranker_tool("rank_level_items_by_variance")

    level_data = {
        "level_number": 2,
        "periods": ["2024-01"],
        "level_items": [{"level_item": "Revenue", "time_series": {"2024-01": 10000}}]
    }

    rank_str = await mod_rank.rank_level_items_by_variance(json.dumps(level_data), "yoy")
    result = json.loads(rank_str)

    assert "error" in result
    print("[PASS] Insufficient periods handled")


# ============================================================================
# Tests for identify_top_level_drivers
# ============================================================================

@pytest.mark.unit
@pytest.mark.csv_mode
@pytest.mark.asyncio
async def test_identify_top_drivers():
    """Test top driver identification."""
    mod_agg = import_hierarchy_ranker_tool("aggregate_by_level")
    mod_rank = import_hierarchy_ranker_tool("rank_level_items_by_variance")
    mod_id = import_hierarchy_ranker_tool("identify_top_level_drivers")
    csv_data = _make_validated_csv()

    agg_str = await mod_agg.aggregate_by_level(csv_data, 2)
    rank_str = await mod_rank.rank_level_items_by_variance(agg_str, "yoy")
    id_str = await mod_id.identify_top_level_drivers(rank_str, top_n=5, cumulative_threshold=80.0)
    result = json.loads(id_str)

    assert result["analysis_type"] == "top_level_driver_identification"
    assert result["items_selected_count"] >= 1
    assert result["variance_explained_pct"] > 0

    # Recommendation should be a non-empty string
    assert len(result["recommendation"]) > 0

    print(f"[PASS] Top drivers: {result['items_selected_count']} items, {result['variance_explained_pct']:.1f}% explained")


@pytest.mark.unit
@pytest.mark.csv_mode
@pytest.mark.asyncio
async def test_identify_top_drivers_missing_input():
    """Test error on missing ranked_items."""
    mod_id = import_hierarchy_ranker_tool("identify_top_level_drivers")

    result_str = await mod_id.identify_top_level_drivers(json.dumps({"no_ranked_items": True}))
    result = json.loads(result_str)

    assert "error" in result
    print("[PASS] Missing input handled")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s", "--tb=short"])
