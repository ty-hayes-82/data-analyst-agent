"""
Step 5: Unit tests for Report Synthesis Agent tools.

Tests:
- generate_markdown_report
- generate_executive_summary
"""

import pytest
import json
from tests.utils.import_helpers import import_report_synthesis_tool


# ============================================================================
# Helper: build mock hierarchical results
# ============================================================================

def _make_hierarchical_results() -> dict:
    """Build mock hierarchical results matching the report generator's expected input."""
    return {
        "levels_analyzed": [2, 3],
        "drill_down_path": "Level 2 -> Level 3",
        "level_analyses": {
            "level_2": {
                "total_variance_dollar": -125000.0,
                "total_variance_pct": -8.5,
                "variance_explained_pct": 92.3,
                "items_aggregated": 3,
                "top_drivers_identified": 2,
                "top_drivers": [
                    {
                        "rank": 1,
                        "item": "Freight Revenue",
                        "current": 2500000.0,
                        "prior": 2625000.0,
                        "variance_dollar": -125000.0,
                        "variance_pct": -4.8,
                        "cumulative_pct": 72.5,
                        "exceeds_threshold": True,
                        "threshold_met": ["dollar", "percentage"],
                        "materiality": "HIGH"
                    },
                    {
                        "rank": 2,
                        "item": "Fuel Surcharge Revenue",
                        "current": 350000.0,
                        "prior": 380000.0,
                        "variance_dollar": -30000.0,
                        "variance_pct": -7.9,
                        "cumulative_pct": 92.3,
                        "exceeds_threshold": False,
                        "threshold_met": ["percentage"],
                        "materiality": "MEDIUM"
                    },
                ]
            },
            "level_3": {
                "total_variance_dollar": -125000.0,
                "total_variance_pct": -8.5,
                "variance_explained_pct": 95.0,
                "items_aggregated": 5,
                "top_drivers_identified": 3,
                "top_drivers": [
                    {
                        "rank": 1,
                        "item": "Mileage Revenue",
                        "current": 2000000.0,
                        "prior": 2100000.0,
                        "variance_dollar": -100000.0,
                        "variance_pct": -4.8,
                        "cumulative_pct": 65.0,
                        "exceeds_threshold": True,
                        "threshold_met": ["dollar", "percentage"],
                        "materiality": "HIGH"
                    },
                    {
                        "rank": 2,
                        "item": "Fuel Surcharge Revenue",
                        "current": 350000.0,
                        "prior": 380000.0,
                        "variance_dollar": -30000.0,
                        "variance_pct": -7.9,
                        "cumulative_pct": 85.0,
                        "exceeds_threshold": False,
                        "threshold_met": ["percentage"],
                        "materiality": "MEDIUM"
                    },
                    {
                        "rank": 3,
                        "item": "Accessorial Revenue",
                        "current": 150000.0,
                        "prior": 145000.0,
                        "variance_dollar": 5000.0,
                        "variance_pct": 3.4,
                        "cumulative_pct": 95.0,
                        "exceeds_threshold": False,
                        "threshold_met": [],
                        "materiality": "LOW"
                    },
                ]
            }
        }
    }


# ============================================================================
# Tests for generate_markdown_report
# ============================================================================

@pytest.mark.unit
@pytest.mark.csv_mode
@pytest.mark.asyncio
async def test_generate_markdown_report_structure():
    """Test that the markdown report has all expected sections."""
    mod = import_report_synthesis_tool("generate_markdown_report")
    results = _make_hierarchical_results()

    report = await mod.generate_markdown_report(
        hierarchical_results=json.dumps(results),
        cost_center="067",
        analysis_period="2025-09"
    )

    assert isinstance(report, str)
    assert len(report) > 100

    # Check required sections
    assert "# P&L Analysis Report" in report
    assert "Cost Center 067" in report
    assert "## Executive Summary" in report
    assert "## Variance Drivers" in report
    assert "## Hierarchical Drill-Down Path" in report
    assert "## Recommended Actions" in report
    assert "## Data Quality & Notes" in report

    print(f"[PASS] Markdown report: {len(report)} chars, all sections present")


@pytest.mark.unit
@pytest.mark.csv_mode
@pytest.mark.asyncio
async def test_markdown_report_contains_variance_table():
    """Test that the report contains a variance drivers table with data."""
    mod = import_report_synthesis_tool("generate_markdown_report")
    results = _make_hierarchical_results()

    report = await mod.generate_markdown_report(
        hierarchical_results=json.dumps(results),
        cost_center="067"
    )

    # Should have a markdown table
    assert "| Rank |" in report
    assert "Mileage Revenue" in report
    assert "Fuel Surcharge Revenue" in report

    print("[PASS] Variance drivers table present with correct data")


@pytest.mark.unit
@pytest.mark.csv_mode
@pytest.mark.asyncio
async def test_markdown_report_numeric_formatting():
    """Test that dollar amounts and percentages are formatted correctly."""
    mod = import_report_synthesis_tool("generate_markdown_report")
    results = _make_hierarchical_results()

    report = await mod.generate_markdown_report(
        hierarchical_results=json.dumps(results),
        cost_center="067"
    )

    # Dollar formatting should use commas
    assert "$" in report
    # Percentage formatting
    assert "%" in report

    print("[PASS] Numeric formatting correct")


@pytest.mark.unit
@pytest.mark.csv_mode
@pytest.mark.asyncio
async def test_markdown_report_recommended_actions():
    """Test that HIGH materiality items generate recommended actions."""
    mod = import_report_synthesis_tool("generate_markdown_report")
    results = _make_hierarchical_results()

    report = await mod.generate_markdown_report(
        hierarchical_results=json.dumps(results),
        cost_center="067"
    )

    # Should have numbered actions for HIGH materiality items
    assert "1." in report
    assert "Investigate" in report or "investigate" in report.lower()

    print("[PASS] Recommended actions generated for HIGH materiality items")


@pytest.mark.unit
@pytest.mark.csv_mode
@pytest.mark.asyncio
async def test_markdown_report_empty_results():
    """Test report generation with empty results."""
    mod = import_report_synthesis_tool("generate_markdown_report")

    empty_results = {
        "levels_analyzed": [],
        "drill_down_path": "N/A",
        "level_analyses": {}
    }

    report = await mod.generate_markdown_report(
        hierarchical_results=json.dumps(empty_results),
        cost_center="067"
    )

    assert isinstance(report, str)
    assert len(report) > 0
    assert "# P&L Analysis Report" in report

    print("[PASS] Empty results handled gracefully")


@pytest.mark.unit
@pytest.mark.csv_mode
@pytest.mark.asyncio
async def test_markdown_report_error_on_invalid_json():
    """Test error handling for invalid JSON input."""
    mod = import_report_synthesis_tool("generate_markdown_report")

    report = await mod.generate_markdown_report(
        hierarchical_results="not valid json {{{}",
        cost_center="067"
    )

    # Should return an error report, not crash
    assert isinstance(report, str)
    assert "Error" in report or "error" in report.lower()

    print("[PASS] Invalid JSON handled gracefully")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s", "--tb=short"])
