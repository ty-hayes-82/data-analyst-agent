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
Severity Score Calculation for Alert Scoring Pipeline.

Implements the severity formula from ALERT_SCORING_INSTRUCTION prompt:
  - high_priority_count > 0  : 0.6 + (top_alert_score * 0.4)   [range: 0.6–1.0]
  - medium_priority_count > 0: 0.3 + (top_alert_score * 0.3)   [range: 0.3–0.6]
  - low_priority_count > 0   : top_alert_score                  [range: 0.0–0.3]
  - no alerts                : 0.0
"""

from __future__ import annotations


def compute_severity(scored_digest: dict) -> dict:
    """
    Compute the overall severity score from a scored alert digest.

    Args:
        scored_digest: The dict output from score_alerts() containing
                       top_alerts, high/medium/low_priority_count, etc.

    Returns:
        {
            "severity_score": float,
            "threshold_detail": str,
            "high_priority_count": int,
            "medium_priority_count": int,
            "low_priority_count": int,
            "top_alert_score": float,
            "total_alerts": int,
        }
    """
    high_count = int(scored_digest.get("high_priority_count", 0))
    medium_count = int(scored_digest.get("medium_priority_count", 0))
    low_count = int(scored_digest.get("low_priority_count", 0))
    total_alerts = int(scored_digest.get("total_alerts_scored", 0))

    top_alerts = scored_digest.get("top_alerts", [])
    top_score = float(top_alerts[0]["score"]) if top_alerts else 0.0

    if high_count > 0:
        severity_score = 0.6 + (top_score * 0.4)
        threshold_detail = (
            f"{high_count} high-priority alert(s) detected; "
            f"top score={top_score:.3f}"
        )
    elif medium_count > 0:
        severity_score = 0.3 + (top_score * 0.3)
        threshold_detail = (
            f"{medium_count} medium-priority alert(s), no high; "
            f"top score={top_score:.3f}"
        )
    elif low_count > 0:
        severity_score = top_score
        threshold_detail = (
            f"{low_count} low-priority alert(s) only; "
            f"top score={top_score:.3f}"
        )
    else:
        severity_score = 0.0
        threshold_detail = "No actionable alerts detected."

    # Clamp to [0, 1]
    severity_score = max(0.0, min(1.0, severity_score))

    return {
        "severity_score": round(severity_score, 3),
        "threshold_detail": threshold_detail,
        "high_priority_count": high_count,
        "medium_priority_count": medium_count,
        "low_priority_count": low_count,
        "top_alert_score": round(top_score, 3),
        "total_alerts": total_alerts,
    }
