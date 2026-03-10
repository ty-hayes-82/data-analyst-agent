"""Incremental E2E pipeline tests (trade_data only).

Strategy: validate the pipeline one agent at a time, building state incrementally.

Per Ty's instruction:
- Implement Level N only after Level N-1 is green.
- Fix underlying agent code when a level fails (don’t bandaid the test).

Status:
- Level 0: ✅
- Level 1: ✅
- Level 2: in progress
"""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

import pandas as pd
import pytest

from data_analyst_agent.sub_agents.data_cache import (
    clear_all_caches,
    get_validated_csv,
    set_analysis_context,
    set_validated_csv,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_C_PATH = REPO_ROOT / "data" / "validation" / "fixture_c_minimal_lax_8542.csv"
TRADE_CONTRACT_PATH = REPO_ROOT / "config" / "datasets" / "csv" / "trade_data" / "contract.yaml"
TRADE_DATA_PATH = REPO_ROOT / "data" / "synthetic" / "synthetic_hierarchical_trade_dataset_250k.csv"
VALIDATION_PATH = REPO_ROOT / "data" / "validation" / "validation_datapoints.json"


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


def _load_fixture_c_and_prime_cache() -> pd.DataFrame:
    """Load fixture_c and prime caches (A1 anomaly fixture)."""
    df = pd.read_csv(FIXTURE_C_PATH)
    _prime_cache(df, run_id="e2e-incremental-fixture-c")
    return df


def _load_full_trade_dataset_and_prime_cache() -> pd.DataFrame:
    """Load the full synthetic trade dataset and prime caches (seasonality baseline)."""
    df = pd.read_csv(TRADE_DATA_PATH)
    _prime_cache(df, run_id="e2e-incremental-full-trade")
    return df


@pytest.mark.e2e
@pytest.mark.trade_data
@pytest.mark.csv_mode
class TestLevel0_DataLoading:
    def test_load_fixture_c_into_data_cache(self) -> None:
        """Load fixture_c via data_cache.set_validated_csv() and assert integrity."""
        clear_all_caches()
        try:
            df = _load_fixture_c_and_prime_cache()
            assert len(df) > 0

            cached = get_validated_csv()
            assert cached, "Expected validated CSV to be present in cache"

            cached_df = pd.read_csv(StringIO(cached))
            assert len(cached_df) == len(df)

            required_cols = {
                # time + value
                "period_end",
                "trade_value_usd",
                # minimal identity/hierarchy
                "flow",
                "region",
                "state",
                "port_code",
                "hs2",
                "hs4",
                "hierarchy_path",
                "hierarchy_depth",
                # temporal helpers
                "grain",
                "year",
                "month",
                "iso_week",
                # anomaly labels (used by later assertions)
                "anomaly_flag",
            }
            missing = required_cols - set(cached_df.columns)
            assert not missing, f"Missing required columns: {sorted(missing)}"
        finally:
            clear_all_caches()


@pytest.mark.e2e
@pytest.mark.trade_data
@pytest.mark.csv_mode
class TestLevel1_HierarchyVariance:
    @pytest.mark.asyncio
    async def test_compute_level_statistics_non_empty(self) -> None:
        """Call hierarchy_variance_agent tool directly and assert structure."""
        from data_analyst_agent.sub_agents.hierarchy_variance_agent.tools.compute_level_statistics import (
            compute_level_statistics,
        )

        clear_all_caches()
        try:
            _load_fixture_c_and_prime_cache()

            # Use the anomaly window end as a stable analysis period for fixture_c
            validation = json.loads(VALIDATION_PATH.read_text())
            scenario = next(
                s
                for s in validation["anomaly_scenarios"]
                if s["scenario_id"] == "A1" and s["grain"] == "weekly"
            )
            analysis_period = scenario["last_period"]

            # Level 1 == Flow in full_hierarchy (Flow -> Region -> State -> Port -> HS2 -> HS4)
            result_json = await compute_level_statistics(
                level=1,
                analysis_period=analysis_period,
                variance_type="yoy",
                top_n=10,
                hierarchy_name="full_hierarchy",
            )
            result = json.loads(result_json)

            assert "error" not in result, result
            assert isinstance(result.get("top_drivers"), list)
            assert len(result["top_drivers"]) >= 1

            first = result["top_drivers"][0]
            # Minimal structural expectations for downstream stages
            for k in ("item", "current", "prior", "variance_dollar", "variance_pct"):
                assert k in first
        finally:
            clear_all_caches()


@pytest.mark.e2e
@pytest.mark.trade_data
@pytest.mark.csv_mode
class TestLevel2_StatisticalInsights:
    @pytest.mark.asyncio
    async def test_anomaly_a1_detected_matches_validation(self) -> None:
        """Run statistical insight tools and assert A1 anomaly matches validation."""
        from data_analyst_agent.sub_agents.statistical_insights_agent.tools.compute_anomaly_indicators import (
            compute_anomaly_indicators,
        )
        from data_analyst_agent.sub_agents.statistical_insights_agent.tools.compute_period_over_period_changes import (
            compute_period_over_period_changes,
        )

        clear_all_caches()
        try:
            _load_fixture_c_and_prime_cache()

            validation = json.loads(VALIDATION_PATH.read_text())
            scenario = next(
                s
                for s in validation["anomaly_scenarios"]
                if s["scenario_id"] == "A1" and s["grain"] == "weekly"
            )

            changes = json.loads(await compute_period_over_period_changes())
            assert "error" not in changes, changes

            anomalies_payload = json.loads(await compute_anomaly_indicators())
            assert "error" not in anomalies_payload, anomalies_payload
            anomalies = anomalies_payload.get("anomalies") or []
            assert anomalies, "Expected at least one anomaly summary"

            a1 = next(a for a in anomalies if a.get("scenario_id") == "A1")

            # Match the validation datapoints (allow small drift due to fixture minimalism)
            assert a1["rows_impacted"] == scenario["rows_impacted"]
            assert a1["first_period"] == scenario["first_period"]
            assert a1["last_period"] == scenario["last_period"]

            assert a1["avg_anomaly_value"] == pytest.approx(scenario["avg_anomaly_value"], rel=0.01)
            assert a1["avg_baseline_value"] == pytest.approx(scenario["avg_baseline_value"], rel=0.05)
            assert a1["deviation_pct"] == pytest.approx(scenario["deviation_pct"], abs=3)

            assert changes["deviation_pct"] == pytest.approx(scenario["deviation_pct"], abs=3)
        finally:
            clear_all_caches()


@pytest.mark.e2e
@pytest.mark.trade_data
@pytest.mark.csv_mode
class TestLevel3_SeasonalBaseline:
    @pytest.mark.asyncio
    async def test_peak_trough_months_match_validation(self) -> None:
        from data_analyst_agent.sub_agents.statistical_insights_agent.tools.compute_seasonal_decomposition import (
            compute_seasonal_decomposition,
        )

        clear_all_caches()
        try:
            _load_full_trade_dataset_and_prime_cache()

            validation = json.loads(VALIDATION_PATH.read_text())["seasonal_pattern"]

            seasonal = json.loads(await compute_seasonal_decomposition())
            assert "error" not in seasonal, seasonal

            summary = seasonal.get("seasonality_summary") or {}
            assert summary, "Expected seasonality_summary in compute_seasonal_decomposition output"

            assert summary["peak_month"] == validation["peak_month"]
            assert summary["trough_month"] == validation["trough_month"]
            assert summary["seasonal_amplitude_pct"] == pytest.approx(validation["seasonal_amplitude_pct"], abs=0.5)
        finally:
            clear_all_caches()


@pytest.mark.e2e
@pytest.mark.trade_data
@pytest.mark.csv_mode
class TestLevel4_NarrativeGeneration:
    @pytest.mark.asyncio
    async def test_narrative_non_empty_contains_keywords(self) -> None:
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

        validation = json.loads(VALIDATION_PATH.read_text())
        scenario = next(
            s
            for s in validation["anomaly_scenarios"]
            if s["scenario_id"] == "A1" and s["grain"] == "weekly"
        )

        # Collect anomaly + hierarchy variance from fixture_c
        clear_all_caches()
        try:
            _load_fixture_c_and_prime_cache()
            hv = json.loads(
                await compute_level_statistics(
                    level=1,
                    analysis_period=scenario["last_period"],
                    variance_type="yoy",
                    hierarchy_name="full_hierarchy",
                )
            )
            assert "error" not in hv, hv
            ai = json.loads(await compute_anomaly_indicators())
            assert "error" not in ai, ai
        finally:
            clear_all_caches()

        # Collect seasonality from full dataset
        clear_all_caches()
        try:
            _load_full_trade_dataset_and_prime_cache()
            sd = json.loads(await compute_seasonal_decomposition())
            assert "error" not in sd, sd
        finally:
            clear_all_caches()

        narrative = await generate_narrative_summary(
            hierarchy_variance=hv,
            anomaly_indicators=ai,
            seasonal_decomposition=sd,
        )

        assert isinstance(narrative, str)
        assert narrative.strip(), "Expected non-empty narrative"
        # Keyword expectations
        low = narrative.lower()
        assert ("electronics" in low) or ("hs2=85" in low) or ("hs2 85" in low), narrative
        assert ("region=west" in low) or ("state_name=california" in low) or ("region west" in low), narrative
        assert "season" in low, narrative


@pytest.mark.e2e
@pytest.mark.trade_data
@pytest.mark.csv_mode
class TestLevel5_AlertScoring:
    @pytest.mark.asyncio
    async def test_alerts_generated_have_severity(self) -> None:
        from data_analyst_agent.sub_agents.statistical_insights_agent.tools.compute_anomaly_indicators import (
            compute_anomaly_indicators,
        )
        from data_analyst_agent.sub_agents.alert_scoring_agent.tools.extract_alerts_from_analysis import (
            extract_alerts_from_analysis,
        )
        from data_analyst_agent.sub_agents.alert_scoring_agent.tools.apply_suppression import (
            apply_suppression,
        )

        validation = json.loads(VALIDATION_PATH.read_text())
        scenario = next(
            s
            for s in validation["anomaly_scenarios"]
            if s["scenario_id"] == "A1" and s["grain"] == "weekly"
        )

        clear_all_caches()
        try:
            _load_fixture_c_and_prime_cache()
            ai = json.loads(await compute_anomaly_indicators())
            assert "error" not in ai, ai

            extracted = json.loads(
                await extract_alerts_from_analysis(
                    statistical_summary="",
                    statistical_insights_result="",
                    synthesis=json.dumps(ai),
                    analysis_target="trade_fixture_c",
                )
            )
            assert "error" not in extracted, extracted

            suppressed = json.loads(
                await apply_suppression(
                    json.dumps(
                        {
                            "alerts": extracted.get("alerts", []),
                            "dimension_value": "trade_fixture_c",
                            "period": scenario["last_period"],
                            "events_calendar": [],
                            "feedback_history": [],
                        }
                    )
                )
            )

            active = suppressed.get("active_alerts") or []
            assert active, "Expected at least 1 active alert"
            assert "severity" in active[0], active[0]
        finally:
            clear_all_caches()


@pytest.mark.e2e
@pytest.mark.trade_data
@pytest.mark.csv_mode
class TestLevel6_ReportSynthesis:
    @pytest.mark.asyncio
    async def test_markdown_report_contains_required_sections(self) -> None:
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

        validation = json.loads(VALIDATION_PATH.read_text())
        scenario = next(
            s
            for s in validation["anomaly_scenarios"]
            if s["scenario_id"] == "A1" and s["grain"] == "weekly"
        )

        clear_all_caches()
        try:
            _load_fixture_c_and_prime_cache()
            hv = json.loads(
                await compute_level_statistics(
                    level=1,
                    analysis_period=scenario["last_period"],
                    variance_type="yoy",
                    hierarchy_name="full_hierarchy",
                )
            )
            ai = json.loads(await compute_anomaly_indicators())
        finally:
            clear_all_caches()

        clear_all_caches()
        try:
            _load_full_trade_dataset_and_prime_cache()
            sd = json.loads(await compute_seasonal_decomposition())
        finally:
            clear_all_caches()

        narrative = await generate_narrative_summary(
            hierarchy_variance=hv,
            anomaly_indicators=ai,
            seasonal_decomposition=sd,
        )
        narrative_results = json.dumps({"narrative_summary": narrative, "insight_cards": []})
        hierarchical_results = json.dumps({"level_1": hv, "levels_analyzed": [1], "drill_down_path": "Flow"})

        report = await generate_markdown_report(
            hierarchical_results=hierarchical_results,
            analysis_target="trade_fixture_c",
            analysis_period=scenario["last_period"],
            statistical_summary=None,
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
            assert required in low, f"Missing section: {required}\n\n{report[:800]}"


@pytest.mark.e2e
@pytest.mark.trade_data
@pytest.mark.csv_mode
class TestLevel7_FullPipeline:
    @pytest.mark.asyncio
    async def test_end_to_end_sequence_produces_complete_report(self) -> None:
        from data_analyst_agent.sub_agents.hierarchy_variance_agent.tools.compute_level_statistics import (
            compute_level_statistics,
        )
        from data_analyst_agent.sub_agents.statistical_insights_agent.tools.compute_anomaly_indicators import (
            compute_anomaly_indicators,
        )
        from data_analyst_agent.sub_agents.statistical_insights_agent.tools.compute_period_over_period_changes import (
            compute_period_over_period_changes,
        )
        from data_analyst_agent.sub_agents.statistical_insights_agent.tools.compute_seasonal_decomposition import (
            compute_seasonal_decomposition,
        )
        from data_analyst_agent.sub_agents.alert_scoring_agent.tools.extract_alerts_from_analysis import (
            extract_alerts_from_analysis,
        )
        from data_analyst_agent.sub_agents.alert_scoring_agent.tools.apply_suppression import (
            apply_suppression,
        )
        from data_analyst_agent.sub_agents.narrative_agent.tools.generate_narrative_summary import (
            generate_narrative_summary,
        )
        from data_analyst_agent.sub_agents.report_synthesis_agent.tools.generate_markdown_report import (
            generate_markdown_report,
        )

        validation = json.loads(VALIDATION_PATH.read_text())
        scenario = next(
            s
            for s in validation["anomaly_scenarios"]
            if s["scenario_id"] == "A1" and s["grain"] == "weekly"
        )

        # 0-2: load fixture + hierarchy variance + statistical insights
        clear_all_caches()
        try:
            _load_fixture_c_and_prime_cache()
            hv = json.loads(
                await compute_level_statistics(
                    level=1,
                    analysis_period=scenario["last_period"],
                    variance_type="yoy",
                    hierarchy_name="full_hierarchy",
                )
            )
            ai = json.loads(await compute_anomaly_indicators())
            pop = json.loads(await compute_period_over_period_changes())
            assert "error" not in hv and "error" not in ai and "error" not in pop

            extracted = json.loads(
                await extract_alerts_from_analysis(
                    synthesis=json.dumps(ai),
                    analysis_target="trade_fixture_c",
                )
            )
            suppressed = json.loads(
                await apply_suppression(
                    json.dumps(
                        {
                            "alerts": extracted.get("alerts", []),
                            "dimension_value": "trade_fixture_c",
                            "period": scenario["last_period"],
                            "events_calendar": [],
                            "feedback_history": [],
                        }
                    )
                )
            )
            active_alerts = suppressed.get("active_alerts") or []
            assert active_alerts and "severity" in active_alerts[0]
        finally:
            clear_all_caches()

        # 3: seasonality from full dataset
        clear_all_caches()
        try:
            _load_full_trade_dataset_and_prime_cache()
            sd = json.loads(await compute_seasonal_decomposition())
            assert "error" not in sd
        finally:
            clear_all_caches()

        # 4: narrative
        narrative = await generate_narrative_summary(
            hierarchy_variance=hv,
            anomaly_indicators=ai,
            seasonal_decomposition=sd,
        )
        assert narrative and isinstance(narrative, str)

        # 6: report synthesis
        narrative_results = json.dumps({"narrative_summary": narrative, "insight_cards": []})
        hierarchical_results = json.dumps({"level_1": hv, "levels_analyzed": [1], "drill_down_path": "Flow"})

        report = await generate_markdown_report(
            hierarchical_results=hierarchical_results,
            analysis_target="trade_fixture_c",
            analysis_period=scenario["last_period"],
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
