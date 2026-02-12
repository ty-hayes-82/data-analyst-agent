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
Report Synthesis Agent - Main agent module.
"""

from typing import AsyncGenerator

from google.adk import Agent
from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.genai import types

from config.model_loader import get_agent_model
from .prompt import REPORT_SYNTHESIS_AGENT_INSTRUCTION
from .tools import generate_markdown_report


_base_agent = Agent(
    model=get_agent_model("report_report_synthesis_agent"),
    name="report_report_synthesis_agent",
    description="Synthesizes results from all parallel analysis agents into a structured executive report using 3-level framework.",
    instruction=REPORT_SYNTHESIS_AGENT_INSTRUCTION,
    output_key="report_synthesis_result",
    tools=[generate_markdown_report],
    generate_content_config=types.GenerateContentConfig(
        response_modalities=["TEXT"],
        temperature=0.2,
    ),
)


class ReportSynthesisWrapper(BaseAgent):
    """Wrapper to add debug logging for report synthesis agent."""
    
    def __init__(self, wrapped_agent):
        super().__init__(name="report_report_synthesis_agent")
        # Store agent in __dict__ to avoid Pydantic validation issues
        object.__setattr__(self, 'wrapped_agent', wrapped_agent)
    
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        print(f"\n{'='*80}")
        print(f"[REPORT_SYNTHESIS] Starting report synthesis agent")
        print(f"{'='*80}\n")
        try:
            async for event in self.wrapped_agent.run_async(ctx):
                yield event
        except Exception as e:
            print(f"[REPORT_SYNTHESIS] ERROR: {e}")
            import traceback
            traceback.print_exc()
            raise
        print(f"\n{'='*80}")
        print(f"[REPORT_SYNTHESIS] Report synthesis agent complete")
        print(f"{'='*80}\n")


# Export wrapped agent
root_agent = ReportSynthesisWrapper(_base_agent)

