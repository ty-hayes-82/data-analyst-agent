"""
Top-level conftest.py for Data Analyst Agent test suite.

Provides shared fixtures for unit, integration, and e2e tests including:
- Contract loading (ops_metrics, account_research)
- Sample DataFrames and CSV strings
- AnalysisContext construction
- A2A client for live integration tests
- Mock module patching for isolated testing
"""

import sys
import os
import json
import pytest
import pandas as pd
import numpy as np
from pathlib import Path
from unittest.mock import MagicMock
from io import StringIO

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.parent
DATASETS_DIR = PROJECT_ROOT / "config" / "datasets"
DATA_DIR = PROJECT_ROOT / "data"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Mock heavy dependencies that may not be installed in CI
# ---------------------------------------------------------------------------
_MOCK_MODULES = [
    "ruptures",
    "ruptures.costs",
    "ruptures.detection",
]

for _mod in _MOCK_MODULES:
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()


# ---------------------------------------------------------------------------
# Contract fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def ops_metrics_contract():
    """Load the Ops Metrics DatasetContract from YAML."""
    from data_analyst_agent.semantic.models import DatasetContract
    path = DATASETS_DIR / "ops_metrics" / "contract.yaml"
    assert path.exists(), f"Contract not found: {path}"
    return DatasetContract.from_yaml(str(path))


@pytest.fixture(scope="session")
def account_research_contract():
    """Load the Account Research DatasetContract from YAML."""
    from data_analyst_agent.semantic.models import DatasetContract
    path = DATASETS_DIR / "account_research" / "contract.yaml"
    assert path.exists(), f"Contract not found: {path}"
    return DatasetContract.from_yaml(str(path))


@pytest.fixture(scope="session")
def order_dispatch_contract():
    """Load the Order Dispatch DatasetContract from YAML."""
    from data_analyst_agent.semantic.models import DatasetContract
    path = DATASETS_DIR / "order_dispatch" / "contract.yaml"
    if not path.exists():
        pytest.skip(f"Contract not found: {path}")
    return DatasetContract.from_yaml(str(path))


@pytest.fixture(scope="session")
def minimal_contract():
    """Load the minimal test-only DatasetContract from fixtures."""
    from data_analyst_agent.semantic.models import DatasetContract
    path = PROJECT_ROOT / "tests" / "fixtures" / "minimal_contract.yaml"
    assert path.exists(), f"Fixture not found: {path}"
    return DatasetContract.from_yaml(str(path))


# ---------------------------------------------------------------------------
# Ops metrics sample data fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def ops_metrics_line_haul_df():
    """Load ops_metrics_line_haul_sample.csv as a DataFrame."""
    path = DATA_DIR / "ops_metrics_line_haul_sample.csv"
    if not path.exists():
        pytest.skip(f"Sample data not found: {path}")
    return pd.read_csv(path)


@pytest.fixture(scope="session")
def ops_metrics_067_df():
    """Load ops_metrics_067_sample.csv as a DataFrame."""
    path = DATA_DIR / "ops_metrics_067_sample.csv"
    if not path.exists():
        pytest.skip(f"Sample data not found: {path}")
    return pd.read_csv(path)


@pytest.fixture
def ops_metrics_sample_df(ops_metrics_067_df):
    """Alias for the primary ops metrics sample DataFrame (CC 067)."""
    return ops_metrics_067_df.copy()


@pytest.fixture
def ops_metrics_sample_csv(ops_metrics_067_df):
    """Ops metrics sample data as CSV string."""
    return ops_metrics_067_df.to_csv(index=False)


# ---------------------------------------------------------------------------
# AnalysisContext fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def ops_metrics_analysis_context(ops_metrics_contract, ops_metrics_line_haul_df):
    """Create an AnalysisContext from the ops_metrics contract + line haul sample data.

    Uses the line-haul sample (which includes ``ops_ln_of_bus_ref_nm``) rather
    than the CC-067 stub so that tools that resolve grain columns work correctly.
    """
    from data_analyst_agent.semantic.models import AnalysisContext

    df = ops_metrics_line_haul_df.copy()
    target_metric = ops_metrics_contract.get_metric("total_revenue")
    primary_dim = ops_metrics_contract.get_dimension("lob")

    return AnalysisContext(
        contract=ops_metrics_contract,
        df=df,
        target_metric=target_metric,
        primary_dimension=primary_dim,
        run_id="test-ops-metrics",
        max_drill_depth=3,
    )


@pytest.fixture
def ops_metrics_context_with_cache(ops_metrics_analysis_context):
    """
    Set up the AnalysisContext AND populate the data cache so tools can
    call resolve_data_and_columns().  Cleans up after the test.
    """
    from data_analyst_agent.sub_agents.data_cache import (
        set_analysis_context,
        set_validated_csv,
        clear_all_caches,
    )

    ctx = ops_metrics_analysis_context
    set_validated_csv(ctx.df.to_csv(index=False))
    set_analysis_context(ctx)
    yield ctx
    clear_all_caches()


# ---------------------------------------------------------------------------
# P&L contract + AnalysisContext fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def pl_contract():
    """Load the PL-067 fixture DatasetContract from YAML."""
    from data_analyst_agent.semantic.models import DatasetContract
    path = PROJECT_ROOT / "tests" / "fixtures" / "pl_067_contract.yaml"
    assert path.exists(), f"Fixture not found: {path}"
    return DatasetContract.from_yaml(str(path))


@pytest.fixture
def pl_analysis_context(pl_contract, mock_pl_data_df):
    """Create an AnalysisContext backed by P&L 067 data.

    This context is suitable for tools that call ``resolve_data_and_columns``
    (e.g. compute_statistical_summary, compute_level_statistics).
    """
    from data_analyst_agent.semantic.models import AnalysisContext

    df = mock_pl_data_df.copy()
    # Ensure hierarchical columns are present; fill missing ones from gl_account
    for col in ("canonical_category", "level_2", "level_3"):
        if col not in df.columns:
            df[col] = df.get("level_1", df["gl_account"])

    target_metric = pl_contract.get_metric("amount")
    primary_dim = pl_contract.get_dimension("dimension_value")

    return AnalysisContext(
        contract=pl_contract,
        df=df,
        target_metric=target_metric,
        primary_dimension=primary_dim,
        run_id="test-pl-067",
        max_drill_depth=4,
    )


@pytest.fixture
def pl_context_with_cache(pl_analysis_context):
    """Set up the P&L AnalysisContext AND populate the data cache.

    Use this fixture in tests that call tools via ``resolve_data_and_columns``.
    Cleans up all caches after each test.
    """
    from data_analyst_agent.sub_agents.data_cache import (
        set_analysis_context,
        set_validated_csv,
        clear_all_caches,
    )

    ctx = pl_analysis_context
    set_validated_csv(ctx.df.to_csv(index=False))
    set_analysis_context(ctx)
    yield ctx
    clear_all_caches()


# ---------------------------------------------------------------------------
# P&L / legacy fixtures (for existing test_full_workflow.py compatibility)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def mock_cost_center():
    """Default cost center used in test mode."""
    return "067"


@pytest.fixture(scope="session")
def mock_cost_centers():
    """List of cost centers for multi-CC tests."""
    return ["067", "071", "085"]


@pytest.fixture(scope="session")
def mock_date_ranges():
    """Standard date ranges used in testing (query-key format)."""
    return {
        "primary_query_start_date": "2024-01",
        "primary_query_end_date": "2025-12",
        "supplementary_query_start_date": "2024-01",
        "supplementary_query_end_date": "2025-12",
        "detail_query_start_date": "2024-01",
        "detail_query_end_date": "2025-12",
    }


@pytest.fixture
def mock_pl_data_csv():
    """Mock P&L data as a CSV string (time-series format)."""
    from tests.fixtures.test_data_loader import TestDataLoader
    loader = TestDataLoader()
    return loader.get_time_series_csv_string()


@pytest.fixture
def mock_pl_data_df(mock_pl_data_csv):
    """Mock P&L data as a DataFrame.

    Forces ``dimension_value`` to str so that comparisons like
    ``df["dimension_value"] == "67"`` work correctly after CSV round-trip.
    """
    return pd.read_csv(StringIO(mock_pl_data_csv), dtype={"dimension_value": str})


@pytest.fixture
def mock_ops_metrics_csv():
    """Mock operational metrics as a CSV string."""
    from tests.fixtures.test_data_loader import TestDataLoader
    loader = TestDataLoader()
    return loader.get_mock_ops_metrics_csv()


@pytest.fixture
def mock_ops_metrics_df(mock_ops_metrics_csv):
    """Mock operational metrics as a DataFrame."""
    return pd.read_csv(StringIO(mock_ops_metrics_csv))


@pytest.fixture
def mock_validated_pl_data_csv():
    """Mock validated P&L data (with ops metrics joined) as CSV string."""
    from tests.fixtures.test_data_loader import TestDataLoader
    loader = TestDataLoader()
    return loader.get_validated_pl_data_csv()


@pytest.fixture
def mock_chart_of_accounts():
    """Chart of accounts configuration with full metadata per GL account."""
    return {
        "3100-00": {
            "description": "Mileage Revenue",
            "canonical_category": "Revenue",
            "level_1": "Revenue",
            "level_2": "Operating Revenue",
            "level_3": "Freight Revenue",
            "level_4": "Mileage",
        },
        "3200-00": {
            "description": "Fuel Surcharge Revenue",
            "canonical_category": "Revenue",
            "level_1": "Revenue",
            "level_2": "Operating Revenue",
            "level_3": "Surcharges",
            "level_4": "Fuel Surcharge",
        },
        "5010-00": {
            "description": "Driver Pay",
            "canonical_category": "Operating Expenses",
            "level_1": "Operating Expenses",
            "level_2": "Labor",
            "level_3": "Driver Wages",
            "level_4": "Regular Pay",
        },
        "5020-00": {
            "description": "Fuel Expense",
            "canonical_category": "Operating Expenses",
            "level_1": "Operating Expenses",
            "level_2": "Fuel & Maintenance",
            "level_3": "Fuel",
            "level_4": "Diesel",
        },
        "6010-00": {
            "description": "Insurance",
            "canonical_category": "Overhead",
            "level_1": "Overhead",
            "level_2": "Insurance & Benefits",
            "level_3": "Liability Insurance",
            "level_4": "General Liability",
        },
    }


# ---------------------------------------------------------------------------
# Temporary output directory fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_output_dir(tmp_path):
    """Create a temporary directory for test outputs.  Auto-cleaned by pytest."""
    out = tmp_path / "pl_analyst_test_output"
    out.mkdir(parents=True, exist_ok=True)
    return out


# ---------------------------------------------------------------------------
# A2A client fixture (for live integration tests)
# ---------------------------------------------------------------------------

A2A_OPS_METRICS_URL = "http://localhost:8001/a2a/tableau_ops_metrics_ds_agent"


class A2ATestClient:
    """Lightweight JSON-RPC 2.0 client for A2A agent communication in tests."""

    def __init__(self, base_url: str, timeout: int = 120):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._msg_counter = 0

    def health_check(self) -> bool:
        """Return True if the agent card endpoint responds."""
        import urllib.request
        url = f"{self.base_url}/.well-known/agent-card.json"
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                return "name" in data or "url" in data
        except Exception:
            return False

    def send_message(self, text: str) -> dict:
        """Send a message/send JSON-RPC request and return the parsed response."""
        import urllib.request
        import uuid

        self._msg_counter += 1
        payload = {
            "jsonrpc": "2.0",
            "method": "message/send",
            "params": {
                "message": {
                    "role": "user",
                    "messageId": uuid.uuid4().hex,
                    "parts": [{"text": text}],
                }
            },
            "id": str(self._msg_counter),
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.base_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read())

    def extract_text(self, response: dict) -> str:
        """Extract text content from an A2A JSON-RPC response."""
        try:
            result = response.get("result", {})
            if isinstance(result, str):
                return result
            artifacts = result.get("artifacts", [])
            texts = []
            for artifact in artifacts:
                for part in artifact.get("parts", []):
                    if "text" in part:
                        texts.append(part["text"])
            if texts:
                return "\n".join(texts)
            status = result.get("status", {})
            msg = status.get("message", {})
            for part in msg.get("parts", []):
                if "text" in part:
                    texts.append(part["text"])
            if texts:
                return "\n".join(texts)
            return json.dumps(result, indent=2)
        except Exception:
            return json.dumps(response, indent=2)


@pytest.fixture(scope="session")
def a2a_client():
    """
    Create an A2ATestClient pointing at the ops_metrics agent.
    Skips the entire test if the A2A server is unreachable.
    """
    client = A2ATestClient(A2A_OPS_METRICS_URL)
    if not client.health_check():
        pytest.skip("A2A server not running at localhost:8001 -- skipping live tests")
    return client


# ---------------------------------------------------------------------------
# Session-state helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def populated_session_state(mock_cost_center, mock_pl_data_csv, mock_ops_metrics_csv,
                            mock_validated_pl_data_csv):
    """Return a MagicMock that mimics a fully-populated ADK session."""
    state = {
        "dimension_value": mock_cost_center,
        "current_cost_center": mock_cost_center,
        "primary_query_start_date": "2024-01",
        "primary_query_end_date": "2025-12",
        "primary_data_csv": mock_pl_data_csv,
        "supplementary_data_csv": mock_ops_metrics_csv,
        "validated_pl_data_csv": mock_validated_pl_data_csv,
        "current_level": 2,
        "analysis_context_ready": True,
    }
    session = MagicMock()
    session.state = state
    session.session_id = f"test-session-{mock_cost_center}"
    return session


# ---------------------------------------------------------------------------
# Assertion helpers exposed as fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def assert_csv_valid():
    """Fixture returning a callable that validates a CSV string."""
    def _validate(csv_string: str) -> pd.DataFrame:
        assert csv_string and csv_string.strip(), "CSV string is empty"
        df = pd.read_csv(StringIO(csv_string))
        assert len(df) > 0, "CSV parsed to empty DataFrame"
        return df
    return _validate


@pytest.fixture
def assert_json_valid():
    """Fixture returning a callable that validates a JSON string."""
    def _validate(json_string: str) -> dict:
        assert json_string and json_string.strip(), "JSON string is empty"
        data = json.loads(json_string)
        assert isinstance(data, (dict, list)), "JSON must be object or array"
        return data
    return _validate
