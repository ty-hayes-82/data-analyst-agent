"""
Test helper utilities for Data Analyst Agent testing.

Provides common functions for:
- Mock data generation
- Assertion helpers
- Test result validation
- File comparison
"""

import pandas as pd
import numpy as np
import json
from typing import Any, Dict, List
from pathlib import Path
import difflib


def generate_mock_pl_data(
    cost_center: str,
    periods: int = 24,
    gl_accounts: List[str] = None
) -> pd.DataFrame:
    """
    Generate mock P&L data for testing.

    Args:
        cost_center: Cost center ID
        periods: Number of monthly periods
        gl_accounts: List of GL account codes

    Returns:
        DataFrame with P&L data
    """
    if gl_accounts is None:
        gl_accounts = ["5010", "5020", "5030", "6010", "6020"]

    period_range = pd.date_range(start="2023-01", periods=periods, freq="MS")
    periods_str = period_range.strftime("%Y-%m")

    data = []
    for period in periods_str:
        for gl in gl_accounts:
            # Generate realistic amounts
            base_amount = 50000 if gl.startswith("5") else 40000
            variance = np.random.randint(-10000, 10000)
            amount = base_amount + variance

            data.append({
                "period": period,
                "gl_account": gl,
                "amount": float(amount),
                "dimension_value": cost_center
            })

    return pd.DataFrame(data)


def generate_mock_ops_metrics(
    cost_center: str,
    periods: int = 24
) -> pd.DataFrame:
    """
    Generate mock operational metrics for testing.

    Args:
        cost_center: Cost center ID
        periods: Number of monthly periods

    Returns:
        DataFrame with operational metrics
    """
    period_range = pd.date_range(start="2023-01", periods=periods, freq="MS")
    periods_str = period_range.strftime("%Y-%m")

    data = []
    for period in periods_str:
        data.append({
            "period": period,
            "miles": float(np.random.randint(80000, 120000)),
            "stops": float(np.random.randint(2000, 4000)),
            "loads": float(np.random.randint(1500, 3500)),
            "dimension_value": cost_center
        })

    return pd.DataFrame(data)


def assert_dataframe_structure(
    df: pd.DataFrame,
    required_columns: List[str],
    min_rows: int = 1
) -> None:
    """
    Assert that a DataFrame has the required structure.

    Args:
        df: DataFrame to validate
        required_columns: List of required column names
        min_rows: Minimum number of rows expected

    Raises:
        AssertionError: If validation fails
    """
    assert isinstance(df, pd.DataFrame), "Input must be a pandas DataFrame"
    assert len(df) >= min_rows, f"Expected at least {min_rows} rows, got {len(df)}"

    missing_columns = set(required_columns) - set(df.columns)
    assert not missing_columns, f"Missing required columns: {missing_columns}"


def assert_json_structure(
    data: Dict[str, Any],
    required_keys: List[str]
) -> None:
    """
    Assert that a JSON object has the required keys.

    Args:
        data: Dictionary to validate
        required_keys: List of required keys

    Raises:
        AssertionError: If validation fails
    """
    assert isinstance(data, dict), "Input must be a dictionary"

    missing_keys = set(required_keys) - set(data.keys())
    assert not missing_keys, f"Missing required keys: {missing_keys}"


def assert_csv_format_valid(csv_string: str) -> pd.DataFrame:
    """
    Assert that a string is valid CSV and return as DataFrame.

    Args:
        csv_string: CSV string to validate

    Returns:
        DataFrame parsed from CSV

    Raises:
        AssertionError: If CSV is invalid
    """
    try:
        df = pd.read_csv(pd.io.common.StringIO(csv_string))
        assert len(df) > 0, "CSV is empty"
        return df
    except Exception as e:
        raise AssertionError(f"Invalid CSV format: {e}")


def assert_json_format_valid(json_string: str) -> Dict[str, Any]:
    """
    Assert that a string is valid JSON and return as dict.

    Args:
        json_string: JSON string to validate

    Returns:
        Dictionary parsed from JSON

    Raises:
        AssertionError: If JSON is invalid
    """
    try:
        data = json.loads(json_string)
        assert isinstance(data, (dict, list)), "JSON must be object or array"
        return data
    except Exception as e:
        raise AssertionError(f"Invalid JSON format: {e}")


def assert_variance_calculated_correctly(
    current_value: float,
    prior_value: float,
    expected_variance_pct: float,
    tolerance: float = 0.01
) -> None:
    """
    Assert that variance percentage is calculated correctly.

    Args:
        current_value: Current period value
        prior_value: Prior period value
        expected_variance_pct: Expected variance percentage
        tolerance: Tolerance for floating point comparison

    Raises:
        AssertionError: If variance is incorrect
    """
    if prior_value == 0:
        return  # Skip if prior value is zero

    calculated_variance = ((current_value - prior_value) / prior_value) * 100
    assert abs(calculated_variance - expected_variance_pct) <= tolerance, \
        f"Expected variance {expected_variance_pct}%, got {calculated_variance}%"


def compare_files_content(file1: Path, file2: Path) -> bool:
    """
    Compare content of two files.

    Args:
        file1: First file path
        file2: Second file path

    Returns:
        True if files are identical
    """
    with open(file1, 'r') as f1, open(file2, 'r') as f2:
        return f1.read() == f2.read()


def get_file_diff(file1: Path, file2: Path) -> str:
    """
    Get diff between two files.

    Args:
        file1: First file path
        file2: Second file path

    Returns:
        Diff string
    """
    with open(file1, 'r') as f1, open(file2, 'r') as f2:
        diff = difflib.unified_diff(
            f1.readlines(),
            f2.readlines(),
            fromfile=str(file1),
            tofile=str(file2)
        )
        return ''.join(diff)


def validate_alert_structure(alert: Dict[str, Any]) -> None:
    """
    Validate that an alert has the required structure.

    Args:
        alert: Alert dictionary to validate

    Raises:
        AssertionError: If alert structure is invalid
    """
    required_keys = [
        "alert_id",
        "category",
        "description",
        "impact_score",
        "confidence_score",
        "total_score",
        "severity"
    ]

    assert_json_structure(alert, required_keys)

    # Validate score ranges
    assert 0 <= alert["impact_score"] <= 10, "Impact score must be 0-10"
    assert 0 <= alert["confidence_score"] <= 1, "Confidence score must be 0-1"
    assert 0 <= alert["total_score"] <= 10, "Total score must be 0-10"

    # Validate severity
    assert alert["severity"] in ["low", "medium", "high", "critical"], \
        f"Invalid severity: {alert['severity']}"


def validate_synthesis_report_structure(report: str) -> None:
    """
    Validate that a synthesis report has the required structure.

    Args:
        report: Markdown report string

    Raises:
        AssertionError: If report structure is invalid
    """
    assert "# Executive Summary" in report, "Missing Executive Summary section"
    assert "# Category Analysis" in report, "Missing Category Analysis section"
    assert "# GL Drill-Down" in report or "GL" in report, "Missing GL section"


def create_mock_session_state(
    cost_center: str = "067",
    with_data: bool = True
) -> Dict[str, Any]:
    """
    Create a mock session state dictionary.

    Args:
        cost_center: Cost center ID
        with_data: Whether to include mock data

    Returns:
        Mock session state dictionary
    """
    from datetime import datetime, timedelta

    end_date = datetime.now()
    start_date = end_date - timedelta(days=730)

    state = {
        "dimension_value": cost_center,
        "current_cost_center": cost_center,
        "primary_query_start_date": start_date.strftime("%Y-%m"),
        "primary_query_end_date": end_date.strftime("%Y-%m"),
        "current_level": 2,
    }

    if with_data:
        pl_df = generate_mock_pl_data(cost_center)
        ops_df = generate_mock_ops_metrics(cost_center)

        state["primary_data_csv"] = pl_df.to_csv(index=False)
        state["supplementary_data_csv"] = ops_df.to_csv(index=False)

    return state


def extract_numbers_from_text(text: str) -> List[float]:
    """
    Extract all numbers from a text string.

    Args:
        text: Text to parse

    Returns:
        List of extracted numbers
    """
    import re
    pattern = r'-?\d+(?:\.\d+)?'
    matches = re.findall(pattern, text)
    return [float(m) for m in matches]


def assert_percentage_in_range(
    value: float,
    min_pct: float,
    max_pct: float
) -> None:
    """
    Assert that a percentage value is in the expected range.

    Args:
        value: Percentage value to check
        min_pct: Minimum expected percentage
        max_pct: Maximum expected percentage

    Raises:
        AssertionError: If value is out of range
    """
    assert min_pct <= value <= max_pct, \
        f"Expected percentage in range [{min_pct}, {max_pct}], got {value}"
