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
Statistical Insights Agent - Stats-first architecture.

Computes all statistics upfront in Python/pandas, then uses LLM to interpret
and provide business insights.
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

from config.model_loader import get_agent_model
from .prompt import STATISTICAL_INSIGHTS_INSTRUCTION
from .tools import compute_statistical_summary


class StatisticalComputationAgent(BaseAgent):
    """Computes comprehensive statistics using pure Python/pandas/numpy."""
    
    def __init__(self):
        super().__init__(name="statistical_computation_agent")
    
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        print(f"\n{'='*80}")
        print("[StatisticalComputation] Computing comprehensive statistical summary...")
        print(f"{'='*80}\n")
        
        # Call the statistical summary tool
        stats_json = await compute_statistical_summary()
        
        # Validate data integrity - fail fast if missing or invalid
        try:
            stats = json.loads(stats_json)
            
            # Check for errors from compute tool
            if 'error' in stats:
                error_msg = json.dumps({
                    "error": "DataUnavailable",
                    "source": "StatisticalComputation",
                    "detail": stats.get('error', 'Unknown error in statistical computation'),
                    "action": "stop"
                })
                print(f"[StatisticalComputation] ERROR: {stats.get('error')}\n")
                
                # Store error in state and stop
                actions = EventActions(state_delta={
                    "statistical_summary": error_msg,
                    "computation_error": True
                })
                yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=actions)
                return
            
            # Validate required fields exist
            required_fields = ['top_drivers', 'anomalies', 'monthly_totals', 'summary_stats']
            missing_fields = [field for field in required_fields if field not in stats]
            
            if missing_fields:
                error_msg = json.dumps({
                    "error": "DataUnavailable",
                    "source": "StatisticalComputation",
                    "detail": f"Missing required fields in statistical summary: {', '.join(missing_fields)}",
                    "action": "stop"
                })
                print(f"[StatisticalComputation] ERROR: Missing required fields: {missing_fields}\n")
                
                actions = EventActions(state_delta={
                    "statistical_summary": error_msg,
                    "computation_error": True
                })
                yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=actions)
                return
            
            # Print summary to console
            print(f"[StatisticalComputation] Analysis complete:")
            print(f"  - Top drivers identified: {len(stats.get('top_drivers', []))}")
            print(f"  - Anomalies detected: {len(stats.get('anomalies', []))}")
            print(f"  - Correlations found: {len(stats.get('correlations', {}))}")
            print(f"  - Total periods: {stats.get('summary_stats', {}).get('total_periods', 0)}")
            print(f"  - Total accounts: {stats.get('summary_stats', {}).get('total_accounts', 0)}\n")
            
        except json.JSONDecodeError as e:
            error_msg = json.dumps({
                "error": "DataUnavailable",
                "source": "StatisticalComputation",
                "detail": f"Failed to parse statistical summary JSON: {str(e)}",
                "action": "stop"
            })
            print(f"[StatisticalComputation] ERROR: Invalid JSON returned from compute tool\n")
            
            actions = EventActions(state_delta={
                "statistical_summary": error_msg,
                "computation_error": True
            })
            yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=actions)
            return
        
        # Store in state for LLM interpretation
        actions = EventActions(state_delta={
            "statistical_summary": stats_json
        })
        yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=actions)


class StatisticalInsightsAgent(LlmAgent):
    """LLM agent that interprets statistical results with business context."""
    
    def __init__(self):
        super().__init__(
            name="statistical_insights_agent",
            model=get_agent_model("statistical_insights_agent"),
            instruction=STATISTICAL_INSIGHTS_INSTRUCTION,
            output_key="data_analyst_result",
            generate_content_config=types.GenerateContentConfig(
                response_modalities=["TEXT"],
                response_mime_type="application/json",
                temperature=0.0,
            ),
        )


# Main data analyst agent - Simple sequential flow
root_agent = SequentialAgent(
    name="statistical_insights_agent",
    sub_agents=[
        StatisticalComputationAgent(),    # Compute all stats in Python/pandas
        StatisticalInsightsAgent(),       # LLM interprets and provides business insights
    ],
    description="Stats-first P&L analysis: Computes comprehensive statistics in Python, then uses LLM for business interpretation and actionable insights"
)
