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
Ingest & Validator Agent - Main agent module.
"""

from google.adk import Agent
from google.genai import types

from config.model_loader import get_agent_model
from .prompt import DATA_VALIDATION_INSTRUCTION
from .tools import reshape_and_validate, load_and_validate_from_cache, aggregate_by_category, join_ops_metrics, join_chart_metadata, json_to_csv, csv_to_json_passthrough, load_from_global_cache, flip_revenue_signs


root_agent = Agent(
    model=get_agent_model("data_validation_agent"),
    name="data_validation_agent",
    instruction=DATA_VALIDATION_INSTRUCTION,
    tools=[reshape_and_validate, load_and_validate_from_cache, aggregate_by_category, join_ops_metrics, join_chart_metadata, json_to_csv, csv_to_json_passthrough, load_from_global_cache, flip_revenue_signs],
    generate_content_config=types.GenerateContentConfig(
        response_modalities=["TEXT"],
        temperature=0.0,
    ),
    # output_key="validated_data"  # REMOVED: May cause session state conflicts in nested agent hierarchy
)
