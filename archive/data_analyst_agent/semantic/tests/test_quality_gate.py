import pytest
import pandas as pd
from data_analyst_agent.semantic.models import DatasetContract
from data_analyst_agent.semantic.quality import DataQualityGate
import os

FIX_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../tests/fixtures"))

@pytest.fixture
def contract():
    path = os.path.join(FIX_DIR, "minimal_contract.yaml")
    return DatasetContract.from_yaml(path)

@pytest.fixture
def gate(contract):
    return DataQualityGate(contract)

def test_quality_gate_success(gate):
    df = pd.DataFrame({
        "date": ["2025-01-01", "2025-01-02"],
        "category_name": ["A", "B"],
        "row_count": [10, 20]
    })
    report = gate.validate(df)
    assert report.is_valid is True
    assert report.checks["schema_validation"] is True
    assert report.checks["grain_uniqueness"] is True

def test_quality_gate_missing_column(gate):
    df = pd.DataFrame({
        "date": ["2025-01-01"],
        "category_name": ["A"]
        # row_count is missing
    })
    report = gate.validate(df)
    assert report.is_valid is False
    assert "Missing required columns" in report.errors[0]

def test_quality_gate_duplicate_grain(gate):
    df = pd.DataFrame({
        "date": ["2025-01-01", "2025-01-01"],
        "category_name": ["A", "A"],
        "row_count": [10, 20]
    })
    report = gate.validate(df)
    assert report.is_valid is False
    assert "duplicate rows" in report.errors[0]

def test_quality_gate_non_numeric_metric(gate):
    df = pd.DataFrame({
        "date": ["2025-01-01"],
        "category_name": ["A"],
        "row_count": ["not-a-number"]
    })
    report = gate.validate(df)
    assert report.is_valid is False
    assert "not numeric" in report.errors[0]
