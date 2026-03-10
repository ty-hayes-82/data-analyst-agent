"""Smoke tests for the enhanced public CSV datasets (v2)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from data_analyst_agent.semantic.models import DatasetContract

REPO_ROOT = Path(__file__).resolve().parents[2]
CSV_ROOT = REPO_ROOT / "config" / "datasets" / "csv"
DATA_ROOT = REPO_ROOT / "data" / "public"


def _load_contract(dataset: str) -> DatasetContract:
    path = CSV_ROOT / dataset / "contract.yaml"
    if not path.exists():
        pytest.skip(f"{dataset} contract not found")
    return DatasetContract.from_yaml(path)


def _load_csv(filename: str) -> pd.DataFrame:
    path = DATA_ROOT / filename
    if not path.exists():
        pytest.skip(f"Data file {filename} not found")
    return pd.read_csv(path)


def test_covid_us_counties_v2_has_trimmed_window():
    contract = _load_contract("covid_us_counties_v2")
    df = _load_csv("us_counties_covid_sampled.csv")
    assert df["date"].str.startswith("2022").any()
    assert contract.time.column == "period_end"
    assert len(df) >= 50000


def test_co2_global_regions_has_region_breakdown():
    contract = _load_contract("co2_global_regions")
    df = _load_csv("owid_co2_data_enriched.csv")
    assert {"region", "sub_region"}.issubset(df.columns)
    assert df["region"].nunique() >= 5
    assert df["co2"].astype(float).abs().max() > 0
    assert contract.grain.columns == ["period_end", "region", "sub_region", "country"]


def test_worldbank_population_regions_has_period_end_column():
    contract = _load_contract("worldbank_population_regions")
    df = _load_csv("worldbank_population_enriched.csv")
    assert "period_end" in df.columns
    assert df["period_end"].str.match(r"\d{4}-\d{2}-\d{2}").all()
    assert df["population"].astype(float).sum() > 0
    assert contract.time.frequency == "yearly"
