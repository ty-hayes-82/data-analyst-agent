"""
Shared pytest fixtures and configuration for P&L Analyst Agent testing.

This module provides reusable fixtures for all test phases:
- Mock data generation
- Session management
- Agent initialization
- Database mocking
- File I/O utilities
"""

import pytest
import pandas as pd
import json
import os
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Any
from unittest.mock import Mock, MagicMock
import tempfile
import shutil

# ============================================================================
# Path and Environment Fixtures
# ============================================================================

@pytest.fixture(scope="session")
def project_root() -> Path:
    """Return the project root directory."""
    return Path(__file__).parent


@pytest.fixture(scope="session")
def test_data_dir(project_root) -> Path:
    """Return the test data directory."""
    return project_root / "tests" / "fixtures" / "mock_data"


@pytest.fixture(scope="session")
def test_config_dir(project_root) -> Path:
    """Return the test config directory."""
    return project_root / "tests" / "fixtures" / "mock_configs"


@pytest.fixture(scope="function")
def temp_output_dir():
    """Create a temporary directory for test outputs."""
    temp_dir = tempfile.mkdtemp(prefix="pl_analyst_test_")
    yield Path(temp_dir)
    # Cleanup after test
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture(scope="function", autouse=True)
def setup_test_environment(monkeypatch):
    """Set up test environment variables."""
    monkeypatch.setenv("PL_ANALYST_TEST_MODE", "true")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    yield


# ============================================================================
# Mock Data Generation Fixtures
# ============================================================================

@pytest.fixture
def mock_cost_center() -> str:
    """Return a test cost center ID."""
    return "067"


@pytest.fixture
def mock_cost_centers() -> List[str]:
    """Return a list of test cost center IDs."""
    return ["067", "385", "102"]


@pytest.fixture
def mock_date_ranges() -> Dict[str, str]:
    """Return mock date ranges for testing."""
    end_date = datetime.now()
    start_date = end_date - timedelta(days=730)  # 24 months

    return {
        "pl_query_start_date": start_date.strftime("%Y-%m"),
        "pl_query_end_date": end_date.strftime("%Y-%m"),
        "ops_metrics_query_start_date": start_date.strftime("%Y-%m"),
        "ops_metrics_query_end_date": end_date.strftime("%Y-%m"),
        "order_query_start_date": (end_date - timedelta(days=90)).strftime("%Y-%m"),
        "order_query_end_date": end_date.strftime("%Y-%m"),
    }


@pytest.fixture
def mock_pl_data_df() -> pd.DataFrame:
    """Load real test P&L data (PL-067) in time-series format as DataFrame."""
    from tests.fixtures.test_data_loader import load_test_time_series_df
    return load_test_time_series_df()


@pytest.fixture
def mock_pl_data_csv() -> str:
    """Load real test P&L data (PL-067) in time-series format as CSV string."""
    from tests.fixtures.test_data_loader import load_test_time_series_csv
    return load_test_time_series_csv()


@pytest.fixture
def mock_ops_metrics_df() -> pd.DataFrame:
    """Load mock operational metrics (generated to match PL-067 periods) as DataFrame."""
    from tests.fixtures.test_data_loader import load_test_ops_metrics_df
    return load_test_ops_metrics_df()


@pytest.fixture
def mock_ops_metrics_csv() -> str:
    """Load mock ops metrics (generated to match PL-067 periods) as CSV string."""
    from tests.fixtures.test_data_loader import load_test_ops_metrics_csv
    return load_test_ops_metrics_csv()


@pytest.fixture
def mock_validated_pl_data_csv() -> str:
    """Load validated P&L data (PL-067 + ops metrics joined) as CSV string."""
    from tests.fixtures.test_data_loader import load_validated_test_data_csv
    return load_validated_test_data_csv()


@pytest.fixture
def mock_chart_of_accounts() -> Dict[str, Any]:
    """Generate mock chart of accounts configuration."""
    return {
        "5010": {
            "description": "Contract Revenue",
            "canonical_category": "Revenue",
            "level_1": "Revenue",
            "level_2": "Contract Revenue",
            "level_3": "5010",
            "level_4": "5010"
        },
        "5020": {
            "description": "Accessorial Revenue",
            "canonical_category": "Revenue",
            "level_1": "Revenue",
            "level_2": "Accessorial Revenue",
            "level_3": "5020",
            "level_4": "5020"
        },
        "6010": {
            "description": "Driver Wages",
            "canonical_category": "Operating Expenses",
            "level_1": "Operating Expenses",
            "level_2": "Labor",
            "level_3": "6010",
            "level_4": "6010"
        }
    }


@pytest.fixture
def mock_statistical_analysis() -> Dict[str, Any]:
    """Generate mock statistical analysis results."""
    return {
        "yoy_variance": {
            "Revenue": {"amount": 125000, "percent": 8.5},
            "Operating Expenses": {"amount": -45000, "percent": -3.2}
        },
        "mom_variance": {
            "Revenue": {"amount": 15000, "percent": 1.2},
            "Operating Expenses": {"amount": -5000, "percent": -0.8}
        },
        "moving_averages": {
            "3MMA": {"Revenue": 1500000, "Operating Expenses": 1350000},
            "6MMA": {"Revenue": 1480000, "Operating Expenses": 1340000}
        },
        "outliers": [
            {"period": "2024-08", "gl_account": "5010", "z_score": 3.2}
        ],
        "change_points": [
            {"period": "2024-06", "type": "mean_shift", "magnitude": 75000}
        ]
    }


@pytest.fixture
def mock_synthesis_result() -> str:
    """Generate mock report synthesis result."""
    return """
# Executive Summary

1. Total revenue increased 8.5% YoY driven by Contract Revenue growth
2. Operating expenses declined 3.2% due to improved efficiency
3. Seasonal pattern detected in Q4 with 15% uplift
4. One-time charge in August 2024 identified ($75K)
5. Recommend investigation of Contract Revenue variance drivers

# Category Analysis

## Revenue (+$125K, +8.5%)
- Contract Revenue: +$150K (+12%)
- Accessorial Revenue: -$25K (-5%)

## Operating Expenses (-$45K, -3.2%)
- Driver Wages: -$30K (-4%)
- Fuel: -$15K (-2%)

# GL Drill-Down

## GL 5010 - Contract Revenue
- YoY variance: +$150K (+12%)
- Root cause: Volume increase (loads +10%, rate +2%)
- Trend: Sustained growth over 6 months
"""


@pytest.fixture
def mock_alerts() -> List[Dict[str, Any]]:
    """Generate mock alert scoring results."""
    return [
        {
            "alert_id": "ALR-001",
            "category": "Revenue",
            "gl_account": "5010",
            "description": "Contract Revenue YoY variance exceeds threshold",
            "impact_score": 8.5,
            "confidence_score": 0.92,
            "persistence_score": 0.85,
            "total_score": 6.65,
            "severity": "high",
            "recommended_action": "Investigate volume and rate changes"
        },
        {
            "alert_id": "ALR-002",
            "category": "Operating Expenses",
            "gl_account": "6010",
            "description": "Driver Wages one-time reduction detected",
            "impact_score": 4.2,
            "confidence_score": 0.78,
            "persistence_score": 0.45,
            "total_score": 1.47,
            "severity": "medium",
            "recommended_action": "Verify staffing levels"
        }
    ]


# ============================================================================
# Session and Agent Fixtures
# ============================================================================

@pytest.fixture
def mock_session():
    """Create a mock ADK session for testing."""
    session = MagicMock()
    session.session_id = "test-session-123"
    session.state = {}
    return session


@pytest.fixture
def mock_session_store():
    """Create a mock session store."""
    store = MagicMock()
    store.create_session = MagicMock(return_value=mock_session())
    return store


@pytest.fixture
def populated_session_state(
    mock_session,
    mock_cost_center,
    mock_date_ranges,
    mock_pl_data_csv,
    mock_ops_metrics_csv,
    mock_validated_pl_data_csv
):
    """Create a session with populated state for testing."""
    mock_session.state = {
        "cost_center": mock_cost_center,
        "current_cost_center": mock_cost_center,
        **mock_date_ranges,
        "pl_data_csv": mock_pl_data_csv,
        "ops_metrics_csv": mock_ops_metrics_csv,
        "validated_pl_data_csv": mock_validated_pl_data_csv,
        "current_level": 2,
    }
    return mock_session


# ============================================================================
# File I/O Fixtures
# ============================================================================

@pytest.fixture
def mock_output_files(temp_output_dir, mock_cost_center):
    """Generate paths for mock output files."""
    return {
        "json": temp_output_dir / f"cost_center_{mock_cost_center}.json",
        "alerts": temp_output_dir / f"alerts_payload_cc{mock_cost_center}.json",
        "markdown": temp_output_dir / f"cost_center_{mock_cost_center}_report.md"
    }


@pytest.fixture
def create_mock_output_files(mock_output_files, mock_synthesis_result, mock_alerts):
    """Create mock output files for testing."""
    # JSON output
    json_data = {
        "cost_center": "067",
        "timeframe": {"start": "2023-01", "end": "2024-12"},
        "executive_summary": "Mock summary",
        "synthesis_result": mock_synthesis_result,
        "alerts": mock_alerts
    }
    with open(mock_output_files["json"], "w") as f:
        json.dump(json_data, f, indent=2)

    # Alerts payload
    with open(mock_output_files["alerts"], "w") as f:
        json.dump(mock_alerts, f, indent=2)

    # Markdown report
    with open(mock_output_files["markdown"], "w") as f:
        f.write(mock_synthesis_result)

    return mock_output_files


# ============================================================================
# Database and External Service Mocking
# ============================================================================

@pytest.fixture
def mock_tableau_agent():
    """Create a mock Tableau A2A agent."""
    agent = MagicMock()
    agent.name = "mock_tableau_agent"
    agent.run_async = MagicMock(return_value={"data": "mock_csv_data"})
    return agent


@pytest.fixture
def mock_database_connection():
    """Create a mock database connection."""
    conn = MagicMock()
    cursor = MagicMock()
    cursor.fetchall = MagicMock(return_value=[])
    conn.cursor = MagicMock(return_value=cursor)
    return conn


# ============================================================================
# Utility Functions for Tests
# ============================================================================

@pytest.fixture
def assert_csv_valid():
    """Fixture providing a CSV validation function."""
    def _validate(csv_string: str) -> bool:
        """Check if a string is valid CSV format."""
        try:
            df = pd.read_csv(pd.io.common.StringIO(csv_string))
            return len(df) > 0
        except Exception:
            return False
    return _validate


@pytest.fixture
def assert_json_valid():
    """Fixture providing a JSON validation function."""
    def _validate(json_string: str) -> bool:
        """Check if a string is valid JSON format."""
        try:
            data = json.loads(json_string)
            return isinstance(data, (dict, list))
        except Exception:
            return False
    return _validate


@pytest.fixture
def compare_dataframes():
    """Fixture providing a DataFrame comparison function."""
    def _compare(df1: pd.DataFrame, df2: pd.DataFrame, tolerance: float = 0.01) -> bool:
        """Compare two DataFrames with numeric tolerance."""
        try:
            pd.testing.assert_frame_equal(df1, df2, atol=tolerance)
            return True
        except AssertionError:
            return False
    return _compare


# ============================================================================
# Performance Testing Fixtures
# ============================================================================

@pytest.fixture
def performance_timer():
    """Fixture for timing test execution."""
    import time

    class Timer:
        def __init__(self):
            self.start_time = None
            self.end_time = None

        def start(self):
            self.start_time = time.time()

        def stop(self):
            self.end_time = time.time()

        def elapsed(self):
            if self.start_time and self.end_time:
                return self.end_time - self.start_time
            return None

    return Timer()


@pytest.fixture
def memory_profiler():
    """Fixture for profiling memory usage."""
    import psutil
    import os

    class MemoryProfiler:
        def __init__(self):
            self.process = psutil.Process(os.getpid())
            self.start_memory = None
            self.end_memory = None

        def start(self):
            self.start_memory = self.process.memory_info().rss / 1024 / 1024  # MB

        def stop(self):
            self.end_memory = self.process.memory_info().rss / 1024 / 1024  # MB

        def delta(self):
            if self.start_memory and self.end_memory:
                return self.end_memory - self.start_memory
            return None

    return MemoryProfiler()


# ============================================================================
# Markers and Test Utilities
# ============================================================================

def pytest_configure(config):
    """Configure custom markers."""
    config.addinivalue_line(
        "markers", "unit: Unit tests for individual functions and tools"
    )
    config.addinivalue_line(
        "markers", "integration: Integration tests for agent pairs and chains"
    )
    config.addinivalue_line(
        "markers", "workflow: Sub-workflow tests for major features"
    )
    config.addinivalue_line(
        "markers", "e2e: End-to-end workflow tests"
    )
    config.addinivalue_line(
        "markers", "edge_case: Edge case and error handling tests"
    )
    config.addinivalue_line(
        "markers", "performance: Performance and load tests"
    )


def pytest_collection_modifyitems(config, items):
    """Modify test collection to add markers based on test location."""
    for item in items:
        # Add markers based on file path
        if "unit" in str(item.fspath):
            item.add_marker(pytest.mark.unit)
        elif "integration" in str(item.fspath):
            item.add_marker(pytest.mark.integration)
        elif "workflow" in str(item.fspath):
            item.add_marker(pytest.mark.workflow)
        elif "e2e" in str(item.fspath):
            item.add_marker(pytest.mark.e2e)
        elif "edge_cases" in str(item.fspath):
            item.add_marker(pytest.mark.edge_case)
        elif "performance" in str(item.fspath):
            item.add_marker(pytest.mark.performance)
