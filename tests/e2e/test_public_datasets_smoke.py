"""Smoke tests for the newly added public CSV datasets."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from data_analyst_agent.semantic.models import DatasetContract

REPO_ROOT = Path(__file__).resolve().parents[2]
CSV_CONFIG_ROOT = REPO_ROOT / "config" / "datasets" / "csv"
PUBLIC_DATA_ROOT = REPO_ROOT / "data" / "public"


def _contract_path(dataset: str) -> Path:
    path = CSV_CONFIG_ROOT / dataset / "contract.yaml"
    if not path.exists():
        pytest.skip(f"contract for {dataset} not present in this workspace")
    return path


def _load_contract(dataset: str) -> DatasetContract:
    return DatasetContract.from_yaml(_contract_path(dataset))


def test_covid_us_counties_contract_and_sample_columns():
    contract = _load_contract("covid_us_counties")
    assert contract.metrics, "contract missing metrics"
    csv_path = PUBLIC_DATA_ROOT / "us_counties_covid_sampled.csv"
    assert csv_path.exists()
    df = pd.read_csv(csv_path)
    expected = {contract.time.column, "state", "county", "cases", "deaths"}
    assert expected.issubset({c.lower() for c in df.columns})
    assert len(df) > 10_000


def test_owid_co2_emissions_contract_and_sample_columns():
    contract = _load_contract("owid_co2_emissions")
    metric_names = {m.name for m in contract.metrics}
    assert {"co2", "coal_co2", "gas_co2", "oil_co2"}.issubset(metric_names)
    csv_path = PUBLIC_DATA_ROOT / "owid_co2_data.csv"
    assert csv_path.exists()
    df = pd.read_csv(csv_path)
    assert {"country", contract.time.column.lower(), "co2"}.issubset({c.lower() for c in df.columns})
    assert df["co2"].astype(float).abs().max() > 0


def test_worldbank_population_contract_and_sample_columns():
    contract = _load_contract("worldbank_population")
    assert contract.metrics[0].name == "population"
    csv_path = PUBLIC_DATA_ROOT / "worldbank_population.csv"
    assert csv_path.exists()
    df = pd.read_csv(csv_path)
    expected = {contract.time.column.lower(), contract.metrics[0].column.lower(), contract.dimensions[0].column.lower()}
    assert expected.issubset({c.lower() for c in df.columns})
    assert df[contract.metrics[0].column].astype(float).sum() > 0


def test_global_temperature_contract_and_sample_columns():
    contract = _load_contract("global_temperature")
    assert contract.metrics[0].name == "temperature_anomaly"
    csv_path = PUBLIC_DATA_ROOT / "global_temp_monthly.csv"
    assert csv_path.exists()
    df = pd.read_csv(csv_path)
    assert {contract.time.column.lower(), "source", contract.metrics[0].column.lower()}.issubset({c.lower() for c in df.columns})
    assert df[contract.metrics[0].column].astype(float).abs().max() > 0
