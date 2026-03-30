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

Computes all statistics upfront in Python/pandas, then either:
  - (default) Runs code-based insight card generation via generate_statistical_insight_cards()
  - (fallback) Uses LLM to interpret and provide business insights

Feature flag: USE_CODE_INSIGHTS (env var, default "true")
"""

import os
from typing import AsyncGenerator
import json

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.sequential_agent import SequentialAgent
from google.adk.agents.llm_agent import Agent as LlmAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.adk.planners import BuiltInPlanner
from google.genai import types

from config.model_loader import get_agent_model, get_agent_thinking_config
from .prompt import STATISTICAL_INSIGHTS_INSTRUCTION
from .tools import compute_statistical_summary
from .tools.generate_insight_cards import generate_statistical_insight_cards
from ...utils.focus_directives import augment_instruction

USE_CODE_INSIGHTS = os.environ.get("USE_CODE_INSIGHTS", "true").lower() == "true"


def _cache_statistical_insight_cards_for_troubleshooting(
    ctx: InvocationContext, result: dict
) -> None:
    """Write code-generated statistical insight cards under run ``.cache/`` (always on).

    Hierarchy finalization overwrites ``data_analyst_result`` with drill-down output,
    so this file preserves cards for debugging and brief forensics.
    """
    out_dir = os.environ.get("DATA_ANALYST_OUTPUT_DIR")
    if not out_dir:
        return
    target = ctx.session.state.get("current_analysis_target") or ctx.session.state.get(
        "analysis_target"
    )
    if not target:
        return
    try:
        from data_analyst_agent.cache import InsightCache

        metric_key = str(target).replace(" ", "_").lower()
        cache = InsightCache(out_dir)
        payload = {
            "metric": target,
            "insight_cards": result.get("insight_cards", []),
            "summary_stats": result.get("summary_stats", {}),
            "card_count": len(result.get("insight_cards", [])),
        }
        if result.get("error"):
            payload["error"] = result["error"]
        path = cache.save_stage("statistical_insight_cards", metric_key, payload)
        print(
            f"[StatisticalInsightCardGenerator] Cached {payload['card_count']} cards for "
            f"troubleshooting: {path}",
            flush=True,
        )
    except Exception as exc:
        print(
            f"[StatisticalInsightCardGenerator] WARNING: could not cache insight cards: {exc}",
            flush=True,
        )


class StatisticalComputationAgent(BaseAgent):
    """Computes comprehensive statistics using pure Python/pandas/numpy."""
    
    def __init__(self):
        super().__init__(name="statistical_calculator")
    
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        print(f"\n{'='*80}", flush=True)
        print("[StatisticalComputation] Computing comprehensive statistical summary...", flush=True)
        print(f"{'='*80}\n", flush=True)
        
        # Call the statistical summary tool
        stats_json = await compute_statistical_summary(
            analysis_focus=ctx.session.state.get("analysis_focus"),
            custom_focus=ctx.session.state.get("custom_focus"),
        )
        
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
            print(f"  - Total accounts: {stats.get('summary_stats', {}).get('total_items', 0)}\n")
            
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
    """LLM agent that interprets statistical results with business context (fallback path)."""

    def __init__(self):
        _thinking = get_agent_thinking_config("statistical_insights_agent")
        super().__init__(
            name="statistical_llm_interpreter",
            model=get_agent_model("statistical_insights_agent"),
            instruction=STATISTICAL_INSIGHTS_INSTRUCTION,
            output_key="data_analyst_result",
            generate_content_config=types.GenerateContentConfig(
                response_modalities=["TEXT"],
                response_mime_type="application/json",
                temperature=0.0,
            ),
            **({"planner": BuiltInPlanner(thinking_config=_thinking)} if _thinking else {}),
        )


class FocusAwareStatisticalInterpreter(BaseAgent):
    """Wrapper that appends focus directives to the statistical LLM."""

    def __init__(self):
        super().__init__(name="statistical_llm_interpreter")
        self._wrapped = StatisticalInsightsAgent()
        self.output_key = getattr(self._wrapped, "output_key", "data_analyst_result")

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        self._wrapped.instruction = augment_instruction(STATISTICAL_INSIGHTS_INSTRUCTION, ctx.session.state)
        async for event in self._wrapped.run_async(ctx):
            yield event


class StatisticalInsightCardGenerator(BaseAgent):
    """Code-based insight card generator — replaces the LLM interpreter.

    Reads the pre-computed statistical_summary from session state and runs
    generate_statistical_insight_cards() to produce deterministic Insight Cards.
    No LLM call is made.
    """

    def __init__(self):
        super().__init__(name="statistical_code_interpreter")

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        print(f"\n{'='*80}", flush=True)
        print("[StatisticalInsightCardGenerator] Generating insight cards from pre-computed stats...", flush=True)
        print(f"{'='*80}\n", flush=True)

        stats_json = ctx.session.state.get("statistical_summary", "{}")

        try:
            stats = json.loads(stats_json) if isinstance(stats_json, str) else stats_json
        except json.JSONDecodeError as exc:
            error_result = json.dumps({
                "error": f"Failed to parse statistical_summary: {exc}",
                "insight_cards": [],
                "summary_stats": {}
            })
            yield Event(
                invocation_id=ctx.invocation_id,
                author=self.name,
                actions=EventActions(state_delta={"data_analyst_result": error_result}),
            )
            return

        # Propagate upstream computation errors
        if isinstance(stats, dict) and "error" in stats:
            error_result = json.dumps({
                "error": stats["error"],
                "insight_cards": [],
                "summary_stats": {}
            })
            print(f"[StatisticalInsightCardGenerator] Upstream error: {stats['error']}\n")
            _cache_statistical_insight_cards_for_troubleshooting(
                ctx,
                {"insight_cards": [], "summary_stats": {}, "error": str(stats.get("error", ""))},
            )
            yield Event(
                invocation_id=ctx.invocation_id,
                author=self.name,
                actions=EventActions(state_delta={"data_analyst_result": error_result}),
            )
            return

        result = generate_statistical_insight_cards(stats)
        result_json = json.dumps(result, indent=2)

        n_cards = len(result.get("insight_cards", []))
        print(f"[StatisticalInsightCardGenerator] Generated {n_cards} insight cards (no LLM call)\n")

        _cache_statistical_insight_cards_for_troubleshooting(ctx, result)

        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            actions=EventActions(state_delta={"data_analyst_result": result_json}),
        )


# Select interpreter based on feature flag at import time
_interpreter = (
    StatisticalInsightCardGenerator() if USE_CODE_INSIGHTS else FocusAwareStatisticalInterpreter()
)

print(
    f"[StatisticalInsightsAgent] Using "
    f"{'code-based card generator' if USE_CODE_INSIGHTS else 'LLM interpreter'} "
    f"(USE_CODE_INSIGHTS={USE_CODE_INSIGHTS})"
)

# Main data analyst agent - Simple sequential flow
root_agent = SequentialAgent(
    name="statistical_insights_agent",
    sub_agents=[
        StatisticalComputationAgent(),  # Compute all stats in Python/pandas
        _interpreter,                   # Code-based (default) or LLM (fallback)
    ],
    description="Computes core statistics, correlations, and identifies outliers. [Requires: time-series data]"
)
