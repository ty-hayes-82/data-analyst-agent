"""
Spec 008 — Phase 2: Unit tests for format_hierarchy_insight_cards() and should_continue_drilling().

Tests the code-based hierarchy formatters that replace HierarchyVarianceRankerAgent
and DrillDownDecisionAgent LLM calls.
"""

import importlib
import pytest


# ---------------------------------------------------------------------------
# Import helpers
# ---------------------------------------------------------------------------

def _import_formatter():
    mod = importlib.import_module(
        "data_analyst_agent.sub_agents.hierarchy_variance_agent"
        ".tools.format_insight_cards"
    )
    return mod.format_hierarchy_insight_cards, mod.should_continue_drilling


# ---------------------------------------------------------------------------
# Schema validation helper
# ---------------------------------------------------------------------------

def _assert_card_schema(card: dict):
    required = ["title", "what_changed", "why", "evidence", "now_what", "priority", "tags"]
    for field in required:
        assert field in card, f"Missing field '{field}' in card: {card}"
    assert card["priority"] in ("critical", "high", "medium", "low")
    ev = card["evidence"]
    assert "variance_dollar" in ev
    assert "variance_pct" in ev
    assert "is_pvm" in ev


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _level_stats(
    top_drivers=None,
    is_last_level=False,
    is_duplicate=False,
    total_variance=-187500.0,
    level=2,
    level_name="terminal",
):
    return {
        "level": level,
        "level_name": level_name,
        "metric": "amount",
        "analysis_period": "2025-08",
        "variance_type": "YOY",
        "total_variance_dollar": total_variance,
        "top_drivers": top_drivers or [],
        "items_analyzed": len(top_drivers) if top_drivers else 0,
        "variance_explained_pct": 100.0,
        "is_last_level": is_last_level,
        "is_duplicate": is_duplicate,
    }


def _material_driver(item="TERM-A", var_dollar=-110000.0, var_pct=-35.5, level=2):
    return {
        "rank": 1, "item": item,
        "current": -420000.0, "prior": -310000.0,
        "variance_dollar": var_dollar,
        "variance_pct": var_pct,
        "cumulative_pct": 58.7,
        "exceeds_threshold": True,
        "materiality": "HIGH",
    }


def _immaterial_driver(item="TERM-C"):
    """Driver truly below both materiality thresholds (|dollar| < 50K AND |pct| < 5%)."""
    return {
        "rank": 3, "item": item,
        "current": -210000.0, "prior": -208000.0,
        "variance_dollar": -2000.0,   # Below $50K
        "variance_pct": -0.96,        # Below 5%
        "cumulative_pct": 93.3,
        "exceeds_threshold": False,
        "materiality": "LOW",
    }


# ============================================================================
# T045 — Three material items produce three cards
# ============================================================================

@pytest.mark.unit
def test_three_material_items_produce_three_cards():
    """Level stats with 3 material items produces 3 insight cards with correct schema."""
    fmt, _ = _import_formatter()
    drivers = [
        _material_driver("TERM-A", -110000.0, -35.5),
        _material_driver("TERM-B", -50000.0, -34.5),
        _material_driver("TERM-C", -250000.0, -12.1),  # exceeds $200K → high
    ]
    result = fmt(_level_stats(top_drivers=drivers))

    assert "insight_cards" in result
    assert len(result["insight_cards"]) == 3
    for card in result["insight_cards"]:
        _assert_card_schema(card)

    print(f"[PASS] 3 material items → 3 insight cards")


# ============================================================================
# T046 — PVM data included in evidence
# ============================================================================

@pytest.mark.unit
def test_pvm_data_included_in_evidence():
    """Level stats with PVM data produces cards with price/volume breakdown in evidence."""
    fmt, _ = _import_formatter()
    drivers = [_material_driver("TERM-A", -110000.0, -35.5)]
    pvm = {
        "top_drivers": [{
            "item": "TERM-A",
            "total_variance": -110000.0,
            "volume_impact": -38000.0,
            "price_impact": -72000.0,
            "residual": 0.0,
        }]
    }
    result = fmt(_level_stats(top_drivers=drivers), pvm_data=pvm)

    cards = result["insight_cards"]
    assert len(cards) == 1
    ev = cards[0]["evidence"]
    assert ev["is_pvm"] is True
    assert "pvm_details" in ev
    pvm_d = ev["pvm_details"]
    assert pvm_d["volume_impact"] == pytest.approx(-38000.0)
    assert pvm_d["price_impact"] == pytest.approx(-72000.0)
    assert "pvm" in cards[0]["tags"]
    print("[PASS] PVM details correctly included in evidence")


# ============================================================================
# T047 — Small-variance drivers still become ranked cards
# ============================================================================

@pytest.mark.unit
def test_small_variance_drivers_still_emit_ranked_cards():
    """All top_drivers are card candidates; impact_score ranks and top N are kept."""
    fmt, _ = _import_formatter()
    drivers = [
        _immaterial_driver("TERM-C"),  # -$2K, -0.96%
        {
            "rank": 4, "item": "TERM-D",
            "current": -44000.0, "prior": -43000.0,
            "variance_dollar": -1000.0,
            "variance_pct": -1.5,
            "cumulative_pct": 98.9,
            "exceeds_threshold": False, "materiality": "LOW",
        },
    ]
    result = fmt(_level_stats(top_drivers=drivers, level=0, level_name="Total"))
    assert len(result["insight_cards"]) >= 1
    assert all("variance" in c.get("tags", []) for c in result["insight_cards"])
    assert result.get("top_drivers") == drivers
    print("[PASS] Small-variance drivers → ranked insight_cards, top_drivers preserved")


@pytest.mark.unit
def test_empty_drivers_returns_empty_cards():
    """Level stats with no drivers returns empty insight_cards."""
    fmt, _ = _import_formatter()
    result = fmt(_level_stats(top_drivers=[]))
    assert result["insight_cards"] == []
    assert result.get("top_drivers") == []
    print("[PASS] Empty top_drivers → empty insight_cards")


@pytest.mark.unit
def test_low_variance_level1_emits_variance_driver_cards():
    """Ratio-style small WoW still surfaces ranked variance driver cards (not filtered out)."""
    fmt, _ = _import_formatter()
    stats = {
        "level": 1,
        "level_name": "gl_rgn_nm",
        "metric": "trpm",
        "analysis_period": "2026-03-14",
        "prior_period": "2026-03-07",
        "total_variance_dollar": -0.01,
        "current_total": 2.332,
        "prior_total": 2.339,
        "items_analyzed": 2,
        "variance_explained_pct": 100.0,
        "top_drivers": [
            {
                "rank": 1,
                "item": "West",
                "current": 2.286,
                "prior": 2.29,
                "variance_dollar": -0.004,
                "variance_pct": -0.17,
                "share_current": 0.33,
                "share_prior": 0.33,
                "share_change": 0.0,
                "cumulative_pct": 40.0,
            },
            {
                "rank": 2,
                "item": "East",
                "current": 2.438,
                "prior": 2.44,
                "variance_dollar": -0.002,
                "variance_pct": -0.08,
                "share_current": 0.34,
                "share_prior": 0.34,
                "share_change": 0.0,
                "cumulative_pct": 70.0,
            },
        ],
        "is_last_level": False,
    }
    result = fmt(stats)
    assert len(result["insight_cards"]) == 2
    assert all("variance" in c.get("tags", []) for c in result["insight_cards"])
    west = next(c for c in result["insight_cards"] if "West" in c["title"])
    assert west["evidence"]["current"] == pytest.approx(2.29)
    assert west["evidence"]["variance_pct"] == pytest.approx(-0.17)
    assert len(result["top_drivers"]) == 2


# ============================================================================
# T048-T051 — should_continue_drilling()
# ============================================================================

@pytest.mark.unit
def test_should_continue_with_material_findings():
    """Material findings at level 2, max_depth 5 → CONTINUE."""
    _, scd = _import_formatter()
    level_result = {
        "insight_cards": [_card(-110000.0, -35.5)],
        "is_last_level": False,
        "is_duplicate": False,
    }
    decision = scd(level_result, current_level=2, max_depth=5)
    assert decision["action"] == "CONTINUE"
    assert decision["next_level"] == 3
    assert len(decision["material_variances"]) > 0
    print(f"[PASS] Material findings → CONTINUE (next_level=3)")


@pytest.mark.unit
def test_stop_at_last_level():
    """is_last_level=true → STOP regardless of material findings."""
    _, scd = _import_formatter()
    level_result = {
        "insight_cards": [_card(-500000.0, -45.0)],  # Very material
        "is_last_level": True,
        "is_duplicate": False,
    }
    decision = scd(level_result, current_level=4, max_depth=5)
    assert decision["action"] == "STOP"
    assert "is_last_level" in decision["reasoning"].lower() or "last" in decision["reasoning"].lower()
    print("[PASS] is_last_level=true → STOP")


@pytest.mark.unit
def test_stop_with_no_material_findings():
    """No material findings at level → STOP."""
    _, scd = _import_formatter()
    level_result = {
        "insight_cards": [],  # No material findings
        "is_last_level": False,
        "is_duplicate": False,
    }
    decision = scd(level_result, current_level=2, max_depth=5)
    assert decision["action"] == "STOP"
    assert decision["material_variances"] == []
    print("[PASS] No material findings → STOP")


@pytest.mark.unit
def test_stop_at_max_depth():
    """current_level at max_depth - 1 → STOP."""
    _, scd = _import_formatter()
    level_result = {
        "insight_cards": [_card(-200000.0, -18.0)],  # Material
        "is_last_level": False,
        "is_duplicate": False,
    }
    # current_level=4, max_depth=5 → 4 >= 5-1 → STOP
    decision = scd(level_result, current_level=4, max_depth=5)
    assert decision["action"] == "STOP"
    assert "max" in decision["reasoning"].lower() or "depth" in decision["reasoning"].lower()
    print("[PASS] At max_depth → STOP")


@pytest.mark.unit
def test_min_impact_score_override_allows_marginal_cards():
    """Default 0.15 threshold stops; contract-style override can continue to next level."""
    _, scd = _import_formatter()
    level_result = {
        "insight_cards": [
            _card(-1000.0, -1.0, impact_score=0.12, priority="medium"),
        ],
        "is_last_level": False,
        "is_duplicate": False,
    }
    assert scd(level_result, current_level=1, max_depth=5)["action"] == "STOP"
    decision = scd(
        level_result, current_level=1, max_depth=5, min_impact_score=0.10
    )
    assert decision["action"] == "CONTINUE"
    assert decision["next_level"] == 2


@pytest.mark.unit
def test_stop_on_duplicate_level():
    """is_duplicate=true → STOP."""
    _, scd = _import_formatter()
    level_result = {
        "insight_cards": [_card(-110000.0, -35.5)],
        "is_last_level": False,
        "is_duplicate": True,
    }
    decision = scd(level_result, current_level=3, max_depth=5)
    assert decision["action"] == "STOP"
    print("[PASS] Duplicate level → STOP")


# ---------------------------------------------------------------------------
# Helpers for drill-down tests
# ---------------------------------------------------------------------------

def _card(
    var_dollar: float,
    var_pct: float,
    *,
    impact_score: float | None = None,
    priority: str = "high",
) -> dict:
    """Build a minimal insight card for drill-down decision tests."""
    card = {
        "title": f"Level 2 Variance Driver: TERM-X",
        "what_changed": f"${var_dollar:+,.0f} ({var_pct:+.1f}%)",
        "why": "Material variance.",
        "evidence": {
            "variance_dollar": var_dollar,
            "variance_pct": var_pct,
            "is_pvm": False,
        },
        "now_what": "Drill down.",
        "priority": priority,
        "tags": ["hierarchy", "variance"],
    }
    if impact_score is not None:
        card["impact_score"] = impact_score
    return card


# ============================================================================
# Priority classification
# ============================================================================

@pytest.mark.unit
@pytest.mark.parametrize("var_dollar,var_pct,expected_priority", [
    (-600000.0, -22.0, "critical"),
    (-250000.0, -12.0, "high"),
    (-60000.0, -6.0, "medium"),
    (-110000.0, -35.0, "critical"),   # >20% → critical
])
def test_priority_classification(var_dollar, var_pct, expected_priority):
    """Priority is correctly classified from variance_dollar and variance_pct."""
    fmt, _ = _import_formatter()
    result = fmt(_level_stats(top_drivers=[_material_driver("X", var_dollar, var_pct)]))
    cards = result["insight_cards"]
    if expected_priority != "low":
        assert len(cards) == 1
        assert cards[0]["priority"] == expected_priority, \
            f"var_dollar={var_dollar}, var_pct={var_pct}: got '{cards[0]['priority']}'"
    print(f"[PASS] var_dollar={var_dollar}, var_pct={var_pct} → {expected_priority}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s", "--tb=short"])
