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


def _prime_cache(df: pd.DataFrame, run_id: str) -> None:
    from data_analyst_agent.semantic.models import AnalysisContext, DatasetContract

    set_validated_csv(df.to_csv(index=False))

    contract = DatasetContract.from_yaml(str(TRADE_CONTRACT_PATH))
    contract._source_path = str(TRADE_CONTRACT_PATH)

    ctx = AnalysisContext(
        contract=contract,
        df=df,
        target_metric=contract.get_metric("trade_value_usd"),
        primary_dimension=contract.get_dimension("flow"),
        run_id=run_id,
        max_drill_depth=5,
    )
    set_analysis_context(ctx)


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
    df = _load_full_trade_df()
    _prime_cache(df, run_id="e2e-insight-quality-full-trade")


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


@pytest.mark.e2e
@pytest.mark.trade_data
class TestVarianceAttributionAccuracy:
    @pytest.mark.asyncio
    async def test_region_ranking_and_state_driver(self) -> None:
        from data_analyst_agent.sub_agents.hierarchy_variance_agent.tools.compute_level_statistics import (
            compute_level_statistics,
        )

        df = _load_full_trade_df()
        weekly = df[df["grain"] == "weekly"].copy()

        clear_all_caches()
        try:
            _prime_cache(weekly, run_id="e2e-variance-weekly")

            region_stats = json.loads(
                await compute_level_statistics(
                    level=2,
                    analysis_period="2024",
                    variance_type="yoy",
                    hierarchy_name="full_hierarchy",
                    top_n=10,
                )
            )
            assert "error" not in region_stats, region_stats

            drivers = region_stats.get("top_drivers") or []
            assert drivers
            # Ensure ranking by absolute variance matches ground truth ordering.
            ranked = sorted(drivers, key=lambda d: abs(d.get("variance_dollar", 0) or 0), reverse=True)
            top_regions = [d.get("item") for d in ranked[:4]]
            assert top_regions == ["West", "South", "Northeast", "Midwest"]
        finally:
            clear_all_caches()

        # West state driver: CA should be top
        clear_all_caches()
        try:
            west = weekly[weekly["region"] == "West"].copy()
            _prime_cache(west, run_id="e2e-variance-west")

            state_stats = json.loads(
                await compute_level_statistics(
                    level=3,
                    analysis_period="2024",
                    variance_type="yoy",
                    hierarchy_name="full_hierarchy",
                    top_n=10,
                )
            )
            assert "error" not in state_stats, state_stats
            top = (state_stats.get("top_drivers") or [])[0]
            assert top.get("item") == "CA"
        finally:
            clear_all_caches()

    def test_total_and_flow_yoy_variance(self) -> None:
        df = _load_full_trade_df()
        weekly = df[df["grain"] == "weekly"].copy()

        yearly = weekly.groupby("year")["trade_value_usd"].sum()
        y2024 = float(yearly.loc[2024])
        y2023 = float(yearly.loc[2023])
        total_pct = (y2024 - y2023) / y2023 * 100
        assert total_pct == pytest.approx(1.24, abs=0.5)

        flow_year = weekly.groupby(["flow", "year"])["trade_value_usd"].sum().unstack().fillna(0.0)
        imports_pct = (float(flow_year.loc["imports", 2024]) - float(flow_year.loc["imports", 2023])) / float(flow_year.loc["imports", 2023]) * 100
        exports_pct = (float(flow_year.loc["exports", 2024]) - float(flow_year.loc["exports", 2023])) / float(flow_year.loc["exports", 2023]) * 100

        assert imports_pct == pytest.approx(1.27, abs=0.5)
        assert exports_pct == pytest.approx(1.19, abs=0.5)
        assert imports_pct > exports_pct
