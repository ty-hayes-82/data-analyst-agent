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


async def extract_alerts_from_analysis(
    statistical_summary: str = "",
    statistical_insights_result: str = "",
    synthesis: str = "",
    cost_center: str = "unknown"
) -> str:
    """Extract alerts from analysis results text.
    
    This tool automatically parses the outputs from analysis agents
    and creates properly formatted alert objects for scoring.
    
    Args:
        statistical_summary: JSON output from compute_statistical_summary tool
        statistical_insights_result: Output from statistical_insights_agent (LLM insights)
        synthesis: Output from synthesis_agent
        cost_center: Cost center being analyzed
        
    Returns:
        JSON string with alerts array and config for the alert_scoring_agent
    """
    try:
        alerts = []
        
        # Parse statistical summary
        stats_data = {}
        if statistical_summary:
            try:
                stats_data = json.loads(statistical_summary)
            except:
                pass
        
        # Extract anomalies from statistical summary
        anomalies = stats_data.get('anomalies', [])
        top_drivers = stats_data.get('top_drivers', [])
        
        # Convert anomalies to alerts
        for anomaly in anomalies[:15]:  # Limit to top 15 anomalies
            period = anomaly.get('period', 'unknown')
            account = anomaly.get('account', 'unknown')
            account_name = anomaly.get('account_name', account)
            value = anomaly.get('value', 0)
            z_score = abs(anomaly.get('z_score', 0))
            avg = anomaly.get('avg', 0)
            std = anomaly.get('std', 0)
            
            variance_amount = abs(value - avg)
            variance_pct = abs((variance_amount / avg * 100)) if avg != 0 else 0
            
            alert = {
                "id": f"{period}-{account}-anomaly",
                "period": period,
                "gl_code": account,
                "account_name": account_name,
                "cost_center": cost_center,
                "category": "financial_variance",
                "variance_amount": round(variance_amount, 2),
                "variance_pct": round(variance_pct, 2),
                "cv": abs(std / avg) if avg != 0 else 0,
                "history_count": stats_data.get('summary_stats', {}).get('total_periods', 0),
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
                    "description": f"Statistical anomaly in {account_name} for {period}",
                    "z_score": round(z_score, 2),
                    "trend": "increasing" if value > avg else "decreasing",
                    "amount": value,
                    "baseline": avg,
                    "std_dev": std
                }
            }
            alerts.append(alert)
        
        # Add alerts for top volatile drivers
        most_volatile = stats_data.get('most_volatile', [])
        for driver in most_volatile[:5]:  # Top 5 most volatile
            account = driver.get('account', 'unknown')
            account_name = driver.get('account_name', account)
            cv = driver.get('cv', 0)
            
            # Only create alert if CV is high
            if cv > 0.5:
                alert = {
                    "id": f"{account}-high-volatility",
                    "period": "multi-period",
                    "gl_code": account,
                    "account_name": account_name,
                    "cost_center": cost_center,
                    "category": "volatility",
                    "variance_amount": 0,
                    "variance_pct": 0,
                    "cv": round(cv, 4),
                    "history_count": stats_data.get('summary_stats', {}).get('total_periods', 0),
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
                        "description": f"High volatility detected in {account_name}",
                        "cv": round(cv, 4),
                        "avg": driver.get('avg', 0),
                        "std": driver.get('std', 0)
                    }
                }
                alerts.append(alert)
        
        # Extract utilization degradation alerts from statistical_summary
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
                "gl_code": metric,
                "account_name": label,
                "cost_center": cost_center,
                "category": "utilization_degradation",
                "variance_amount": round(abs(current_val - baseline_val), 4),
                "variance_pct": round(abs(variance_pct), 2),
                "cv": 0,
                "history_count": stats_data.get('utilization_summary', {}).get('periods_analyzed', 0),
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

            alert = {
                "id": f"{period}-{metric}-util-outlier",
                "period": period,
                "gl_code": metric,
                "account_name": f"Utilization Outlier: {metric}",
                "cost_center": cost_center,
                "category": "utilization_outlier",
                "variance_amount": round(abs(value - mean_val), 4),
                "variance_pct": round(abs((value - mean_val) / mean_val * 100), 2) if mean_val != 0 else 0,
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
        output = {
            "alerts": alerts,
            "config": {
                "top_n": 10,
                "min_score_threshold": 0.05
            },
            "metadata": {
                "cost_center": cost_center,
                "extracted_at": str(__import__('datetime').datetime.now()),
                "total_alerts": len(alerts),
                "source": "statistical_summary"
            }
        }
        
        # Save payload to file for debugging
        from pathlib import Path
        output_dir = Path("outputs")
        output_dir.mkdir(exist_ok=True)
        payload_file = output_dir / f"alerts_payload_cc{cost_center}.json"
        
        try:
            with open(payload_file, 'w') as f:
                json.dump(output, f, indent=2)
            print(f"[extract_alerts_from_analysis] Alert payload saved to: {payload_file}")
        except Exception as e:
            print(f"[extract_alerts_from_analysis] Could not save alert payload: {e}")
        
        return json.dumps(output, indent=2)
        
    except Exception as e:
        import traceback
        return json.dumps({
            "error": "ExtractionError",
            "source": "extract_alerts_from_analysis",
            "detail": str(e),
            "traceback": traceback.format_exc(),
            "action": "stop"
        }, indent=2)

