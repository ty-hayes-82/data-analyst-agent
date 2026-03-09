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
Apply Suppression tool for suppression_agent.
"""

import json
import fnmatch
from pathlib import Path
from typing import Any
import yaml


def _load_business_context():
    """Load business context suppression rules."""
    context_path = Path(__file__).parent.parent.parent.parent.parent / "config" / "business_context.yaml"
    try:
        if context_path.exists():
            with open(context_path, 'r', encoding='utf-8') as f:
                context = yaml.safe_load(f)
                return context.get("suppression_rules", {}) if context else {}
    except Exception as e:
        print(f"[SUPPRESSION] Warning: Could not load business context: {e}")
    return {}


def _matches_pattern(value: str, pattern: str) -> bool:
    """Check if value matches pattern (supports wildcards)."""
    if not pattern:
        return False
    if pattern == "*":
        return True
    return fnmatch.fnmatch(value, pattern)


def _check_business_context_suppression(alert: dict, suppression_rules: dict, analysis_target: str = None, period: int = None) -> tuple:
    """
    Check if alert should be suppressed based on business context rules.
    
    Returns:
        (should_suppress, reason, rule_id) tuple
    """
    alert_gl = alert.get("gl_account", "")
    alert_severity = alert.get("severity_score", 0.0)
    
    for rule_id, rule in suppression_rules.items():
        if not rule.get("active", True):
            continue
        
        # Check GL match
        affected_gls = rule.get("affected_gls", [])
        gl_match = any(_matches_pattern(alert_gl, gl_pattern) for gl_pattern in affected_gls)
        
        if not gl_match:
            continue
        
        # Check analysis target match
        affected_targets = rule.get("analysis_targets", ["*"])
        if analysis_target:
            target_match = any(_matches_pattern(analysis_target, t_pattern) for t_pattern in affected_targets)
            if not target_match:
                continue
        
        # Check period match (if specified)
        affected_periods = rule.get("periods", [])
        if affected_periods and period and period not in affected_periods:
            continue
        
        # Check severity threshold
        suppress_below = rule.get("suppress_severity_below", 1.0)
        if alert_severity < suppress_below:
            reason = rule.get("reason", "Matched business context suppression rule")
            return (True, f"{reason} (Rule: {rule_id})", rule_id)
    
    return (False, None, None)


def _check_event_match(alert: dict, event: dict) -> bool:
    """Check if an alert matches a known event."""
    # Simple matching logic: compare item_id (metric/terminal) and period
    alert_item = alert.get("item_id", "").lower()
    event_item = event.get("item_id", "").lower()
    alert_period = str(alert.get("period", "")).lower()
    event_period = str(event.get("period", "")).lower()

    if alert_item and event_item and alert_item == event_item:
        # If period is specified in event, it must match
        if event_period and event_period != "unknown":
            return alert_period == event_period
        return True
    return False


async def apply_suppression(data: str) -> str:
    """Apply suppression rules to alerts based on events calendar, feedback, and business context.
    
    Args:
        data: JSON string with 'alerts' list and optional 'events_calendar', 'feedback_history', 
              'dimension_value', and 'period'.
    
    Returns:
        JSON string with suppressed/labeled alerts and suppression statistics.
    """
    try:
        input_data = json.loads(data)
        
        if not isinstance(input_data, dict):
            return json.dumps({
                "error": "DataUnavailable",
                "source": "suppression_agent",
                "detail": "Input must be a dict with 'alerts', optional 'events_calendar' and 'feedback_history'",
                "action": "stop"
            })
        
        alerts = input_data.get("alerts", [])
        events_calendar = input_data.get("events_calendar", [])
        feedback_history = input_data.get("feedback_history", [])
        analysis_target = input_data.get("dimension_value")
        period = input_data.get("period")
        
        if not alerts:
            return json.dumps({
                "analysis_type": "suppression",
                "message": "No alerts to process",
                "suppressed_alerts": [],
                "active_alerts": []
            })
        
        # Load business context suppression rules
        business_context_rules = _load_business_context()
        
        suppressed_alerts = []
        active_alerts = []
        
        # Build feedback lookup for quick access
        feedback_lookup = {}
        for feedback in feedback_history:
            alert_id = feedback.get("alert_id")
            if alert_id:
                feedback_lookup[alert_id] = feedback
        
        for alert in alerts:
            alert_id = alert.get("id")
            suppression_reason = None
            suppression_type = None
            
            # Check against business context rules (highest priority)
            if business_context_rules:
                should_suppress, reason, rule_id = _check_business_context_suppression(
                    alert, business_context_rules, analysis_target, period
                )
                if should_suppress:
                    suppression_reason = reason
                    suppression_type = f"business_context_{rule_id}"
            
            # Check against events calendar (if not already suppressed)
            if not suppression_reason:
                for event in events_calendar:
                    if _check_event_match(alert, event):
                        suppression_reason = event.get("description", "Known event")
                        suppression_type = event.get("type", "known_event")
                        break
            
            # Check feedback history (if not already suppressed)
            if not suppression_reason and alert_id in feedback_lookup:
                feedback = feedback_lookup[alert_id]
                analyst_tag = feedback.get("tag")
                
                if analyst_tag == "expected":
                    suppression_reason = feedback.get("comment", "Previously marked as expected")
                    suppression_type = "feedback_expected"
                elif analyst_tag == "false_positive":
                    suppression_reason = feedback.get("comment", "Previously marked as false positive")
                    suppression_type = "feedback_false_positive"
            
            # Apply suppression
            if suppression_reason:
                suppressed_alert = alert.copy()
                suppressed_alert["suppressed"] = True
                suppressed_alert["suppression_reason"] = suppression_reason
                suppressed_alert["suppression_type"] = suppression_type
                suppressed_alert["label"] = "heads-up"  # Soft suppress with label
                suppressed_alerts.append(suppressed_alert)
            else:
                active_alert = alert.copy()
                active_alert["suppressed"] = False
                active_alerts.append(active_alert)
        
        # Generate suppression statistics
        suppression_stats = {
            "total_alerts": len(alerts),
            "suppressed_count": len(suppressed_alerts),
            "active_count": len(active_alerts),
            "suppression_rate_pct": round((len(suppressed_alerts) / len(alerts) * 100), 2) if alerts else 0,
            "by_type": {},
            "business_context_rules_loaded": len(business_context_rules)
        }
        
        # Count by suppression type
        for alert in suppressed_alerts:
            sup_type = alert.get("suppression_type", "unknown")
            suppression_stats["by_type"][sup_type] = suppression_stats["by_type"].get(sup_type, 0) + 1
        
        return json.dumps({
            "analysis_type": "suppression",
            "suppression_stats": suppression_stats,
            "suppressed_alerts": suppressed_alerts,
            "active_alerts": active_alerts,
            "events_checked": len(events_calendar),
            "feedback_entries_checked": len(feedback_history)
        }, indent=2)
        
    except json.JSONDecodeError as e:
        return json.dumps({
            "error": "DataUnavailable",
            "source": "suppression_agent",
            "detail": f"Invalid JSON input: {str(e)}",
            "action": "stop"
        })
    except Exception as e:
        return json.dumps({
            "error": "ProcessingError",
            "source": "suppression_agent",
            "detail": str(e),
            "action": "stop"
        })
