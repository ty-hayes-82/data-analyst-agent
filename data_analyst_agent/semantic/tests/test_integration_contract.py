"""
Integration test: Load pl_contract.yaml, build AnalysisContext from sample data.

Corresponds to task T054 in specs/001-semantic-core/tasks.md.
"""

import pytest
import pandas as pd
from pathlib import Path

from ..models import DatasetContract, AnalysisContext, QualityReport
from ..quality import DataQualityGate

# Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
CONTRACTS_DIR = PROJECT_ROOT / "contracts"
FIXTURES_DIR = PROJECT_ROOT / "tests" / "fixtures"


class TestPLContractIntegration:
    """End-to-end: load pl_contract.yaml -> validate sample data -> build context."""

    @pytest.fixture
    def pl_contract(self) -> DatasetContract:
        path = CONTRACTS_DIR / "pl_contract.yaml"
        assert path.exists(), f"pl_contract.yaml not found at {path}"
        return DatasetContract.from_yaml(str(path))

    @pytest.fixture
    def sample_pl_df(self) -> pd.DataFrame:
        path = FIXTURES_DIR / "sample_pl_data.csv"
        assert path.exists(), f"sample_pl_data.csv not found at {path}"
        return pd.read_csv(str(path))

    def test_pl_contract_loads(self, pl_contract):
        """pl_contract.yaml loads and passes schema validation."""
        assert pl_contract.name is not None
        assert pl_contract.time.column == "period"
        assert pl_contract.time.frequency == "monthly"
        assert len(pl_contract.metrics) >= 1
        assert len(pl_contract.dimensions) >= 1

    def test_pl_contract_metric_lookup(self, pl_contract):
        """Can look up the 'amount' metric by name."""
        metric = pl_contract.get_metric("amount")
        assert metric.column == "amount"
        assert metric.type == "additive"

    def test_pl_contract_dimension_lookup(self, pl_contract):
        """Can look up the 'dimension_value' dimension by name."""
        dim = pl_contract.get_dimension("dimension_value")
        assert dim.column == "dimension_value"
        assert dim.role == "primary"

    def test_quality_gate_validates_sample_data(self, pl_contract, sample_pl_df):
        """DataQualityGate passes for sample_pl_data against pl_contract."""
        gate = DataQualityGate(pl_contract)
        report = gate.validate(sample_pl_df)
        assert isinstance(report, QualityReport)
        assert report.is_valid, f"Quality gate failed: {report.errors}"

    def test_analysis_context_from_sample_data(self, pl_contract, sample_pl_df):
        """Can build an AnalysisContext from the contract and sample data."""
        gate = DataQualityGate(pl_contract)
        report = gate.validate(sample_pl_df)

        ctx = AnalysisContext(
            contract=pl_contract,
            df=sample_pl_df,
            target_metric=pl_contract.get_metric("amount"),
            primary_dimension=pl_contract.get_dimension("dimension_value"),
            quality_report=report,
            run_id="integration-test-001",
            max_drill_depth=5,
        )

        assert ctx.run_id == "integration-test-001"
        assert ctx.max_drill_depth == 5
        assert len(ctx.get_metric_data()) == len(sample_pl_df)
        assert len(ctx.get_dimension_data()) == len(sample_pl_df)
        assert len(ctx.get_time_data()) == len(sample_pl_df)

    def test_context_slice_by_dimension(self, pl_contract, sample_pl_df):
        """AnalysisContext.slice_by_dimension works for analysis target."""
        ctx = AnalysisContext(
            contract=pl_contract,
            df=sample_pl_df,
            target_metric=pl_contract.get_metric("amount"),
            primary_dimension=pl_contract.get_dimension("dimension_value"),
            run_id="integration-test-002",
        )

        sliced = ctx.slice_by_dimension("dimension_value", "067")
        assert len(sliced) > 0
        assert all(sliced["dimension_value"] == "067")


class TestOpsContractIntegration:
    """End-to-end: load ops_contract.yaml -> validate sample data -> build context."""

    @pytest.fixture
    def ops_contract(self) -> DatasetContract:
        path = CONTRACTS_DIR / "ops_contract.yaml"
        assert path.exists(), f"ops_contract.yaml not found at {path}"
        return DatasetContract.from_yaml(str(path))

    @pytest.fixture
    def sample_ops_df(self) -> pd.DataFrame:
        path = FIXTURES_DIR / "sample_ops_data.csv"
        assert path.exists(), f"sample_ops_data.csv not found at {path}"
        return pd.read_csv(str(path))

    def test_ops_contract_loads(self, ops_contract):
        """ops_contract.yaml loads and passes schema validation."""
        assert ops_contract.name == "Operational Metrics"
        assert ops_contract.time.column == "date"
        assert ops_contract.time.frequency == "daily"

    def test_ops_contract_has_metrics(self, ops_contract):
        """ops_contract has at least 3 metrics: latency, requests, error_rate."""
        assert len(ops_contract.metrics) >= 3
        latency = ops_contract.get_metric("latency")
        assert latency.optimization == "minimize"

    def test_quality_gate_validates_ops_data(self, ops_contract, sample_ops_df):
        """DataQualityGate passes for sample_ops_data against ops_contract."""
        gate = DataQualityGate(ops_contract)
        report = gate.validate(sample_ops_df)
        assert isinstance(report, QualityReport)
        assert report.is_valid, f"Quality gate failed: {report.errors}"

    def test_ops_analysis_context(self, ops_contract, sample_ops_df):
        """Can build an AnalysisContext from ops contract and sample data."""
        ctx = AnalysisContext(
            contract=ops_contract,
            df=sample_ops_df,
            target_metric=ops_contract.get_metric("latency"),
            primary_dimension=ops_contract.get_dimension("region"),
            run_id="ops-integration-test-001",
            max_drill_depth=3,
        )

        assert ctx.max_drill_depth == 3
        assert len(ctx.get_metric_data()) == len(sample_ops_df)
