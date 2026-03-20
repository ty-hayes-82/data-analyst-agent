import json
from pathlib import Path

import pandas as pd
import pytest

from data_analyst_agent.semantic.models import AnalysisContext, DatasetContract
from data_analyst_agent.sub_agents.data_cache import clear_all_caches, set_analysis_context
from data_analyst_agent.sub_agents.statistical_insights_agent.tools.compute_period_over_period_changes import (
    compute_period_over_period_changes,
)


REPO_ROOT = Path(__file__).resolve().parents[2]




@pytest.fixture(autouse=True)
def _reset_data_cache():
    clear_all_caches()
    yield
    clear_all_caches()

def _load_contract(dataset: str) -> DatasetContract:
    contract_path = REPO_ROOT / "config" / "datasets" / "csv" / dataset / "contract.yaml"
    if not contract_path.exists():
        pytest.skip(f"contract for {dataset} not present in this workspace")
    return DatasetContract.from_yaml(str(contract_path))


def _prime_context(contract: DatasetContract, df: pd.DataFrame, metric_name: str, dimension_name: str) -> None:
    clear_all_caches()
    ctx = AnalysisContext(
        contract=contract,
        df=df,
        target_metric=contract.get_metric(metric_name),
        primary_dimension=contract.get_dimension(dimension_name),
        run_id=f"test_{contract.name}",
        max_drill_depth=contract.reporting.max_drill_depth,
        temporal_grain=contract.time.frequency,
        time_frequency=contract.time.frequency,
    )
    set_analysis_context(ctx)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_trade_data_validation_overlays_are_contract_driven():
    contract = _load_contract("trade_data")
    df = pd.DataFrame(
        {
            "period_end": ["2024-01-07", "2024-01-14", "2024-01-21", "2024-01-28"],
            "trade_value_usd": [10_000_000, 12_000_000, 9_500_000, 11_000_000],
            "flow": ["imports"] * 4,
            "anomaly_flag": [1, "0", "true", "false"],
            "scenario_id": ["A1", None, "A1", None],
        }
    )
    _prime_context(contract, df, metric_name="trade_value_usd", dimension_name="flow")

    result = json.loads(await compute_period_over_period_changes())

    assert result["time_col"] == contract.time.column
    assert result["metric_col"] == contract.metrics[0].column
    assert "avg_anomaly_value" in result

    overlays = result.get("validation_overlays")
    assert overlays and "scenario_summaries" in overlays
    summaries = overlays["scenario_summaries"]
    assert len(summaries) == 1
    summary = summaries[0]
    assert summary["scenario_id"] == "A1"
    assert summary["row_count"] == 2
    assert summary["metadata"]["severity"].lower() == "high"
    assert summary["share_of_metric_pct"] > 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_public_dataset_without_validation_columns():
    contract = _load_contract("global_temperature")
    df = pd.DataFrame(
        {
            "Year": ["2020-01", "2020-02", "2020-03"],
            "Source": ["gcag", "gcag", "gcag"],
            "Mean": [0.5, 0.55, 0.6],
        }
    )
    _prime_context(contract, df, metric_name="temperature_anomaly", dimension_name="temperature_source")

    result = json.loads(await compute_period_over_period_changes())

    assert result["time_col"] == contract.time.column
    assert result["metric_col"] == contract.metrics[0].column
    assert "avg_anomaly_value" not in result
    assert "validation_overlays" not in result
    assert result["latest_value"] == pytest.approx(0.6)
    assert result["prior_value"] == pytest.approx(0.55)
    assert result["pct_change"] == pytest.approx(((0.6 - 0.55) / 0.55) * 100.0)
