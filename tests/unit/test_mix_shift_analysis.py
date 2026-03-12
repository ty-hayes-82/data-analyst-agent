"""Unit tests for mix shift analysis narrative correctness."""

from __future__ import annotations

import importlib
import json
from types import SimpleNamespace

import pandas as pd
import pytest

mix_module = importlib.import_module(
    "data_analyst_agent.sub_agents.hierarchy_variance_agent.tools.compute_mix_shift_analysis"
)


async def _run_mix_shift(monkeypatch, df: pd.DataFrame, analysis_period: str, prior_period: str) -> dict:
    def _fake_resolver(_role: str):
        return df, "period", None, None, None, SimpleNamespace(contract=None)

    monkeypatch.setattr(mix_module, "resolve_data_and_columns", _fake_resolver)
    payload = await mix_module.compute_mix_shift_analysis(
        target_metric="revenue",
        price_metric="rate",
        volume_metric="volume",
        segment_dimension="segment",
        analysis_period=analysis_period,
        prior_period=prior_period,
    )
    return json.loads(payload)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_mix_shift_narrative_matches_sign(monkeypatch):
    """Narrative wording should align with mix effect and blended rate directions."""
    df_positive = pd.DataFrame(
        [
            {"period": "2024-01", "segment": "A", "revenue": 100.0, "volume": 10.0},
            {"period": "2024-01", "segment": "B", "revenue": 50.0, "volume": 10.0},
            {"period": "2025-01", "segment": "A", "revenue": 150.0, "volume": 12.0},
            {"period": "2025-01", "segment": "B", "revenue": 40.0, "volume": 8.0},
        ]
    )

    positive = await _run_mix_shift(monkeypatch, df_positive, "2025-01", "2024-01")
    narrative = positive["summary"]["narrative"]
    mix_effect = positive["total_decomposition"]["mix_effect"]
    blended_change = positive["blended_price"]["change_total"]

    if mix_effect >= 0:
        assert "added" in narrative
    else:
        assert "reduced" in narrative

    if blended_change >= 0:
        assert "increased" in narrative
    else:
        assert "decreased" in narrative

    df_negative = pd.DataFrame(
        [
            {"period": "2024-01", "segment": "A", "revenue": 120.0, "volume": 12.0},
            {"period": "2024-01", "segment": "B", "revenue": 90.0, "volume": 8.0},
            {"period": "2025-01", "segment": "A", "revenue": 80.0, "volume": 10.0},
            {"period": "2025-01", "segment": "B", "revenue": 130.0, "volume": 14.0},
        ]
    )

    negative = await _run_mix_shift(monkeypatch, df_negative, "2025-01", "2024-01")
    narrative_neg = negative["summary"]["narrative"]
    mix_effect_neg = negative["total_decomposition"]["mix_effect"]
    blended_change_neg = negative["blended_price"]["change_total"]

    if mix_effect_neg >= 0:
        assert "added" in narrative_neg
    else:
        assert "reduced" in narrative_neg

    if blended_change_neg >= 0:
        assert "increased" in narrative_neg
    else:
        assert "decreased" in narrative_neg
