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
