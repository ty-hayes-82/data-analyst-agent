"""Smoke tests for the newly added public CSV datasets."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

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


def _resolve_data_path(contract: DatasetContract) -> Path:
    data_source = contract.data_source
    if data_source is None or not data_source.file:
        pytest.skip(f"contract {contract.name} is missing data_source.file")
    path = REPO_ROOT / data_source.file
    if not path.exists():
        pytest.skip(f"data file {data_source.file} not found")
    return path


def _normalize_columns(columns: Iterable[str]) -> set[str]:
    return {c.strip().lower() for c in columns if isinstance(c, str)}


def _expected_contract_columns(contract: DatasetContract) -> set[str]:
    """Return the set of canonical columns that the CSV must contain."""
    expected: set[str] = set()

    if contract.time.column:
        expected.add(contract.time.column)

    if contract.grain and contract.grain.columns:
        expected.update(contract.grain.columns)

    expected.update(m.column for m in contract.metrics if m.column)

    expected.update(
        d.column for d in contract.dimensions if d.role in {"primary", "secondary", "time"}
    )

    return _normalize_columns(expected)


def test_covid_us_counties_dataset_loads_and_has_core_columns():
    contract = _load_contract("covid_us_counties")
    assert contract.metrics, "contract missing metrics"
    csv_path = _resolve_data_path(contract)
    df = pd.read_csv(csv_path)

    expected = _expected_contract_columns(contract)

    assert expected.issubset(_normalize_columns(df.columns)), "core contract columns missing from CSV"
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


def test_worldbank_population_dataset_loads_and_has_population():
    contract = _load_contract("worldbank_population")
    assert contract.metrics[0].name == "population"
    csv_path = _resolve_data_path(contract)
    df = pd.read_csv(csv_path)

    metric_column = contract.metrics[0].column
    assert metric_column, "population metric is missing a source column"
    country_dimension = next((d.column for d in contract.dimensions if d.role == "primary"), None)
    assert country_dimension, "contract missing a primary dimension"

    expected = _expected_contract_columns(contract)

    assert expected.issubset(_normalize_columns(df.columns)), "population columns missing from CSV"
    assert df[metric_column].astype(float).sum() > 0


def test_global_temperature_contract_and_sample_columns():
    contract = _load_contract("global_temperature")
    assert contract.metrics[0].name == "temperature_anomaly"
    csv_path = PUBLIC_DATA_ROOT / "global_temp_monthly.csv"
    assert csv_path.exists()
    df = pd.read_csv(csv_path)
    assert {contract.time.column.lower(), "source", contract.metrics[0].column.lower()}.issubset({c.lower() for c in df.columns})
    assert df[contract.metrics[0].column].astype(float).abs().max() > 0
