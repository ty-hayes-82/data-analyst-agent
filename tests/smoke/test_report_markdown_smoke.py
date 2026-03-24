import json

import pytest

from tests.utils.import_helpers import import_report_synthesis_tool


def _minimal_hierarchical_results() -> dict:
    return {
        "levels_analyzed": [1],
        "drill_down_path": "Level 1",
        "level_analyses": {
            "level_1": {
                "top_drivers": [
                    {
                        "rank": 1,
                        "item": "West",
                        "variance_dollar": 125000.0,
                        "variance_pct": 6.8,
                    }
                ]
            }
        },
    }


@pytest.mark.smoke
@pytest.mark.unit
@pytest.mark.csv_mode
@pytest.mark.asyncio
async def test_generate_markdown_report_smoke_no_error_stub():
    mod = import_report_synthesis_tool("generate_markdown_report")
    payload = json.dumps(_minimal_hierarchical_results())

    reports = []
    for metric in ("lrpm", "trpm"):
        report = await mod.generate_markdown_report(
            hierarchical_results=payload,
            analysis_target=metric,
            analysis_period="the period ending 2026-03-14",
            target_label="Metric",
        )
        reports.append(report)

    assert all(isinstance(report, str) and report.strip() for report in reports)
    assert all(not report.lstrip().startswith("# Error Generating Report") for report in reports)
