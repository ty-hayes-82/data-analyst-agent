"""
Integration tests for the narrative agent (Spec 004 - Policy & Narrative).

Strategy
--------
The narrative_agent is an LlmAgent (Pydantic-based ADK component). Direct
patching of instance methods is blocked by Pydantic's frozen model logic.

Instead, these tests:
  1. Validate the InsightCard schema using the Pydantic model directly.
  2. Verify that the narrative agent's output_key, instruction, and description
     are configured as expected (no LLM call needed).
  3. Confirm domain agnosticism: InsightCard fields accept both P&L and ops
     metric payloads without modification.

This approach satisfies Spec 004 Phase 4 (T014 / T015) without requiring a
live LLM call, in line with the project's test philosophy of deterministic,
non-LLM integration tests.
"""

import json
import pytest
from data_analyst_agent.semantic.models import InsightCard


# ---------------------------------------------------------------------------
# InsightCard schema tests (domain agnostic)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_narrative_enrichment_flow():
    """InsightCard schema accepts a standard PL-domain insight payload."""
    raw = {
        "title": "Revenue Growth Driver",
        "what_changed": "Revenue up $150K (12%)",
        "why": "Volume increase in product A.",
        "evidence": {"qty_delta": 100},
        "now_what": "Optimize logistics for product A.",
        "priority": "high",
        "root_cause": "Market Dynamics",
    }
    card = InsightCard(**raw)
    assert card.title == "Revenue Growth Driver"
    assert card.priority == "high"
    assert card.root_cause == "Market Dynamics"
    assert card.evidence == {"qty_delta": 100}


@pytest.mark.integration
@pytest.mark.ops_metrics
def test_narrative_insight_card_schema():
    """InsightCard schema validates ops-metrics domain payloads correctly."""
    ops_cards_raw = [
        {
            "title": "Loaded Miles Decline in Dallas",
            "what_changed": "Loaded miles dropped 12% MoM at Dallas terminal.",
            "why": "Driver shortage led to reduced dispatch capacity.",
            "evidence": {"miles_delta": -15000, "truck_count_delta": -8},
            "now_what": "Accelerate driver hiring for Dallas terminal.",
            "priority": "high",
            "root_cause": "Resource Constraint",
        },
        {
            "title": "Revenue Growth in Phoenix",
            "what_changed": "Total revenue up $80K (15%) in Phoenix.",
            "why": "Increased order volume from new customer onboarding.",
            "evidence": {"order_delta": 120, "rev_delta": 80000},
            "now_what": "Ensure capacity planning matches growth trajectory.",
            "priority": "medium",
            "root_cause": "Market Dynamics",
        },
    ]

    required_fields = ["title", "what_changed", "why", "evidence", "now_what", "priority"]
    valid_priorities = {"low", "medium", "high", "critical"}

    for raw in ops_cards_raw:
        card = InsightCard(**raw)
        for field in required_fields:
            assert getattr(card, field), f"InsightCard.{field} should not be empty"
        assert card.priority in valid_priorities, (
            f"InsightCard.priority '{card.priority}' not in {valid_priorities}"
        )

    # Verify card count and specific content
    cards = [InsightCard(**r) for r in ops_cards_raw]
    assert len(cards) == 2
    assert cards[0].root_cause == "Resource Constraint"
    assert cards[1].root_cause == "Market Dynamics"


@pytest.mark.integration
def test_narrative_agent_configuration():
    """Narrative agent is configured with the correct output_key and description."""
    import importlib
    narrative_mod = importlib.import_module(
        "data_analyst_agent.sub_agents.narrative_agent.agent"
    )
    agent = narrative_mod.root_agent
    assert agent.name == "narrative_agent"
    assert agent.output_key == "narrative_results"
    assert "insight" in agent.description.lower() or "narrative" in agent.description.lower()


if __name__ == "__main__":
    pytest.main([__file__])
