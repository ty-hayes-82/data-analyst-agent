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
Extract Alerts From Analysis tool for alert_scoring_coordinator_agent.
"""

import json
from typing import Any


_VOLATILITY_ALERT_THRESHOLD = 0.5


async def extract_alerts_from_analysis(
    statistical_summary: str = "",
    statistical_insights_result: str = "",
    synthesis: str = "",
    analysis_target: str = "unknown",
    cost_center: str | None = None,
) -> str:
    """Extract alerts from analysis results text.
    
    This tool automatically parses the outputs from analysis agents
    and creates properly formatted alert objects for scoring.
    
    Args:
        statistical_summary: JSON output from compute_statistical_summary tool
        statistical_insights_result: Output from statistical_insights_agent (LLM insights)
        synthesis: Output from synthesis_agent
        analysis_target: Analysis target being analyzed
        cost_center: Optional friendly identifier (used when analysis_target is generic)
        
    Returns:
        JSON string with alerts array and config for the alert_scoring_agent
    """
    try:
        target_name = cost_center or analysis_target
        print(f"[extract_alerts_from_analysis] Starting extraction for {target_name}...", flush=True)
        alerts = []
        
        stats_data = {}
        if statistical_summary:
            try:
                stats_data = json.loads(statistical_summary)
                print(f"[extract_alerts_from_analysis] Loaded stats_data: {len(statistical_summary)} chars", flush=True)
            except Exception as e:
                print(f"[extract_alerts_from_analysis] Warning: Could not parse statistical_summary: {e}", flush=True)
                pass

        # Compute grand total for materiality weighting
        _summary_stats = stats_data.get('summary_stats', {})
        _grand_total = 0.0
        if isinstance(_summary_stats, dict) and _summary_stats.get('grand_total'):
            try:
                _grand_total = abs(float(_summary_stats['grand_total']))
            except (ValueError, TypeError):
                pass
        if not _grand_total:
            _monthly = stats_data.get('monthly_totals', {})
            if isinstance(_monthly, dict):
                _vals = [abs(v) for v in _monthly.values() if isinstance(v, (int, float))]
                # Use average of period totals (not sum) so ratio metrics aren't inflated
                _grand_total = sum(_vals) / len(_vals) if _vals else 0.0
            elif isinstance(_monthly, list):
                for t in _monthly:
                    if isinstance(t, dict):
                        _grand_total += abs(t.get('total', 0))
                    elif isinstance(t, (int, float)):
                        _grand_total += abs(t)

        # Build a lookup of item averages for materiality weighting
        _item_avgs: dict[str, float] = {}
        for _d in stats_data.get('top_drivers', []):
            _key = _d.get('item_name', _d.get('item', ''))
            _item_avgs[_key] = abs(_d.get('avg', 0)) * _d.get('count', 1)

        print(f"[extract_alerts_from_analysis] Processing anomalies...", flush=True)
        anomalies = stats_data.get('anomalies', [])
        
        # Convert anomalies to alerts
        for anomaly in anomalies[:15]:  # Limit to top 15 anomalies
            period = anomaly.get('period', 'unknown')
            item_id = anomaly.get('item', 'unknown')
            item_name = anomaly.get('item_name', item_id)
            value = anomaly.get('value', 0)
            z_score = abs(anomaly.get('z_score', 0))
            avg = anomaly.get('avg', 0)
            std = anomaly.get('std', 0)
            
            variance_amount = abs(value - avg)
            variance_pct = abs((variance_amount / avg * 100)) if avg != 0 else 0
            
            alert = {
                "id": f"{period}-{item_id}-anomaly",
                "period": period,
                "item_id": item_id,
                "item_name": item_name,
                "dimension_value": target_name,
                "category": "statistical_anomaly",
                "variance_amount": round(variance_amount, 2),
                "variance_pct": round(variance_pct, 2),
                "item_total": round(_item_avgs.get(item_name, 0), 2),
                "grand_total": round(_grand_total, 2),
                "cv": abs(std / avg) if avg != 0 else 0,
                "history_count": stats_data.get('summary_stats', {}).get('total_periods', 0) if isinstance(stats_data.get('summary_stats'), dict) else 0,
                "signals": {
                    "mad_outlier": z_score >= 2.0,
                    "change_point": z_score >= 3.0,
                    "mom_breach": False,
                    "yoy_breach": False,
                    "drift_detected": False,
                    "seasonal_outlier": z_score >= 2.0,
                    "pi_breach": False
                },
                "months_flagged_in_last_3": 1,
                "revenue": None,
                "details": {
                    "description": f"Statistical anomaly in {item_name} for {period}",
                    "z_score": round(z_score, 2),
                    "trend": "increasing" if value > avg else "decreasing",
                    "amount": value,
                    "baseline": avg,
                    "std_dev": std
                }
            }
            alerts.append(alert)
        
        # Add alerts for top volatile drivers
        print(f"[extract_alerts_from_analysis] Processing volatile drivers...", flush=True)
        most_volatile = stats_data.get('most_volatile', [])
        for driver in most_volatile[:5]:  # Top 5 most volatile
            item_id = driver.get('item', 'unknown')
            item_name = driver.get('item_name', item_id)
            cv = driver.get('cv', 0)
            
            if cv >= _VOLATILITY_ALERT_THRESHOLD:
                alert = {
                    "id": f"{item_id}-high-volatility",
                    "period": "multi-period",
                    "item_id": item_id,
                    "item_name": item_name,
                    "dimension_value": target_name,
                    "category": "volatility",
                    "variance_amount": 0,
                    "variance_pct": 0,
                    "item_total": round(_item_avgs.get(item_name, 0), 2),
                    "grand_total": round(_grand_total, 2),
                    "cv": round(cv, 4),
                    "history_count": stats_data.get('summary_stats', {}).get('total_periods', 0) if isinstance(stats_data.get('summary_stats'), dict) else 0,
                    "signals": {
                        "mad_outlier": False,
                        "change_point": False,
                        "mom_breach": False,
                        "yoy_breach": False,
                        "drift_detected": False,
                        "seasonal_outlier": False,
                        "pi_breach": False
                    },
                    "months_flagged_in_last_3": 0,
                    "revenue": None,
                    "details": {
                        "description": f"High volatility detected in {item_name}",
                        "cv": round(cv, 4),
                        "avg": driver.get('avg', 0),
                        "std": driver.get('std', 0)
                    }
                }
                alerts.append(alert)
        
        # Extract change points — may be a list of dicts, a dict, or a list of strings
        print(f"[extract_alerts_from_analysis] Processing changepoints...", flush=True)
        changepoints = stats_data.get('change_points', [])
        if isinstance(changepoints, dict):
            changepoints = list(changepoints.values())
        for cp in changepoints[:10]:
            # Skip non-dict entries (e.g. plain string period labels)
            if not isinstance(cp, dict):
                continue
            period = cp.get('period', 'unknown')
            item_id = cp.get('item', 'unknown')
            item_name = cp.get('item_name', item_id)
            mag_dollar = cp.get('magnitude_dollar', 0)
            mag_pct = cp.get('magnitude_pct', 0)
            conf = cp.get('confidence_score', 0)
            
            alert = {
                "id": f"{period}-{item_id}-changepoint",
                "period": period,
                "item_id": item_id,
                "item_name": item_name,
                "dimension_value": target_name,
                "category": "structural_break",
                "variance_amount": round(mag_dollar, 2),
                "variance_pct": round(mag_pct, 2),
                "item_total": round(_item_avgs.get(item_name, 0), 2),
                "grand_total": round(_grand_total, 2),
                "cv": 0,
                "history_count": stats_data.get('summary_stats', {}).get('total_periods', 0) if isinstance(stats_data.get('summary_stats'), dict) else 0,
                "signals": {
                    "mad_outlier": False,
                    "change_point": True,
                    "mom_breach": False,
                    "yoy_breach": False,
                    "drift_detected": True,
                    "seasonal_outlier": False,
                    "pi_breach": False
                },
                "months_flagged_in_last_3": 1,
                "revenue": None,
                "details": {
                    "description": f"Structural shift detected in {item_name} starting {period}",
                    "magnitude": round(mag_dollar, 2),
                    "confidence": round(conf, 2),
                    "before_mean": cp.get('before_mean', 0),
                    "after_mean": cp.get('after_mean', 0)
                }
            }
            alerts.append(alert)

        # Extract utilization degradation alerts from statistical_summary
        print(f"[extract_alerts_from_analysis] Processing utilization alerts...", flush=True)
        util_degradation = stats_data.get('utilization_degradation_alerts', [])
        util_outliers = stats_data.get('utilization_outliers', [])

        for util_alert in util_degradation[:10]:
            metric = util_alert.get('metric', 'unknown')
            label = util_alert.get('label', metric)
            current_val = util_alert.get('current', 0)
            baseline_val = util_alert.get('baseline_3m', 0)
            variance_pct = util_alert.get('variance_pct', 0)
            severity = util_alert.get('severity', 'MEDIUM')
            period = util_alert.get('period', 'unknown')

            alert = {
                "id": f"{period}-{metric}-util-degradation",
                "period": period,
                "item_id": metric,
                "item_name": label,
                "dimension_value": target_name,
                "category": "utilization_degradation",
                "variance_amount": round(abs(current_val - baseline_val), 4),
                "variance_pct": round(abs(variance_pct), 2),
                "item_total": round(_item_avgs.get(label, 0), 2),
                "grand_total": round(_grand_total, 2),
                "cv": 0,
                "history_count": stats_data.get('utilization_summary', {}).get('periods_analyzed', 0) if isinstance(stats_data.get('utilization_summary'), dict) else 0,
                "signals": {
                    "mad_outlier": False,
                    "change_point": False,
                    "mom_breach": abs(variance_pct) > 5,
                    "yoy_breach": False,
                    "drift_detected": abs(variance_pct) > 10,
                    "seasonal_outlier": False,
                    "pi_breach": False,
                },
                "months_flagged_in_last_3": 1,
                "revenue": None,
                "details": {
                    "description": f"Utilization degradation: {label} at {current_val:.2f} vs 3M baseline {baseline_val:.2f}",
                    "current": current_val,
                    "baseline_3m": baseline_val,
                    "variance_pct": variance_pct,
                    "severity": severity,
                    "metric_type": "utilization",
                }
            }
            alerts.append(alert)

        for outlier in util_outliers[:5]:
            metric = outlier.get('metric', 'unknown')
            period = outlier.get('period', 'unknown')
            z_score = outlier.get('z_score', 0)
            value = outlier.get('value', 0)
            mean_val = outlier.get('mean', 0)

            _outlier_label = f"Utilization Outlier: {metric}"
            alert = {
                "id": f"{period}-{metric}-util-outlier",
                "period": period,
                "item_id": metric,
                "item_name": _outlier_label,
                "dimension_value": target_name,
                "category": "utilization_outlier",
                "variance_amount": round(abs(value - mean_val), 4),
                "variance_pct": round(abs((value - mean_val) / mean_val * 100), 2) if mean_val != 0 else 0,
                "item_total": round(_item_avgs.get(metric, 0), 2),
                "grand_total": round(_grand_total, 2),
                "cv": 0,
                "history_count": 0,
                "signals": {
                    "mad_outlier": z_score >= 2.0,
                    "change_point": z_score >= 3.0,
                    "mom_breach": False,
                    "yoy_breach": False,
                    "drift_detected": False,
                    "seasonal_outlier": z_score >= 2.0,
                    "pi_breach": False,
                },
                "months_flagged_in_last_3": 1,
                "revenue": None,
                "details": {
                    "description": f"Utilization outlier in {metric} for {period}",
                    "z_score": round(z_score, 2),
                    "value": value,
                    "mean": mean_val,
                    "metric_type": "utilization",
                }
            }
            alerts.append(alert)

        # Create output structure
        print(f"[extract_alerts_from_analysis] Building output for {len(alerts)} alerts...", flush=True)
        # Debugging: print first alert if any
        if alerts:
            print(f"[extract_alerts_from_analysis] Sample alert (first of {len(alerts)}): {json.dumps(alerts[0], indent=2)[:500]}...", flush=True)

        output = {
            "alerts": alerts,
            "config": {
                "top_n": 10,
                "min_score_threshold": 0.05
            },
            "metadata": {
                "dimension_value": str(target_name),
                "extracted_at": str(__import__('datetime').datetime.now()),
                "total_alerts": len(alerts),
                "source": "statistical_summary"
            }
        }
        
        # Save payload to file for debugging
        from pathlib import Path
        output_dir = Path("outputs")
        output_dir.mkdir(exist_ok=True)
        # Sanitize target for filename
        safe_target = str(target_name).replace("/", "-").replace("\\", "-").replace(":", "-").replace(" ", "_")
        payload_file = output_dir / f"alerts_payload_{safe_target}.json"
        
        print(f"[extract_alerts_from_analysis] Attempting to save alert payload to: {payload_file}", flush=True)
        try:
            with open(payload_file, 'w') as f:
                json.dump(output, f, indent=2)
            print(f"[extract_alerts_from_analysis] Alert payload saved to: {payload_file}", flush=True)
        except Exception as e:
            print(f"[extract_alerts_from_analysis] Could not save alert payload: {e}", flush=True)
        
        print(f"[extract_alerts_from_analysis] Returning JSON string of length {len(json.dumps(output))}", flush=True)
        return json.dumps(output, indent=2)
    
    except Exception as e:
        import traceback
        error_msg = f"ExtractionError: {str(e)}\n{traceback.format_exc()}"
        print(f"[extract_alerts_from_analysis] FATAL ERROR: {error_msg}")
        return json.dumps({
            "error": "ExtractionError",
            "source": "extract_alerts_from_analysis",
            "detail": str(e),
            "traceback": traceback.format_exc(),
            "action": "stop"
        }, indent=2)
