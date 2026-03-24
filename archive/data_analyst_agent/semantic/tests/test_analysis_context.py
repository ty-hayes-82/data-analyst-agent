import pytest
import pandas as pd
from data_analyst_agent.semantic.models import DatasetContract, AnalysisContext
import os

FIX_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../tests/fixtures"))

@pytest.fixture
def sample_context():
    contract_path = os.path.join(FIX_DIR, "minimal_contract.yaml")
    contract = DatasetContract.from_yaml(contract_path)
    
    df = pd.DataFrame({
        "date": ["2025-01-01", "2025-01-02"],
        "category_name": ["A", "B"],
        "row_count": [10, 20]
    })
    
    return AnalysisContext(
        contract=contract,
        df=df,
        target_metric=contract.get_metric("count"),
        primary_dimension=contract.get_dimension("category"),
        run_id="test-run-123"
    )

def test_context_initialization(sample_context):
    assert sample_context.run_id == "test-run-123"
    assert sample_context.max_drill_depth == 3

def test_semantic_accessors(sample_context):
    metric_data = sample_context.get_metric_data()
    assert list(metric_data) == [10, 20]
    
    dim_data = sample_context.get_dimension_data()
    assert list(dim_data) == ["A", "B"]
    
    time_data = sample_context.get_time_data()
    assert list(time_data) == ["2025-01-01", "2025-01-02"]

def test_slice_by_dimension(sample_context):
    sliced_df = sample_context.slice_by_dimension("category", "A")
    assert len(sliced_df) == 1
    assert sliced_df["row_count"].iloc[0] == 10

def test_context_immutability(sample_context):
    from pydantic import ValidationError
    with pytest.raises(Exception): # Pydantic v2 frozen models raise ValidationError or AttributeError
        sample_context.run_id = "new-id"
