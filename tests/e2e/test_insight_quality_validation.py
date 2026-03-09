"""Insight quality validation for trade_data synthetic dataset.

This suite validates that agents extract accurate, meaningful insights using the
embedded ground-truth anomaly scenarios (A1-F1).

Per Ty's instruction: implement Class 1 first.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import pandas as pd
import pytest

from data_analyst_agent.sub_agents.data_cache import clear_all_caches, set_analysis_context, set_validated_csv


REPO_ROOT = Path(__file__).resolve().parents[2]
TRADE_DATA_PATH = REPO_ROOT / "data" / "synthetic" / "synthetic_hierarchical_trade_dataset_250k.csv"
TRADE_CONTRACT_PATH = REPO_ROOT / "config" / "datasets" / "csv" / "trade_data" / "contract.yaml"
VALIDATION_PATH = REPO_ROOT / "data" / "validation" / "validation_datapoints.json"


@lru_cache(maxsize=1)
def _load_full_trade_df() -> pd.DataFrame:
    return pd.read_csv(TRADE_DATA_PATH)


@lru_cache(maxsize=1)
def _load_validation() -> dict:
    return json.loads(VALIDATION_PATH.read_text())


def _prime_cache_with_full_trade_df() -> None:
    from data_analyst_agent.semantic.models import AnalysisContext, DatasetContract

    df = _load_full_trade_df()
    set_validated_csv(df.to_csv(index=False))

    contract = DatasetContract.from_yaml(str(TRADE_CONTRACT_PATH))
    contract._source_path = str(TRADE_CONTRACT_PATH)

    ctx = AnalysisContext(
        contract=contract,
        df=df,
        target_metric=contract.get_metric("trade_value_usd"),
        primary_dimension=contract.get_dimension("flow"),
        run_id="e2e-insight-quality-full-trade",
        max_drill_depth=5,
    )
    set_analysis_context(ctx)


@pytest.mark.e2e
@pytest.mark.trade_data
class TestAnomalyDetectionAccuracy:
    @pytest.mark.asyncio
    async def test_all_scenarios_detected_weekly_accuracy(self) -> None:
        """Run compute_anomaly_indicators on full dataset and validate A1-F1 weekly."""
        from data_analyst_agent.sub_agents.statistical_insights_agent.tools.compute_anomaly_indicators import (
            compute_anomaly_indicators,
        )

        validation = _load_validation()
        scenarios = [
            s for s in validation["anomaly_scenarios"]
            if s["grain"] == "weekly" and s["scenario_id"] in {"A1", "B1", "C1", "D1", "E1", "F1"}
        ]
        assert len(scenarios) == 6

        clear_all_caches()
        try:
            _prime_cache_with_full_trade_df()
            result = json.loads(await compute_anomaly_indicators())
            assert "error" not in result, result

            produced = result.get("anomalies") or []
            assert produced, "Expected anomaly indicators"

            for s in scenarios:
                sid = s["scenario_id"]
                p = next(
                    a
                    for a in produced
                    if a.get("scenario_id") == sid and a.get("grain") == "weekly"
                )

                # deviation_pct within 5 percentage points
                assert p["deviation_pct"] == pytest.approx(s["deviation_pct"], abs=5.0)

                # direction correct
                expected_dir = "positive" if s["deviation_pct"] >= 0 else "negative"
                assert p["direction"] == expected_dir

                # severity classification matches
                assert p["severity"] == (s.get("severity") or "unknown").lower()
        finally:
            clear_all_caches()
