"""
Test data structure validation in format_hierarchy_insight_cards().

Ensures that the function correctly detects and reports when statistical
summary data (with slopes) is incorrectly passed instead of hierarchy
level statistics (with variance_dollar/variance_pct).
"""

import pytest

from data_analyst_agent.sub_agents.hierarchy_variance_agent.tools.format_insight_cards import (
    format_hierarchy_insight_cards,
)


def test_detects_statistical_summary_mismatch():
    """
    When statistical summary data (slope_3mo, avg, cv) is passed instead of
    hierarchy level stats (variance_dollar, variance_pct), the function should
    return a clear error rather than silently producing 0 cards.
    """
    # Simulate statistical summary data (WRONG structure)
    statistical_summary_data = {
        "level": 0,
        "level_name": "Region",
        "top_drivers": [
            {
                "item": "East",
                "avg": 8000000.0,
                "slope_3mo": -1300000.0,  # This is a SLOPE not variance_dollar
                "cv": 0.15,
            },
            {
                "item": "West",
                "avg": 7500000.0,
                "slope_3mo": -1000000.0,
                "cv": 0.12,
            },
        ],
    }

    result = format_hierarchy_insight_cards(statistical_summary_data)

    # Should return error, not empty cards
    assert "error" in result, "Expected error field in result"
    assert result["error"] == "DataStructureMismatch"
    assert "variance_dollar" in result["message"]
    assert "slope_3mo" in str(result.get("received_fields", []))
    assert result["insight_cards"] == []


def test_handles_missing_variance_fields_gracefully():
    """
    When variance fields are missing but it's not statistical data,
    the function should still process (though may produce 0 cards if not material).
    """
    # Data without variance fields but also without statistical fields
    incomplete_data = {
        "level": 0,
        "level_name": "Region",
        "top_drivers": [
            {
                "item": "East",
                "current": 8000000.0,
                "prior": 9300000.0,
                # Missing variance_dollar and variance_pct
            },
        ],
    }

    result = format_hierarchy_insight_cards(incomplete_data)

    # Should not raise error for missing fields, just produce 0 cards
    # (because variance defaults to 0 which fails materiality check)
    assert "error" not in result or result.get("error") != "DataStructureMismatch"
    assert isinstance(result["insight_cards"], list)


def test_processes_correct_hierarchy_data():
    """
    When correct hierarchy level statistics are provided, should process normally.
    """
    correct_data = {
        "level": 0,
        "level_name": "Region",
        "total_variance_dollar": -3000000.0,
        "top_drivers": [
            {
                "item": "East",
                "variance_dollar": -1300000.0,
                "variance_pct": -15.0,
                "current": 7200000.0,
                "prior": 8500000.0,
                "share_current": 0.40,
                "share_prior": 0.38,
                "share_change": 0.02,
                "cumulative_pct": 43.3,
            },
        ],
        "is_last_level": False,
    }

    result = format_hierarchy_insight_cards(correct_data)

    # Should process successfully and generate card
    assert "error" not in result or result.get("error") != "DataStructureMismatch"
    assert len(result["insight_cards"]) == 1
    assert result["insight_cards"][0]["title"] == "Level 0 Variance Driver: East"


def test_error_message_includes_diagnostic_info():
    """
    Error message should include helpful diagnostic information for debugging.
    """
    statistical_summary_data = {
        "level": 1,
        "level_name": "Division",
        "top_drivers": [
            {
                "item": "Central",
                "avg": 5000000.0,
                "slope_3mo": -500000.0,
                "cv": 0.10,
            },
        ],
    }

    result = format_hierarchy_insight_cards(statistical_summary_data)

    assert result["error"] == "DataStructureMismatch"
    assert "expected_fields" in result
    assert "variance_dollar" in result["expected_fields"]
    assert "variance_pct" in result["expected_fields"]
    assert "received_fields" in result
    assert "slope_3mo" in result["received_fields"]
    assert result["level"] == 1
    assert result["level_name"] == "Division"
