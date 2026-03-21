"""Smoke tests for the ops_metrics_weekly Tableau dataset."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from data_analyst_agent.semantic.models import DatasetContract

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = REPO_ROOT / "config" / "datasets" / "tableau" / "ops_metrics_weekly" / "contract.yaml"
TDSX_PATH = REPO_ROOT / "data" / "tableau" / "Ops Metrics Weekly Scorecard.tdsx"


@pytest.fixture(scope="module")
def ops_metrics_contract() -> DatasetContract:
    """Load the ops_metrics_weekly contract."""
    if not CONTRACT_PATH.exists():
        pytest.skip(f"Contract not found: {CONTRACT_PATH}")
    return DatasetContract.from_yaml(str(CONTRACT_PATH))


@pytest.fixture(scope="module")
def ops_metrics_df(ops_metrics_contract: DatasetContract) -> pd.DataFrame:
    """Load the ops_metrics_weekly DataFrame from Tableau extract."""
    if not TDSX_PATH.exists():
        pytest.skip(f"TDSX file not found: {TDSX_PATH}")
    
    # Use the Tableau Hyper loading infrastructure
    try:
        from data_analyst_agent.sub_agents.tableau_hyper_fetcher.loader_config import HyperLoaderConfig
        from data_analyst_agent.sub_agents.tableau_hyper_fetcher.hyper_connection import get_or_create_manager
        from data_analyst_agent.sub_agents.tableau_hyper_fetcher.query_builder import HyperQueryBuilder
        
        # Load the loader config for the dataset
        loader_config_path = REPO_ROOT / "config" / "datasets" / "tableau" / "ops_metrics_weekly" / "loader.yaml"
        if not loader_config_path.exists():
            pytest.skip(f"Loader config not found: {loader_config_path}")
        
        import yaml
        with open(loader_config_path, "r") as f:
            loader_raw = yaml.safe_load(f) or {}
        
        loader_config = HyperLoaderConfig(**loader_raw)
        
        # Create a manager and extract the Hyper file
        manager = get_or_create_manager("ops_metrics_weekly", loader_config)
        manager.ensure_extracted(REPO_ROOT)
        
        # Build and execute a simple query to load all data
        builder = HyperQueryBuilder(loader_config)
        sql = builder.build_query(date_start=None, date_end=None, filters={})
        
        df = manager.execute_query(sql)
        return df
        
    except ImportError as e:
        pytest.skip(f"Tableau Hyper API not available: {e}")
    except Exception as e:
        pytest.fail(f"Failed to load Tableau extract: {e}")


def test_contract_loads_successfully(ops_metrics_contract: DatasetContract):
    """Verify the contract loads and has expected metadata."""
    assert ops_metrics_contract.name == "ops_metrics_weekly"
    assert ops_metrics_contract.display_name == "Ops Metrics Weekly Scorecard"
    assert ops_metrics_contract.data_source is not None
    assert ops_metrics_contract.data_source.type == "tableau_hyper"


def test_expected_columns_exist(ops_metrics_df: pd.DataFrame):
    """Verify critical columns exist in the dataset."""
    expected_columns = {
        "cal_dt",
        "gl_rgn_nm",
        "gl_div_nm",
        "ttl_rev_amt",
        "ordr_cnt",
    }
    
    df_columns = {col.lower() for col in ops_metrics_df.columns}
    
    for col in expected_columns:
        assert col.lower() in df_columns, f"Expected column '{col}' not found in dataset"


def test_dataframe_not_empty(ops_metrics_df: pd.DataFrame):
    """Verify the DataFrame has data."""
    assert len(ops_metrics_df) > 0, "DataFrame is empty"
    assert ops_metrics_df.shape[0] > 100, f"Dataset only has {ops_metrics_df.shape[0]} rows, expected more"


def test_time_column_parses_correctly(
    ops_metrics_contract: DatasetContract,
    ops_metrics_df: pd.DataFrame
):
    """Verify the time column can be parsed and contains valid dates."""
    time_col = ops_metrics_contract.time.column
    
    assert time_col in ops_metrics_df.columns, f"Time column '{time_col}' not found"
    
    # Try parsing the time column (handle Tableau Date objects)
    try:
        # Convert Tableau Date objects to strings first if needed
        time_series = ops_metrics_df[time_col]
        
        # Check if we have Tableau Date objects
        try:
            from tableauhyperapi import Date as HyperDate
            if isinstance(time_series.iloc[0], HyperDate):
                # Convert Tableau Date objects to strings
                time_series = time_series.apply(lambda d: str(d) if d is not None else None)
        except (ImportError, IndexError):
            pass
        
        parsed_dates = pd.to_datetime(time_series, errors="coerce")
        assert parsed_dates.notna().sum() > 0, "No valid dates parsed"
        
        # Verify dates are in reasonable range (not all nulls or defaults)
        assert parsed_dates.min() < parsed_dates.max(), "All dates are the same"
        
    except Exception as e:
        pytest.fail(f"Failed to parse time column '{time_col}': {e}")


def test_geographic_hierarchy_exists(ops_metrics_df: pd.DataFrame):
    """Verify the gl_rgn_nm → gl_div_nm hierarchy relationship exists."""
    
    # Check columns exist
    assert "gl_rgn_nm" in ops_metrics_df.columns, "gl_rgn_nm column missing"
    assert "gl_div_nm" in ops_metrics_df.columns, "gl_div_nm column missing"
    
    # Group by region to verify divisions nest under regions
    hierarchy_check = ops_metrics_df.groupby("gl_rgn_nm")["gl_div_nm"].nunique()
    
    # Should have at least one region with divisions
    assert hierarchy_check.sum() > 0, "No geographic hierarchy found"
    
    # At least one region should have multiple divisions
    assert hierarchy_check.max() > 1, "No multi-division regions found"


def test_metric_columns_are_numeric(ops_metrics_df: pd.DataFrame):
    """Verify key metric columns contain numeric data."""
    metric_columns = ["ttl_rev_amt", "ordr_cnt"]
    
    for col in metric_columns:
        assert col in ops_metrics_df.columns, f"Metric column '{col}' not found"
        
        # Try converting to numeric
        try:
            numeric_series = pd.to_numeric(ops_metrics_df[col], errors="coerce")
            valid_count = numeric_series.notna().sum()
            
            assert valid_count > 0, f"Column '{col}' has no valid numeric values"
            
            # At least 90% of values should be numeric
            valid_pct = valid_count / len(ops_metrics_df)
            assert valid_pct > 0.9, f"Column '{col}' only {valid_pct:.1%} numeric"
            
        except Exception as e:
            pytest.fail(f"Failed to validate numeric column '{col}': {e}")


def test_contract_metrics_defined(ops_metrics_contract: DatasetContract):
    """Verify the contract defines expected metrics."""
    metric_names = {m.name for m in ops_metrics_contract.metrics}
    
    expected_metrics = {
        "ttl_rev_amt",
        "lh_rev_amt",
        "ordr_cnt",
        "truck_count",
    }
    
    assert expected_metrics.issubset(metric_names), \
        f"Missing metrics: {expected_metrics - metric_names}"


def test_contract_hierarchies_defined(ops_metrics_contract: DatasetContract):
    """Verify the contract defines hierarchies."""
    assert ops_metrics_contract.hierarchies, "No hierarchies defined in contract"
    
    hierarchy_names = {h.name for h in ops_metrics_contract.hierarchies}
    
    assert "geographic" in hierarchy_names, "Geographic hierarchy missing"
    assert "business_line" in hierarchy_names, "Business line hierarchy missing"
