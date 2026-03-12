"""
Step 5: Unit tests for Report Synthesis Agent tools.

Tests:
- generate_markdown_report
- generate_executive_summary
"""

import pytest
import json
from pathlib import Path
from config.dataset_resolver import clear_dataset_cache
from data_analyst_agent.sub_agents.report_synthesis_agent.tools.report_markdown.formatting import clear_metric_units_cache
from tests.utils.import_helpers import import_report_synthesis_tool

DATASETS_ROOT = Path(__file__).resolve().parents[2] / "config" / "datasets" / "csv"



# ============================================================================
# Helper: build mock hierarchical results
# ============================================================================



def _require_dataset(slug: str) -> None:
    dataset_dir = DATASETS_ROOT / slug
    if not dataset_dir.exists():
        pytest.skip(f"dataset '{slug}' not present in this workspace")

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
    assert "# Executive Analysis Report - 067" in report
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
async def test_variance_table_cumulative_pct_monotonic():
    """Variance table cumulative column should be monotonic and end near 100%."""
    mod = import_report_synthesis_tool("generate_markdown_report")
    results = _make_hierarchical_results()

    report = await mod.generate_markdown_report(
        hierarchical_results=json.dumps(results),
        cost_center="067"
    )

    section = report.split("## Variance Drivers", 1)[1]
    table_block = section.split("##", 1)[0]
    rows = [line.strip() for line in table_block.splitlines() if line.strip().startswith("|")]
    data_rows = [line for line in rows if not line.startswith("|------") and not line.startswith("| Rank")]

    cumulative_values: list[float] = []
    for row in data_rows:
        cells = [cell.strip() for cell in row.strip().split("|") if cell.strip()]
        if not cells:
            continue
        cumulative_str = cells[-1].rstrip("%")
        cumulative_values.append(float(cumulative_str))

    assert cumulative_values, "No cumulative values parsed"
    assert cumulative_values[-1] == pytest.approx(100.0, abs=0.2)
    assert all(curr >= prev for prev, curr in zip(cumulative_values, cumulative_values[1:])), "Cumulative values must be monotonic"
    assert any(val > 0 for val in cumulative_values), "Cumulative column should not be all zeros"


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
async def test_markdown_report_respects_presentation_unit_for_counts():
    """Metrics declared as counts should not be rendered with currency formatting."""
    mod = import_report_synthesis_tool("generate_markdown_report")
    results = _make_hierarchical_results()

    report = await mod.generate_markdown_report(
        hierarchical_results=json.dumps(results),
        cost_center="067",
        presentation_unit="count"
    )

    assert "Variance (count)" in report
    assert "Variance $" not in report
    assert "| ${" not in report

    print("[PASS] Count units render without currency symbols")


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

    # Recommended section should include multiple specific actions
    assert "## Recommended Actions" in report
    rec_section = report.split("## Recommended Actions", 1)[1].split("##", 1)[0]
    prefixes = tuple(f"{i}." for i in range(1, 6))
    action_lines = [line.strip() for line in rec_section.splitlines() if line.strip().startswith(prefixes)]

    assert len(action_lines) >= 3, f"Expected at least 3 actions, found {len(action_lines)}"
    assert any("Freight Revenue" in line for line in action_lines)
    assert any("Fuel Surcharge Revenue" in line for line in action_lines)

    print("[PASS] Recommended actions reference top drivers with specific guidance")


@pytest.mark.unit
@pytest.mark.csv_mode
@pytest.mark.asyncio
async def test_anomalies_section_prioritizes_trade_scenarios_with_truncation_note():
    """Synthetic trade_data scenarios should appear in anomalies with truncation rationale."""
    mod = import_report_synthesis_tool("generate_markdown_report")
    results = _make_hierarchical_results()

    scenario_ids = ["A1", "B1", "C1", "D1", "E1", "F1"]
    scenarios = []
    for idx, sid in enumerate(scenario_ids, start=1):
        scenarios.append({
            "scenario_id": sid,
            "grain": "weekly",
            "first_period": f"2024-0{idx}-01",
            "last_period": f"2024-0{idx}-07",
            "avg_anomaly_value": 1500 - idx * 100,
            "avg_baseline_value": 500,
            "deviation_pct": 25 - idx,  # ensure later scenarios rank lower
            "severity": "high" if idx <= 3 else "medium",
            "ground_truth_insight": f"{sid} ground truth",
        })

    report = await mod.generate_markdown_report(
        hierarchical_results=json.dumps(results),
        anomaly_indicators=json.dumps({"anomalies": scenarios}),
        statistical_summary=json.dumps({"summary_stats": {"temporal_grain": "weekly"}}),
        analysis_period="2025-12",
    )

    section = report.split("## Anomalies", 1)[1]
    anomaly_block = section.split("##", 1)[0]

    # Scenario IDs from synthetic trade_data should be present
    assert "A1" in anomaly_block
    assert "B1" in anomaly_block
    # Truncation note should explain omitted scenarios (e.g., F1)
    assert "Showing top" in anomaly_block
    assert "Omitted scenarios" in anomaly_block
    assert "F1" in anomaly_block


@pytest.mark.unit
def test_filtered_narrative_actions_drop_stub_strings():
    """Stubbed LLM actions should be suppressed so reports have no placeholder text."""
    mod = import_report_synthesis_tool("generate_markdown_report")
    narrative = {
        "recommended_actions": [
            "Stub action with specificity (HS4 8542 @ LAX).",
            "Investigate legitimate driver variance vs prior month.",
        ]
    }

    filtered = mod._filtered_narrative_actions(narrative)

    assert filtered == ["Investigate legitimate driver variance vs prior month."]


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
    assert "# Executive Analysis Report - 067" in report

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


@pytest.mark.unit
@pytest.mark.csv_mode
@pytest.mark.asyncio
async def test_markdown_report_uses_metric_units_for_covid_cases(monkeypatch):
    """covid_us_counties cases should render people units from metric_units.yaml."""
    _require_dataset("covid_us_counties")
    mod = import_report_synthesis_tool("generate_markdown_report")
    results = _make_hierarchical_results()

    monkeypatch.setenv("ACTIVE_DATASET", "covid_us_counties")
    clear_dataset_cache()
    clear_metric_units_cache()

    report = await mod.generate_markdown_report(
        hierarchical_results=json.dumps(results),
        analysis_target="cases",
    )

    lines = [line for line in report.splitlines() if "Total Variance" in line]
    assert lines, "Total Variance line missing in covid unit test"
    assert all("$" not in line for line in lines)
    assert any("people" in line.lower() for line in lines)

    rec_section = report.split("## Recommended Actions", 1)[1].split("##", 1)[0]
    assert "$" not in rec_section
    assert "people" in rec_section.lower()

    assert "Variance (people)" in report

    clear_metric_units_cache()
    clear_dataset_cache()


@pytest.mark.unit
@pytest.mark.csv_mode
@pytest.mark.asyncio
async def test_markdown_report_prefers_metric_units_over_contract(monkeypatch):
    """owid_co2_emissions co2 should render MtCO2 even if contract says tonnes."""
    _require_dataset("owid_co2_emissions")
    mod = import_report_synthesis_tool("generate_markdown_report")
    results = _make_hierarchical_results()

    monkeypatch.setenv("ACTIVE_DATASET", "owid_co2_emissions")
    clear_dataset_cache()
    clear_metric_units_cache()

    report = await mod.generate_markdown_report(
        hierarchical_results=json.dumps(results),
        analysis_target="co2",
        presentation_unit="tonnes",
    )

    lines = [line for line in report.splitlines() if "Total Variance" in line]
    assert lines, "Total Variance line missing in CO2 unit test"
    assert all("$" not in line for line in lines)
    assert any("mtco2" in line.lower() for line in lines)

    rec_section = report.split("## Recommended Actions", 1)[1].split("##", 1)[0]
    assert "$" not in rec_section
    assert "mtco2" in rec_section.lower()

    assert "Variance (MtCO2)" in report

    clear_metric_units_cache()
    clear_dataset_cache()


@pytest.mark.unit
@pytest.mark.csv_mode
@pytest.mark.asyncio
async def test_markdown_report_populates_anomalies_from_stats():
    mod = import_report_synthesis_tool("generate_markdown_report")
    results = _make_hierarchical_results()

    stats_payload = {
        "anomalies": [
            {
                "item": "California",
                "period": "2020-05-01",
                "value": 1250,
                "z_score": 3.5,
                "p_value": 0.0004,
            }
        ]
    }

    report = await mod.generate_markdown_report(
        hierarchical_results=json.dumps(results),
        statistical_summary=json.dumps(stats_payload),
        analysis_target="cases",
    )

    assert "## Anomalies" in report
    anomaly_section = report.split("## Anomalies", 1)[1].split("##", 1)[0]
    assert "California" in anomaly_section
    assert "z=3.50" in anomaly_section
