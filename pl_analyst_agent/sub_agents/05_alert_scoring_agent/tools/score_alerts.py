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
Score Alerts tool for alert_scoring_coordinator_agent.
"""

import json
from typing import Any


def _calculate_impact_score(variance_amount: float, variance_pct: float, revenue: float = None, period: str = None) -> float:
    """Calculate impact score based on absolute variance and percentage."""
    # Base impact on absolute value
    abs_impact = min(variance_amount / 50000, 1.0)  # Normalize to $50k = 1.0
    
    # Base impact on percentage
    pct_impact = min(variance_pct / 50, 1.0)  # Normalize to 50% = 1.0
    
    # Take the maximum of the two
    impact = max(abs_impact, pct_impact)
    
    # Scale by revenue if available
    if revenue and revenue > 0:
        revenue_pct = (variance_amount / revenue) * 100
        revenue_impact = min(revenue_pct / 5, 1.0)  # 5% of revenue = 1.0
        impact = max(impact, revenue_impact)
    
    return min(impact, 1.0)


def _calculate_confidence_score(signals: dict[str, bool]) -> float:
    """Calculate confidence score based on ensemble of detection signals."""
    # Count how many detection methods flagged this
    total_signals = len(signals)
    if total_signals == 0:
        return 0.0
    
    flagged_signals = sum(1 for v in signals.values() if v)
    
    # Confidence is proportion of methods that flagged
    return flagged_signals / total_signals


def _calculate_persistence_score(months_flagged: int, lookback_months: int = 3) -> float:
    """Calculate persistence score based on how many recent months were flagged."""
    if lookback_months == 0:
        return 0.0
    
    persistence = months_flagged / lookback_months
    return min(persistence, 1.0)


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
            variance_amount = abs(float(alert["variance_amount"]))
            variance_pct = abs(float(alert.get("variance_pct", 0)))
            revenue = float(alert.get("revenue")) if alert.get("revenue") is not None else None
            
            # Detection signals (which methods flagged this)
            signals = alert.get("signals", {})
            
            # Historical persistence
            months_flagged = int(alert.get("months_flagged_in_last_3", 1))
            
            # Calculate component scores
            period = alert.get("period")
            impact = _calculate_impact_score(variance_amount, variance_pct, revenue, period)
            confidence = _calculate_confidence_score(signals)
            persistence = _calculate_persistence_score(months_flagged, lookback_months=3)
            
            # Overall score (multiplicative)
            score = impact * confidence * persistence
            
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
                "cost_center": alert.get("cost_center"),
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
        
        # Filter by minimum score
        scored_alerts = [a for a in scored_alerts if a["score"] >= min_score_threshold]
        
        # Sort by score (descending)
        scored_alerts.sort(key=lambda x: (-x["score"], x["id"]))
        
        # Apply top N limit, but allow override for high scores
        top_alerts = []
        for alert in scored_alerts:
            if len(top_alerts) < top_n or alert["score"] >= budget_override_score:
                top_alerts.append(alert)
            else:
                break
        
        # Generate digest
        digest = {
            "analysis_type": "alert_scoring",
            "total_alerts_received": len(alerts),
            "total_alerts_scored": len(scored_alerts),
            "alerts_above_threshold": len(scored_alerts),
            "top_n": top_n,
            "min_score_threshold": min_score_threshold,
            "budget_override_score": budget_override_score,
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
