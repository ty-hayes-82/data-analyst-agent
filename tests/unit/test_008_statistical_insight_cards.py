"""
Spec 008 — Phase 1: Unit tests for generate_statistical_insight_cards().

Tests the code-based insight card generator that replaces StatisticalInsightsAgent LLM.
All tests use purely synthetic data — no live pipeline or data cache required.
"""

import json
import importlib
import pytest
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "008"


# ---------------------------------------------------------------------------
# Import helper
# ---------------------------------------------------------------------------

def _import_generator():
    mod = importlib.import_module(
        "data_analyst_agent.sub_agents.statistical_insights_agent"
        ".tools.generate_insight_cards"
    )
    return mod.generate_statistical_insight_cards


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _load_fixture(filename: str) -> dict:
    path = FIXTURES_DIR / filename
    assert path.exists(), f"Fixture not found: {path}"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _minimal_summary(anomalies=None, correlations=None, top_drivers=None,
                      most_volatile=None, change_points=None,
                      forecasts=None, seasonal_analysis=None) -> dict:
    return {
        "anomalies": anomalies or [],
        "correlations": correlations or {},
        "top_drivers": top_drivers or [],
        "enhanced_top_drivers": top_drivers or [],
        "most_volatile": most_volatile or [],
        "change_points": change_points or [],
        "forecasts": forecasts or {},
        "seasonal_analysis": seasonal_analysis or {},
        "summary_stats": {
            "total_items": 5,
            "total_periods": 12,
            "period_range": "2024-09 to 2025-08",
        },
    }


# ---------------------------------------------------------------------------
# Schema validation helper
# ---------------------------------------------------------------------------

def _assert_card_schema(card: dict):
    required = ["title", "what_changed", "why", "evidence", "now_what", "priority", "tags"]
    for field in required:
        assert field in card, f"Missing field '{field}' in card: {card}"
    assert card["priority"] in ("critical", "high", "medium", "low"), \
        f"Invalid priority: {card['priority']}"
    assert isinstance(card["tags"], list), "tags must be a list"


# ============================================================================
# T028 — Fixture-based structural test
# ============================================================================

@pytest.mark.unit
def test_generate_cards_from_fixture():
    """generate_statistical_insight_cards() returns valid cards from the sample fixture."""
    gen = _import_generator()
    summary = _load_fixture("statistical_summary_sample.json")
    result = gen(summary)

    assert "insight_cards" in result
    assert "summary_stats" in result
    assert isinstance(result["insight_cards"], list)
    assert len(result["insight_cards"]) > 0

    for card in result["insight_cards"]:
        _assert_card_schema(card)

    print(f"[PASS] {len(result['insight_cards'])} insight cards generated from fixture")


# ============================================================================
# T029 — Anomaly card: priority classification + p_value
# ============================================================================

@pytest.mark.unit
@pytest.mark.parametrize("z_score,expected_priority", [
    (2.1, "medium"),
    (3.0, "high"),
    (3.5, "high"),
    (4.0, "critical"),
    (4.5, "critical"),
    (-2.5, "medium"),
    (-3.1, "high"),
])
def test_anomaly_card_priority(z_score, expected_priority):
    """Anomaly cards have correct priority classification based on |z_score|."""
    gen = _import_generator()
    summary = _minimal_summary(anomalies=[{
        "period": "2025-07",
        "item": "3100-00",
        "item_name": "Mileage Revenue",
        "value": -750000.0,
        "z_score": z_score,
        "p_value": 0.001,
        "avg": -645000.0,
        "std": 37500.0,
    }])
    result = gen(summary)
    cards = result["insight_cards"]
    anomaly_cards = [c for c in cards if "z-score" in c.get("tags", [])]
    assert len(anomaly_cards) == 1
    assert anomaly_cards[0]["priority"] == expected_priority, \
        f"z={z_score}: expected '{expected_priority}', got '{anomaly_cards[0]['priority']}'"
    print(f"[PASS] z={z_score} → priority={anomaly_cards[0]['priority']}")


@pytest.mark.unit
def test_anomaly_card_includes_p_value():
    """Anomaly card evidence includes p_value when present in input."""
    gen = _import_generator()
    summary = _minimal_summary(anomalies=[{
        "period": "2025-07",
        "item": "3100-00",
        "item_name": "Mileage Revenue",
        "value": -750000.0,
        "z_score": 3.5,
        "p_value": 0.0046,
        "avg": -645000.0,
        "std": 37500.0,
    }])
    result = gen(summary)
    cards = [c for c in result["insight_cards"] if "z-score" in c.get("tags", [])]
    assert len(cards) == 1
    assert "p_value" in cards[0]["evidence"]
    assert cards[0]["evidence"]["p_value"] == pytest.approx(0.0046, rel=1e-3)
    print(f"[PASS] p_value={cards[0]['evidence']['p_value']} correctly included")


@pytest.mark.unit
def test_anomaly_below_threshold_excluded():
    """Anomaly with |z_score| < 2.0 is not included in insight cards."""
    gen = _import_generator()
    summary = _minimal_summary(anomalies=[{
        "period": "2025-07",
        "item": "3100-00",
        "item_name": "Mileage Revenue",
        "value": -680000.0,
        "z_score": 1.5,  # Below threshold
        "p_value": 0.13,
        "avg": -645000.0,
        "std": 37500.0,
    }])
    result = gen(summary)
    anomaly_cards = [c for c in result["insight_cards"] if "z-score" in c.get("tags", [])]
    assert len(anomaly_cards) == 0
    print("[PASS] z=1.5 anomaly correctly excluded (below threshold)")


# ============================================================================
# T030 — Correlation cards: r threshold and p-value filter
# ============================================================================

@pytest.mark.unit
def test_strong_significant_correlation_included():
    """Correlation with |r| > 0.7 and p < 0.05 produces a card."""
    gen = _import_generator()
    summary = _minimal_summary(
        correlations={"3100-00_vs_5010-00": {"r": 0.85, "p_value": 0.002}}
    )
    result = gen(summary)
    corr_cards = [c for c in result["insight_cards"] if "correlation" in c.get("tags", [])]
    assert len(corr_cards) == 1
    assert corr_cards[0]["evidence"]["correlation"] == pytest.approx(0.85, rel=1e-3)
    print(f"[PASS] Correlation r=0.85 card generated")


@pytest.mark.unit
def test_weak_correlation_excluded():
    """Correlation with |r| <= 0.7 does not produce a card."""
    gen = _import_generator()
    summary = _minimal_summary(
        correlations={"A_vs_B": {"r": 0.45, "p_value": 0.03}}
    )
    result = gen(summary)
    corr_cards = [c for c in result["insight_cards"] if "correlation" in c.get("tags", [])]
    assert len(corr_cards) == 0
    print("[PASS] Weak correlation (r=0.45) correctly excluded")


@pytest.mark.unit
def test_insignificant_correlation_excluded():
    """Strong correlation with p >= 0.05 is excluded."""
    gen = _import_generator()
    summary = _minimal_summary(
        correlations={"A_vs_B": {"r": 0.82, "p_value": 0.12}}
    )
    result = gen(summary)
    corr_cards = [c for c in result["insight_cards"] if "correlation" in c.get("tags", [])]
    assert len(corr_cards) == 0
    print("[PASS] Insignificant correlation (p=0.12) correctly excluded")


# ============================================================================
# T031 — Trend cards: linregress p-value filter
# ============================================================================

@pytest.mark.unit
def test_significant_slope_included():
    """Item with significant slope (p < 0.05) produces a trend card."""
    gen = _import_generator()
    summary = _minimal_summary(top_drivers=[{
        "item": "5020-00",
        "item_name": "Fuel Expense",
        "avg": 185000.0, "std": 42000.0, "cv": 0.22,
        "slope_3mo": 3500.0,
        "slope_3mo_p_value": 0.018,
        "slope_3mo_r_value": 0.92,
        "acceleration_3mo": 900.0,
        "min": 110000.0, "max": 260000.0,
    }])
    result = gen(summary)
    trend_cards = [c for c in result["insight_cards"] if "trend" in c.get("tags", [])]
    assert len(trend_cards) == 1
    assert trend_cards[0]["evidence"]["slope_p_value"] == pytest.approx(0.018, rel=1e-3)
    print(f"[PASS] Significant slope (p=0.018) produces trend card")


@pytest.mark.unit
def test_insignificant_slope_excluded():
    """Item with insignificant slope (p >= 0.05) does not produce a trend card."""
    gen = _import_generator()
    summary = _minimal_summary(top_drivers=[{
        "item": "5010-00",
        "item_name": "Driver Pay",
        "avg": 320000.0, "std": 14000.0, "cv": 0.044,
        "slope_3mo": 800.0,
        "slope_3mo_p_value": 0.210,  # Not significant
        "slope_3mo_r_value": 0.61,
        "acceleration_3mo": 50.0,
        "min": 290000.0, "max": 355000.0,
    }])
    result = gen(summary)
    trend_cards = [c for c in result["insight_cards"] if "trend" in c.get("tags", [])]
    assert len(trend_cards) == 0
    print("[PASS] Insignificant slope (p=0.21) correctly excluded")


# ============================================================================
# T032 — Empty input returns empty cards
# ============================================================================

@pytest.mark.unit
def test_empty_summary_returns_empty_cards():
    """Empty statistical_summary dict returns empty insight_cards list."""
    gen = _import_generator()
    result = gen({})
    assert result["insight_cards"] == []
    assert result["summary_stats"] == {}
    print("[PASS] Empty input returns empty insight_cards")


@pytest.mark.unit
def test_none_input_returns_empty_cards():
    """None input returns empty insight_cards list."""
    gen = _import_generator()
    result = gen(None)
    assert result["insight_cards"] == []
    print("[PASS] None input returns empty insight_cards")


@pytest.mark.unit
def test_all_empty_sections_returns_empty_cards():
    """Summary with no anomalies/correlations/etc returns empty cards."""
    gen = _import_generator()
    result = gen(_minimal_summary())
    assert result["insight_cards"] == []
    print("[PASS] Summary with no signals returns empty insight_cards")


# ============================================================================
# T033 — Error propagation
# ============================================================================

@pytest.mark.unit
def test_error_summary_propagates_error():
    """Statistical summary with error key propagates error, no insight cards."""
    gen = _import_generator()
    error_summary = {"error": "DataUnavailable: no cache found"}
    result = gen(error_summary)
    assert "error" in result
    assert result["insight_cards"] == []
    print(f"[PASS] Error propagated: {result['error']}")


# ============================================================================
# Additional: cards sorted by priority
# ============================================================================

@pytest.mark.unit
def test_cards_sorted_by_priority():
    """Insight cards are sorted: critical > high > medium > low."""
    gen = _import_generator()
    summary = _minimal_summary(anomalies=[
        {"period": "2025-05", "item": "A", "item_name": "Alpha", "value": 100.0, "z_score": 2.2, "p_value": 0.028, "avg": 50.0, "std": 22.7},
        {"period": "2025-06", "item": "B", "item_name": "Beta",  "value": 200.0, "z_score": 4.5, "p_value": 0.000007, "avg": 50.0, "std": 33.0},
        {"period": "2025-07", "item": "C", "item_name": "Gamma", "value": 150.0, "z_score": 3.2, "p_value": 0.0013, "avg": 50.0, "std": 31.3},
    ])
    result = gen(summary)
    priorities = [c["priority"] for c in result["insight_cards"]]
    order_map = {"critical": 4, "high": 3, "medium": 2, "low": 1}
    ordered = sorted(priorities, key=lambda p: -order_map.get(p, 0))
    assert priorities == ordered, f"Cards not sorted: {priorities}"
    print(f"[PASS] Cards sorted correctly: {priorities}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s", "--tb=short"])
