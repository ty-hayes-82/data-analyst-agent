"""
Ops Metrics contract fixture helpers.

Provides utilities for loading ops metrics contract, creating matching
DataFrames, and building AnalysisContext instances for testing.
"""

import pandas as pd
import numpy as np
from pathlib import Path
from typing import Optional

from tests.utils.dataset_paths import resolve_dataset_file

PROJECT_ROOT = Path(__file__).parent.parent.parent
DATASETS_DIR = PROJECT_ROOT / "config" / "datasets"
DATA_DIR = PROJECT_ROOT / "data"


class OpsMetricsTestDataLoader:
    """Loads and manages ops metrics test data."""

    def __init__(self):
        resolved_contract = resolve_dataset_file("ops_metrics")
        default_contract = DATASETS_DIR / "ops_metrics" / "contract.yaml"
        self.contract_path = resolved_contract if resolved_contract else default_contract
        self.line_haul_csv_path = DATA_DIR / "ops_metrics_line_haul_sample.csv"
        self.cc067_csv_path = DATA_DIR / "ops_metrics_067_sample.csv"

    def load_contract(self):
        """Load the ops_metrics_contract as a DatasetContract."""
        from data_analyst_agent.semantic.models import DatasetContract

        if not self.contract_path.exists():
            raise FileNotFoundError(f"Ops metrics contract not found: {self.contract_path}")
        return DatasetContract.from_yaml(str(self.contract_path))

    def load_line_haul_df(self) -> pd.DataFrame:
        """Load the Line Haul sample CSV."""
        if not self.line_haul_csv_path.exists():
            raise FileNotFoundError(f"Sample data not found: {self.line_haul_csv_path}")
        return pd.read_csv(self.line_haul_csv_path)

    def load_cc067_df(self) -> pd.DataFrame:
        """Load the CC 067 sample CSV."""
        if not self.cc067_csv_path.exists():
            raise FileNotFoundError(f"Sample data not found: {self.cc067_csv_path}")
        return pd.read_csv(self.cc067_csv_path)

    def build_analysis_context(
        self,
        df: Optional[pd.DataFrame] = None,
        target_metric_name: str = "total_revenue",
        primary_dimension_name: str = "lob",
        max_drill_depth: int = 3,
    ):
        """
        Build an AnalysisContext from the ops metrics contract and sample data.

        Args:
            df: DataFrame to use. Defaults to line_haul_sample.
            target_metric_name: Target metric name from contract.
            primary_dimension_name: Primary dimension name from contract.
            max_drill_depth: Maximum drill-down depth.

        Returns:
            AnalysisContext instance.
        """
        from data_analyst_agent.semantic.models import AnalysisContext

        contract = self.load_contract()
        if df is None:
            df = self.load_line_haul_df()

        return AnalysisContext(
            contract=contract,
            df=df,
            target_metric=contract.get_metric(target_metric_name),
            primary_dimension=contract.get_dimension(primary_dimension_name),
            run_id="test-ops-metrics-fixture",
            max_drill_depth=max_drill_depth,
        )

    def generate_synthetic_ops_data(
        self,
        periods: int = 14,
        lobs: Optional[list] = None,
        terminals: Optional[list] = None,
        driver_leaders: Optional[list] = None,
    ) -> pd.DataFrame:
        """
        Generate synthetic ops metrics data matching the contract schema.

        Useful when the real sample CSVs are not available.
        """
        if lobs is None:
            lobs = ["Line Haul", "Dedicated"]
        if terminals is None:
            terminals = ["Phoenix", "Dallas", "Chicago"]
        if driver_leaders is None:
            driver_leaders = ["MGR01", "MGR02", "MGR03"]

        period_range = pd.date_range(start="2024-01", periods=periods, freq="MS")
        periods_str = period_range.strftime("%Y-%m").tolist()

        rng = np.random.default_rng(42)
        rows = []
        for period in periods_str:
            for lob in lobs:
                terminal = rng.choice(terminals)
                leader = rng.choice(driver_leaders)
                rows.append({
                    "cal_dt": period,
                    "ops_ln_of_bus_ref_nm": lob,
                    "gl_div_nm": terminal,
                    "drvr_mgr_cd": leader,
                    "icc_cst_ctr_cd": "067",
                    "ttl_rev_amt": float(rng.integers(400_000, 700_000)),
                    "lh_rev_amt": float(rng.integers(300_000, 550_000)),
                    "ld_trf_mi": float(rng.integers(100_000, 200_000)),
                    "empty_trf_mi": float(rng.integers(10_000, 30_000)),
                    "ordr_cnt": float(rng.integers(500, 1200)),
                    "stop_count": float(rng.integers(1000, 2000)),
                    "truck_count": float(rng.integers(100, 250)),
                    "dot_ocrnce_cnt": float(rng.integers(0, 5)),
                })

        return pd.DataFrame(rows)


# Singleton instance
_loader = OpsMetricsTestDataLoader()


def load_ops_contract():
    """Convenience: load the ops_metrics contract."""
    return _loader.load_contract()


def load_ops_line_haul_df() -> pd.DataFrame:
    """Convenience: load line haul sample DataFrame."""
    return _loader.load_line_haul_df()


def load_ops_cc067_df() -> pd.DataFrame:
    """Convenience: load CC 067 sample DataFrame."""
    return _loader.load_cc067_df()


def build_ops_analysis_context(**kwargs):
    """Convenience: build an AnalysisContext."""
    return _loader.build_analysis_context(**kwargs)


def generate_synthetic_ops_data(**kwargs) -> pd.DataFrame:
    """Convenience: generate synthetic ops data."""
    return _loader.generate_synthetic_ops_data(**kwargs)
