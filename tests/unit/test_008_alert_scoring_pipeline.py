"""
Spec 008 — Phase 3: Unit tests for compute_severity() and AlertScoringPipeline helpers.

Tests the code-based severity calculator and related scoring logic that replaces
the AlertScoringCoordinator LLM call.
"""

import asyncio
import importlib
import json
from pathlib import Path
import pytest


# ---------------------------------------------------------------------------
# Import helpers
# ---------------------------------------------------------------------------

def _import_compute_severity():
    mod = importlib.import_module(
        "data_analyst_agent.sub_agents.alert_scoring_agent.tools.compute_severity"
    )
    return mod.compute_severity


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

def _scored_digest(
    high=0, medium=0, low=0, total=0, top_alerts=None
) -> dict:
    all_scored = []
    if top_alerts is None:
        top_alerts = []
    return {
        "analysis_type": "alert_scoring",
        "total_alerts_received": total or (high + medium + low),
        "total_alerts_scored": total or (high + medium + low),
        "high_priority_count": high,
        "medium_priority_count": medium,
        "low_priority_count": low,
        "top_alerts": top_alerts,
        "all_scored_alerts": all_scored,
    }


def _alert(score: float, priority: str = "high") -> dict:
    return {"id": "test", "score": score, "priority": priority, "impact": 1.0, "confidence": 1.0, "persistence": 1.0}


# ============================================================================
# T062 — compute_severity: high priority
# ============================================================================

@pytest.mark.unit
def test_severity_high_priority():
    """compute_severity with high_priority_count=2 and top_score=0.8 → 0.92."""
    cs = _import_compute_severity()
    digest = _scored_digest(high=2, medium=0, low=0, total=2, top_alerts=[_alert(0.8)])
    result = cs(digest)
    # Formula: 0.6 + 0.8 * 0.4 = 0.6 + 0.32 = 0.92
    assert result["severity_score"] == pytest.approx(0.92, abs=0.001)
    assert result["high_priority_count"] == 2
    assert result["top_alert_score"] == pytest.approx(0.8, abs=0.001)
    print(f"[PASS] severity_score={result['severity_score']} (expected 0.92)")


@pytest.mark.unit
def test_severity_high_priority_max():
    """High priority with top_score=1.0 → severity_score = 1.0."""
    cs = _import_compute_severity()
    digest = _scored_digest(high=1, total=1, top_alerts=[_alert(1.0)])
    result = cs(digest)
    # 0.6 + 1.0 * 0.4 = 1.0
    assert result["severity_score"] == pytest.approx(1.0, abs=0.001)
    print(f"[PASS] severity_score={result['severity_score']} (expected 1.0)")


# ============================================================================
# T063 — compute_severity: medium only
# ============================================================================

@pytest.mark.unit
def test_severity_medium_only():
    """compute_severity with medium only and top_score=0.5 → severity_score = 0.45."""
    cs = _import_compute_severity()
    digest = _scored_digest(high=0, medium=3, low=0, total=3, top_alerts=[_alert(0.5, "medium")])
    result = cs(digest)
    # Formula: 0.3 + 0.5 * 0.3 = 0.3 + 0.15 = 0.45
    assert result["severity_score"] == pytest.approx(0.45, abs=0.001)
    assert result["medium_priority_count"] == 3
    print(f"[PASS] severity_score={result['severity_score']} (expected 0.45)")


@pytest.mark.unit
def test_severity_medium_only_max():
    """Medium only with top_score=1.0 → severity_score = 0.6."""
    cs = _import_compute_severity()
    digest = _scored_digest(high=0, medium=1, total=1, top_alerts=[_alert(1.0, "medium")])
    result = cs(digest)
    # 0.3 + 1.0 * 0.3 = 0.6
    assert result["severity_score"] == pytest.approx(0.6, abs=0.001)
    print(f"[PASS] severity_score={result['severity_score']} (expected 0.6)")


# ============================================================================
# T064 — compute_severity: no alerts
# ============================================================================

@pytest.mark.unit
def test_severity_no_alerts():
    """compute_severity with no alerts → severity_score = 0.0."""
    cs = _import_compute_severity()
    digest = _scored_digest(high=0, medium=0, low=0, total=0, top_alerts=[])
    result = cs(digest)
    assert result["severity_score"] == 0.0
    assert result["top_alert_score"] == 0.0
    assert "No actionable" in result["threshold_detail"]
    print(f"[PASS] severity_score=0.0 (no alerts)")


# ============================================================================
# Additional: low priority only
# ============================================================================

@pytest.mark.unit
def test_severity_low_only():
    """Low only → severity_score = top_alert_score."""
    cs = _import_compute_severity()
    digest = _scored_digest(high=0, medium=0, low=2, total=2, top_alerts=[_alert(0.3, "low")])
    result = cs(digest)
    # Formula: top_alert_score = 0.3
    assert result["severity_score"] == pytest.approx(0.3, abs=0.001)
    print(f"[PASS] severity_score={result['severity_score']} (low-only = top_score)")


@pytest.mark.unit
def test_severity_clamped_to_one():
    """Severity score is clamped to [0.0, 1.0]."""
    cs = _import_compute_severity()
    # Even with top_score > 1.0 (edge case), should not exceed 1.0
    digest = _scored_digest(high=1, total=1, top_alerts=[_alert(2.0)])
    result = cs(digest)
    assert result["severity_score"] <= 1.0
    print(f"[PASS] severity_score clamped to {result['severity_score']}")


@pytest.mark.unit
def test_severity_empty_top_alerts():
    """Handles empty top_alerts list (top_score defaults to 0.0)."""
    cs = _import_compute_severity()
    # High count but no top_alerts (edge case)
    digest = _scored_digest(high=1, total=1, top_alerts=[])
    result = cs(digest)
    # 0.6 + 0.0 * 0.4 = 0.6
    assert result["severity_score"] == pytest.approx(0.6, abs=0.001)
    assert result["top_alert_score"] == 0.0
    print(f"[PASS] Empty top_alerts handled (severity_score={result['severity_score']})")


# ============================================================================
# Result schema validation
# ============================================================================

@pytest.mark.unit
def test_compute_severity_schema():
    """compute_severity returns all required schema fields."""
    cs = _import_compute_severity()
    digest = _scored_digest(high=1, medium=2, low=3, total=6,
                             top_alerts=[_alert(0.75)])
    result = cs(digest)
    required = [
        "severity_score", "threshold_detail", "high_priority_count",
        "medium_priority_count", "low_priority_count", "top_alert_score",
        "total_alerts",
    ]
    for field in required:
        assert field in result, f"Missing field: {field}"
    assert 0.0 <= result["severity_score"] <= 1.0
    print(f"[PASS] Schema complete: {list(result.keys())}")


# ---------------------------------------------------------------------------
# T065: End-to-end alert pipeline using statistical_summary_sample.json fixture
# ---------------------------------------------------------------------------

class TestAlertPipelineEndToEnd:
    """T065: Full extract->score->severity pipeline using fixture input."""

    @pytest.fixture(scope="class")
    def fixture_json_str(self):
        """Load statistical_summary_sample.json from tests/fixtures/008/."""
        fixture_path = Path(__file__).parent.parent / "fixtures" / "008" / "statistical_summary_sample.json"
        if not fixture_path.exists():
            pytest.skip(f"Fixture not found: {fixture_path}")
        with open(fixture_path) as f:
            return f.read()

    def _extract_alerts(self, fixture_json_str: str, cost_center: str = "test-067") -> dict:
        extract_alerts_from_analysis = importlib.import_module(
            "data_analyst_agent.sub_agents.alert_scoring_agent.tools.extract_alerts_from_analysis"
        ).extract_alerts_from_analysis
        return json.loads(
            asyncio.run(extract_alerts_from_analysis(statistical_summary=fixture_json_str, cost_center=cost_center))
        )

    def _score(self, extracted: dict) -> dict:
        score_alerts = importlib.import_module(
            "data_analyst_agent.sub_agents.alert_scoring_agent.tools.score_alerts"
        ).score_alerts
        return json.loads(asyncio.run(score_alerts(data=json.dumps(extracted))))

    def _severity(self, scored: dict) -> dict:
        compute_severity = importlib.import_module(
            "data_analyst_agent.sub_agents.alert_scoring_agent.tools.compute_severity"
        ).compute_severity
        return compute_severity(scored)

    def test_extract_alerts_returns_alerts_list(self, fixture_json_str):
        """extract_alerts_from_analysis with sample fixture should produce at least 1 alert."""
        result = self._extract_alerts(fixture_json_str)
        assert "alerts" in result, f"No 'alerts' key in output: {list(result.keys())}"
        assert len(result["alerts"]) > 0, "No alerts extracted from fixture"

    def test_score_alerts_produces_scored_digest(self, fixture_json_str):
        """Full extract + score pipeline produces a scored digest with top_alerts."""
        extracted = self._extract_alerts(fixture_json_str)
        scored = self._score(extracted)
        assert "top_alerts" in scored, f"No top_alerts in scored output: {list(scored.keys())}"
        assert "total_alerts_scored" in scored

    def test_full_pipeline_severity_is_valid_range(self, fixture_json_str):
        """Full extract->score->severity pipeline produces severity_score in [0, 1]."""
        extracted = self._extract_alerts(fixture_json_str)
        scored = self._score(extracted)
        severity = self._severity(scored)
        assert 0.0 <= severity["severity_score"] <= 1.0, \
            f"severity_score out of range: {severity['severity_score']}"
        print(
            f"\n[T065] Pipeline result: severity={severity['severity_score']}, "
            f"high={severity['high_priority_count']}, "
            f"medium={severity['medium_priority_count']}, "
            f"low={severity['low_priority_count']}"
        )

    def test_fixture_anomalies_produce_correct_alert_ids(self, fixture_json_str):
        """Anomaly alert IDs should follow the {period}-{item_id}-anomaly pattern."""
        result = self._extract_alerts(fixture_json_str)
        anomaly_alerts = [a for a in result["alerts"] if a.get("id", "").endswith("-anomaly")]
        assert len(anomaly_alerts) > 0, "No anomaly alerts extracted from fixture"
        for alert in anomaly_alerts:
            parts = alert["id"].split("-")
            assert parts[-1] == "anomaly", f"Unexpected alert id format: {alert['id']}"

    def test_fixture_change_points_produce_changepoint_alerts(self, fixture_json_str):
        """change_points in fixture should produce alerts with category=structural_break."""
        result = self._extract_alerts(fixture_json_str)
        cp_alerts = [a for a in result["alerts"] if a.get("category") == "structural_break"]
        assert len(cp_alerts) > 0, "No structural_break alerts extracted from fixture"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s", "--tb=short"])
