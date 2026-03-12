"""Tests for severity_guard module."""

import json
import pytest
from data_analyst_agent.sub_agents.executive_brief_agent.severity_guard import (
    has_critical_or_high_findings,
    build_severity_enforcement_block,
)


def test_has_critical_findings_from_alert_scoring():
    """Test detection of CRITICAL priority in alert_scoring."""
    json_data = {
        "cases": {
            "alert_scoring": {
                "top_alerts": [
                    {"priority": "CRITICAL", "item_name": "Arizona", "variance_pct": 150.0}
                ]
            }
        }
    }
    
    has_critical, critical_metrics = has_critical_or_high_findings(json_data)
    assert has_critical is True
    assert "cases" in critical_metrics


def test_has_high_findings_from_narrative():
    """Test detection of HIGH priority in narrative_results."""
    json_data = {
        "deaths": {
            "narrative_results": {
                "insight_cards": [
                    {"priority": "high", "title": "Mortality spike"}
                ]
            }
        }
    }
    
    has_critical, critical_metrics = has_critical_or_high_findings(json_data)
    assert has_critical is True
    assert "deaths" in critical_metrics


def test_has_critical_findings_from_hierarchical():
    """Test detection of CRITICAL in hierarchical_analysis."""
    json_data = {
        "revenue": {
            "hierarchical_analysis": {
                "level_0": {
                    "insight_cards": [
                        {"priority": "critical", "title": "Major variance"}
                    ]
                }
            }
        }
    }
    
    has_critical, critical_metrics = has_critical_or_high_findings(json_data)
    assert has_critical is True
    assert "revenue" in critical_metrics


def test_no_critical_findings():
    """Test when only LOW/MEDIUM findings exist."""
    json_data = {
        "metric1": {
            "narrative_results": {
                "insight_cards": [
                    {"priority": "low", "title": "Minor change"},
                    {"priority": "medium", "title": "Moderate shift"}
                ]
            }
        }
    }
    
    has_critical, critical_metrics = has_critical_or_high_findings(json_data)
    assert has_critical is False
    assert len(critical_metrics) == 0


def test_multiple_metrics_with_critical():
    """Test detection across multiple metrics."""
    json_data = {
        "cases": {
            "alert_scoring": {
                "top_alerts": [
                    {"priority": "CRITICAL", "variance_pct": 150.0}
                ]
            }
        },
        "deaths": {
            "narrative_results": {
                "insight_cards": [
                    {"priority": "high", "title": "Spike"}
                ]
            }
        },
        "hospitalizations": {
            "narrative_results": {
                "insight_cards": [
                    {"priority": "low", "title": "Normal"}
                ]
            }
        }
    }
    
    has_critical, critical_metrics = has_critical_or_high_findings(json_data)
    assert has_critical is True
    assert "cases" in critical_metrics
    assert "deaths" in critical_metrics
    assert "hospitalizations" not in critical_metrics


def test_build_enforcement_block_with_critical():
    """Test enforcement block generation when critical findings exist."""
    block = build_severity_enforcement_block(True, ["cases", "deaths"])
    
    assert "CRITICAL FINDINGS DETECTED" in block
    assert "cases" in block
    assert "deaths" in block
    assert "DO NOT use fallback text" in block
    assert "MANDATORY ENFORCEMENT" in block


def test_build_enforcement_block_without_critical():
    """Test enforcement block is empty when no critical findings."""
    block = build_severity_enforcement_block(False, [])
    
    assert block == ""


def test_handles_string_json_in_alert_scoring():
    """Test parsing when alert_scoring is a JSON string."""
    json_data = {
        "metric1": {
            "alert_scoring": json.dumps({
                "top_alerts": [
                    {"priority": "HIGH", "variance_pct": 80.0}
                ]
            })
        }
    }
    
    has_critical, critical_metrics = has_critical_or_high_findings(json_data)
    assert has_critical is True
    assert "metric1" in critical_metrics


def test_handles_string_json_in_narrative():
    """Test parsing when narrative_results is a JSON string."""
    json_data = {
        "metric2": {
            "narrative_results": json.dumps({
                "insight_cards": [
                    {"priority": "critical", "title": "Major issue"}
                ]
            })
        }
    }
    
    has_critical, critical_metrics = has_critical_or_high_findings(json_data)
    assert has_critical is True
    assert "metric2" in critical_metrics


def test_ignores_invalid_json():
    """Test graceful handling of invalid JSON strings."""
    json_data = {
        "metric3": {
            "alert_scoring": "{invalid json",
            "narrative_results": "not json at all"
        }
    }
    
    has_critical, critical_metrics = has_critical_or_high_findings(json_data)
    assert has_critical is False
    assert len(critical_metrics) == 0


def test_case_insensitive_priority():
    """Test that priority matching is case-insensitive."""
    json_data = {
        "m1": {
            "narrative_results": {
                "insight_cards": [
                    {"priority": "CRITICAL"},  # uppercase
                    {"priority": "High"},       # mixed case
                    {"priority": "critical"}    # lowercase
                ]
            }
        }
    }
    
    has_critical, critical_metrics = has_critical_or_high_findings(json_data)
    assert has_critical is True
    assert "m1" in critical_metrics
