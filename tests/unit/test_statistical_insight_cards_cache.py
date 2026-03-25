"""Statistical insight cards are cached under run .cache/ before hierarchy overwrites data_analyst_result."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.mark.unit
def test_statistical_insight_cards_cache_writes_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATA_ANALYST_OUTPUT_DIR", str(tmp_path))
    from data_analyst_agent.sub_agents.statistical_insights_agent import agent as si_agent

    ctx = MagicMock()
    ctx.session.state = {"current_analysis_target": "toll_expense"}

    si_agent._cache_statistical_insight_cards_for_troubleshooting(
        ctx,
        {
            "insight_cards": [{"title": "Test", "priority": "high"}],
            "summary_stats": {"n": 1},
        },
    )

    cache_file = tmp_path / ".cache" / "statistical_insight_cards_toll_expense.json"
    assert cache_file.is_file()
    text = cache_file.read_text(encoding="utf-8")
    assert "Test" in text
    assert "card_count" in text


@pytest.mark.unit
def test_insight_cache_stage_list_includes_statistical_insight_cards() -> None:
    from data_analyst_agent.cache.insight_cache import InsightCache

    assert "statistical_insight_cards" in InsightCache.STAGES
