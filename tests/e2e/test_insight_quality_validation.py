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


@pytest.mark.e2e
@pytest.mark.trade_data
class TestSeasonalPatternAccuracy:
    @pytest.mark.asyncio
    async def test_seasonality_matches_ground_truth(self) -> None:
        from data_analyst_agent.sub_agents.statistical_insights_agent.tools.compute_seasonal_decomposition import (
            compute_seasonal_decomposition,
        )

        validation = _load_validation()["seasonal_pattern"]

        df = _load_full_trade_df()
        clear_all_caches()
        try:
            _prime_cache(df, run_id="e2e-seasonality-full")
            seasonal = json.loads(await compute_seasonal_decomposition())
            assert "error" not in seasonal, seasonal

            summary = seasonal.get("seasonality_summary") or {}
            assert summary

            assert summary["peak_month"] == validation["peak_month"]
            assert summary["trough_month"] == validation["trough_month"]
            assert summary["seasonal_amplitude_pct"] == pytest.approx(validation["seasonal_amplitude_pct"], abs=2.0)
        finally:
            clear_all_caches()


@pytest.mark.e2e
@pytest.mark.trade_data
class TestNarrativeInsightQuality:
    @pytest.mark.asyncio
    async def test_narrative_mentions_terms_locations_and_quant_claims(self) -> None:
        import re

        from data_analyst_agent.sub_agents.hierarchy_variance_agent.tools.compute_level_statistics import (
            compute_level_statistics,
        )
        from data_analyst_agent.sub_agents.statistical_insights_agent.tools.compute_anomaly_indicators import (
            compute_anomaly_indicators,
        )
        from data_analyst_agent.sub_agents.statistical_insights_agent.tools.compute_seasonal_decomposition import (
            compute_seasonal_decomposition,
        )
        from data_analyst_agent.sub_agents.narrative_agent.tools.generate_narrative_summary import (
            generate_narrative_summary,
        )

        df = _load_full_trade_df()
        validation = _load_validation()
        gt_weekly = [
            s
            for s in validation["anomaly_scenarios"]
            if s["grain"] == "weekly" and s["scenario_id"] in {"A1", "B1", "C1", "D1", "E1", "F1"}
        ]
        gt_pcts = [float(s["deviation_pct"]) for s in gt_weekly]

        clear_all_caches()
        try:
            _prime_cache(df, run_id="e2e-narrative-full")

            hv = json.loads(
                await compute_level_statistics(
                    level=2,
                    analysis_period="2024",
                    variance_type="yoy",
                    hierarchy_name="full_hierarchy",
                    top_n=10,
                )
            )
            ai = json.loads(await compute_anomaly_indicators())
            sd = json.loads(await compute_seasonal_decomposition())

            narrative = await generate_narrative_summary(
                hierarchy_variance=hv,
                anomaly_indicators=ai,
                seasonal_decomposition=sd,
            )
        finally:
            clear_all_caches()

        low = narrative.lower()

        # Required terms
        assert ("semiconductors" in low) or ("8542" in low)
        assert ("energy" in low) or ("natural gas" in low) or ("2711" in low)
        assert ("weather" in low) or ("disruption" in low)
        assert ("machinery" in low) or ("8409" in low)
        assert ("auto parts" in low) or ("8703" in low) or ("8708" in low)
        assert ("plastics" in low) or ("3901" in low) or ("3923" in low)

        # Geographic locations
        for geo in (
            "california",
            "lax",
            "texas",
            "houston",
            "newark",
            "northeast",
            "chicago",
            "midwest",
            "michigan",
            "detroit",
            "florida",
        ):
            assert geo in low, f"Missing geo term: {geo}\n\n{narrative}"

        # Quantitative claims: at least 3 percentages, each within 10 pts of a ground-truth deviation
        percents = [float(m.group(1)) for m in re.finditer(r"([+-]?\d+(?:\.\d+)?)%", narrative)]
        assert len(percents) >= 3, narrative

        matched = 0
        for p in percents:
            if any(abs(p - gt) <= 10.0 for gt in gt_pcts):
                matched += 1
        assert matched >= 3, f"Not enough percent claims matched ground truth. percents={percents} gt={gt_pcts}"


@pytest.mark.e2e
@pytest.mark.trade_data
class TestReportCompleteness:
    @pytest.mark.asyncio
    async def test_report_sections_anomalies_variance_recommendations(self) -> None:
        from data_analyst_agent.sub_agents.hierarchy_variance_agent.tools.compute_level_statistics import (
            compute_level_statistics,
        )
        from data_analyst_agent.sub_agents.statistical_insights_agent.tools.compute_anomaly_indicators import (
            compute_anomaly_indicators,
        )
        from data_analyst_agent.sub_agents.statistical_insights_agent.tools.compute_seasonal_decomposition import (
            compute_seasonal_decomposition,
        )
        from data_analyst_agent.sub_agents.narrative_agent.tools.generate_narrative_summary import (
            generate_narrative_summary,
        )
        from data_analyst_agent.sub_agents.report_synthesis_agent.tools.generate_markdown_report import (
            generate_markdown_report,
        )

        df = _load_full_trade_df()
        clear_all_caches()
        try:
            _prime_cache(df, run_id="e2e-report-full")

            hv = json.loads(
                await compute_level_statistics(
                    level=2,
                    analysis_period="2024",
                    variance_type="yoy",
                    hierarchy_name="full_hierarchy",
                    top_n=10,
                )
            )
            ai = json.loads(await compute_anomaly_indicators())
            sd = json.loads(await compute_seasonal_decomposition())
            narrative = await generate_narrative_summary(
                hierarchy_variance=hv,
                anomaly_indicators=ai,
                seasonal_decomposition=sd,
            )
        finally:
            clear_all_caches()

        narrative_results = json.dumps({"narrative_summary": narrative, "insight_cards": []})
        hierarchical_results = json.dumps({"level_2": hv, "levels_analyzed": [2], "drill_down_path": "Region"})

        report = await generate_markdown_report(
            hierarchical_results=hierarchical_results,
            analysis_target="trade_full",
            analysis_period="2024",
            narrative_results=narrative_results,
            target_label="Trade",
            anomaly_indicators=json.dumps(ai),
            seasonal_decomposition=json.dumps(sd),
        )

        low = report.lower()
        for required in (
            "executive summary",
            "variance",
            "anomalies",
            "seasonality",
            "recommended actions",
        ):
            assert required in low

        # Anomalies section should mention at least 4 of the scenario categories
        categories = [
            "volume_drop",
            "surge",
            "weather_disruption",
            "rebound",
            "shutdown",
            "demand_shift",
        ]
        mentioned = sum(1 for c in categories if c in low)
        assert mentioned >= 4, f"Only mentioned {mentioned}/6 anomaly categories"

        # Variance section should clearly indicate West as top region
        assert "west" in low

        # Recommendations: >=3 actionable items, not boilerplate-only
        rec_idx = low.find("recommended actions")
        assert rec_idx != -1
        rec_block = report[rec_idx : rec_idx + 900]
        action_lines = [
            ln
            for ln in rec_block.splitlines()
            if ln.strip().startswith(("1.", "2.", "3.", "4.", "5."))
        ]
        assert len(action_lines) >= 3

        specific = any(
            (
                "a1" in ln.lower()
                or "b1" in ln.lower()
                or "8542" in ln
                or "2711" in ln
                or "detroit" in ln.lower()
            )
            for ln in action_lines
        )
        assert specific, f"Recommendations too generic:\n{rec_block}"
