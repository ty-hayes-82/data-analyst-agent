"""Regression: brief_utils must tolerate JSON-null nested dicts (e.g. hierarchical_analysis: null)."""

from __future__ import annotations

from data_analyst_agent.brief_utils import BriefUtils, SignalRanker, _dict_or_empty
from data_analyst_agent.sub_agents.executive_brief_agent.brief_pipeline import (
    run_brief_sync,
)


def test_dict_or_empty() -> None:
    assert _dict_or_empty(None) == {}
    assert _dict_or_empty([]) == {}
    assert _dict_or_empty({"a": 1}) == {"a": 1}


def test_get_network_totals_null_hierarchical_analysis() -> None:
    metrics = {
        "rev": {"hierarchical_analysis": None},
        "miles": {"hierarchical_analysis": {}},
    }
    totals = BriefUtils.get_network_totals(metrics)
    assert totals == {}


def test_get_network_totals_level_0_with_cards() -> None:
    metrics = {
        "rev": {
            "hierarchical_analysis": {
                "level_0": {
                    "insight_cards": [
                        {
                            "evidence": {
                                "current": 100,
                                "prior": 90,
                                "variance_pct": 11.1,
                                "variance_dollar": 10,
                            }
                        }
                    ]
                }
            }
        }
    }
    totals = BriefUtils.get_network_totals(metrics)
    assert "rev" in totals
    assert totals["rev"]["var_pct"] == 11.1


def test_signal_ranker_null_hierarchy_extract_all_no_raise() -> None:
    metrics = {"x": {"hierarchical_analysis": None, "statistical_summary": None}}
    ranker = SignalRanker(metrics)
    signals = ranker.extract_all()
    assert isinstance(signals, list)


def test_signal_ranker_null_summary_stats_inner() -> None:
    metrics = {
        "x": {
            "hierarchical_analysis": {},
            "statistical_summary": {"summary_stats": None, "anomalies": None},
        }
    }
    ranker = SignalRanker(metrics)
    ranker.extract_anomalies()
    assert ranker.scored_signals == []


def test_run_brief_sync_skips_llm_when_no_signals() -> None:
    """Pass 0 yields no signals: deterministic brief, no genai client needed."""
    json_data = {
        "m1": {"hierarchical_analysis": None, "statistical_summary": None},
    }
    executive, md, meta = run_brief_sync(
        json_data,
        analysis_period="the week ending 2026-03-14",
        period_end="2026-03-14",
        canonical_grain="weekly",
        top_signals=10,
        max_curated=5,
        skip_curation=False,
        lite_model="unused",
        pro_model="unused",
    )
    assert meta.get("empty_signals") is True
    assert meta.get("pass0_count") == 0
    assert meta.get("pass1_skipped") is True
    assert "No ranked signals" in executive["header"]["summary"] or "No ranked signals" in md
    assert "pipeline" in executive
