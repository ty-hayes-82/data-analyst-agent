from data_analyst_agent.sub_agents.executive_brief_agent import scope_utils


def test_scoped_digest_uses_report_fallback_when_narrative_missing() -> None:
    metric_name = "Test Metric"
    json_data = {
        metric_name: {
            "hierarchical_analysis": {
                "level_1": {
                    "insight_cards": [],
                    "level_name": "State",
                }
            },
            "statistical_summary": {},
            "analysis": {},
            "narrative_results": {},
        }
    }
    reports_md = {
        metric_name: "## Insight Cards\n### California Spike\nVariance centered in California counties."
    }

    digest = scope_utils._build_scoped_digest(  # type: ignore[attr-defined]
        json_data=json_data,
        reports_md=reports_md,
        scope_entity="California",
        scope_level=1,
        analysis_period="2024-03",
    )

    assert "California Spike" in digest
