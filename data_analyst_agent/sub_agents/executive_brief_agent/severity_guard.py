"""Severity guard for preventing fallback when critical/high alerts exist."""

from __future__ import annotations

import json
from typing import Any


def has_critical_or_high_findings(json_data: dict[str, Any]) -> tuple[bool, list[str]]:
    """Check if any metric has CRITICAL or HIGH severity findings.
    
    Returns:
        (has_critical_findings, list of affected metrics)
    """
    critical_metrics: list[str] = []
    
    for metric_name, payload in json_data.items():
        if not isinstance(payload, dict):
            continue
            
        # Check alert_scoring results for CRITICAL/HIGH priority
        alert_scoring = payload.get("alert_scoring") or {}
        if isinstance(alert_scoring, str):
            try:
                alert_scoring = json.loads(alert_scoring)
            except json.JSONDecodeError:
                alert_scoring = {}
        
        if isinstance(alert_scoring, dict):
            top_alerts = alert_scoring.get("top_alerts") or []
            if isinstance(top_alerts, list):
                for alert in top_alerts:
                    if not isinstance(alert, dict):
                        continue
                    priority = (alert.get("priority") or "").upper()
                    if priority in ("CRITICAL", "HIGH"):
                        critical_metrics.append(metric_name)
                        break
        
        # Check narrative_results for CRITICAL/HIGH priority insight cards
        narrative = payload.get("narrative_results")
        if isinstance(narrative, str):
            try:
                narrative = json.loads(narrative)
            except json.JSONDecodeError:
                narrative = {}
        
        if isinstance(narrative, dict):
            insight_cards = narrative.get("insight_cards") or []
            if isinstance(insight_cards, list):
                for card in insight_cards:
                    if not isinstance(card, dict):
                        continue
                    priority = (card.get("priority") or "").lower()
                    if priority in ("critical", "high"):
                        if metric_name not in critical_metrics:
                            critical_metrics.append(metric_name)
                        break
        
        # Check hierarchical_analysis for CRITICAL/HIGH cards
        hierarchical = payload.get("hierarchical_analysis") or {}
        if isinstance(hierarchical, str):
            try:
                hierarchical = json.loads(hierarchical)
            except json.JSONDecodeError:
                hierarchical = {}
        
        if isinstance(hierarchical, dict):
            for level_key, level_data in hierarchical.items():
                if not isinstance(level_data, dict):
                    continue
                level_cards = level_data.get("insight_cards") or []
                if isinstance(level_cards, list):
                    for card in level_cards:
                        if not isinstance(card, dict):
                            continue
                        priority = (card.get("priority") or "").lower()
                        if priority in ("critical", "high"):
                            if metric_name not in critical_metrics:
                                critical_metrics.append(metric_name)
                            break
                if metric_name in critical_metrics:
                    break
        
        # Check analysis.insight_cards for CRITICAL/HIGH
        analysis = payload.get("analysis") or {}
        if isinstance(analysis, dict):
            analysis_cards = analysis.get("insight_cards") or []
            if isinstance(analysis_cards, list):
                for card in analysis_cards:
                    if not isinstance(card, dict):
                        continue
                    priority = (card.get("priority") or "").lower()
                    if priority in ("critical", "high"):
                        if metric_name not in critical_metrics:
                            critical_metrics.append(metric_name)
                        break
    
    return (len(critical_metrics) > 0, critical_metrics)


def build_severity_enforcement_block(has_critical: bool, critical_metrics: list[str]) -> str:
    """Build a prompt block that prevents fallback when critical findings exist."""
    if not has_critical:
        return ""
    
    metrics_list = ", ".join(critical_metrics)
    return f"""
CRITICAL FINDINGS DETECTED: {metrics_list}

MANDATORY ENFORCEMENT:
- DO NOT use fallback text ("No material change" / "maintain monitoring posture") for metrics with CRITICAL or HIGH findings
- Every metric in the list above MUST have substantive content with specific variance values, baselines, and context
- Minimum content per critical metric: current level + prior baseline + variance magnitude + entity responsible
- If a metric has CRITICAL/HIGH alerts but thin narrative, extract variance data from the alert_scoring or hierarchical_analysis blocks

The fallback sentence ("No material change this period—maintain monitoring posture.") is ONLY allowed for metrics that:
1. Have NO insight cards with priority=CRITICAL or HIGH
2. Have NO alerts with priority=CRITICAL or HIGH  
3. Have variance below materiality thresholds (typically <10% and <$100)

VALIDATION: If the output uses fallback text for any metric in [{metrics_list}], the response will be REJECTED and retried.
"""
