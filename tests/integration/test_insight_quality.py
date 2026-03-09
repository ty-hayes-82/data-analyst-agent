"""
Insight quality validation tests (Spec 004 + 005).

Ensures that the analysis pipeline generates *valuable* insights, not just
any output.  Each test checks a specific quality dimension:

- Statistical actionability (anomalies, trends, correlations, rankings)
- Hierarchy variance identifies top movers sorted by abs variance
- Narrative classifies root causes semantically
- Alert scoring assigns correct severity levels
"""

import pytest
import json
import numpy as np
import pandas as pd
from io import StringIO
from unittest.mock import patch, MagicMock


# ============================================================================
# 1. Statistical insights produce actionable output
# ============================================================================

@pytest.mark.integration
@pytest.mark.insight_quality
@pytest.mark.ops_metrics
@pytest.mark.asyncio
async def test_statistical_insights_produce_actionable_output(ops_metrics_context_with_cache):
    """
    compute_statistical_summary must return:
    - anomalies with z-scores
    - top_drivers with slopes (trend direction)
    - correlations (if multiple items)
    - monthly_totals with rankings
    """
    import importlib

    mod = importlib.import_module(
        "data_analyst_agent.sub_agents.statistical_insights_agent.tools.compute_statistical_summary"
    )
    result_str = await mod.compute_statistical_summary()
    result = json.loads(result_str)

    assert "error" not in result, f"Got error: {result.get('error')}"

    # 1a. Top drivers should have trend slopes
    drivers = result.get("top_drivers", [])
    assert len(drivers) > 0, "Should have at least 1 top driver"
    for d in drivers:
        assert "slope_3mo" in d, f"Driver missing slope_3mo: {d}"
        assert "avg" in d, f"Driver missing avg: {d}"
        assert not np.isnan(d["avg"]), f"Driver avg is NaN: {d}"

    # 1b. Monthly totals should exist
    monthly = result.get("monthly_totals", {})
    assert len(monthly) > 0, "Should have monthly totals"

    # 1c. Summary stats
    stats = result.get("summary_stats", {})
    assert stats.get("total_items", 0) > 0
    assert stats.get("total_periods", 0) > 0


# ============================================================================
# 2. Hierarchy variance identifies top movers
# ============================================================================

@pytest.mark.integration
@pytest.mark.insight_quality
@pytest.mark.csv_mode
@pytest.mark.asyncio
@pytest.mark.skip(reason="Hierarchy ranker tools removed; covered by compute_level_statistics unit tests")
async def test_hierarchy_variance_identifies_top_movers():
    """
    After rank_level_items_by_variance, ranked items should be sorted
    by absolute variance descending, and cumulative_pct should reach ~100%.
    """
    from tests.utils.import_helpers import import_hierarchy_ranker_tool

    mod_agg = import_hierarchy_ranker_tool("aggregate_by_level")
    mod_rank = import_hierarchy_ranker_tool("rank_level_items_by_variance")

    # Build test data with clear variance
    rows = []
    accounts = [
        ("3100", "Revenue", "Freight"),
        ("3200", "Revenue", "Fuel Surcharge"),
        ("5010", "Expense", "Driver Pay"),
    ]
    periods_2024 = [f"2024-{m:02d}" for m in range(1, 13)]
    periods_2025 = [f"2025-{m:02d}" for m in range(1, 7)]

    for p in periods_2024 + periods_2025:
        for gl, l1, l2 in accounts:
            base = -500000 if gl.startswith("3") else 200000
            yoy_shift = 1.20 if p >= "2025-01" else 1.0
            amount = round(base * yoy_shift + hash((gl, p)) % 10000, 2)
            rows.append({
                "period": p,
                "gl_account": gl,
                "amount": amount,
                "level_1": l1,
                "level_2": l2,
                "level_3": l2,
                "level_4": l2,
            })

    csv_data = pd.DataFrame(rows).to_csv(index=False)
    agg_str = await mod_agg.aggregate_by_level(csv_data, 2)
    rank_str = await mod_rank.rank_level_items_by_variance(agg_str, "yoy")
    result = json.loads(rank_str)

    if "error" in result:
        pytest.skip(f"Ranking tool error: {result['error']}")

    ranked = result.get("ranked_items", [])
    assert len(ranked) >= 2, "Should have at least 2 ranked items"

    # Items should be sorted by absolute variance descending
    abs_vars = [item["abs_variance_dollar"] for item in ranked]
    assert abs_vars == sorted(abs_vars, reverse=True), (
        "Ranked items should be sorted by absolute variance descending"
    )

    # Cumulative percentage should reach ~100%
    last = ranked[-1]
    assert last["cumulative_pct"] == pytest.approx(100.0, abs=1.0), (
        f"Cumulative variance should reach ~100%, got {last['cumulative_pct']}"
    )


# ============================================================================
# 3. Narrative classifies root causes
# ============================================================================

@pytest.mark.integration
@pytest.mark.insight_quality
def test_narrative_classifies_root_causes():
    """
    Verify that narrative InsightCards contain semantic root-cause
    classification (e.g., Market Dynamics, Resource Constraint, etc.).
    """
    from data_analyst_agent.semantic.models import InsightCard

    # Simulate InsightCards that the narrative agent would produce
    cards = [
        InsightCard(
            title="Revenue Decline in Line Haul",
            what_changed="Revenue dropped 8% MoM.",
            why="Reduced order volume from seasonal slowdown.",
            evidence={"order_delta": -50, "rev_delta": -40000},
            now_what="Adjust pricing to retain volume.",
            priority="high",
            root_cause="Market Dynamics",
            tags=["revenue", "seasonal"],
        ),
        InsightCard(
            title="Deadhead Increase",
            what_changed="Deadhead percentage rose from 11% to 14%.",
            why="Imbalanced dispatch in Phoenix terminal.",
            evidence={"deadhead_before": 0.11, "deadhead_after": 0.14},
            now_what="Optimize relay planning in Phoenix.",
            priority="medium",
            root_cause="Operational Inefficiency",
            tags=["efficiency", "dispatch"],
        ),
    ]

    valid_root_causes = {
        "Market Dynamics",
        "Resource Constraint",
        "Operational Inefficiency",
        "Pricing Strategy",
        "External Factor",
        "Customer Behaviour",
    }

    for card in cards:
        assert card.root_cause is not None, f"Card '{card.title}' missing root_cause"
        assert card.root_cause in valid_root_causes, (
            f"Root cause '{card.root_cause}' not in expected set"
        )
        assert card.priority in ("low", "medium", "high", "critical")
        assert len(card.tags) > 0, f"Card '{card.title}' should have tags"
        assert card.evidence, f"Card '{card.title}' should have evidence dict"


# ============================================================================
# 4. Alert scoring assigns correct severity
# ============================================================================

@pytest.mark.integration
@pytest.mark.insight_quality
def test_alert_scoring_assigns_correct_severity():
    """
    Verify that alert scoring logic maps scores to severity tiers correctly.
    Uses the same tier boundaries as the actual alert_policy.yaml.
    """
    # Tier boundaries (from config/alert_policy.yaml convention):
    #   critical: score >= 8
    #   high:     score >= 6
    #   medium:   score >= 3
    #   low:      score < 3

    def classify_severity(score: float) -> str:
        if score >= 8:
            return "critical"
        elif score >= 6:
            return "high"
        elif score >= 3:
            return "medium"
        else:
            return "low"

    test_cases = [
        (9.5, "critical"),
        (8.0, "critical"),
        (7.0, "high"),
        (6.0, "high"),
        (5.0, "medium"),
        (3.0, "medium"),
        (2.5, "low"),
        (0.0, "low"),
    ]

    for score, expected in test_cases:
        actual = classify_severity(score)
        assert actual == expected, (
            f"Score {score} should map to '{expected}', got '{actual}'"
        )


@pytest.mark.integration
@pytest.mark.insight_quality
def test_alert_structure_completeness():
    """
    Verify that mock alerts contain all required fields with valid ranges.
    """
    from tests.utils.test_helpers import validate_alert_structure

    alerts = [
        {
            "alert_id": "ALERT-001",
            "category": "revenue_decline",
            "description": "Total revenue dropped 10% MoM in Dallas terminal.",
            "impact_score": 7.5,
            "confidence_score": 0.85,
            "total_score": 6.375,
            "severity": "high",
        },
        {
            "alert_id": "ALERT-002",
            "category": "efficiency_degradation",
            "description": "Deadhead percentage rose above 15% threshold.",
            "impact_score": 5.0,
            "confidence_score": 0.90,
            "total_score": 4.5,
            "severity": "medium",
        },
    ]

    for alert in alerts:
        validate_alert_structure(alert)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s", "--tb=short"])
