import pytest
from data_analyst_agent.semantic.models import DatasetContract
from pydantic import ValidationError
import os

# Helper to get absolute path to fixtures
FIX_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../tests/fixtures"))

def test_load_minimal_contract():
    path = os.path.join(FIX_DIR, "minimal_contract.yaml")
    contract = DatasetContract.from_yaml(path)
    
    assert contract.name == "Minimal Generic Dataset"
    assert contract.time.frequency == "daily"
    assert len(contract.metrics) == 1
    assert contract.metrics[0].name == "count"
    assert contract.get_metric("count").column == "row_count"

def test_invalid_contract_fails():
    path = os.path.join(FIX_DIR, "invalid_contract.yaml")
    with pytest.raises(ValidationError) as excinfo:
        DatasetContract.from_yaml(path)
    
    # Verify specific validation errors
    errors = str(excinfo.value)
    assert "time" in errors  # Missing field
    assert "not_a_valid_role" in errors # Invalid enum

def test_contract_metric_lookup():
    path = os.path.join(FIX_DIR, "minimal_contract.yaml")
    contract = DatasetContract.from_yaml(path)
    
    metric = contract.get_metric("count")
    assert metric.column == "row_count"
    
    with pytest.raises(KeyError):
        contract.get_metric("non_existent")

def test_contract_dimension_lookup():
    path = os.path.join(FIX_DIR, "minimal_contract.yaml")
    contract = DatasetContract.from_yaml(path)
    
    dim = contract.get_dimension("category")
    assert dim.column == "category_name"
    
    with pytest.raises(KeyError):
        contract.get_dimension("non_existent")
