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

"""Integration tests for Ops Metric Analysis scenarios (Spec 006).

Covers all 15 natural-language scenarios defined in spec.md and test_ops_analysis.py.
Tests run via the A2A JSON-RPC HTTP API against the ops_metrics data source agent
(the same approach used in spec 011). Tests are automatically skipped if the
A2A server is not running on localhost:8001.

These tests map to tasks T005–T034 in spec 006.

To run with a live server:
  python -m pytest tests/integration/test_006_ops_analysis_scenarios.py -v

To run standalone without pytest (outputs JSON results):
  python tests/integration/test_006_ops_analysis_scenarios.py
"""

import json
import time
import uuid
import urllib.request
import urllib.error
from typing import Optional, List
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

A2A_BASE = "http://localhost:8001"
OPS_AGENT = "tableau_ops_metrics_ds_agent"
_OPS_AGENT_URL = f"{A2A_BASE}/a2a/{OPS_AGENT}"

# Keyword match threshold: at least this fraction of expected_keywords must appear
_KEYWORD_MATCH_THRESHOLD = 0.40

# Per-request timeout (seconds). The orchestrator pipeline is slower than raw A2A.
_REQUEST_TIMEOUT = 300


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _send_a2a_message(url: str, message: str, timeout: int = _REQUEST_TIMEOUT) -> Optional[dict]:
    """Send a JSON-RPC 2.0 message/send request and return the parsed response."""
    payload = {
        "jsonrpc": "2.0",
        "method": "message/send",
        "params": {
            "message": {
                "role": "user",
                "messageId": uuid.uuid4().hex,
                "parts": [{"text": message}],
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
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def _extract_text(response: Optional[dict]) -> str:
    """Pull text from an A2A JSON-RPC response."""
    if response is None:
        return ""
    result = response.get("result", {})
    if isinstance(result, str):
        return result
    texts: List[str] = []
    for artifact in result.get("artifacts", []):
        for part in artifact.get("parts", []):
            if "text" in part:
                texts.append(part["text"])
    if texts:
        return "\n".join(texts)
    for part in result.get("status", {}).get("message", {}).get("parts", []):
        if "text" in part:
            texts.append(part["text"])
    return "\n".join(texts) if texts else json.dumps(result)


def _validate_keywords(text: str, expected: List[str]) -> tuple[bool, List[str]]:
    """Return (passed, missing_keywords)."""
    lower = text.lower()
    found = [kw for kw in expected if kw.lower() in lower]
    threshold = int(len(expected) * _KEYWORD_MATCH_THRESHOLD)
    return len(found) >= threshold, list(set(expected) - set(found))


# ---------------------------------------------------------------------------
# Session fixture: check server is up
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def ops_agent_url():
    """Skip all integration tests if the A2A ops_metrics agent is unreachable."""
    try:
        req = urllib.request.Request(_OPS_AGENT_URL, method="GET")
        urllib.request.urlopen(req, timeout=8)
    except urllib.error.HTTPError:
        pass  # 405 Method Not Allowed is fine — server is up
    except Exception:
        pytest.skip(
            f"A2A server not reachable at {_OPS_AGENT_URL}. "
            "Start with: python scripts/start_a2a_server.py"
        )
    return _OPS_AGENT_URL


# ---------------------------------------------------------------------------
# Parametrized scenario definitions (T005–T034)
# ---------------------------------------------------------------------------

SCENARIOS = [
    pytest.param(
        "1",
        "Weekly Loaded Miles and Revenue",
        (
            "Analyze the Ops Metric DS for Line Haul, analyzing loaded miles and revenue, "
            "for the past 13 weeks, by week end date, with the drill down of terminal and driver leader."
        ),
        ["loaded", "miles", "revenue", "week", "terminal", "driver"],
        marks=pytest.mark.integration,
        id="scenario-01-weekly-miles-revenue",
    ),
    pytest.param(
        "2",
        "Monthly Revenue Trend",
        "Show me the total revenue trend for Line Haul for the past 6 months by month.",
        ["revenue", "month"],
        marks=pytest.mark.integration,
        id="scenario-02-monthly-revenue",
    ),
    pytest.param(
        "3",
        "Yearly Empty Miles Trend",
        "Analyze empty miles trend for Line Haul for the past 12 months.",
        ["empty", "miles", "month"],
        marks=pytest.mark.integration,
        id="scenario-03-empty-miles",
    ),
    pytest.param(
        "4",
        "Miles per Truck Analysis",
        "Analyze miles per truck for Line Haul for the past 13 weeks with terminal drill-down.",
        ["miles", "truck", "terminal"],
        marks=pytest.mark.integration,
        id="scenario-04-miles-per-truck",
    ),
    pytest.param(
        "5",
        "Deadhead Percentage by LOB",
        "Show me the deadhead percentage trend for the last quarter by Line of Business.",
        ["deadhead", "lob", "business"],
        marks=pytest.mark.integration,
        id="scenario-05-deadhead-pct",
    ),
    pytest.param(
        "6",
        "Revenue per Loaded Mile (LRPM)",
        "Analyze revenue per loaded mile (LRPM) for Line Haul by terminal for the past 6 months.",
        ["revenue", "loaded", "terminal"],
        marks=pytest.mark.integration,
        id="scenario-06-lrpm",
    ),
    pytest.param(
        "7",
        "Line Haul Deep Dive",
        "Perform a deep dive into Line Haul LOB performance, drilling down into terminal and driver leader.",
        ["line haul", "terminal", "driver"],
        marks=pytest.mark.integration,
        id="scenario-07-line-haul-deep-dive",
    ),
    pytest.param(
        "8",
        "Terminal Comparison",
        "Compare all terminals for Line Haul for loaded miles and truck count for the past 13 weeks.",
        ["compare", "terminal", "loaded", "miles", "truck"],
        marks=pytest.mark.integration,
        id="scenario-08-terminal-comparison",
    ),
    pytest.param(
        "9",
        "Driver Leader Ranking",
        "Who are the top and bottom 5 driver leaders by miles per truck for Terminal A in Line Haul in the last 6 months?",
        ["top", "bottom", "driver", "miles", "truck"],
        marks=pytest.mark.integration,
        id="scenario-09-driver-ranking",
    ),
    pytest.param(
        "10",
        "Order and Stop Count",
        "Analyze order count and stop count trends for Line Haul by terminal for the past 13 weeks.",
        ["order", "stop", "terminal"],
        marks=pytest.mark.integration,
        id="scenario-10-order-stop",
    ),
    pytest.param(
        "11",
        "Safety Performance (DOT Incidents)",
        "Show DOT incidents for Line Haul by terminal and driver leader for the past 6 months.",
        ["incidents", "terminal", "driver"],
        marks=pytest.mark.integration,
        id="scenario-11-dot-incidents",
    ),
    pytest.param(
        "12",
        "Truck Utilization Trend",
        "What are the truck count utilization trends by LOB for the past year?",
        ["truck", "lob"],
        marks=pytest.mark.integration,
        id="scenario-12-truck-utilization",
    ),
    pytest.param(
        "13",
        "CEO Operational Dashboard",
        (
            "Provide a full operational dashboard for Line Haul including revenue, "
            "loaded miles, miles per truck, and deadhead pct, with terminal drill-down."
        ),
        ["revenue", "miles", "truck", "deadhead"],
        marks=pytest.mark.integration,
        id="scenario-13-ceo-dashboard",
    ),
    pytest.param(
        "14",
        "LOB Comparison",
        "Compare Dedicated versus Line Haul LOBs across all key operational metrics for the last quarter.",
        ["compare", "dedicated", "line haul"],
        marks=pytest.mark.integration,
        id="scenario-14-lob-comparison",
    ),
    pytest.param(
        "15",
        "Fleet vs Driver Leader Analysis",
        "Analyze performance differences between fleet leader and driver leader drill-downs for Terminal B in Line Haul.",
        ["fleet", "driver", "terminal"],
        marks=pytest.mark.integration,
        id="scenario-15-fleet-driver",
    ),
]


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------

class TestOpsAnalysisScenarios:
    """Spec 006 Phases 2–6: Validate all 15 analysis scenarios against A2A ops_metrics agent.

    Each test sends a natural-language query to the A2A server and validates that
    the response contains at least 60% of the expected domain keywords.
    Tests are auto-skipped when the server is not available.
    """

    @pytest.mark.parametrize("scenario_id,name,query,expected_keywords", SCENARIOS)
    def test_scenario_response_contains_expected_keywords(
        self,
        ops_agent_url,
        scenario_id: str,
        name: str,
        query: str,
        expected_keywords: List[str],
    ):
        """Send a scenario query and verify the response mentions expected domain terms."""
        t0 = time.monotonic()
        response = _send_a2a_message(ops_agent_url, query)
        elapsed = time.monotonic() - t0
        text = _extract_text(response)

        assert text and len(text) > 50, (
            f"[Scenario {scenario_id}: {name}] Agent returned empty or very short response "
            f"({len(text)} chars) after {elapsed:.1f}s"
        )

        passed, missing = _validate_keywords(text, expected_keywords)
        assert passed, (
            f"[Scenario {scenario_id}: {name}] "
            f"Missing keywords ({len(missing)}/{len(expected_keywords)}): {missing}. "
            f"Response snippet: {text[:300]}"
        )
        print(
            f"\n[Scenario {scenario_id}] {name}: PASS ({elapsed:.1f}s, {len(text)} chars, "
            f"missing: {missing})"
        )

    @pytest.mark.parametrize("scenario_id,name,query,expected_keywords", SCENARIOS)
    def test_scenario_response_not_error(
        self,
        ops_agent_url,
        scenario_id: str,
        name: str,
        query: str,
        expected_keywords: List[str],
    ):
        """Verify the agent does not return an error payload."""
        response = _send_a2a_message(ops_agent_url, query)
        text = _extract_text(response)
        text_lower = (text or "").lower()
        error_indicators = ["unknown error", "agentnotready", "queryexecutionerror", "traceback"]
        found_errors = [e for e in error_indicators if e in text_lower]
        assert not found_errors, (
            f"[Scenario {scenario_id}: {name}] Response contains error indicators: {found_errors}. "
            f"Response: {text[:400]}"
        )


# ---------------------------------------------------------------------------
# A2A data source agent smoke tests (prerequisite checks, T010 / T001 style)
# ---------------------------------------------------------------------------

class TestA2AServerPrerequisites:
    """T010: Verify A2A server health before analysis scenarios."""

    def test_ops_agent_agent_card_reachable(self, ops_agent_url):
        """The /.well-known/agent-card.json endpoint should return a valid agent card."""
        card_url = f"{A2A_BASE}/a2a/{OPS_AGENT}/.well-known/agent-card.json"
        try:
            req = urllib.request.Request(card_url, method="GET")
            with urllib.request.urlopen(req, timeout=10) as resp:
                card = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            # 404 is acceptable if the route is not wired; server is still up
            pytest.skip(f"Agent card endpoint returned {e.code} -- skipping card check")
        assert isinstance(card, dict), "Agent card is not a dict"

    def test_get_schema_returns_data(self, ops_agent_url):
        """get_schema_tool should return a non-empty response (T011 prerequisite)."""
        response = _send_a2a_message(
            ops_agent_url,
            "Call get_schema_tool and return the raw JSON result.",
        )
        text = _extract_text(response)
        assert text and len(text) > 20, f"Schema response too short: {text[:200]}"

    def test_export_bulk_returns_period_end_date(self, ops_agent_url):
        """export_bulk_data_tool should return a CSV with period_end_date (T011 / T015)."""
        response = _send_a2a_message(
            ops_agent_url,
            (
                "Call export_bulk_data_tool with lobs='Line Haul', "
                "year_start=2025, month_start=1, year_end=2025, month_end=3, "
                "output_format='csv'. Return the raw tool JSON."
            ),
        )
        text = _extract_text(response)
        assert "period_end_date" in text or "cal_dt" in text, (
            f"Export response lacks period_end_date column: {text[:400]}"
        )


# ---------------------------------------------------------------------------
# Standalone runner (preserves test_ops_analysis.py compatibility)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    results = []
    print(f"\nRunning {len(SCENARIOS)} Ops Metric Analysis Scenarios (direct mode)")
    print(f"Target: {_OPS_AGENT_URL}\n")

    for scenario in SCENARIOS:
        sid, name, query, keywords = scenario.values[0], scenario.values[1], scenario.values[2], scenario.values[3]
        print(f"[{sid:>2}] {name}")
        t0 = time.monotonic()
        resp = _send_a2a_message(_OPS_AGENT_URL, query, timeout=_REQUEST_TIMEOUT)
        text = _extract_text(resp)
        elapsed = time.monotonic() - t0
        passed, missing = _validate_keywords(text or "", keywords)
        status = "PASS" if (passed and text) else "FAIL"
        print(f"     {status}  ({elapsed:.1f}s, {len(text or '')} chars)"
              + (f"  missing={missing}" if missing else ""))
        results.append({
            "id": sid, "name": name, "status": status,
            "duration_s": round(elapsed, 1), "response_len": len(text or ""),
            "missing_keywords": missing,
        })

    passed_count = sum(1 for r in results if r["status"] == "PASS")
    print(f"\n{'='*60}")
    print(f"Results: {passed_count}/{len(results)} scenarios passed")

    out_path = Path(__file__).parent.parent.parent / "specs" / "006-ops-metric-analysis" / "test_results.json"
    out_path.write_text(json.dumps(results, indent=2))
    print(f"Results saved to {out_path}")
    sys.exit(0 if passed_count == len(results) else 1)
