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
Hierarchical Analysis Agent - Drill-Down Orchestrator.

Manages Level 0 -> N hierarchical analysis with code-based or LLM-driven
drill-down decisions based on variance materiality.

Architecture:
1. InitializeHierarchicalLoop: Set starting level (0)
2. hierarchical_drill_down_loop (LoopAgent):
   - hierarchy_variance_ranker_agent: Aggregate & rank by level
   - DrillDownDecisionFunction (code) or DrillDownDecisionAgent (LLM)
   - ProcessDrillDownDecision: Update state, escalate if done
3. FinalizeAnalysisResults: Aggregate all level results

Feature flag: USE_CODE_INSIGHTS (env var, default "true")
"""

import os
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

from config.model_loader import get_agent_model, get_agent_thinking_config
from .prompt import DRILL_DOWN_DECISION_INSTRUCTION

USE_CODE_INSIGHTS = os.environ.get("USE_CODE_INSIGHTS", "true").lower() == "true"
CROSS_DIMENSION_ANALYSIS = os.environ.get("CROSS_DIMENSION_ANALYSIS", "false").lower() == "true"
INDEPENDENT_LEVEL_ANALYSIS = os.environ.get("INDEPENDENT_LEVEL_ANALYSIS", "false").lower() == "true"
_INDEPENDENT_LEVEL_MAX_CARDS = max(1, int(os.environ.get("INDEPENDENT_LEVEL_MAX_CARDS", "5")))

from ..hierarchy_variance_agent.agent import root_agent as hierarchy_variance_ranker_agent


# --- Logging Wrapper for hierarchy_variance_ranker_agent ---

class HierarchyRankerLoggingWrapper(BaseAgent):
    """Adds logging around the hierarchy variance ranker agent."""
    
    def __init__(self):
        super().__init__(name="hierarchy_ranker_logging")
    
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        phase_logger = ctx.session.state.get("phase_logger")
        current_level = ctx.session.state.get("current_level", 2)
        analysis_target = (
            ctx.session.state.get("current_analysis_target", "unknown")
        )
        dimension_value = ctx.session.state.get("dimension_value", analysis_target)

        # Log start
        if phase_logger:
            phase_logger.log_workflow_transition(
                from_agent="hierarchical_drill_down_loop",
                to_agent="hierarchy_variance_ranker_agent",
                message=f"Starting Level {current_level} aggregation and ranking"
            )
        
        print(f"\n[HierarchyVarianceRanker] Analyzing Level {current_level} for target: {dimension_value}")
        
        # Just pass through - no yielding
        yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=EventActions())


class HierarchyRankerResultLogger(BaseAgent):
    """Logs results after hierarchy variance ranker completes."""
    
    def __init__(self):
        super().__init__(name="hierarchy_ranker_result_logger")
    
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        from ...utils.json_utils import safe_parse_json
        phase_logger = ctx.session.state.get("phase_logger")
        current_level = ctx.session.state.get("current_level", 0)
        result_data = ctx.session.state.get("level_analysis_result")
        
        if result_data:
            try:
                result = safe_parse_json(result_data)
                
                # HierarchyVarianceRanker LLM agent returns a JSON with 'insight_cards'
                # But it might also return the raw tool output if it's not following instructions
                # or if we are in a mode where we want the raw stats.
                # The current prompt for hierarchy_variance_ranker_agent asks for insight_cards.
                
                # Check for insight_cards
                insight_cards = result.get("insight_cards", [])
                total_variance = result.get("total_variance_dollar", 0)
                
                # Log summary
                if phase_logger:
                    summary = {
                        "level": current_level,
                        "insight_cards_count": len(insight_cards),
                        "total_variance_dollar": total_variance
                    }
                    phase_logger.log_agent_output(
                        agent_name=f"hierarchy_variance_ranker_level_{current_level}",
                        output_summary=summary
                    )
                
                print(f"[HierarchyVarianceRanker] Level {current_level} Results:")
                print(f"  Insight Cards: {len(insight_cards)}")
                print(f"  Total Variance: ${total_variance:,.0f}")
                
                if insight_cards and len(insight_cards) > 0:
                    print(f"  Top 3 Insights:")
                    for i, card in enumerate(insight_cards[:3], 1):
                        title = card.get("title", "No Title")
                        what = card.get("what_changed", "N/A")
                        print(f"    {i}. {title}: {what}")
                
                # Store in level-specific key
                state_delta = {f"level_{current_level}_analysis": result}
                # Workaround for state propagation
                ctx.session.state[f"level_{current_level}_analysis"] = result
                
                yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=EventActions(state_delta=state_delta))
                return
                
            except (json.JSONDecodeError, AttributeError, KeyError) as e:
                print(f"[HierarchyVarianceRanker] Warning: Could not parse result data: {e}")
        
        yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=EventActions())


# --- Cross-Dimension Analysis Step ---

class CrossDimensionAnalysisStep(BaseAgent):
    """Run cross-dimension analysis for auxiliary dimensions at the current level.

    Gated by CROSS_DIMENSION_ANALYSIS env var (default false). When disabled,
    yields a no-op event with zero overhead.
    """

    def __init__(self):
        super().__init__(name="cross_dimension_analysis_step")

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        if not CROSS_DIMENSION_ANALYSIS:
            yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=EventActions())
            return

        current_level = ctx.session.state.get("current_level", 0)

        from ..data_cache import get_analysis_context
        analysis_ctx = get_analysis_context()
        if not analysis_ctx or not analysis_ctx.contract:
            yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=EventActions())
            return

        cross_dims = analysis_ctx.contract.get_cross_dimensions_for_level(current_level)
        if not cross_dims:
            yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=EventActions())
            return

        import asyncio
        from ..statistical_insights_agent.tools.compute_cross_dimension_analysis import (
            compute_cross_dimension_analysis,
        )

        state_delta: Dict[str, Any] = {}

        for cd_cfg in cross_dims:
            cd_name = cd_cfg.name
            print(
                f"[CrossDimensionAnalysis] Level {current_level}: "
                f"cross-analyzing with '{cd_name}'"
            )
            try:
                result_str = await compute_cross_dimension_analysis(
                    hierarchy_level=current_level,
                    auxiliary_dimension=cd_name,
                    min_sample_size=cd_cfg.min_sample_size,
                    max_cardinality=cd_cfg.max_cardinality,
                )
                state_key = f"level_{current_level}_cross_dimension_{cd_name}"
                state_delta[state_key] = result_str
                ctx.session.state[state_key] = result_str

                parsed = json.loads(result_str) if isinstance(result_str, str) else result_str
                summary = parsed.get("summary", {})
                if summary.get("interaction_significant"):
                    print(
                        f"  -> Significant interaction detected "
                        f"(drags={summary.get('cross_cutting_drags', 0)}, "
                        f"boosts={summary.get('cross_cutting_boosts', 0)})"
                    )
                elif parsed.get("skipped"):
                    print(f"  -> Skipped: {parsed.get('reason', 'unknown')}")
                else:
                    print("  -> No significant interaction")
            except Exception as e:
                print(f"  -> Failed: {e}")

        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            actions=EventActions(state_delta=state_delta),
        )


# --- Helper Agents for Hierarchical Drill-Down ---

class InitializeHierarchicalLoop(BaseAgent):
    """Initialize hierarchical loop state - starts at Level 0."""
    
    def __init__(self):
        super().__init__(name="initialize_hierarchical_loop")
    
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        # Get phase logger from state if available
        phase_logger = ctx.session.state.get("phase_logger")
        analysis_target = (
            ctx.session.state.get("current_analysis_target", "unknown")
        )
        dimension_value = ctx.session.state.get("dimension_value", analysis_target)
        
        # Determine hierarchy and max drill depth from AnalysisContext
        from ..data_cache import get_analysis_context
        analysis_ctx = get_analysis_context()
        
        # Default starting values
        start_level = 0
        max_depth = 5 
        hierarchy_name = None
        
        if analysis_ctx and analysis_ctx.contract:
            # If hierarchies are defined, max_depth is len(children)
            if analysis_ctx.contract.hierarchies:
                hierarchy = analysis_ctx.contract.hierarchies[0]
                max_depth = len(hierarchy.children)
                hierarchy_name = hierarchy.name
            
            # Use max_drill_depth from context as a cap if provided
            if hasattr(analysis_ctx, 'max_drill_depth') and analysis_ctx.max_drill_depth:
                max_depth = min(max_depth, analysis_ctx.max_drill_depth)
        
        # Initialize loop state
        initial_state = {
            "current_level": start_level,
            "max_drill_depth": max_depth,
            "hierarchy_name": hierarchy_name,
            "drill_down_history": [],
            "continue_loop": True,
            "levels_analyzed": []
        }
        
        # Log initialization
        if phase_logger:
            phase_logger.log_workflow_transition(
                from_agent="data_analyst_agent",
                to_agent="hierarchical_drill_down_loop",
                message=f"Initializing recursive drill-down at Level {start_level} for target: {dimension_value}"
            )
            phase_logger.log_level_start(
                level=start_level,
                dimension_value=dimension_value,
                message=f"Starting analysis at level {start_level}"
            )
        
        print(f"\n{'='*80}")
        print(f"[InitializeHierarchicalLoop] Starting hierarchical analysis at Level {start_level}")
        target_label = ctx.session.state.get("target_label", "Target")
        print(f"  {target_label}: {dimension_value}")
        print(f"  Hierarchy: {hierarchy_name or 'Default'}")
        print(f"  Max Drill Depth: {max_depth}")
        print(f"{'='*80}\n")
        
        actions = EventActions(state_delta=initial_state)
        yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=actions)


class DrillDownDecisionFunction(BaseAgent):
    """Code-based drill-down decision agent — replaces the LLM decision agent.

    Reads level_analysis_result from state and calls should_continue_drilling()
    to produce a deterministic CONTINUE/STOP decision. No LLM call is made.
    """

    def __init__(self):
        super().__init__(name="drill_down_decision_agent")

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        from ..hierarchy_variance_agent.tools.format_insight_cards import should_continue_drilling

        level_result_raw = ctx.session.state.get("level_analysis_result", "{}")
        current_level = ctx.session.state.get("current_level", 0)
        max_depth = ctx.session.state.get("max_drill_depth", 5)

        try:
            level_result = (
                json.loads(level_result_raw)
                if isinstance(level_result_raw, str)
                else level_result_raw
            )
        except json.JSONDecodeError:
            level_result = {}

        decision = should_continue_drilling(level_result, current_level, max_depth)
        decision_json = json.dumps(decision)

        print(
            f"[DrillDownDecisionFunction] Level {current_level}: "
            f"action={decision['action']} — {decision['reasoning']}"
        )

        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            actions=EventActions(state_delta={"drill_down_decision": decision_json}),
        )


class DrillDownDecisionAgent(LlmAgent):
    """LLM agent that decides whether to drill down to next level (fallback path)."""

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
                thinking_config=get_agent_thinking_config("drill_down_decision_agent"),
            ),
        )


class ProcessDrillDownDecision(BaseAgent):
    """Process drill-down decision and update loop state."""
    
    def __init__(self):
        super().__init__(name="process_drill_down_decision")
    
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        # Get phase logger
        phase_logger = ctx.session.state.get("phase_logger")
        
        # Check if current level was a duplicate or marked as last level
        level_analysis_result = ctx.session.state.get("level_analysis_result", "{}")
        try:
            level_result = json.loads(level_analysis_result) if isinstance(level_analysis_result, str) else level_analysis_result
        except json.JSONDecodeError:
            level_result = {}
        
        is_duplicate = level_result.get("is_duplicate", False)
        is_last_level = level_result.get("is_last_level", False)
        
        # Get decision from state
        decision_str = ctx.session.state.get("drill_down_decision", "{}")
        current_level = ctx.session.state.get("current_level", 0)
        drill_down_history = ctx.session.state.get("drill_down_history", [])
        levels_analyzed = ctx.session.state.get("levels_analyzed", [])
        
        # If current level is a duplicate, automatically skip to next level
        if is_duplicate:
            next_level = current_level + 1
            
            # Log decision
            if phase_logger:
                phase_logger.log_drill_down_decision(
                    level=current_level,
                    decision="SKIP",
                    reasoning=f"Level {current_level} is duplicate of Level {current_level-1}",
                    next_level=next_level
                )
            
            state_delta = {
                "current_level": next_level,
                "continue_loop": not is_last_level
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
        max_depth = ctx.session.state.get("max_drill_depth", 5)
        if action == "CONTINUE" and not is_last_level and current_level < max_depth:
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
            
            state_delta = {
                "current_level": next_level,
                "drill_down_history": drill_down_history,
                "continue_loop": True,
                "levels_analyzed": levels_analyzed
            }
            
            yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=EventActions(state_delta=state_delta))
        
        else:
            # Stop drilling - escalate to finalize
            if is_last_level:
                stop_reason = "Reached end of hierarchy"
            elif current_level >= (max_depth - 1):
                stop_reason = f"Reached max drill depth ({max_depth})"
            else:
                stop_reason = reasoning
            
            # Log decision
            if phase_logger:
                phase_logger.log_drill_down_decision(
                    level=current_level,
                    decision="STOP",
                    reasoning=stop_reason,
                    next_level=None
                )
            
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


class IndependentLevelAnalysisAgent(BaseAgent):
    """Multi-pass flat scan: for each non-zero hierarchy level, runs an independent
    top-down analysis starting at that level, bypassing the drill-down gate from
    higher levels.

    Gated by INDEPENDENT_LEVEL_ANALYSIS env var (default false). When disabled,
    yields a no-op event with zero overhead.

    For each starting level N (1 to max_drill_depth - 1):
      1. Call compute_level_statistics() at level N
      2. Call format_hierarchy_insight_cards() to rank findings
      3. Deduplicate against entities already found in Pass 0 (levels_analyzed state)
      4. Tag new cards with discovery_method="independent_scan"
      5. Store in state key independent_level_{N}_analysis
    """

    def __init__(self):
        super().__init__(name="independent_level_analysis_agent")

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        if not INDEPENDENT_LEVEL_ANALYSIS:
            yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=EventActions())
            return

        from ..hierarchy_variance_agent.tools.compute_level_statistics import compute_level_statistics
        from ..hierarchy_variance_agent.tools.format_insight_cards import format_hierarchy_insight_cards

        max_depth = ctx.session.state.get("max_drill_depth", 5)
        levels_analyzed = ctx.session.state.get("levels_analyzed", [])

        # Build set of (level, entity) already found in Pass 0 for dedup
        pass0_found: set = set()
        for lvl in levels_analyzed:
            lvl_data = ctx.session.state.get(f"level_{lvl}_analysis")
            if not lvl_data:
                continue
            try:
                parsed = json.loads(lvl_data) if isinstance(lvl_data, str) else lvl_data
                for card in parsed.get("insight_cards", []):
                    title = card.get("title", "")
                    # Title format: "Level N Variance Driver: {entity}"
                    if ": " in title:
                        entity = title.split(": ", 1)[-1].strip()
                        pass0_found.add((lvl, entity.lower()))
            except (json.JSONDecodeError, AttributeError):
                pass

        state_delta: Dict[str, Any] = {}
        print(
            f"\n[IndependentLevelAnalysis] Starting flat scans for levels 1..{max_depth} "
            f"(Pass 0 surfaced {len(pass0_found)} entity/level pairs)"
        )

        import asyncio

        async def _run_single_scan(start_level: int):
            print(f"[IndependentLevelAnalysis] Pass {start_level}: flat scan starting at Level {start_level}")
            try:
                from ..hierarchy_variance_agent.tools.compute_level_statistics import compute_level_statistics
                from ..hierarchy_variance_agent.tools.format_insight_cards import format_hierarchy_insight_cards

                stats_str = await compute_level_statistics(level=start_level)
                stats = json.loads(stats_str) if isinstance(stats_str, str) else stats_str

                if "error" in stats:
                    print(f"  -> Level {start_level} skipped: {stats.get('message', stats['error'])}")
                    return None

                raw_cards = format_hierarchy_insight_cards(
                    level_stats=stats,
                    discovery_method="independent_scan",
                )

                all_cards = raw_cards.get("insight_cards", [])

                # Deduplicate: remove cards whose entity was already found in Pass 0
                new_cards: list = []
                for card in all_cards:
                    title = card.get("title", "")
                    entity = title.split(": ", 1)[-1].strip() if ": " in title else title
                    card_level = stats.get("level", start_level)
                    if (card_level, entity.lower()) not in pass0_found:
                        card["discovery_method"] = "independent_scan"
                        new_cards.append(card)

                # Cap the number of new cards
                new_cards = new_cards[:_INDEPENDENT_LEVEL_MAX_CARDS]

                result = {
                    "insight_cards": new_cards,
                    "total_variance_dollar": raw_cards.get("total_variance_dollar", 0.0),
                    "level": stats.get("level", start_level),
                    "level_name": stats.get("level_name", f"Level {start_level}"),
                    "is_last_level": stats.get("is_last_level", False),
                    "pass_type": "independent_scan",
                    "start_level": start_level,
                    "total_candidates": raw_cards.get("total_candidates", 0),
                    "new_cards_after_dedup": len(new_cards),
                }
                print(
                    f"  -> Level {start_level} complete: {len(all_cards)} candidates, "
                    f"{len(new_cards)} net-new after dedup"
                )
                return start_level, result

            except Exception as exc:
                print(f"  -> Level {start_level} flat scan failed: {exc}")
                return None

        # Run all scans in parallel
        scan_tasks = [_run_single_scan(lvl) for lvl in range(1, max_depth + 1)]
        scan_results = await asyncio.gather(*scan_tasks)

        for res in scan_results:
            if res:
                start_lvl, result_obj = res
                state_key = f"independent_level_{start_lvl}_analysis"
                state_delta[state_key] = result_obj
                ctx.session.state[state_key] = result_obj

        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            actions=EventActions(state_delta=state_delta),
        )


class FinalizeAnalysisResults(BaseAgent):
    """Aggregate all level analysis results into hierarchical summary."""
    
    def __init__(self):
        super().__init__(name="finalize_analysis_results")
    
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        # Get phase logger
        phase_logger = ctx.session.state.get("phase_logger")
        analysis_target = (
            ctx.session.state.get("current_analysis_target", "unknown")
        )
        
        # DEBUG: Print all state keys
        print(f"[FinalizeAnalysisResults] Session keys: {list(ctx.session.state.keys())}")
        
        # Collect all level results
        levels_analyzed = ctx.session.state.get("levels_analyzed", [])
        drill_down_history = ctx.session.state.get("drill_down_history", [])
        
        # Build hierarchical result
        hierarchical_result = {
            "analysis_type": "hierarchical_drill_down",
            "dimension_value": analysis_target,
            "levels_analyzed": levels_analyzed,
            "drill_down_path": " -> ".join([f"Level {level}" for level in levels_analyzed]),
            "drill_down_history": drill_down_history,
            "level_results": {}
        }
        
        # Collect results from each level (including cross-dimension)
        cross_dim_results: Dict[str, Any] = {}
        for level in levels_analyzed:
            level_key = f"level_{level}_analysis"
            level_result = ctx.session.state.get(level_key)
            if level_result:
                # Ensure it's an object (it should be now, but parse if string found in state)
                from ...utils.json_utils import safe_parse_json
                parsed = safe_parse_json(level_result) if isinstance(level_result, str) else level_result
                if isinstance(parsed, dict):
                    for card in parsed.get("insight_cards", []):
                        card.setdefault("discovery_method", "standard_drill")
                hierarchical_result["level_results"][f"level_{level}"] = parsed
                ctx.session.state[level_key] = parsed

            # Collect cross-dimension results for this level
            for key in list(ctx.session.state.keys()):
                if key.startswith(f"level_{level}_cross_dimension_"):
                    cd_name = key.replace(f"level_{level}_cross_dimension_", "")
                    cd_val = ctx.session.state[key]
                    from ...utils.json_utils import safe_parse_json
                    cross_dim_results.setdefault(f"level_{level}", {})[cd_name] = (
                        safe_parse_json(cd_val) if isinstance(cd_val, str) else cd_val
                    )

        if cross_dim_results:
            hierarchical_result["cross_dimension_results"] = cross_dim_results

        # Collect independent level (flat scan) results
        independent_level_results: Dict[str, Any] = {}
        max_depth = ctx.session.state.get("max_drill_depth", 5)
        total_independent_cards = 0
        for lvl in range(1, max_depth + 1):
            ind_key = f"independent_level_{lvl}_analysis"
            ind_result = ctx.session.state.get(ind_key)
            if ind_result:
                from ...utils.json_utils import safe_parse_json
                parsed_ind = safe_parse_json(ind_result) if isinstance(ind_result, str) else ind_result
                if isinstance(parsed_ind, dict):
                    independent_level_results[f"level_{lvl}"] = parsed_ind
                    total_independent_cards += len(parsed_ind.get("insight_cards", []))

        if independent_level_results:
            hierarchical_result["independent_level_results"] = independent_level_results
            print(
                f"[FinalizeAnalysisResults] Independent scans found {total_independent_cards} "
                f"net-new cards across {len(independent_level_results)} level(s)"
            )
        
        # Store result in state
        state_delta = {
            "data_analyst_result": hierarchical_result,
            "hierarchical_analysis_complete": True
        }

        # Preserve individual level results in state delta
        for level in levels_analyzed:
            level_key = f"level_{level}_analysis"
            if level_key in hierarchical_result["level_results"]:
                state_delta[level_key] = hierarchical_result["level_results"][level_key]

        # Preserve independent level results in state delta
        if independent_level_results:
            state_delta["independent_level_results"] = independent_level_results
            ctx.session.state["independent_level_results"] = independent_level_results
            for lvl_key, lvl_val in independent_level_results.items():
                ind_state_key = f"independent_{lvl_key}_analysis"
                state_delta[ind_state_key] = lvl_val
                ctx.session.state[ind_state_key] = lvl_val
        
        # WORKAROUND: Also set directly in session state to ensure availability 
        # in complex nested agent structures where state deltas might not propagate 
        # correctly across Sequential/Parallel/Loop boundaries.
        ctx.session.state["data_analyst_result"] = hierarchical_result
        for k, v in state_delta.items():
            ctx.session.state[k] = v
            
        print(f"\n{'='*80}")
        print(f"[FinalizeAnalysisResults] COMPLETE - Yielding event (NO ESCALATION)")
        print(f"{'='*80}\n")
        
        actions = EventActions(state_delta=state_delta)
        yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=actions)


# --- Main Workflow Assembly ---

# Select decision agent based on feature flag
_drill_down_decision = (
    DrillDownDecisionFunction() if USE_CODE_INSIGHTS else DrillDownDecisionAgent()
)

print(
    f"[HierarchicalAnalysis] Using "
    f"{'code-based drill-down decisions' if USE_CODE_INSIGHTS else 'LLM drill-down decisions'} "
    f"(USE_CODE_INSIGHTS={USE_CODE_INSIGHTS})"
)

# Hierarchical drill-down loop
hierarchical_drill_down_loop = LoopAgent(
    name="hierarchical_drill_down_loop",
    sub_agents=[
        HierarchyRankerLoggingWrapper(),    # Log before analysis
        hierarchy_variance_ranker_agent,     # Aggregate & rank by current_level
        HierarchyRankerResultLogger(),       # Log results after analysis
        CrossDimensionAnalysisStep(),        # Cross-analyze auxiliary dims (no-op when disabled)
        _drill_down_decision,               # Code-based (default) or LLM (fallback)
        ProcessDrillDownDecision(),          # Update state and escalate if done
    ],
    description="Iterative hierarchical analysis: Level 0 -> N with materiality-based drill-down decisions. Automatically skips duplicate levels."
)

print(
    f"[HierarchicalAnalysis] Independent level analysis "
    f"{'ENABLED' if INDEPENDENT_LEVEL_ANALYSIS else 'disabled'} "
    f"(INDEPENDENT_LEVEL_ANALYSIS={INDEPENDENT_LEVEL_ANALYSIS}, "
    f"max_cards={_INDEPENDENT_LEVEL_MAX_CARDS})"
)

# Root data analyst agent
root_agent = SequentialAgent(
    name="hierarchical_analysis_agent",
    sub_agents=[
        InitializeHierarchicalLoop(),           # Initialize at Level 0
        hierarchical_drill_down_loop,           # Pass 0: standard top-down drill
        IndependentLevelAnalysisAgent(),        # Passes 1..N: flat scans (no-op when disabled)
        FinalizeAnalysisResults(),              # Aggregate all passes
    ],
    description="Hierarchical drill-down orchestrator: Pass 0 standard drill + optional independent flat scans per level."
)

