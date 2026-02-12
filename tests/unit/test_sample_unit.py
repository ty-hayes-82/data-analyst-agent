"""
Sample unit test demonstrating test infrastructure.

This file shows how to write unit tests using the fixtures and utilities.
"""

import pytest
import pandas as pd
from tests.utils.test_helpers import (
    assert_dataframe_structure,
    assert_csv_format_valid,
    assert_json_structure
)


@pytest.mark.unit
@pytest.mark.csv_mode
def test_load_test_data(mock_pl_data_df):
    """Test that we can load the PL-067 test data."""
    # Verify it's a DataFrame
    assert isinstance(mock_pl_data_df, pd.DataFrame)

    # Verify it has data
    assert len(mock_pl_data_df) > 0

    # Verify required columns exist
    assert_dataframe_structure(
        mock_pl_data_df,
        required_columns=["period", "gl_account", "amount", "cost_center"],
        min_rows=1
    )

    # Verify cost center is 067
    assert (mock_pl_data_df["cost_center"] == "67").all()

    print(f"[PASS] Loaded {len(mock_pl_data_df)} rows of test data")


@pytest.mark.unit
@pytest.mark.csv_mode
def test_load_test_data_csv_format(mock_pl_data_csv):
    """Test that we can load test data as CSV string."""
    # Verify it's valid CSV
    df = assert_csv_format_valid(mock_pl_data_csv)

    # Verify it has data
    assert len(df) > 0

    # Verify key columns
    assert "period" in df.columns
    assert "gl_account" in df.columns
    assert "amount" in df.columns

    print(f"[PASS] CSV format valid with {len(df)} rows")


@pytest.mark.unit
@pytest.mark.csv_mode
def test_ops_metrics_data(mock_ops_metrics_df):
    """Test that we can load operational metrics."""
    # Verify it's a DataFrame
    assert isinstance(mock_ops_metrics_df, pd.DataFrame)

    # Verify required columns
    assert_dataframe_structure(
        mock_ops_metrics_df,
        required_columns=["period", "miles", "stops", "loads", "cost_center"],
        min_rows=1
    )

    # Verify all numeric columns are positive
    assert (mock_ops_metrics_df["miles"] > 0).all()
    assert (mock_ops_metrics_df["stops"] > 0).all()
    assert (mock_ops_metrics_df["loads"] > 0).all()

    print(f"[PASS] Ops metrics loaded with {len(mock_ops_metrics_df)} periods")


@pytest.mark.unit
@pytest.mark.csv_mode
def test_validated_data_structure(mock_validated_pl_data_csv):
    """Test that validated data has correct structure."""
    # Parse CSV
    df = assert_csv_format_valid(mock_validated_pl_data_csv)

    # Should have P&L data columns
    assert "period" in df.columns
    assert "gl_account" in df.columns
    assert "amount" in df.columns

    # Should have ops metrics columns (joined)
    assert "miles" in df.columns
    assert "stops" in df.columns
    assert "loads" in df.columns

    # Should have hierarchy columns
    assert "canonical_category" in df.columns

    print(f"[PASS] Validated data has {len(df)} rows with correct structure")


@pytest.mark.unit
def test_date_ranges_fixture(mock_date_ranges):
    """Test that date ranges fixture works correctly."""
    # Verify required keys
    assert_json_structure(
        mock_date_ranges,
        required_keys=[
            "pl_query_start_date",
            "pl_query_end_date",
            "ops_metrics_query_start_date",
            "ops_metrics_query_end_date",
            "order_query_start_date",
            "order_query_end_date",
        ]
    )

    # Verify format (YYYY-MM)
    import re
    date_pattern = re.compile(r"^\d{4}-\d{2}$")

    for key, value in mock_date_ranges.items():
        assert date_pattern.match(value), f"{key} has invalid format: {value}"

    print(f"[PASS] Date ranges valid: {mock_date_ranges['pl_query_start_date']} to {mock_date_ranges['pl_query_end_date']}")


@pytest.mark.unit
def test_mock_session_fixture(mock_session):
    """Test that mock session fixture works correctly."""
    # Verify session has required attributes
    assert hasattr(mock_session, "session_id")
    assert hasattr(mock_session, "state")

    # Verify state is a dict
    assert isinstance(mock_session.state, dict)

    print(f"[PASS] Mock session created with ID: {mock_session.session_id}")


@pytest.mark.unit
def test_populated_session_state(populated_session_state):
    """Test that populated session state has all required data."""
    # Verify it's a mock session
    assert hasattr(populated_session_state, "state")

    state = populated_session_state.state

    # Verify required keys
    assert "cost_center" in state
    assert "current_cost_center" in state
    assert "pl_data_csv" in state
    assert "ops_metrics_csv" in state
    assert "validated_pl_data_csv" in state

    # Verify cost center
    assert state["cost_center"] == "067"

    # Verify data is CSV format
    assert_csv_format_valid(state["pl_data_csv"])
    assert_csv_format_valid(state["ops_metrics_csv"])
    assert_csv_format_valid(state["validated_pl_data_csv"])

    print(f"[PASS] Session state populated for cost center: {state['cost_center']}")


@pytest.mark.unit
def test_temp_output_dir(temp_output_dir):
    """Test that temp output directory is created."""
    # Verify it exists
    assert temp_output_dir.exists()

    # Verify it's a directory
    assert temp_output_dir.is_dir()

    # Test we can write to it
    test_file = temp_output_dir / "test.txt"
    test_file.write_text("test content")

    assert test_file.exists()
    assert test_file.read_text() == "test content"

    print(f"[PASS] Temp directory created: {temp_output_dir}")


@pytest.mark.unit
def test_chart_of_accounts_fixture(mock_chart_of_accounts):
    """Test that chart of accounts fixture is structured correctly."""
    # Verify it's a dict
    assert isinstance(mock_chart_of_accounts, dict)

    # Verify it has GL accounts
    assert len(mock_chart_of_accounts) > 0

    # Verify structure of one GL account
    for gl, metadata in mock_chart_of_accounts.items():
        assert "description" in metadata
        assert "canonical_category" in metadata
        assert "level_1" in metadata
        assert "level_2" in metadata
        assert "level_3" in metadata
        assert "level_4" in metadata
        break  # Just check first one

    print(f"[PASS] Chart of accounts has {len(mock_chart_of_accounts)} GL accounts")


if __name__ == "__main__":
    # Allow running this file directly for quick testing
    pytest.main([__file__, "-v", "-s"])
