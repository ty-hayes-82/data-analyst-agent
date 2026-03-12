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
Seasonal Baseline Agent - Detects true anomalies after seasonal adjustment.

Architecture: Sequential (Computation -> LLM Interpretation)
"""

from typing import AsyncGenerator
import json

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.sequential_agent import SequentialAgent
from google.adk.agents.llm_agent import Agent as LlmAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.genai import types

from config.model_loader import get_agent_model, get_agent_thinking_config
from .prompt import SEASONAL_BASELINE_INSTRUCTION
from ..statistical_insights_agent.tools.compute_seasonal_decomposition import compute_seasonal_decomposition
from ...utils.focus_directives import augment_instruction


class SeasonalComputationAgent(BaseAgent):
    """Computes seasonal decomposition using statsmodels."""
    
    def __init__(self):
        super().__init__(name="seasonal_computation_agent")
    
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        print(f"\n{'='*80}")
        print("[SeasonalBaseline] Computing seasonal decomposition (STL)...")
        print(f"{'='*80}\n")
        
        # Call the seasonal decomposition tool
        seasonal_json = await compute_seasonal_decomposition()
        
        # Validate results
        try:
            seasonal_data = json.loads(seasonal_json)
            
            # Check for errors
            if 'error' in seasonal_data:
                error_msg = json.dumps({
                    "error": "SeasonalAnalysisFailed",
                    "source": "SeasonalBaseline",
                    "detail": seasonal_data.get('message', 'Unknown error in seasonal analysis'),
                    "action": "continue"  # Not critical, workflow can continue
                })
                print(f"[SeasonalBaseline] WARNING: {seasonal_data.get('message')}\n")
                
                actions = EventActions(state_delta={
                    "seasonal_baseline_summary": error_msg,
                    "seasonal_computation_warning": True
                })
                yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=actions)
                return
            
            # Print summary
            summary = seasonal_data.get('summary', {})
            print(f"[SeasonalBaseline] Decomposition complete:")
            print(f"  - Accounts analyzed: {summary.get('accounts_analyzed', 0)}")
            print(f"  - Total anomalies detected: {summary.get('total_anomalies_detected', 0)}")
            print(f"  - Accounts with anomalies: {summary.get('accounts_with_anomalies', 0)}")
            print(f"  - Anomaly rate: {summary.get('anomaly_rate_pct', 0)}%\n")
            
        except json.JSONDecodeError as e:
            error_msg = json.dumps({
                "error": "SeasonalAnalysisFailed",
                "source": "SeasonalBaseline",
                "detail": f"Failed to parse seasonal analysis JSON: {str(e)}",
                "action": "continue"
            })
            print(f"[SeasonalBaseline] WARNING: Invalid JSON returned\n")
            
            actions = EventActions(state_delta={
                "seasonal_baseline_summary": error_msg,
                "seasonal_computation_warning": True
            })
            yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=actions)
            return
        
        # Store in state for LLM interpretation
        actions = EventActions(state_delta={
            "seasonal_baseline_summary": seasonal_json
        })
        yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=actions)


class SeasonalInterpretationAgent(LlmAgent):
    """LLM agent that interprets seasonal results with business context."""
    
    def __init__(self):
        super().__init__(
            name="seasonal_baseline_agent",
            model=get_agent_model("seasonal_baseline_agent"),
            instruction=SEASONAL_BASELINE_INSTRUCTION,
            output_key="seasonal_baseline_result",
            generate_content_config=types.GenerateContentConfig(
                response_modalities=["TEXT"],
                response_mime_type="application/json",
                temperature=0.0,
                thinking_config=get_agent_thinking_config("seasonal_baseline_agent"),
            ),
        )


class FocusAwareSeasonalInterpreter(BaseAgent):
    """Wrapper that appends focus directives to the seasonal instruction."""

    def __init__(self):
        super().__init__(name="seasonal_baseline_interpreter")
        self._wrapped = SeasonalInterpretationAgent()
        self.output_key = getattr(self._wrapped, "output_key", "seasonal_baseline_result")

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        self._wrapped.instruction = augment_instruction(SEASONAL_BASELINE_INSTRUCTION, ctx.session.state)
        async for event in self._wrapped.run_async(ctx):
            yield event


# Main seasonal baseline agent - Sequential flow
root_agent = SequentialAgent(
    name="seasonal_baseline_agent",
    sub_agents=[
        SeasonalComputationAgent(),            # Compute seasonal decomposition
        FocusAwareSeasonalInterpreter(),       # LLM interprets findings
    ],
    description="Decomposes time series to identify TRUE anomalies after removing seasonal patterns. [Requires: 18+ periods of data]"
)

