"""
Spec 008 — Phase 4: Unit tests for refine_plan() and RuleBasedPlanner logic.

Tests the code-based rule-based planner that replaces the PlannerAgent LLM call.
"""

import importlib
import pytest


# ---------------------------------------------------------------------------
# Import helpers
# ---------------------------------------------------------------------------

def _import_refine_plan():
    mod = importlib.import_module(
        "data_analyst_agent.sub_agents.planner_agent.tools.generate_execution_plan"
    )
    return mod.refine_plan


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

def _plan(*names) -> list[dict]:
    """Build a minimal baseline plan list."""
    return [{"name": n, "justification": f"{n} baseline"} for n in names]


# ============================================================================
# T071 — Broad contract: correct default selections
# ============================================================================

@pytest.mark.unit
def test_seasonal_query_adds_seasonal_agent():
    """Query with 'seasonal' force-adds seasonal_baseline_agent."""
    refine = _import_refine_plan()
    baseline = _plan("hierarchical_analysis_agent", "statistical_insights_agent")
    result = refine(baseline, "analyze seasonal patterns")
    agent_names = [a["name"] for a in result]
    assert "seasonal_baseline_agent" in agent_names
    print(f"[PASS] 'seasonal' → seasonal_baseline_agent added: {agent_names}")


@pytest.mark.unit
def test_outlier_query_adds_statistical_agent():
    """Query with 'outliers and anomalies' force-adds statistical_insights_agent."""
    refine = _import_refine_plan()
    baseline = _plan("hierarchical_analysis_agent")
    result = refine(baseline, "show me outliers and anomalies")
    agent_names = [a["name"] for a in result]
    assert "statistical_insights_agent" in agent_names
    print(f"[PASS] 'outlier/anomalies' → statistical_insights_agent added: {agent_names}")


@pytest.mark.unit
def test_alert_query_adds_alert_scoring():
    """Query with 'alert' force-adds alert_scoring_coordinator."""
    refine = _import_refine_plan()
    baseline = _plan("hierarchical_analysis_agent", "statistical_insights_agent")
    result = refine(baseline, "show me billing alerts and recovery issues")
    agent_names = [a["name"] for a in result]
    assert "alert_scoring_coordinator" in agent_names
    print(f"[PASS] 'alert' → alert_scoring_coordinator added: {agent_names}")


@pytest.mark.unit
def test_variance_query_adds_data_analyst():
    """Query with 'variance' force-adds hierarchical_analysis_agent."""
    refine = _import_refine_plan()
    baseline = _plan("statistical_insights_agent")
    result = refine(baseline, "explain the variance drivers")
    agent_names = [a["name"] for a in result]
    assert "hierarchical_analysis_agent" in agent_names
    print(f"[PASS] 'variance' → hierarchical_analysis_agent added: {agent_names}")


# ============================================================================
# T075 — No duplicate agents
# ============================================================================

@pytest.mark.unit
def test_no_duplicate_agents():
    """refine_plan() does not add duplicate agents."""
    refine = _import_refine_plan()
    baseline = _plan("statistical_insights_agent", "hierarchical_analysis_agent",
                     "seasonal_baseline_agent")
    # Query mentions all existing categories
    result = refine(
        baseline,
        "seasonal trend analysis with outliers, variance, and hierarchy drill down"
    )
    agent_names = [a["name"] for a in result]
    # No duplicates
    assert len(agent_names) == len(set(agent_names)), f"Duplicates found: {agent_names}"
    print(f"[PASS] No duplicates: {agent_names}")


# ============================================================================
# T072 / T073 — Short contract + seasonal query
# ============================================================================

@pytest.mark.unit
def test_seasonal_keyword_adds_agent_even_if_not_in_baseline():
    """Seasonal keyword adds agent even when baseline doesn't include it (< 18 periods contract)."""
    refine = _import_refine_plan()
    # Simulate a 6-period baseline that skipped seasonal
    baseline = _plan("hierarchical_analysis_agent")
    result = refine(baseline, "analyze seasonal patterns over the past 6 months")
    agent_names = [a["name"] for a in result]
    assert "seasonal_baseline_agent" in agent_names
    print(f"[PASS] Seasonal keyword force-adds agent regardless of contract period count: {agent_names}")


@pytest.mark.unit
def test_empty_query_does_not_modify_plan():
    """Empty user query returns the baseline plan unchanged."""
    refine = _import_refine_plan()
    baseline = _plan("hierarchical_analysis_agent", "statistical_insights_agent")
    result = refine(baseline, "")
    assert [a["name"] for a in result] == ["hierarchical_analysis_agent", "statistical_insights_agent"]
    print("[PASS] Empty query leaves plan unchanged")


@pytest.mark.unit
def test_unrelated_query_does_not_modify_plan():
    """Query with no matching keywords leaves the plan unchanged."""
    refine = _import_refine_plan()
    baseline = _plan("hierarchical_analysis_agent")
    result = refine(baseline, "what is the weather today")
    assert [a["name"] for a in result] == ["hierarchical_analysis_agent"]
    print("[PASS] Unrelated query leaves plan unchanged")


# ============================================================================
# T074 — Multiple keywords in single query
# ============================================================================

@pytest.mark.unit
def test_multiple_keywords_add_all_agents():
    """Query with multiple keywords adds all corresponding agents."""
    refine = _import_refine_plan()
    baseline = _plan("hierarchical_analysis_agent")
    result = refine(
        baseline,
        "I need a seasonal and anomaly analysis with billing alerts"
    )
    agent_names = [a["name"] for a in result]
    assert "seasonal_baseline_agent" in agent_names
    assert "statistical_insights_agent" in agent_names
    assert "alert_scoring_coordinator" in agent_names
    print(f"[PASS] Multiple keywords add multiple agents: {agent_names}")


# ============================================================================
# Justification preservation
# ============================================================================

@pytest.mark.unit
def test_added_agent_has_justification():
    """Newly added agents include a justification string."""
    refine = _import_refine_plan()
    baseline = _plan("hierarchical_analysis_agent")
    result = refine(baseline, "analyze seasonal patterns")
    added = next(a for a in result if a["name"] == "seasonal_baseline_agent")
    assert "justification" in added
    assert len(added["justification"]) > 5
    print(f"[PASS] Added agent justification: '{added['justification']}'")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s", "--tb=short"])
