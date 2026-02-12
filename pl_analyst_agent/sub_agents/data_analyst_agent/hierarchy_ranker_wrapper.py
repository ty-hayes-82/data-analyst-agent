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
Logging wrapper for hierarchy_variance_ranker_agent.

Adds detailed logging around the hierarchy variance ranking process to track
level-by-level analysis progress. Also injects historical root cause context
to inform LLM decision-making.
"""

import json
from pathlib import Path
from typing import AsyncGenerator
import yaml

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions

# Import the actual hierarchy_variance_ranker_agent
import importlib
_hierarchy_ranker_module = importlib.import_module(
    'pl_analyst.pl_analyst_agent.sub_agents.03_hierarchy_variance_ranker_agent.agent'
)
hierarchy_variance_ranker_agent_core = _hierarchy_ranker_module.root_agent


def _load_gl_root_cause_history():
    """Load GL root cause history from business context."""
    context_path = Path(__file__).parent.parent.parent.parent / "config" / "business_context.yaml"
    try:
        if context_path.exists():
            with open(context_path, 'r', encoding='utf-8') as f:
                context = yaml.safe_load(f)
                return context.get("gl_root_cause_history", {}) if context else {}
    except Exception as e:
        print(f"[HierarchyRanker] Warning: Could not load business context: {e}")
    return {}


def _get_historical_context_for_gl(gl_account: str, variance_dollar: float, root_cause_history: dict) -> str:
    """
    Get historical root cause context for a GL account.
    
    Returns a context string to inject into analysis, or None if no history.
    """
    if not gl_account or gl_account not in root_cause_history:
        return None
    
    history_entries = root_cause_history.get(gl_account, [])
    if not history_entries:
        return None
    
    # Find similar variance patterns (within 50% magnitude)
    similar_entries = []
    for entry in history_entries[-3:]:  # Last 3 entries
        hist_variance = entry.get("variance_dollar", 0)
        if hist_variance != 0:
            ratio = abs(variance_dollar / hist_variance)
            if 0.5 <= ratio <= 2.0:  # Within 50% to 200%
                similar_entries.append(entry)
    
    if not similar_entries:
        return None
    
    # Build context string
    context_lines = [f"Historical context for {gl_account}:"]
    for entry in similar_entries[:2]:  # Top 2 similar patterns
        period = entry.get("period", "Unknown")
        hist_variance = entry.get("variance_dollar", 0)
        root_cause = entry.get("root_cause", "Unknown")
        sub_class = entry.get("sub_classification", "")
        reasoning = entry.get("reasoning", "")
        status = entry.get("status", "")
        
        context_lines.append(
            f"  - {period}: ${hist_variance:+,.0f} due to {root_cause}"
            + (f"/{sub_class}" if sub_class else "")
            + (f" - {reasoning}" if reasoning else "")
            + (f" [{status}]" if status else "")
        )
    
    return "\n".join(context_lines)


class HierarchyVarianceRankerWithLogging(BaseAgent):
    """
    Logging wrapper around hierarchy_variance_ranker_agent.
    
    Logs level analysis details including:
    - Current level being analyzed
    - Number of items aggregated
    - Top drivers identified
    - Variance amounts
    """
    
    def __init__(self):
        super().__init__(name="hierarchy_variance_ranker_with_logging")
    
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        # Get phase logger and current level
        phase_logger = ctx.session.state.get("phase_logger")
        current_level = ctx.session.state.get("current_level", 2)
        cost_center = ctx.session.state.get("current_cost_center", "unknown")
        
        # Load historical root cause context
        root_cause_history = _load_gl_root_cause_history()
        if root_cause_history:
            print(f"[HierarchyRanker] Loaded {len(root_cause_history)} GL accounts with historical root cause data")
        
        # Log start of level analysis
        if phase_logger:
            phase_logger.log_workflow_transition(
                from_agent="hierarchical_drill_down_loop",
                to_agent="hierarchy_variance_ranker_agent",
                message=f"Starting Level {current_level} aggregation and ranking"
            )
        
        print(f"\n[HierarchyVarianceRanker] Analyzing Level {current_level} for CC {cost_center}")
        
        # Run the actual agent
        async for event in hierarchy_variance_ranker_agent_core._run_async_impl(ctx):
            # Check if this is the final event with results
            if event.actions and event.actions.state_delta:
                level_result_key = "level_analysis_result"
                if level_result_key in event.actions.state_delta:
                    result_data = event.actions.state_delta[level_result_key]
                    
                    # Parse and log results
                    try:
                        if isinstance(result_data, str):
                            result = json.loads(result_data)
                        else:
                            result = result_data
                        
                        # Extract key metrics
                        top_items = result.get("top_items", [])
                        # Fallback to top_drivers if top_items is not available
                        if not top_items:
                            top_items = result.get("top_drivers", [])
                        total_variance = result.get("total_variance_dollar", 0)
                        items_count = result.get("items_selected_count", 0)
                        
                        # NEW: Inject historical context for GL accounts (Level 4 only)
                        if current_level == 4 and root_cause_history and top_items:
                            historical_insights = []
                            for item in top_items[:5]:  # Top 5 items
                                gl_account = item.get("item", "")
                                variance_dollar = item.get("variance_dollar", 0)
                                
                                if gl_account and variance_dollar:
                                    context = _get_historical_context_for_gl(
                                        gl_account, variance_dollar, root_cause_history
                                    )
                                    if context:
                                        historical_insights.append(context)
                            
                            # Add to result if we found any historical context
                            if historical_insights:
                                result["historical_context"] = "\n\n".join(historical_insights)
                                print(f"[HierarchyRanker] Injected historical context for {len(historical_insights)} GL accounts")
                        
                        # Log summary
                        if phase_logger:
                            summary = {
                                "level": current_level,
                                "items_aggregated": len(top_items),
                                "top_drivers_identified": items_count,
                                "total_variance_dollar": total_variance,
                                "historical_context_added": current_level == 4 and bool(result.get("historical_context"))
                            }
                            
                            phase_logger.log_agent_output(
                                agent_name=f"hierarchy_variance_ranker_level_{current_level}",
                                output_summary=summary
                            )
                        
                        print(f"[HierarchyVarianceRanker] Level {current_level} Results:")
                        print(f"  Items Aggregated: {len(top_items)}")
                        print(f"  Top Drivers: {items_count}")
                        print(f"  Total Variance: ${total_variance:,.0f}")
                        
                        # Log top drivers
                        if top_items and len(top_items) > 0:
                            print(f"  Top 3 Drivers:")
                            for i, item in enumerate(top_items[:3], 1):
                                item_name = item.get("item", "Unknown")
                                variance = item.get("variance_dollar", 0)
                                print(f"    {i}. {item_name}: ${variance:,.0f}")
                    
                    except (json.JSONDecodeError, AttributeError, KeyError) as e:
                        print(f"[HierarchyVarianceRanker] Warning: Could not parse result data: {e}")
                    
                    # Also store in a level-specific state key for later reference
                    updated_state = dict(event.actions.state_delta)
                    updated_state[f"level_{current_level}_analysis"] = result if not isinstance(result, str) else result_data
                    
                    # Yield event with updated state
                    yield Event(
                        invocation_id=ctx.invocation_id,
                        author=self.name,
                        actions=EventActions(state_delta=updated_state)
                    )
                else:
                    yield event
            else:
                yield event


# Export the logging wrapper as the agent to use
root_agent_with_logging = HierarchyVarianceRankerWithLogging()

