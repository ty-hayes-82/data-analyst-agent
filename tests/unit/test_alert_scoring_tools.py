"""
Step 6: Unit tests for Alert Scoring Agent tools.

Tests:
- extract_alerts_from_analysis
- score_alerts
"""

import pytest
import json
from tests.utils.import_helpers import import_alert_scoring_tool


# ============================================================================
# Helper: build mock statistical summary for alert extraction
# ============================================================================

def _make_mock_statistical_summary() -> dict:
    """Build a mock statistical summary with anomalies and volatile drivers."""
    return {
        "anomalies": [
            {
                "period": "2025-07",
                "account": "3100-00",
                "account_name": "Mileage Revenue",
                "value": -750000.0,
                "z_score": 2.8,
                "avg": -645000.0,
                "std": 37500.0
            },
            {
                "period": "2025-08",
                "account": "3200-00",
                "account_name": "Fuel Surcharge Revenue",
                "value": -180000.0,
                "z_score": 2.3,
                "avg": -120000.0,
                "std": 26000.0
            },
        ],
        "most_volatile": [
            {
                "account": "3115-00",
                "account_name": "Load/Unload",
                "avg": -15000.0,
                "std": 12000.0,
                "cv": 0.8
            },
            {
                "account": "3120-00",
                "account_name": "Stop-Offs",
                "avg": -8000.0,
                "std": 2000.0,
                "cv": 0.25  # Below threshold, should NOT generate alert
            },
        ],
        "top_drivers": [
            {"account": "3100-00", "account_name": "Mileage Revenue", "avg": -645000.0, "std": 37500.0, "cv": 0.058}
        ],
        "summary_stats": {
            "total_accounts": 10,
            "total_periods": 15
        }
    }


# ============================================================================
# Tests for extract_alerts_from_analysis
# ============================================================================

@pytest.mark.unit
@pytest.mark.csv_mode
@pytest.mark.asyncio
async def test_extract_alerts_structure():
    """Test that alert extraction produces correct structure."""
    mod = import_alert_scoring_tool("extract_alerts_from_analysis")

    stats_json = json.dumps(_make_mock_statistical_summary())
    result_str = await mod.extract_alerts_from_analysis(
        statistical_summary=stats_json,
        cost_center="067"
    )
    result = json.loads(result_str)

    assert "alerts" in result
    assert "config" in result
    assert "metadata" in result
    assert result["metadata"]["cost_center"] == "067"
    assert len(result["alerts"]) > 0

    print(f"[PASS] Extracted {len(result['alerts'])} alerts")


@pytest.mark.unit
@pytest.mark.csv_mode
@pytest.mark.asyncio
async def test_extract_alerts_from_anomalies():
    """Test that anomalies are converted to alerts with proper fields."""
    mod = import_alert_scoring_tool("extract_alerts_from_analysis")

    stats_json = json.dumps(_make_mock_statistical_summary())
    result_str = await mod.extract_alerts_from_analysis(
        statistical_summary=stats_json,
        cost_center="067"
    )
    result = json.loads(result_str)

    alerts = result["alerts"]
    # Should have alerts from anomalies
    anomaly_alerts = [a for a in alerts if "anomaly" in a["id"]]
    assert len(anomaly_alerts) >= 2

    for alert in anomaly_alerts:
        assert "id" in alert
        assert "period" in alert
        assert "gl_code" in alert
        assert "variance_amount" in alert
        assert "variance_pct" in alert
        assert "signals" in alert
        assert isinstance(alert["signals"], dict)
        assert "months_flagged_in_last_3" in alert

    print(f"[PASS] {len(anomaly_alerts)} anomaly alerts with correct structure")


@pytest.mark.unit
@pytest.mark.csv_mode
@pytest.mark.asyncio
async def test_extract_alerts_volatility_threshold():
    """Test that only high-CV accounts generate volatility alerts."""
    mod = import_alert_scoring_tool("extract_alerts_from_analysis")

    stats_json = json.dumps(_make_mock_statistical_summary())
    result_str = await mod.extract_alerts_from_analysis(
        statistical_summary=stats_json,
        cost_center="067"
    )
    result = json.loads(result_str)

    alerts = result["alerts"]
    vol_alerts = [a for a in alerts if "volatility" in a["id"]]

    # 3115-00 has CV=0.8 (above 0.5 threshold) - should have alert
    # 3120-00 has CV=0.25 (below 0.5 threshold) - should NOT have alert
    gl_codes_with_vol = [a["gl_code"] for a in vol_alerts]
    assert "3115-00" in gl_codes_with_vol
    assert "3120-00" not in gl_codes_with_vol

    print(f"[PASS] Volatility threshold correctly applied: {len(vol_alerts)} volatility alerts")


@pytest.mark.unit
@pytest.mark.csv_mode
@pytest.mark.asyncio
async def test_extract_alerts_empty_input():
    """Test alert extraction with empty input."""
    mod = import_alert_scoring_tool("extract_alerts_from_analysis")

    result_str = await mod.extract_alerts_from_analysis(
        statistical_summary="",
        cost_center="067"
    )
    result = json.loads(result_str)

    assert "alerts" in result
    assert len(result["alerts"]) == 0

    print("[PASS] Empty input produces zero alerts")


# ============================================================================
# Tests for score_alerts
# ============================================================================

@pytest.mark.unit
@pytest.mark.csv_mode
@pytest.mark.asyncio
async def test_score_alerts_structure():
    """Test that alert scoring produces correct output structure."""
    mod = import_alert_scoring_tool("score_alerts")

    input_data = {
        "alerts": [
            {
                "id": "2025-07-3100-00-anomaly",
                "period": "2025-07",
                "gl_code": "3100-00",
                "cost_center": "067",
                "category": "financial_variance",
                "variance_amount": 105000.0,
                "variance_pct": 16.3,
                "signals": {
                    "mad_outlier": True,
                    "change_point": False,
                    "mom_breach": True,
                    "yoy_breach": False,
                    "seasonal_outlier": True
                },
                "months_flagged_in_last_3": 2
            }
        ],
        "config": {"top_n": 10, "min_score_threshold": 0.05}
    }

    result_str = await mod.score_alerts(json.dumps(input_data))
    result = json.loads(result_str)

    assert result["analysis_type"] == "alert_scoring"
    assert result["total_alerts_received"] == 1
    assert len(result["top_alerts"]) >= 1

    alert = result["top_alerts"][0]
    assert "score" in alert
    assert "impact" in alert
    assert "confidence" in alert
    assert "persistence" in alert
    assert "priority" in alert
    assert alert["priority"] in ["high", "medium", "low"]

    print(f"[PASS] Alert scored: score={alert['score']}, priority={alert['priority']}")


@pytest.mark.unit
@pytest.mark.csv_mode
@pytest.mark.asyncio
async def test_score_alerts_scoring_formula():
    """Test that score = impact * confidence * persistence."""
    mod = import_alert_scoring_tool("score_alerts")

    input_data = {
        "alerts": [
            {
                "id": "test-alert-1",
                "variance_amount": 50000.0,  # = 1.0 impact (50K / 50K)
                "variance_pct": 10.0,
                "signals": {"a": True, "b": True, "c": False, "d": False},  # 2/4 = 0.5 confidence
                "months_flagged_in_last_3": 3  # 3/3 = 1.0 persistence
            }
        ]
    }

    result_str = await mod.score_alerts(json.dumps(input_data))
    result = json.loads(result_str)

    alert = result["top_alerts"][0]
    expected_score = alert["impact"] * alert["confidence"] * alert["persistence"]
    assert abs(alert["score"] - expected_score) < 0.01

    print(f"[PASS] Score formula verified: {alert['impact']} * {alert['confidence']} * {alert['persistence']} = {alert['score']}")


@pytest.mark.unit
@pytest.mark.csv_mode
@pytest.mark.asyncio
async def test_score_alerts_priority_classification():
    """Test priority classification thresholds."""
    mod = import_alert_scoring_tool("score_alerts")

    input_data = {
        "alerts": [
            {
                "id": "high-alert",
                "variance_amount": 200000.0,
                "variance_pct": 40.0,
                "signals": {"a": True, "b": True, "c": True},
                "months_flagged_in_last_3": 3
            },
            {
                "id": "low-alert",
                "variance_amount": 5000.0,
                "variance_pct": 2.0,
                "signals": {"a": False, "b": True, "c": False},
                "months_flagged_in_last_3": 1
            },
        ]
    }

    result_str = await mod.score_alerts(json.dumps(input_data))
    result = json.loads(result_str)

    all_scored = result["all_scored_alerts"]
    alerts_by_id = {a["id"]: a for a in all_scored}

    # High-impact alert should be high/medium priority
    assert "high-alert" in alerts_by_id
    assert alerts_by_id["high-alert"]["priority"] in ["high", "medium"]

    # Low-impact alert may be filtered by min_score_threshold;
    # check it was either scored as low or filtered out entirely
    if "low-alert" in alerts_by_id:
        assert alerts_by_id["low-alert"]["priority"] in ["low", "medium"]
        print(f"[PASS] Priority: high-alert={alerts_by_id['high-alert']['priority']}, "
              f"low-alert={alerts_by_id['low-alert']['priority']}")
    else:
        # Filtered by min_score_threshold - that's expected for very low scores
        assert result["total_alerts_received"] == 2
        print(f"[PASS] Priority: high-alert={alerts_by_id['high-alert']['priority']}, "
              f"low-alert filtered out (score below threshold)")


@pytest.mark.unit
@pytest.mark.csv_mode
@pytest.mark.asyncio
async def test_score_alerts_empty_alerts():
    """Test scoring with empty alerts list."""
    mod = import_alert_scoring_tool("score_alerts")

    input_data = {"alerts": []}
    result_str = await mod.score_alerts(json.dumps(input_data))
    result = json.loads(result_str)

    assert "error" in result
    print("[PASS] Empty alerts handled gracefully")


@pytest.mark.unit
@pytest.mark.csv_mode
@pytest.mark.asyncio
async def test_score_alerts_invalid_json():
    """Test scoring with invalid JSON."""
    mod = import_alert_scoring_tool("score_alerts")

    result_str = await mod.score_alerts("not valid json")
    result = json.loads(result_str)

    assert "error" in result
    print("[PASS] Invalid JSON handled gracefully")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s", "--tb=short"])
