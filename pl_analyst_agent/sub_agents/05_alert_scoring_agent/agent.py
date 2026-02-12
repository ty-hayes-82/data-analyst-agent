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
Alert Scoring Agent - Main agent module.
"""

from google.adk import Agent
from google.genai import types

from config.model_loader import get_agent_model
from .prompt import ALERT_SCORING_INSTRUCTION
from .tools import (
    extract_alerts_from_analysis, 
    get_order_details_for_period,
    get_top_shippers_by_miles,
    get_monthly_aggregates_by_cost_center,
    score_alerts,
    apply_suppression
)


root_agent = Agent(
    model=get_agent_model("alert_scoring_coordinator"),
    name="alert_scoring_coordinator",
    description="Intelligent alert lifecycle manager: extracts anomalies, applies suppression rules, scores alerts using multi-factor analysis (Impact x Confidence x Persistence), and provides prioritized actionable insights. Integrates suppression and feedback learning.",
    instruction=ALERT_SCORING_INSTRUCTION,
    tools=[
        extract_alerts_from_analysis, 
        apply_suppression,
        score_alerts,
        get_order_details_for_period,
        get_top_shippers_by_miles,
        get_monthly_aggregates_by_cost_center
    ],
    output_key="alert_scoring_result",
    generate_content_config=types.GenerateContentConfig(
        response_modalities=["TEXT"],
        temperature=0.1,  # Slight temperature for flexibility in parsing text
    ),
)


