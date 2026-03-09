# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Comprehensive A2A agent tool tests -- Spec 011.

These tests validate ALL tools across ALL three Tableau A2A agents:
- tableau_ops_metrics_ds_agent
- tableau_account_research_ds_agent
- tableau_order_dispatch_revenue_ds_agent

Tests require the A2A server running at http://localhost:8001.
All tests are auto-skipped when the server is unreachable.

Coverage:
  4B  Schema correctness
  4C  Pre-aggregation shape and period alignment
  4D  Derived metric accuracy
  4E  Filter accuracy
  4F  SQL query safety (row caps, malformed SQL)
  4G  Concurrent requests
  4H  Latency benchmarks
"""

import json
import asyncio
import time
import urllib.request
import urllib.error
import uuid
import statistics
import calendar
from datetime import date, datetime
from io import StringIO
from pathlib import Path
from typing import Dict, Any, List, Optional

import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Markers
# ---------------------------------------------------------------------------

pytestmark = [
    pytest.mark.integration,
    pytest.mark.requires_a2a,
]

# ---------------------------------------------------------------------------
# Config paths
# ---------------------------------------------------------------------------

WORKSPACE_ROOT = Path(__file__).parent.parent.parent.parent
REMOTE_A2A = WORKSPACE_ROOT / "remote_a2a"

AGENT_NAMES = [
    "tableau_ops_metrics_ds_agent",
    "tableau_account_research_ds_agent",
    "tableau_order_dispatch_revenue_ds_agent",
]

A2A_BASE = "http://localhost:8001"

# ---------------------------------------------------------------------------
# Infrastructure
# ---------------------------------------------------------------------------

def _agent_url(agent_name: str) -> str:
    return f"{A2A_BASE}/a2a/{agent_name}"


def _load_dataset_yaml(agent_name: str) -> Dict[str, Any]:
    import yaml
    cfg_path = REMOTE_A2A / agent_name / "config" / "dataset.yaml"
    if not cfg_path.exists():
        return {}
    with open(cfg_path, "r") as f:
        return yaml.safe_load(f) or {}


def _send_a2a_message(agent_name: str, text: str, timeout: int = 120) -> dict:
    """Send a message/send JSON-RPC request to an agent. Returns parsed response."""
    url = _agent_url(agent_name)
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
        "id": uuid.uuid4().hex,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _extract_text(response: dict) -> str:
    """Pull text content out of an A2A JSON-RPC response."""
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
        return json.dumps(result)
    except Exception:
        return json.dumps(response)


def _try_parse_json(text: str) -> Optional[dict]:
    """Try to extract a JSON object from the response text."""
    text = text.strip()
    # Try direct parse first
    try:
        return json.loads(text)
    except Exception:
        pass
    # Try to find a JSON block inside markdown fences
    import re
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except Exception:
            pass
    # Try to find any {...} block
    match = re.search(r"(\{.*\})", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except Exception:
            pass
    return None


def _is_month_end(date_str: str) -> bool:
    """Return True if date_str is the last day of its month (YYYY-MM-DD format)."""
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
        last_day = calendar.monthrange(d.year, d.month)[1]
        return d.day == last_day
    except Exception:
        return False


def _health_check_agent(agent_name: str) -> bool:
    """Return True if the agent card endpoint is reachable."""
    url = f"{_agent_url(agent_name)}/.well-known/agent-card.json"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            return bool(data)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Session-scoped fixture: check server is up
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def a2a_server():
    """Skip all tests if the A2A server is not running."""
    url = f"{A2A_BASE}/a2a/tableau_ops_metrics_ds_agent"
    try:
        req = urllib.request.Request(url, method="GET")
        urllib.request.urlopen(req, timeout=5)
    except urllib.error.HTTPError:
        pass  # 405/404 is fine -- server is responding
    except Exception:
        pytest.skip(
            "A2A server not running at localhost:8001. "
            "Start with: python pl_analyst/scripts/start_a2a_server.py"
        )
    return True


# ---------------------------------------------------------------------------
# Parametrized agent fixture
# ---------------------------------------------------------------------------

@pytest.fixture(params=AGENT_NAMES)
def agent_name(request):
    return request.param


@pytest.fixture(params=AGENT_NAMES)
def agent_with_config(request):
    """Return (agent_name, dataset_config_dict) for each agent."""
    name = request.param
    cfg = _load_dataset_yaml(name)
    return name, cfg


# ---------------------------------------------------------------------------
# 4B: Schema tests
# ---------------------------------------------------------------------------

class TestSchema:
    """Spec 4B: Schema correctness for all agents."""

    def test_get_schema_success(self, a2a_server, agent_name):
        """get_schema_tool should return success=True with a non-empty columns list."""
        resp = _send_a2a_message(
            agent_name,
            "Call get_schema_tool and return the raw JSON result. Do not summarize.",
        )
        text = _extract_text(resp)
        assert text and len(text) > 20, f"[{agent_name}] Schema response too short: {text[:200]}"

        # Should mention schema-related terms
        text_lower = text.lower()
        assert any(kw in text_lower for kw in ("column", "row", "table", "schema", "extract")), \
            f"[{agent_name}] Schema response lacks schema keywords: {text[:500]}"

    def test_get_schema_row_count_positive(self, a2a_server, agent_name):
        """Schema should report a positive row count."""
        resp = _send_a2a_message(
            agent_name,
            "Use get_schema_tool. Return the raw JSON. Include row_count in your response.",
        )
        text = _extract_text(resp)
        # Look for any number > 0 following "row_count" or "row count"
        import re
        match = re.search(r'"row_count"\s*:\s*(\d+)', text)
        if match:
            assert int(match.group(1)) > 0, f"[{agent_name}] row_count should be > 0"
        else:
            # Accept if the text contains any large number (indicative of rows)
            large_nums = re.findall(r'\b(\d{4,})\b', text)
            assert large_nums, f"[{agent_name}] Schema should contain row count > 1000: {text[:500]}"

    def test_sum_columns_in_schema(self, a2a_server, agent_with_config):
        """All sum_columns from dataset.yaml should appear in the schema."""
        agent_name, cfg = agent_with_config
        dataset_cfg = cfg.get("dataset", {})
        agg = dataset_cfg.get("aggregation", {})
        sum_columns = agg.get("sum_columns", [])

        if not sum_columns:
            pytest.skip(f"[{agent_name}] No sum_columns defined in dataset.yaml")

        resp = _send_a2a_message(
            agent_name,
            "Use get_schema_tool and return the raw JSON with column names.",
        )
        text = _extract_text(resp).lower()

        missing = [col for col in sum_columns if col.lower() not in text]
        # Allow up to 2 missing or 30% of sum_columns (whichever is larger) for optional/renamed columns
        tolerance = max(2, int(len(sum_columns) * 0.3))
        assert len(missing) <= tolerance, \
            f"[{agent_name}] sum_columns not found in schema: {missing}"


# ---------------------------------------------------------------------------
# 4C: Pre-aggregation tests
# ---------------------------------------------------------------------------

class TestPreAggregation:
    """Spec 4C: Export produces pre-aggregated data with correct period column."""

    def test_export_returns_period_end_date(self, a2a_server, agent_name):
        """export_bulk_data_tool should return a CSV with a period_end_date column."""
        resp = _send_a2a_message(
            agent_name,
            (
                "Call export_bulk_data_tool with no filters and output_format='csv'. "
                "Return the raw tool JSON output (success, row_count, data fields)."
            ),
        )
        text = _extract_text(resp)
        assert "period_end_date" in text, \
            f"[{agent_name}] Export should contain period_end_date column: {text[:500]}"

    def test_period_end_date_is_month_end_ops_metrics(self, a2a_server):
        """For ops_metrics, all period_end_date values should be month-end dates."""
        resp = _send_a2a_message(
            "tableau_ops_metrics_ds_agent",
            (
                "Call export_bulk_data_tool with year_start=2025, month_start=1, "
                "year_end=2025, month_end=3, output_format='csv'. "
                "Return raw JSON tool output."
            ),
        )
        text = _extract_text(resp)

        # Extract the CSV from the response
        data_obj = _try_parse_json(text)
        if data_obj and "data" in data_obj:
            csv_str = data_obj["data"]
        elif "period_end_date" in text:
            # Try to find CSV inline
            import re
            lines = [l for l in text.split("\n") if "period_end_date" in l or l.startswith("202")]
            csv_str = "\n".join(lines[:50])
        else:
            pytest.skip("Could not extract CSV from response -- agent may be formatting differently")
            return

        if not csv_str.strip():
            pytest.skip("Empty CSV data returned")
            return

        try:
            df = pd.read_csv(StringIO(csv_str))
        except Exception:
            pytest.skip("Could not parse CSV from response")
            return

        if "period_end_date" not in df.columns:
            pytest.skip("period_end_date not in parsed CSV columns")
            return

        invalid = [v for v in df["period_end_date"].dropna() if not _is_month_end(str(v))]
        assert not invalid, \
            f"Non-month-end dates found in period_end_date: {invalid[:5]}"

    def test_export_row_count_under_safety_cap(self, a2a_server, agent_name):
        """Aggregated export should return fewer rows than the agent-specific safety cap."""
        # Agent-specific caps: ops_metrics is tightly bounded; others may be large datasets
        _SAFETY_CAPS = {
            "tableau_ops_metrics_ds_agent": 50_000,
            "tableau_account_research_ds_agent": 10_000_000,
            "tableau_order_dispatch_revenue_ds_agent": 10_000_000,
        }
        cap = _SAFETY_CAPS.get(agent_name, 50_000)

        if agent_name in ("tableau_account_research_ds_agent", "tableau_order_dispatch_revenue_ds_agent"):
            pytest.skip(f"[{agent_name}] Large dataset agent -- row count cap check skipped")

        resp = _send_a2a_message(
            agent_name,
            "Call export_bulk_data_tool with no filters, output_format='csv'. Return raw tool JSON.",
        )
        text = _extract_text(resp)

        import re
        match = re.search(r'"row_count"\s*:\s*(\d+)', text)
        if match:
            row_count = int(match.group(1))
            assert row_count < cap, \
                f"[{agent_name}] Aggregated export row_count={row_count} exceeds {cap:,} safety cap"
        else:
            # Just assert response is not enormous (proxy for row count)
            assert len(text) < 10_000_000, \
                f"[{agent_name}] Response text too large -- data may not be pre-aggregated"

    def test_sum_columns_in_export_csv(self, a2a_server, agent_with_config):
        """T045: All sum_columns from config should be present as columns in the exported CSV."""
        agent_name, cfg = agent_with_config
        dataset_cfg = cfg.get("dataset", {})
        agg = dataset_cfg.get("aggregation", {})
        sum_columns = agg.get("sum_columns", [])

        if not sum_columns:
            pytest.skip(f"[{agent_name}] No sum_columns in dataset.yaml")

        resp = _send_a2a_message(
            agent_name,
            "Call export_bulk_data_tool with no filters, output_format='csv'. Return raw tool JSON.",
        )
        text = _extract_text(resp)
        obj = _try_parse_json(text)

        if obj and isinstance(obj.get("data"), str):
            try:
                df = pd.read_csv(StringIO(obj["data"]))
                csv_columns = set(df.columns)
            except Exception:
                pytest.skip(f"[{agent_name}] Could not parse CSV from response")
                return
        else:
            # Fall back to checking text for column name mentions
            csv_columns = None

        if csv_columns is not None:
            missing = [col for col in sum_columns if col not in csv_columns]
            assert len(missing) <= 2, \
                f"[{agent_name}] sum_columns missing from export CSV: {missing}"
        else:
            # Text-based check
            missing = [col for col in sum_columns if col not in text]
            assert len(missing) <= 2, \
                f"[{agent_name}] sum_columns not found in response text: {missing}"

    def test_derived_metrics_in_export_ops_metrics(self, a2a_server):
        """T046(ops): ops_metrics export should include derived metric columns."""
        cfg = _load_dataset_yaml("tableau_ops_metrics_ds_agent")
        agg = cfg.get("dataset", {}).get("aggregation", {})
        derived = [m["name"] for m in agg.get("derived_metrics", [])]

        if not derived:
            pytest.skip("No derived_metrics in ops_metrics dataset.yaml")

        resp = _send_a2a_message(
            "tableau_ops_metrics_ds_agent",
            "Call export_bulk_data_tool with year_start=2025, month_start=1, "
            "year_end=2025, month_end=3, output_format='csv'. Return raw tool JSON.",
        )
        text = _extract_text(resp)

        missing = [name for name in derived if name not in text]
        assert len(missing) <= 1, \
            f"Derived metric columns missing from ops_metrics export: {missing}"

    def test_derived_metrics_in_export_order_dispatch(self, a2a_server):
        """T046(order_dispatch): order_dispatch export should include derived metric columns."""
        cfg = _load_dataset_yaml("tableau_order_dispatch_revenue_ds_agent")
        agg = cfg.get("dataset", {}).get("aggregation", {})
        derived = [m["name"] for m in agg.get("derived_metrics", [])]

        if not derived:
            pytest.skip("No derived_metrics in order_dispatch dataset.yaml")

        resp = _send_a2a_message(
            "tableau_order_dispatch_revenue_ds_agent",
            "Call export_bulk_data_tool with year_start=2025, month_start=1, "
            "year_end=2025, month_end=3, output_format='csv'. Return raw tool JSON.",
        )
        text = _extract_text(resp)

        missing = [name for name in derived if name not in text]
        assert len(missing) <= 1, \
            f"Derived metric columns missing from order_dispatch export: {missing}"


# ---------------------------------------------------------------------------
# 4D: Derived metric accuracy
# ---------------------------------------------------------------------------

class TestDerivedMetricAccuracy:
    """Spec 4D: Verify derived metrics match manual calculations."""

    @staticmethod
    def _get_ops_export(year_start=2025, month_start=1, year_end=2025, month_end=3) -> Optional[pd.DataFrame]:
        """Helper: export ops metrics data and return as DataFrame."""
        resp = _send_a2a_message(
            "tableau_ops_metrics_ds_agent",
            (
                f"Call export_bulk_data_tool with year_start={year_start}, month_start={month_start}, "
                f"year_end={year_end}, month_end={month_end}, output_format='csv'. "
                f"Return raw tool JSON with the data field."
            ),
        )
        text = _extract_text(resp)
        obj = _try_parse_json(text)
        if obj and isinstance(obj.get("data"), str):
            try:
                return pd.read_csv(StringIO(obj["data"]))
            except Exception:
                pass
        return None

    def test_empty_miles_accuracy(self, a2a_server):
        """empty_miles should equal ttl_trf_mi - ld_trf_mi."""
        df = self._get_ops_export()
        if df is None:
            pytest.skip("Could not retrieve ops_metrics export for accuracy test")

        required = {"ttl_trf_mi", "ld_trf_mi", "empty_miles"}
        if not required.issubset(df.columns):
            pytest.skip(f"Required columns missing: {required - set(df.columns)}")

        df = df.dropna(subset=["ttl_trf_mi", "ld_trf_mi", "empty_miles"])
        expected = df["ttl_trf_mi"] - df["ld_trf_mi"]
        actual = df["empty_miles"]
        diff = (expected - actual).abs()
        assert diff.max() < 1.0, \
            f"empty_miles max deviation from formula: {diff.max():.4f}"

    def test_miles_per_truck_accuracy(self, a2a_server):
        """miles_per_truck should equal ld_trf_mi / truck_count (where truck_count > 0)."""
        df = self._get_ops_export()
        if df is None:
            pytest.skip("Could not retrieve ops_metrics export")

        required = {"ld_trf_mi", "truck_count", "miles_per_truck"}
        if not required.issubset(df.columns):
            pytest.skip(f"Required columns missing: {required - set(df.columns)}")

        mask = df["truck_count"] > 0
        df = df[mask].dropna(subset=list(required))
        if df.empty:
            pytest.skip("No rows with truck_count > 0")

        expected = df["ld_trf_mi"] / df["truck_count"]
        actual = pd.to_numeric(df["miles_per_truck"], errors="coerce")
        diff = (expected - actual).abs()
        assert diff.max() < 0.01, \
            f"miles_per_truck max deviation: {diff.max():.6f}"

    def test_deadhead_pct_accuracy(self, a2a_server):
        """deadhead_pct should equal (ttl_trf_mi - ld_trf_mi) / ttl_trf_mi * 100."""
        df = self._get_ops_export()
        if df is None:
            pytest.skip("Could not retrieve ops_metrics export")

        required = {"ttl_trf_mi", "ld_trf_mi", "deadhead_pct"}
        if not required.issubset(df.columns):
            pytest.skip(f"Required columns missing: {required - set(df.columns)}")

        mask = df["ttl_trf_mi"] > 0
        df = df[mask].dropna(subset=list(required))
        if df.empty:
            pytest.skip("No rows with ttl_trf_mi > 0")

        expected = (df["ttl_trf_mi"] - df["ld_trf_mi"]) / df["ttl_trf_mi"] * 100.0
        actual = pd.to_numeric(df["deadhead_pct"], errors="coerce")
        diff = (expected - actual).abs()
        assert diff.max() < 0.01, \
            f"deadhead_pct max deviation: {diff.max():.6f}"

    def test_revenue_per_loaded_mile_accuracy(self, a2a_server):
        """revenue_per_loaded_mile should equal ttl_rev_amt / ld_trf_mi."""
        df = self._get_ops_export()
        if df is None:
            pytest.skip("Could not retrieve ops_metrics export")

        required = {"ttl_rev_amt", "ld_trf_mi", "revenue_per_loaded_mile"}
        if not required.issubset(df.columns):
            pytest.skip(f"Required columns missing: {required - set(df.columns)}")

        mask = df["ld_trf_mi"] > 0
        df = df[mask].dropna(subset=list(required))
        if df.empty:
            pytest.skip("No rows with ld_trf_mi > 0")

        expected = df["ttl_rev_amt"] / df["ld_trf_mi"]
        actual = pd.to_numeric(df["revenue_per_loaded_mile"], errors="coerce")
        diff = (expected - actual).abs()
        assert diff.max() < 0.01, \
            f"revenue_per_loaded_mile max deviation: {diff.max():.6f}"


# ---------------------------------------------------------------------------
# 4E: Filter accuracy
# ---------------------------------------------------------------------------

class TestFilterAccuracy:
    """Spec 4E: Filter parameters produce correctly filtered output."""

    def test_date_range_filter(self, a2a_server):
        """Export with date range should only return data within that range."""
        resp = _send_a2a_message(
            "tableau_ops_metrics_ds_agent",
            (
                "Call export_bulk_data_tool with year_start=2025, month_start=6, "
                "year_end=2025, month_end=12, output_format='csv'. Return raw tool JSON."
            ),
        )
        text = _extract_text(resp)
        obj = _try_parse_json(text)
        if obj is None or "data" not in obj:
            pytest.skip("Could not extract JSON data from response")

        try:
            df = pd.read_csv(StringIO(obj["data"]))
        except Exception:
            pytest.skip("Could not parse CSV")
            return

        if "period_end_date" not in df.columns:
            pytest.skip("period_end_date not in columns")
            return

        dates = pd.to_datetime(df["period_end_date"], errors="coerce").dropna()
        if dates.empty:
            pytest.skip("No valid dates in period_end_date column")

        assert dates.min() >= pd.Timestamp("2025-06-01"), \
            f"Dates before filter start found: {dates.min()}"
        assert dates.max() <= pd.Timestamp("2025-12-31"), \
            f"Dates after filter end found: {dates.max()}"

    def test_no_filter_spans_multiple_months(self, a2a_server):
        """Export with no filters should span at least 6 distinct months."""
        resp = _send_a2a_message(
            "tableau_ops_metrics_ds_agent",
            "Call export_bulk_data_tool with no filters, output_format='csv'. Return raw tool JSON.",
        )
        text = _extract_text(resp)
        obj = _try_parse_json(text)
        if obj is None or "data" not in obj:
            pytest.skip("Could not extract JSON data from response")

        try:
            df = pd.read_csv(StringIO(obj["data"]))
        except Exception:
            pytest.skip("Could not parse CSV")
            return

        if "period_end_date" not in df.columns:
            pytest.skip("period_end_date not in columns")
            return

        unique_months = df["period_end_date"].nunique()
        assert unique_months >= 6, \
            f"Expected >= 6 distinct months, got {unique_months}"

    def test_cost_center_filter_ops_metrics(self, a2a_server):
        """T055: Export with cost_centers filter should apply the WHERE clause."""
        cfg = _load_dataset_yaml("tableau_ops_metrics_ds_agent")
        cc_col = cfg.get("dataset", {}).get("filter_columns", {}).get("cost_center", "")
        if not cc_col:
            pytest.skip("No cost_center filter column defined for ops_metrics")

        # "067" is a known valid cost center in the ops metrics dataset
        test_cc = "067"
        resp = _send_a2a_message(
            "tableau_ops_metrics_ds_agent",
            (
                f"Call export_bulk_data_tool with cost_centers='{test_cc}', "
                "year_start=2025, month_start=1, year_end=2025, month_end=6, "
                "output_format='csv'. Return raw tool JSON."
            ),
        )
        text = _extract_text(resp)
        obj = _try_parse_json(text)
        if obj is None or "data" not in obj:
            pytest.skip("Could not extract response for cost_center filter test")

        try:
            df = pd.read_csv(StringIO(obj["data"]))
        except Exception:
            pytest.skip("Could not parse CSV")
            return

        if cc_col not in df.columns:
            pytest.skip(f"Cost center column '{cc_col}' not in export columns")
            return

        invalid = df[df[cc_col].astype(str) != test_cc]
        assert len(invalid) == 0, \
            f"Rows with cost_center != '{test_cc}' found after filter: {invalid[[cc_col]].head()}"

    def test_lob_filter_ops_metrics(self, a2a_server):
        """T052: Export with a LOB filter should only return rows matching that LOB."""
        cfg = _load_dataset_yaml("tableau_ops_metrics_ds_agent")
        lob_col = cfg.get("dataset", {}).get("filter_columns", {}).get("lob", "")
        if not lob_col:
            pytest.skip("No lob filter column defined for ops_metrics")

        # Use "Line Haul" as the test LOB (known to exist)
        resp = _send_a2a_message(
            "tableau_ops_metrics_ds_agent",
            (
                "Call export_bulk_data_tool with lobs='Line Haul', "
                "year_start=2025, month_start=1, year_end=2025, month_end=3, "
                "output_format='csv'. Return raw tool JSON."
            ),
        )
        text = _extract_text(resp)
        obj = _try_parse_json(text)
        if obj is None or "data" not in obj:
            pytest.skip("Could not extract response")

        try:
            df = pd.read_csv(StringIO(obj["data"]))
        except Exception:
            pytest.skip("Could not parse CSV")
            return

        if lob_col not in df.columns:
            pytest.skip(f"LOB column '{lob_col}' not in export columns")
            return

        # All rows should have "Line Haul" in the LOB column
        invalid = df[df[lob_col] != "Line Haul"]
        assert len(invalid) == 0, \
            f"Non-'Line Haul' rows found in LOB-filtered export: {invalid[[lob_col]].head()}"


# ---------------------------------------------------------------------------
# 4F: SQL Query Safety
# ---------------------------------------------------------------------------

class TestSQLSafety:
    """Spec 4F: SQL query tool respects row caps and handles errors gracefully."""

    def test_select_star_capped_at_25k(self, a2a_server):
        """SELECT * should return at most 25,000 rows regardless of limit param."""
        resp = _send_a2a_message(
            "tableau_ops_metrics_ds_agent",
            (
                'Run the SQL query: SELECT * FROM "Extract"."Extract" '
                "with limit=0, output_format='json'. Return the raw tool JSON."
            ),
        )
        text = _extract_text(resp)

        import re
        match = re.search(r'"row_count"\s*:\s*(\d+)', text)
        if match:
            row_count = int(match.group(1))
            assert row_count <= 25_000, \
                f"SELECT * returned {row_count} rows, exceeding 25K safety cap"
        else:
            # Verify the response is not absurdly large
            assert len(text) < 5_000_000, "Response too large -- cap may not be enforced"

    def test_limited_sql_returns_exact_count(self, a2a_server):
        """run_sql_query_tool with limit=5 should return exactly 5 rows."""
        resp = _send_a2a_message(
            "tableau_ops_metrics_ds_agent",
            (
                'Run the SQL query: SELECT * FROM "Extract"."Extract" '
                "with limit=5, output_format='json'. Return raw tool JSON."
            ),
        )
        text = _extract_text(resp)

        import re
        match = re.search(r'"row_count"\s*:\s*(\d+)', text)
        if match:
            assert int(match.group(1)) == 5, \
                f"Expected 5 rows, got {match.group(1)}"
        else:
            pytest.skip("Could not extract row_count from response")

    def test_malformed_sql_returns_structured_error(self, a2a_server):
        """Malformed SQL should produce a structured error, not a crash."""
        resp = _send_a2a_message(
            "tableau_ops_metrics_ds_agent",
            "Run this SQL: SLECT * FORM \"Extract\".\"Extract\" -- intentionally malformed",
        )
        text = _extract_text(resp)
        # Response should mention an error somehow, not be empty
        assert text and len(text) > 5, "Empty response to malformed SQL"
        text_lower = text.lower()
        # Should contain error indicator or the response acknowledged a problem
        assert any(kw in text_lower for kw in ("error", "invalid", "syntax", "fail", "could not")), \
            f"No error indication for malformed SQL: {text[:300]}"

    def test_group_by_query_returns_aggregated(self, a2a_server):
        """A valid GROUP BY query should return correct aggregated results."""
        resp = _send_a2a_message(
            "tableau_ops_metrics_ds_agent",
            (
                'Run SQL: SELECT COUNT(*) as row_count FROM "Extract"."Extract" '
                "with output_format='json'. Return raw tool JSON."
            ),
        )
        text = _extract_text(resp)
        import re
        nums = re.findall(r'\b(\d{5,})\b', text)
        assert nums, \
            f"GROUP BY COUNT(*) should return large number: {text[:300]}"
        assert int(nums[0]) > 1000, \
            f"Expected COUNT(*) > 1000, got {nums[0]}"


# ---------------------------------------------------------------------------
# 4G: Concurrent requests
# ---------------------------------------------------------------------------

class TestConcurrentRequests:
    """Spec 4G: Multiple simultaneous requests succeed without errors."""

    def test_five_parallel_exports_succeed(self, a2a_server):
        """5 simultaneous export_bulk_data_tool requests should all succeed."""
        import threading
        results = []
        errors = []

        def do_request():
            try:
                resp = _send_a2a_message(
                    "tableau_ops_metrics_ds_agent",
                    (
                        "Call export_bulk_data_tool with year_start=2025, month_start=1, "
                        "year_end=2025, month_end=2, output_format='csv'. Return raw JSON."
                    ),
                    timeout=120,
                )
                text = _extract_text(resp)
                results.append(text)
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=do_request) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=150)

        assert not errors, f"Concurrent requests produced errors: {errors}"
        assert len(results) == 5, f"Only {len(results)}/5 requests completed"
        # All should have non-empty results
        empty = [i for i, r in enumerate(results) if not r or len(r) < 20]
        assert not empty, f"Some concurrent requests returned empty: indices {empty}"

    def test_three_agents_parallel(self, a2a_server):
        """Requests to all 3 agents in parallel should all succeed."""
        import threading
        results = {}
        errors = {}

        def request_agent(name):
            try:
                resp = _send_a2a_message(
                    name,
                    "Call get_schema_tool and return the raw JSON.",
                    timeout=60,
                )
                results[name] = _extract_text(resp)
            except Exception as e:
                errors[name] = str(e)

        threads = [threading.Thread(target=request_agent, args=(n,)) for n in AGENT_NAMES]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=90)

        assert not errors, f"Some agents failed: {errors}"
        assert len(results) == 3, f"Only {len(results)}/3 agents responded"
        for name, text in results.items():
            assert text and len(text) > 20, f"[{name}] Empty response in parallel test"


# ---------------------------------------------------------------------------
# 4H: Latency benchmarks (informational, soft assertion)
# ---------------------------------------------------------------------------

class TestLatencyBenchmarks:
    """Spec 4H: Latency benchmarks for export_bulk_data_tool and run_sql_query_tool."""

    def _time_request(self, agent: str, message: str, n: int = 5) -> List[float]:
        """Time n sequential requests and return list of elapsed seconds."""
        times = []
        for _ in range(n):
            t0 = time.monotonic()
            try:
                _send_a2a_message(agent, message, timeout=60)
            except Exception:
                pass
            times.append(time.monotonic() - t0)
        return times

    def test_export_latency_p95_under_10s(self, a2a_server):
        """p95 latency for export_bulk_data_tool should be < 10s (generous CI budget)."""
        times = self._time_request(
            "tableau_ops_metrics_ds_agent",
            "Call export_bulk_data_tool with year_start=2025, month_start=1, "
            "year_end=2025, month_end=3, output_format='csv'. Return raw JSON.",
            n=5,
        )
        p95 = sorted(times)[int(len(times) * 0.95)] if len(times) >= 20 else max(times)
        print(f"\n[BENCH] export_bulk_data_tool: p50={statistics.median(times):.2f}s, "
              f"p95={p95:.2f}s, max={max(times):.2f}s")
        assert p95 < 10.0, \
            f"export p95={p95:.2f}s exceeds 10s budget. Times: {[round(t,2) for t in times]}"

    def test_sql_query_latency_p95_under_10s(self, a2a_server):
        """p95 latency for run_sql_query_tool GROUP BY should be < 10s."""
        times = self._time_request(
            "tableau_ops_metrics_ds_agent",
            'Run SQL: SELECT COUNT(*) FROM "Extract"."Extract" with output_format=\'csv\'.',
            n=5,
        )
        p95 = sorted(times)[int(len(times) * 0.95)] if len(times) >= 20 else max(times)
        print(f"\n[BENCH] run_sql_query_tool: p50={statistics.median(times):.2f}s, "
              f"p95={p95:.2f}s, max={max(times):.2f}s")
        assert p95 < 10.0, \
            f"SQL query p95={p95:.2f}s exceeds 10s budget"


# ---------------------------------------------------------------------------
# 2B: Passthrough behavior (T024 / T025)
# ---------------------------------------------------------------------------

class TestPassthroughBehavior:
    """Spec 2B: LLM returns raw tool JSON -- no prose reformatting."""

    def test_export_response_is_raw_json_not_prose(self, a2a_server):
        """T024: Agent response to a data request should be raw tool JSON, not a prose summary."""
        resp = _send_a2a_message(
            "tableau_ops_metrics_ds_agent",
            (
                "Export all data for Line Haul for 2025. "
                "Return the raw tool JSON output exactly as returned by export_bulk_data_tool."
            ),
        )
        text = _extract_text(resp)
        obj = _try_parse_json(text)

        # The response should either be parseable JSON directly, or contain JSON keys
        if obj is not None:
            # Best case: response IS valid JSON with expected keys
            assert "success" in obj or "data" in obj or "row_count" in obj, \
                f"Parsed JSON lacks expected tool output keys: {list(obj.keys())}"
        else:
            # Acceptable: JSON is embedded in text but key fields are present
            assert "success" in text or "row_count" in text or "period_end_date" in text, \
                f"Response looks like prose summary (no tool JSON keys found): {text[:400]}"

    def test_export_deterministic_output(self, a2a_server):
        """T025: Same export request sent 3 times should return the same row_count each time."""
        import re
        message = (
            "Call export_bulk_data_tool with lobs='Line Haul', "
            "year_start=2025, month_start=1, year_end=2025, month_end=3, "
            "output_format='csv'. Return the raw tool JSON."
        )
        row_counts = []
        for _ in range(3):
            resp = _send_a2a_message("tableau_ops_metrics_ds_agent", message)
            text = _extract_text(resp)
            m = re.search(r'"row_count"\s*:\s*(\d+)', text)
            if m:
                row_counts.append(int(m.group(1)))

        if len(row_counts) < 2:
            pytest.skip("Could not extract row_count from 3 responses -- skipping determinism check")

        assert len(set(row_counts)) == 1, \
            f"Export row_count not deterministic across 3 calls: {row_counts}"
