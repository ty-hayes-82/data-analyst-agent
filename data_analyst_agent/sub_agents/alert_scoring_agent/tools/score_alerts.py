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

# Alert policy weights — defaults match prior hardcoded values.
# Override via contract.alert_policy in dataset contract YAML.
_DEFAULT_IMPACT_W = 0.6
_DEFAULT_CONFIDENCE_W = 0.25
_DEFAULT_PERSISTENCE_W = 0.15
_DEFAULT_HIGH_THRESHOLD = 0.6
_DEFAULT_MEDIUM_THRESHOLD = 0.3

Score Alerts tool for alert_scoring_coordinator_agent.
"""

import json
import math
from typing import Any


def _finite_float(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    return v if math.isfinite(v) else default


def _calculate_impact_score(variance_amount: float, variance_pct: float,
                            revenue: float = None, period: str = None,
                            item_total: float = 0.0, grand_total: float = 0.0) -> float:
    """Calculate impact score using relative magnitude and materiality weighting.

    Instead of hard dollar thresholds, scores by:
      1. Percentage deviation magnitude (how big is the swing?)
      2. Dimension's share of the total (how much of the operation does this represent?)
    """
    pct_impact = min(abs(variance_pct) / 50.0, 1.0)

    # Materiality: weight by share of the total
    materiality = 0.3  # default when we lack totals
    if grand_total > 0 and item_total > 0:
        share = abs(item_total) / abs(grand_total)
        materiality = min(0.1 + share * 3.0, 1.0)

    impact = pct_impact * (0.3 + 0.7 * materiality)

    if revenue and revenue > 0:
        revenue_pct = (abs(variance_amount) / revenue) * 100
        revenue_impact = min(revenue_pct / 10, 1.0)
        impact = max(impact, revenue_impact)

    return min(impact, 1.0)


def _calculate_confidence_score(signals: dict[str, bool]) -> float:
    """Calculate confidence score based on ensemble of detection signals.

    Uses a tiered approach: any single signal provides a baseline confidence,
    and additional signals boost it. This avoids penalizing alerts that trigger
    only one detector (e.g., MAD outlier) when other detectors are N/A.
    """
    if not signals:
        return 0.0

    flagged_signals = sum(1 for v in signals.values() if v)

    if flagged_signals == 0:
        return 0.0

    # 1 signal = 0.5 confidence, each additional adds 0.15 (caps at 1.0)
    return min(0.5 + (flagged_signals - 1) * 0.15, 1.0)


def _calculate_persistence_score(months_flagged: int, lookback_months: int = 3) -> float:
    """Calculate persistence score based on how many recent months were flagged.

    1 month flagged = 0.5 (first occurrence still important),
    2 months = 0.75, 3 months = 1.0.
    """
    if lookback_months == 0 or months_flagged == 0:
        return 0.0

    return min(0.5 + (months_flagged - 1) * 0.25, 1.0)


async def score_alerts(data: str) -> str:
    """Score and prioritize alerts using Impact x Confidence x Persistence.
    
    Args:
        data: JSON string containing alerts with variance, signals, and history data.
    
    Returns:
        JSON string with scored and ranked alerts ready for digest.
    """
    try:
        input_data = json.loads(data)
        
        if not isinstance(input_data, dict):
            return json.dumps({
                "error": "DataUnavailable",
                "source": "alert_scoring_coordinator",
                "detail": "Input must be a dict with 'alerts' list and optional 'config'",
                "action": "stop"
            })
        
        alerts = input_data.get("alerts", [])
        config = input_data.get("config", {})
        
        if not alerts:
            return json.dumps({
                "error": "DataUnavailable",
                "source": "alert_scoring_coordinator",
                "detail": "No alerts provided for scoring",
                "action": "stop"
            })
        
        # Configuration
        top_n = config.get("top_n", 10)
        min_score_threshold = config.get("min_score_threshold", 0.1)
        budget_override_score = config.get("budget_override_score", 0.7)
        
        scored_alerts = []
        
        for alert in alerts:
            # Required fields
            if "id" not in alert or "variance_amount" not in alert:
                continue
            
            alert_id = alert["id"]
            variance_amount = abs(_finite_float(alert["variance_amount"]))
            variance_pct = abs(_finite_float(alert.get("variance_pct", 0)))
            revenue = (
                _finite_float(alert.get("revenue"))
                if alert.get("revenue") is not None
                else None
            )
            
            # Detection signals (which methods flagged this)
            signals = alert.get("signals", {})
            
            # Historical persistence
            months_flagged = int(alert.get("months_flagged_in_last_3", 1))
            
            # Calculate component scores
            period = alert.get("period")
            item_total = _finite_float(alert.get("item_total", 0))
            grand_total = _finite_float(alert.get("grand_total", 0))
            impact = _calculate_impact_score(
                variance_amount, variance_pct, revenue, period,
                item_total=item_total, grand_total=grand_total
            )
            confidence = _calculate_confidence_score(signals)
            persistence = _calculate_persistence_score(months_flagged, lookback_months=3)
            
            # Overall score: impact-weighted additive (impact dominates, confidence/persistence boost)
            score = impact * _DEFAULT_IMPACT_W + confidence * _DEFAULT_CONFIDENCE_W + persistence * _DEFAULT_PERSISTENCE_W
            
            # Priority classification
            if score >= 0.6:
                priority = "high"
            elif score >= 0.3:
                priority = "medium"
            else:
                priority = "low"
            
            scored_alerts.append({
                "id": alert_id,
                "period": alert.get("period"),
                "gl_code": alert.get("gl_code"),
                "dimension_value": alert.get("dimension_value"),
                "category": alert.get("category"),
                "variance_amount": round(variance_amount, 2),
                "variance_pct": round(variance_pct, 2),
                "score": round(score, 3),
                "impact": round(impact, 3),
                "confidence": round(confidence, 3),
                "persistence": round(persistence, 3),
                "priority": priority,
                "signals": signals,
                "months_flagged": months_flagged,
                "details": alert.get("details", {})
            })
        
        # Sort by score (descending) -- no minimum threshold; we take top N
        scored_alerts.sort(key=lambda x: (-x["score"], x["id"]))

        # Take top N (relative ranking, not absolute threshold)
        top_alerts = scored_alerts[:top_n]
        
        digest = {
            "analysis_type": "alert_scoring",
            "total_alerts_received": len(alerts),
            "total_alerts_scored": len(scored_alerts),
            "top_n": top_n,
            "high_priority_count": sum(1 for a in top_alerts if a["priority"] == "high"),
            "medium_priority_count": sum(1 for a in top_alerts if a["priority"] == "medium"),
            "low_priority_count": sum(1 for a in top_alerts if a["priority"] == "low"),
            "top_alerts": top_alerts,
            "all_scored_alerts": scored_alerts
        }
        
        return json.dumps(digest, indent=2)
        
    except json.JSONDecodeError as e:
        return json.dumps({
            "error": "DataUnavailable",
            "source": "alert_scoring_coordinator",
            "detail": f"Invalid JSON input: {str(e)}",
            "action": "stop"
        })
    except Exception as e:
        return json.dumps({
            "error": "ProcessingError",
            "source": "alert_scoring_coordinator",
            "detail": str(e),
            "action": "stop"
        })
