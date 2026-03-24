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
                "item": "3100-00",
                "item_name": "Mileage Revenue",
                "value": -750000.0,
                "z_score": 2.8,
                "avg": -645000.0,
                "std": 37500.0
            },
            {
                "period": "2025-08",
                "item": "3200-00",
                "item_name": "Fuel Surcharge Revenue",
                "value": -180000.0,
                "z_score": 2.3,
                "avg": -120000.0,
                "std": 26000.0
            },
        ],
        "most_volatile": [
            {
                "item": "3115-00",
                "item_name": "Load/Unload",
                "avg": -15000.0,
                "std": 12000.0,
                "cv": 0.8
            },
            {
                "item": "3120-00",
                "item_name": "Stop-Offs",
                "avg": -8000.0,
                "std": 2000.0,
                "cv": 0.25  # Below threshold, should NOT generate alert
            },
        ],
        "top_drivers": [
            {"item": "3100-00", "item_name": "Mileage Revenue", "avg": -645000.0, "std": 37500.0, "cv": 0.058}
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
    assert result["metadata"]["dimension_value"] == "067"
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
        assert "item_id" in alert
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
    item_ids_with_vol = [a["item_id"] for a in vol_alerts]
    assert "3115-00" in item_ids_with_vol
    assert "3120-00" not in item_ids_with_vol

    print(f"[PASS] Volatility threshold correctly applied: {len(vol_alerts)} volatility alerts")


@pytest.mark.unit
@pytest.mark.csv_mode
@pytest.mark.asyncio
async def test_extract_alerts_sanitizes_nan_and_inf():
    """Alert payloads must not contain NaN or Infinity (Sprint 1 bugfix)."""
    import math

    mod = import_alert_scoring_tool("extract_alerts_from_analysis")
    summary = {
        "anomalies": [
            {
                "period": "2026-W10",
                "item": "x1",
                "item_name": "RatioDriver",
                "value": float("nan"),
                "z_score": float("inf"),
                "avg": 0.0,
                "std": 1.0,
            },
        ],
        "most_volatile": [
            {
                "item": "v1",
                "item_name": "VolatileInf",
                "avg": 1.0,
                "std": 1.0,
                "cv": float("inf"),
            },
        ],
        "top_drivers": [
            {
                "item_name": "RatioDriver",
                "avg": 1e-308,
                "count": 1e308,
            },
        ],
        "summary_stats": {"total_periods": 5, "grand_total": float("nan")},
    }
    result_str = await mod.extract_alerts_from_analysis(
        statistical_summary=json.dumps(summary),
        cost_center="test_cc",
    )
    result = json.loads(result_str)
    assert len(result["alerts"]) >= 1

    def _walk(obj):
        if isinstance(obj, float):
            assert math.isfinite(obj), f"non-finite float in payload: {obj}"
        elif isinstance(obj, dict):
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, list):
            for v in obj:
                _walk(v)

    _walk(result["alerts"])
    print("[PASS] No NaN/Inf in extracted alert payloads")


@pytest.mark.unit
@pytest.mark.csv_mode
@pytest.mark.asyncio
async def test_extract_alerts_skips_blocklisted_low_signal_dimension(monkeypatch):
    """Corporate-like vestigial rows should be suppressible without hiding valid alerts."""
    mod = import_alert_scoring_tool("extract_alerts_from_analysis")
    summary = {
        "anomalies": [
            {
                "period": "2026-W11",
                "item": "corp",
                "item_name": "Corporate",
                "value": 6.0,
                "avg": 1.0,
                "std": 0.2,
                "z_score": 4.0,
            },
            {
                "period": "2026-W11",
                "item": "west",
                "item_name": "West",
                "value": 130.0,
                "avg": 100.0,
                "std": 5.0,
                "z_score": 2.8,
            },
        ],
        "top_drivers": [
            {"item": "Corporate", "item_name": "Corporate", "avg": 5.0, "count": 1},
            {"item": "West", "item_name": "West", "avg": 1200.0, "count": 10},
        ],
        "summary_stats": {"total_periods": 12, "grand_total": 10_000.0},
    }
    monkeypatch.setenv("ALERT_SKIP_ITEM_NAMES", "Corporate")
    monkeypatch.setenv("ALERT_SKIP_RATIO_EXTREME_PCT_MIN", "200")
    monkeypatch.setenv("ALERT_SKIP_RATIO_ABS_VARIANCE_MAX", "10")

    result_str = await mod.extract_alerts_from_analysis(
        statistical_summary=json.dumps(summary),
        analysis_target="avg_loh",
        cost_center="test_cc",
    )
    result = json.loads(result_str)
    item_names = {str(alert.get("item_name")) for alert in result.get("alerts", [])}
    assert "Corporate" not in item_names
    assert "West" in item_names


@pytest.mark.unit
@pytest.mark.csv_mode
@pytest.mark.asyncio
async def test_extract_alerts_skips_immaterial_item_by_runtime_share(monkeypatch):
    """Runtime share-of-total should suppress low-contribution anomaly rows."""
    mod = import_alert_scoring_tool("extract_alerts_from_analysis")
    summary = {
        "anomalies": [
            {
                "period": "2026-W11",
                "item": "corp",
                "item_name": "Corporate",
                "value": 220.0,
                "avg": 20.0,
                "std": 5.0,
                "z_score": 4.0,
            },
            {
                "period": "2026-W11",
                "item": "west",
                "item_name": "West",
                "value": 2800.0,
                "avg": 2100.0,
                "std": 50.0,
                "z_score": 3.1,
            },
        ],
        "enhanced_top_drivers": [
            {"item_name": "Corporate", "share_of_total": 0.0005},
            {"item_name": "West", "share_of_total": 0.34},
        ],
        "top_drivers": [
            {"item": "Corporate", "item_name": "Corporate", "avg": 20.0},
            {"item": "West", "item_name": "West", "avg": 2100.0},
        ],
        "summary_stats": {"total_periods": 12, "grand_total": 100_000.0},
    }
    monkeypatch.delenv("ALERT_SKIP_ITEM_NAMES", raising=False)
    monkeypatch.setenv("ALERT_MATERIALITY_SHARE_MAX", "0.001")

    result_str = await mod.extract_alerts_from_analysis(
        statistical_summary=json.dumps(summary),
        analysis_target="ttl_rev_xf_sr_amt",
        cost_center="test_cc",
    )
    result = json.loads(result_str)
    item_names = {str(alert.get("item_name")) for alert in result.get("alerts", [])}
    assert "Corporate" not in item_names
    assert "West" in item_names


@pytest.mark.unit
@pytest.mark.csv_mode
@pytest.mark.asyncio
async def test_extract_alerts_honors_contract_low_activity_values(monkeypatch):
    """Contract-level low activity labels should suppress vestigial dimensions."""
    mod = import_alert_scoring_tool("extract_alerts_from_analysis")
    summary = {
        "anomalies": [
            {
                "period": "2026-W11",
                "item": "corp",
                "item_name": "Corporate",
                "value": 80.0,
                "avg": 20.0,
                "std": 5.0,
                "z_score": 3.8,
            },
            {
                "period": "2026-W11",
                "item": "west",
                "item_name": "West",
                "value": 2800.0,
                "avg": 2100.0,
                "std": 50.0,
                "z_score": 3.1,
            },
        ],
        "top_drivers": [
            {"item": "Corporate", "item_name": "Corporate", "avg": 20.0},
            {"item": "West", "item_name": "West", "avg": 2100.0},
        ],
        "summary_stats": {"total_periods": 12, "grand_total": 100_000.0},
    }
    contract = {"low_activity_dimension_values": ["Corporate"]}
    monkeypatch.delenv("ALERT_SKIP_ITEM_NAMES", raising=False)

    result_str = await mod.extract_alerts_from_analysis(
        statistical_summary=json.dumps(summary),
        analysis_target="ttl_rev_xf_sr_amt",
        cost_center="test_cc",
        contract=contract,
    )
    result = json.loads(result_str)
    item_names = {str(alert.get("item_name")) for alert in result.get("alerts", [])}
    assert "Corporate" not in item_names
    assert "West" in item_names


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
                "item_id": "3100-00",
                "dimension_value": "067",
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
    """Test that score matches the additive blend in score_alerts (impact-weighted)."""
    mod = import_alert_scoring_tool("score_alerts")

    input_data = {
        "alerts": [
            {
                "id": "test-alert-1",
                "variance_amount": 50000.0,
                "variance_pct": 10.0,
                "signals": {"a": True, "b": True, "c": False, "d": False},
                "months_flagged_in_last_3": 3,
            }
        ]
    }

    result_str = await mod.score_alerts(json.dumps(input_data))
    result = json.loads(result_str)

    alert = result["top_alerts"][0]
    expected_score = (
        alert["impact"] * 0.6
        + alert["confidence"] * 0.25
        + alert["persistence"] * 0.15
    )
    assert abs(alert["score"] - expected_score) < 0.01

    print(
        f"[PASS] Score formula verified: 0.6*impact + 0.25*confidence + 0.15*persistence = {alert['score']}"
    )


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
