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
Capture Feedback tool for suppression_agent.
"""

import json
from typing import Any


async def capture_feedback(data: str) -> str:
    """Capture analyst feedback on alerts to improve future detection.
    
    Args:
        data: JSON string with alert feedback containing alert_id, tag, and comment.
    
    Returns:
        JSON string confirming feedback capture with storage info.
    """
    try:
        feedback = json.loads(data)
        
        if not isinstance(feedback, dict):
            return json.dumps({
                "error": "DataUnavailable",
                "source": "suppression_agent",
                "detail": "Feedback must be a dict with alert_id, tag, and optional comment",
                "action": "stop"
            })
        
        required_fields = ["alert_id", "tag"]
        if not all(field in feedback for field in required_fields):
            return json.dumps({
                "error": "DataUnavailable",
                "source": "suppression_agent",
                "detail": f"Feedback must contain: {required_fields}",
                "action": "stop"
            })
        
        # Add timestamp
        feedback["timestamp"] = datetime.utcnow().isoformat()
        
        # Validate tag
        valid_tags = ["expected", "issue", "false_positive", "investigate"]
        if feedback["tag"] not in valid_tags:
            return json.dumps({
                "error": "DataUnavailable",
                "source": "suppression_agent",
                "detail": f"Tag must be one of: {valid_tags}",
                "action": "stop"
            })
        
        return json.dumps({
            "analysis_type": "feedback_capture",
            "status": "success",
            "feedback": feedback,
            "message": "Feedback captured successfully. Store this in artifacts/ or database."
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
