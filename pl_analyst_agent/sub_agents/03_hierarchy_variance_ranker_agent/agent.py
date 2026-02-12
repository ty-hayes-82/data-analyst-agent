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
Hierarchy Variance Ranker Agent - Analyzes data at specific hierarchy levels.

EFFICIENCY UPDATE: Now uses compute_level_statistics() - a single pure Python tool
that does ALL aggregation, variance calculation, and ranking. LLM receives ONLY
top 5-10 pre-computed items (not full datasets).
"""

from google.adk import Agent
from google.genai import types

from config.model_loader import get_agent_model
from .prompt import HIERARCHY_VARIANCE_RANKER_INSTRUCTION
from .tools import compute_level_statistics


root_agent = Agent(
    model=get_agent_model("hierarchy_variance_ranker_agent"),
    name="hierarchy_variance_ranker_agent",
    description="Analyzes financial data at hierarchy levels using efficient Python tools. Receives only top drivers with pre-computed statistics.",
    instruction=HIERARCHY_VARIANCE_RANKER_INSTRUCTION,
    tools=[compute_level_statistics],  # Single efficient tool replaces 4 old tools
    generate_content_config=types.GenerateContentConfig(
        response_modalities=["TEXT"],
        temperature=0.0,
    ),
    output_key="level_analysis_result"
)

