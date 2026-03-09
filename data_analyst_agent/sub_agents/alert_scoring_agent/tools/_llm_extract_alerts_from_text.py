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
LLM Extract Alerts From Text — legacy fallback for alert_scoring_coordinator_agent.

This module is gated behind the LEGACY_LLM_ALERT_EXTRACTION environment variable
(default "false"). It is only invoked when structured JSON parsing fails, and
should be removed once the structured path via extract_alerts_from_analysis() is
proven reliable.

To re-enable: set LEGACY_LLM_ALERT_EXTRACTION=true in your .env
"""

import os
import json
from typing import Any

LEGACY_LLM_ALERT_EXTRACTION = (
    os.environ.get("LEGACY_LLM_ALERT_EXTRACTION", "false").lower() == "true"
)


async def _llm_extract_alerts_from_text(
    descriptive_stats: str,
    seasonal_baseline: str,
    drift_detection: str,
    synthesis: str,
    analysis_target: str,
    cv: float,
    history_count: int
) -> list:
    """Use an LLM to intelligently extract alerts from analysis text outputs.
    
    This is more robust than regex parsing and can understand context better.
    """
    if not LEGACY_LLM_ALERT_EXTRACTION:
        print(
            "[_llm_extract_alerts_from_text] Skipped — LEGACY_LLM_ALERT_EXTRACTION=false. "
            "Set LEGACY_LLM_ALERT_EXTRACTION=true to re-enable this fallback."
        )
        return []

    client = Client()

    prompt = f"""You are an expert financial analyst. Extract anomaly alerts from these analysis results for target {analysis_target}.

**Descriptive Statistics:**
{descriptive_stats[:2000] if descriptive_stats else "N/A"}

**Seasonal Baseline Analysis:**
{seasonal_baseline[:2000] if seasonal_baseline else "N/A"}

**Drift Detection:**
{drift_detection[:1000] if drift_detection else "N/A"}

**Synthesis:**
{synthesis[:1000] if synthesis else "N/A"}

Extract ALL periods that show anomalies, outliers, or significant variances. For EACH period, provide:
- period (YYYY-MM format)
- amount (actual dollar amount)
- variance_amount (dollar variance from baseline/expected)
- variance_pct (percentage variance)
- description (brief explanation of the anomaly)

Output as a JSON array of alerts. Include at least the top 10 most significant anomalies.

Example format:
```json
[
  {{
    "period": "2025-06",
    "amount": 171535.05,
    "variance_amount": 97865.40,
    "variance_pct": 132.8,
    "description": "Extreme high outlier - 4.0 SD above mean"
  }}
]
```

Output ONLY the JSON array, no other text."""

    try:
        response = await client.aio.models.generate_content(
            model="gemini-2.5-flash-exp",
            contents=prompt
        )
        
        # Extract JSON from response
        text = response.text
        # Find JSON array in response
        json_start = text.find('[')
        json_end = text.rfind(']') + 1
        
        if json_start >= 0 and json_end > json_start:
            json_str = text[json_start:json_end]
            extracted_alerts = json.loads(json_str)
            
            # Convert to full alert format
            alerts = []
            for item in extracted_alerts:
                period = item.get("period")
                if not period:
                    continue
                
                # Safe float conversion with None checks
                try:
                    variance_amount_raw = item.get("variance_amount", 0)
                    variance_amount = abs(float(variance_amount_raw)) if variance_amount_raw is not None else 0.0
                    
                    variance_pct_raw = item.get("variance_pct", 0)
                    variance_pct = abs(float(variance_pct_raw)) if variance_pct_raw is not None else 0.0
                    
                    amount_raw = item.get("amount", 0)
                    amount = float(amount_raw) if amount_raw is not None else 0.0
                except (ValueError, TypeError) as e:
                    print(f"[WARNING] Skipping alert with invalid numeric values: {e}")
                    continue
                
                description = item.get("description", "Anomaly detected")
                
                # Determine GL code (simplified - use default toll expense code)
                gl_code = "4560-06"
                
                # Create signals based on description keywords
                desc_lower = description.lower()
                signals = {
                    "mad_outlier": "outlier" in desc_lower or "extreme" in desc_lower,
                    "change_point": "change" in desc_lower or "shift" in desc_lower,
                    "mom_breach": "mom" in desc_lower or "month-over-month" in desc_lower,
                    "yoy_breach": "yoy" in desc_lower or "year-over-year" in desc_lower,
                    "drift_detected": "drift" in desc_lower or "trend" in desc_lower,
                    "seasonal_outlier": "seasonal" in desc_lower,
                    "pi_breach": "prediction interval" in desc_lower or "forecast" in desc_lower
                }
                
                alert = {
                    "id": f"{period}-llm-extracted",
                    "period": period,
                    "gl_code": gl_code,
                    "dimension_value": analysis_target,
                    "category": "toll_expenses",
                    "variance_amount": round(variance_amount, 2),
                    "variance_pct": round(variance_pct, 2),
                    "cv": cv,
                    "history_count": history_count,
                    "signals": signals,
                    "months_flagged_in_last_3": 1,
                    "revenue": None,
                    "details": {
                        "description": description,
                        "amount": amount
                    }
                }
                alerts.append(alert)
            
            return alerts
            
    except Exception as e:
        print(f"[WARNING] LLM alert extraction failed: {e}")
        return []
    
    return []


def _extract_alerts_from_text(text: str, analysis_target: str, validated_data: Any, cv: float, history_count: int) -> list:
    """Extract alert information from text responses when JSON parsing fails.
    
    Args:
        text: Text response from analysis agents
        analysis_target: Target being analyzed
        validated_data: Validated time series data
        cv: Coefficient of variation
        history_count: Number of historical data points
        
    Returns:
        List of alert dictionaries
    """
    alerts = []
    
    # Extract extreme highs with pattern like "2025-06: $171,535.05 (4.02 standard deviations above the mean)"
    extreme_high_pattern = r'(\d{4}-\d{2})[:\s]+\$?([\d,]+\.?\d*)[^\n]*?(\d+\.?\d*)\s+standard deviations? above'
    for match in re.finditer(extreme_high_pattern, text, re.IGNORECASE):
        period = match.group(1)
        amount_str = match.group(2).replace(',', '')
        z_score = float(match.group(3))
        
        try:
            amount = float(amount_str)
            gl_code = _extract_gl_code(validated_data, period)
            
            # Estimate variance (z_score * typical_std_dev, use 20000 as estimate)
            variance_amount = abs(z_score * 20000)
            variance_pct = abs(z_score * 30)  # Rough estimate
            
            alert = {
                "id": f"{period}-extreme-high",
                "period": period,
                "gl_code": gl_code,
                    "dimension_value": analysis_target,
                "category": "toll_expenses",
                "variance_amount": round(variance_amount, 2),
                "variance_pct": round(variance_pct, 2),
                "cv": cv,
                "history_count": history_count,
                "signals": {
                    "mad_outlier": True,
                    "change_point": False,
                    "mom_breach": False,
                    "yoy_breach": False,
                    "drift_detected": False,
                    "seasonal_outlier": False,
                    "pi_breach": False
                },
                "months_flagged_in_last_3": 1,  # Default to 1 since this period is being flagged
                "revenue": None,
                "details": {
                    "description": f"Extreme high detected in {period} - {z_score:.1f} SD above mean",
                    "z_score": round(z_score, 2),
                    "trend": "increasing",
                    "amount": amount
                }
            }
            alerts.append(alert)
        except (ValueError, TypeError):
            continue
    
    # Extract drift detection info
    drift_detected = "drift detected" in text.lower() and "yes" in text.lower()
    if drift_detected:
        # Mark all alerts as having drift
        for alert in alerts:
            alert["signals"]["drift_detected"] = True
    
    # Extract YoY variance pattern like "YTD Variance: +32.94%" or "Variance (%): 32.94%"
    yoy_pattern = r'(?:YTD|Year[- ]to[- ]Date).*?Variance[^:]*:\s*\+?(\d+\.?\d*)%'
    yoy_match = re.search(yoy_pattern, text, re.IGNORECASE)
    if yoy_match:
        try:
            yoy_pct = float(yoy_match.group(1))
            if yoy_pct > 20:  # Significant YoY change
                # Mark alerts as having YoY breach
                for alert in alerts:
                    alert["signals"]["yoy_breach"] = True
        except (ValueError, TypeError):
            pass
    
    return alerts
