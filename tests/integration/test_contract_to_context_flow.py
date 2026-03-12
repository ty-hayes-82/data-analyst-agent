"""
Integration tests for the contract-to-analysis-context flow (Spec 001 + 003).

Tests:
- All available dataset contracts load and validate
- AnalysisContext initialises correctly with ops data (when dataset present)
- Semantic accessors (metric data, dimension data, time data)
- slice_by_dimension
- DatasetContract.capabilities
"""

import pytest
import pandas as pd
from pathlib import Path


PROJECT_ROOT = Path(__file__).parent.parent.parent
DATASETS_DIR = PROJECT_ROOT / "config" / "datasets"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.ops_metrics
def test_ops_contract_loads_and_validates(ops_metrics_contract):
    """ops_metrics_contract.yaml loads without errors."""
    assert ops_metrics_contract.name == "Ops Metrics"
    assert ops_metrics_contract.version >= "2.0.0"  # bumped to 2.1.0 in spec 010
    assert len(ops_metrics_contract.metrics) >= 8
    assert len(ops_metrics_contract.dimensions) >= 5
    assert len(ops_metrics_contract.hierarchies) >= 2


@pytest.mark.integration
def test_account_research_contract_loads(account_research_contract):
    """account_research_contract.yaml loads without errors."""
    assert account_research_contract.name == "Account Research"
    assert len(account_research_contract.metrics) >= 1
    assert len(account_research_contract.dimensions) >= 4


@pytest.mark.integration
def test_all_contracts_loadable():
    """Every dataset folder under config/datasets/ should have a loadable contract.yaml."""
    from data_analyst_agent.semantic.models import DatasetContract

    contract_files = list(DATASETS_DIR.glob("**/contract.yaml"))
    assert contract_files, "No dataset contract files found under config/datasets/"

    for path in contract_files:
        contract = DatasetContract.from_yaml(str(path))
        assert contract.name, f"Contract in {path.parent.name} has no name"
        assert len(contract.metrics) > 0, f"Contract {path.parent.name} has no metrics"
        assert len(contract.dimensions) > 0, f"Contract {path.parent.name} has no dimensions"


@pytest.mark.integration
@pytest.mark.ops_metrics
def test_analysis_context_from_ops_contract(ops_metrics_analysis_context):
    """AnalysisContext should initialise correctly with ops data."""
    ctx = ops_metrics_analysis_context

    assert ctx.run_id == "test-ops-metrics"
    assert ctx.contract.name == "Ops Metrics"
    assert ctx.target_metric.name == "total_revenue"
    assert ctx.primary_dimension.name == "lob"
    assert ctx.max_drill_depth == 3
    assert len(ctx.df) > 0


@pytest.mark.integration
@pytest.mark.ops_metrics
def test_context_semantic_accessors(ops_metrics_analysis_context):
    """Semantic accessors should return correct Series from the DataFrame."""
    ctx = ops_metrics_analysis_context

    # Skip if the sample DataFrame uses P&L format (missing ops metrics columns)
    if ctx.target_metric.column and ctx.target_metric.column not in ctx.df.columns:
        pytest.skip(
            f"Sample DataFrame does not contain ops metrics column "
            f"'{ctx.target_metric.column}' — use ops_metrics_line_haul_sample.csv."
        )

    # Metric data
    metric_data = ctx.get_metric_data()
    assert len(metric_data) == len(ctx.df)
    assert metric_data.name == ctx.target_metric.column

    # Dimension data
    dim_col = ctx.primary_dimension.column
    if dim_col not in ctx.df.columns:
        pytest.skip(f"Sample DataFrame does not contain dimension column '{dim_col}'.")
    dim_data = ctx.get_dimension_data()
    assert len(dim_data) == len(ctx.df)

    # Time data
    time_col = ctx.contract.time.column
    if time_col not in ctx.df.columns:
        pytest.skip(f"Sample DataFrame does not contain time column '{time_col}'.")
    time_data = ctx.get_time_data()
    assert len(time_data) == len(ctx.df)


@pytest.mark.integration
@pytest.mark.ops_metrics
def test_context_slice_by_dimension(ops_metrics_analysis_context):
    """slice_by_dimension should filter rows correctly."""
    ctx = ops_metrics_analysis_context

    # The CC 067 sample data should all be "Line Haul" for the lob dimension
    lob_col = ctx.primary_dimension.column  # ops_ln_of_bus_ref_nm

    if lob_col not in ctx.df.columns:
        pytest.skip(
            f"Sample DataFrame does not contain LOB column '{lob_col}'. "
            "The ops_metrics_067_sample.csv uses P&L format; "
            "use ops_metrics_line_haul_sample.csv for full ops accessors."
        )
    unique_lobs = ctx.df[lob_col].unique()

    if len(unique_lobs) == 0:
        pytest.skip("No LOB values in sample data")

    first_lob = unique_lobs[0]
    sliced = ctx.slice_by_dimension("lob", first_lob)

    assert len(sliced) > 0
    assert all(sliced[lob_col] == first_lob)


@pytest.mark.integration
@pytest.mark.ops_metrics
def test_ops_contract_capabilities(ops_metrics_contract):
    """Contract.capabilities should include hierarchy and PVM flags."""
    caps = ops_metrics_contract.capabilities

    assert "hierarchical_drill_down" in caps, (
        "ops_metrics has hierarchies, so hierarchical_drill_down should be a capability"
    )
    assert "pvm_decomposition" in caps, (
        "ops_metrics has pvm_role tags, so pvm_decomposition should be a capability"
    )


@pytest.mark.integration
@pytest.mark.ops_metrics
def test_ops_contract_metric_lookup(ops_metrics_contract):
    """get_metric and get_dimension should resolve by name."""
    metric = ops_metrics_contract.get_metric("total_revenue")
    assert metric.column == "total_revenue"
    # pvm_role removed from contract in v2.1

    dim = ops_metrics_contract.get_dimension("terminal")
    assert dim.column == "terminal"
    assert dim.role == "secondary"

    with pytest.raises(KeyError):
        ops_metrics_contract.get_metric("non_existent_metric")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
