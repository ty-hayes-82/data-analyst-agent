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
Data Analyst Agent - Hierarchical Drill-Down Orchestrator.

Manages Level 2 -> Level 3 -> Level 4 hierarchical analysis with LLM-driven
drill-down decisions based on variance materiality.

Architecture:
1. InitializeHierarchicalLoop: Set starting level (2)
2. hierarchical_drill_down_loop (LoopAgent):
   - hierarchy_variance_ranker_agent: Aggregate & rank by level
   - DrillDownDecisionAgent: LLM decides CONTINUE or STOP
   - ProcessDrillDownDecision: Update state, escalate if done
3. FinalizeAnalysisResults: Aggregate all level results
"""

import json
from typing import AsyncGenerator, Dict, Any, List

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.llm_agent import Agent as LlmAgent
from google.adk.agents.sequential_agent import SequentialAgent
from google.adk.agents.loop_agent import LoopAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.genai import types

from config.model_loader import get_agent_model
from .prompt import DRILL_DOWN_DECISION_INSTRUCTION

# Import existing hierarchy_variance_ranker_agent directly
import importlib
_hierarchy_ranker_module = importlib.import_module(
    'pl_analyst_agent.sub_agents.03_hierarchy_variance_ranker_agent.agent'
)
hierarchy_variance_ranker_agent = _hierarchy_ranker_module.root_agent


# --- Logging Wrapper for hierarchy_variance_ranker_agent ---

class HierarchyRankerLoggingWrapper(BaseAgent):
    """Adds logging around the hierarchy variance ranker agent."""
    
    def __init__(self):
        super().__init__(name="hierarchy_ranker_logging")
    
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        phase_logger = ctx.session.state.get("phase_logger")
        current_level = ctx.session.state.get("current_level", 2)
        cost_center = ctx.session.state.get("current_cost_center", "unknown")
        
        # Log start
        if phase_logger:
            phase_logger.log_workflow_transition(
                from_agent="hierarchical_drill_down_loop",
                to_agent="hierarchy_variance_ranker_agent",
                message=f"Starting Level {current_level} aggregation and ranking"
            )
        
        print(f"\n[HierarchyVarianceRanker] Analyzing Level {current_level} for CC {cost_center}")
        
        # Just pass through - no yielding
        yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=EventActions())


class HierarchyRankerResultLogger(BaseAgent):
    """Logs results after hierarchy variance ranker completes."""
    
    def __init__(self):
        super().__init__(name="hierarchy_ranker_result_logger")
    
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        phase_logger = ctx.session.state.get("phase_logger")
        current_level = ctx.session.state.get("current_level", 2)
        result_data = ctx.session.state.get("level_analysis_result")
        
        if result_data:
            try:
                if isinstance(result_data, str):
                    result = json.loads(result_data)
                else:
                    result = result_data
                
                top_items = result.get("top_items", [])
                total_variance = result.get("total_variance_dollar") or 0  # Handle None from JSON null
                items_count = result.get("items_selected_count", 0)
                
                # Log summary
                if phase_logger:
                    summary = {
                        "level": current_level,
                        "items_aggregated": len(top_items),
                        "top_drivers_identified": items_count,
                        "total_variance_dollar": total_variance
                    }
                    phase_logger.log_agent_output(
                        agent_name=f"hierarchy_variance_ranker_level_{current_level}",
                        output_summary=summary
                    )
                
                print(f"[HierarchyVarianceRanker] Level {current_level} Results:")
                print(f"  Items Aggregated: {len(top_items)}")
                print(f"  Top Drivers: {items_count}")
                print(f"  Total Variance: ${total_variance:,.0f}")
                
                if top_items and len(top_items) > 0:
                    print(f"  Top 3 Drivers:")
                    for i, item in enumerate(top_items[:3], 1):
                        item_name = item.get("item", "Unknown")
                        variance = item.get("variance_dollar", 0)
                        print(f"    {i}. {item_name}: ${variance:,.0f}")
                
                # Store in level-specific key
                state_delta = {f"level_{current_level}_analysis": result_data}
                yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=EventActions(state_delta=state_delta))
                return
                
            except (json.JSONDecodeError, AttributeError, KeyError) as e:
                print(f"[HierarchyVarianceRanker] Warning: Could not parse result data: {e}")
        
        yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=EventActions())


# --- Helper Agents for Hierarchical Drill-Down ---

class InitializeHierarchicalLoop(BaseAgent):
    """Initialize hierarchical loop state - starts at Level 2."""
    
    def __init__(self):
        super().__init__(name="initialize_hierarchical_loop")
    
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        # Get phase logger from state if available
        phase_logger = ctx.session.state.get("phase_logger")
        cost_center = ctx.session.state.get("current_cost_center", "unknown")
        
        # Initialize loop state
        initial_state = {
            "current_level": 2,
            "drill_down_history": [],
            "continue_loop": True,
            "levels_analyzed": []
        }
        
        # Log initialization
        if phase_logger:
            phase_logger.log_workflow_transition(
                from_agent="data_analyst_agent",
                to_agent="hierarchical_drill_down_loop",
                message=f"Initializing hierarchical drill-down at Level 2 for cost center {cost_center}"
            )
            phase_logger.log_level_start(
                level=2,
                cost_center=cost_center,
                message="Starting Level 2 analysis (high-level categories)"
            )
        
        print(f"\n{'='*80}")
        print(f"[InitializeHierarchicalLoop] Starting hierarchical analysis at Level 2")
        print(f"  Cost Center: {cost_center}")
        print(f"  Analysis Path: Level 2 -> Level 3 -> Level 4 (as needed)")
        print(f"{'='*80}\n")
        
        actions = EventActions(state_delta=initial_state)
        yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=actions)


class DrillDownDecisionAgent(LlmAgent):
    """LLM agent that decides whether to drill down to next level."""
    
    def __init__(self):
        super().__init__(
            name="drill_down_decision_agent",
            model=get_agent_model("drill_down_decision_agent"),
            instruction=DRILL_DOWN_DECISION_INSTRUCTION,
            output_key="drill_down_decision",
            generate_content_config=types.GenerateContentConfig(
                response_modalities=["TEXT"],
                response_mime_type="application/json",
                temperature=0.0,
            ),
        )


class ProcessDrillDownDecision(BaseAgent):
    """Process drill-down decision and update loop state."""
    
    def __init__(self):
        super().__init__(name="process_drill_down_decision")
    
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        # Get phase logger
        phase_logger = ctx.session.state.get("phase_logger")
        
        # Check if current level was a duplicate (from hierarchy_variance_ranker)
        level_analysis_result = ctx.session.state.get("level_analysis_result", "{}")
        try:
            level_result = json.loads(level_analysis_result) if isinstance(level_analysis_result, str) else level_analysis_result
        except json.JSONDecodeError:
            level_result = {}
        
        is_duplicate = level_result.get("is_duplicate", False)
        
        # Get decision from state
        decision_str = ctx.session.state.get("drill_down_decision", "{}")
        current_level = ctx.session.state.get("current_level", 2)
        drill_down_history = ctx.session.state.get("drill_down_history", [])
        levels_analyzed = ctx.session.state.get("levels_analyzed", [])
        
        # If current level is a duplicate, automatically skip to next level
        if is_duplicate:
            print(f"\n{'='*80}")
            print(f"[DrillDownDecision] SKIP Level {current_level} (duplicate of Level {current_level-1})")
            print(f"  Automatically continuing to next level")
            print(f"{'='*80}\n")
            
            next_level = current_level + 1
            
            # Log decision
            if phase_logger:
                phase_logger.log_drill_down_decision(
                    level=current_level,
                    decision="SKIP",
                    reasoning=f"Level {current_level} is duplicate of Level {current_level-1}",
                    next_level=next_level
                )
                phase_logger.log_level_start(
                    level=next_level,
                    cost_center=ctx.session.state.get("current_cost_center", "unknown"),
                    message=f"Skipping to Level {next_level}"
                )
            
            state_delta = {
                "current_level": next_level,
                "drill_down_history": drill_down_history,
                "continue_loop": True,
                "levels_analyzed": levels_analyzed
            }
            
            yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=EventActions(state_delta=state_delta))
            return
        
        try:
            decision = json.loads(decision_str) if isinstance(decision_str, str) else decision_str
        except json.JSONDecodeError:
            decision = {"action": "STOP", "reasoning": "Invalid decision format"}
        
        action = decision.get("action", "STOP")
        reasoning = decision.get("reasoning", "No reasoning provided")
        
        # Record this level as analyzed
        if current_level not in levels_analyzed:
            levels_analyzed.append(current_level)
        
        # Add to history
        drill_down_history.append({
            "level": current_level,
            "action": action,
            "reasoning": reasoning
        })
        
        # Determine next action
        # UPDATED: Allow drilling to Level 5 (GL accounts)
        # Level 5 is always GL accounts regardless of hierarchy structure
        if action == "CONTINUE" and current_level < 5:
            # Continue to next level
            next_level = current_level + 1
            
            # Log decision
            if phase_logger:
                phase_logger.log_drill_down_decision(
                    level=current_level,
                    decision="CONTINUE",
                    reasoning=reasoning,
                    next_level=next_level
                )
                phase_logger.log_level_start(
                    level=next_level,
                    cost_center=ctx.session.state.get("current_cost_center", "unknown"),
                    message=f"Drilling down to Level {next_level}"
                )
            
            print(f"\n{'='*80}")
            print(f"[DrillDownDecision] CONTINUE to Level {next_level}")
            print(f"  Reasoning: {reasoning}")
            print(f"{'='*80}\n")
            
            state_delta = {
                "current_level": next_level,
                "drill_down_history": drill_down_history,
                "continue_loop": True,
                "levels_analyzed": levels_analyzed
            }
            
            yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=EventActions(state_delta=state_delta))
        
        else:
            # Stop drilling - escalate to finalize
            stop_reason = "Reached Level 5 (GL account detail)" if current_level == 5 else reasoning
            
            # Log decision
            if phase_logger:
                phase_logger.log_drill_down_decision(
                    level=current_level,
                    decision="STOP",
                    reasoning=stop_reason,
                    next_level=None
                )
            
            print(f"\n{'='*80}")
            print(f"[DrillDownDecision] STOP at Level {current_level}")
            print(f"  Reasoning: {stop_reason}")
            print(f"  Levels Analyzed: {levels_analyzed}")
            print(f"{'='*80}\n")
            
            state_delta = {
                "drill_down_history": drill_down_history,
                "continue_loop": False,
                "levels_analyzed": levels_analyzed
            }
            
            # Escalate to exit loop
            yield Event(
                invocation_id=ctx.invocation_id,
                author=self.name,
                actions=EventActions(state_delta=state_delta, escalate=True)
            )


class FinalizeAnalysisResults(BaseAgent):
    """Aggregate all level analysis results into hierarchical summary."""
    
    def __init__(self):
        super().__init__(name="finalize_analysis_results")
    
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        # Get phase logger
        phase_logger = ctx.session.state.get("phase_logger")
        cost_center = ctx.session.state.get("current_cost_center", "unknown")
        
        # Collect all level results
        levels_analyzed = ctx.session.state.get("levels_analyzed", [])
        drill_down_history = ctx.session.state.get("drill_down_history", [])
        
        # Build hierarchical result
        hierarchical_result = {
            "analysis_type": "hierarchical_drill_down",
            "cost_center": cost_center,
            "levels_analyzed": levels_analyzed,
            "drill_down_path": " -> ".join([f"Level {level}" for level in levels_analyzed]),
            "drill_down_history": drill_down_history,
            "level_results": {}
        }
        
        # Collect results from each level
        for level in levels_analyzed:
            level_key = f"level_{level}_analysis"
            level_result = ctx.session.state.get(level_key)
            if level_result:
                hierarchical_result["level_results"][f"level_{level}"] = level_result
        
        # Convert to JSON string
        result_json = json.dumps(hierarchical_result, indent=2)
        
        # Log finalization
        if phase_logger:
            phase_logger.log_workflow_transition(
                from_agent="hierarchical_drill_down_loop",
                to_agent="finalize_analysis_results",
                message=f"Finalizing hierarchical analysis - analyzed {len(levels_analyzed)} level(s)"
            )
            
            summary_metrics = {
                "levels_analyzed_count": len(levels_analyzed),
                "drill_down_path": hierarchical_result["drill_down_path"],
                "deepest_level": max(levels_analyzed) if levels_analyzed else 0
            }
            
            phase_logger.log_level_complete(
                level=max(levels_analyzed) if levels_analyzed else 0,
                cost_center=cost_center,
                summary=summary_metrics
            )
        
        print(f"\n{'='*80}")
        print(f"[FinalizeAnalysisResults] Hierarchical analysis complete")
        print(f"  Levels Analyzed: {levels_analyzed}")
        print(f"  Drill-Down Path: {hierarchical_result['drill_down_path']}")
        print(f"  Total Decisions: {len(drill_down_history)}")
        print(f"{'='*80}\n")
        
        # Store result in state
        state_delta = {
            "data_analyst_result": result_json,
            "hierarchical_analysis_complete": True
        }
        
        print(f"\n{'='*80}")
        print(f"[FinalizeAnalysisResults] COMPLETE - Yielding event (NO ESCALATION)")
        print(f"{'='*80}\n")
        
        actions = EventActions(state_delta=state_delta)
        yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=actions)


# --- Main Workflow Assembly ---

# Hierarchical drill-down loop
hierarchical_drill_down_loop = LoopAgent(
    name="hierarchical_drill_down_loop",
    sub_agents=[
        HierarchyRankerLoggingWrapper(),    # Log before analysis
        hierarchy_variance_ranker_agent,     # Aggregate & rank by current_level
        HierarchyRankerResultLogger(),       # Log results after analysis
        DrillDownDecisionAgent(),            # LLM decides CONTINUE or STOP
        ProcessDrillDownDecision(),          # Update state and escalate if done
    ],
    description="Iterative hierarchical analysis: Level 2 -> 3 -> 4 -> 5 (GL accounts) with LLM-driven drill-down decisions. Automatically skips duplicate levels."
)

# Root data analyst agent
root_agent = SequentialAgent(
    name="data_analyst_agent",
    sub_agents=[
        InitializeHierarchicalLoop(),       # Initialize at Level 2
        hierarchical_drill_down_loop,       # Loop through levels
        FinalizeAnalysisResults(),          # Aggregate all results
    ],
    description="Hierarchical drill-down orchestrator: Manages Level 2->3->4->5 analysis with materiality-based drill-down decisions. Always analyzes GL accounts (Level 5)."
)

