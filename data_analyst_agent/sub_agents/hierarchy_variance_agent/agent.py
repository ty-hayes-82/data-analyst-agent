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

Defaults to code-based insight card generation (HierarchyInsightCardAgent).
Falls back to LLM agent when USE_CODE_INSIGHTS=false.

Feature flag: USE_CODE_INSIGHTS (env var, default "true")
"""

import os
import json
from typing import AsyncGenerator

from google.adk import Agent
from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.adk.planners import BuiltInPlanner
from google.genai import types

from config.model_loader import get_agent_model, get_agent_thinking_config
from .prompt import HIERARCHY_VARIANCE_RANKER_INSTRUCTION
from ...utils.focus_directives import augment_instruction
from .tools import (
    compute_level_statistics,
    compute_pvm_decomposition,
    format_hierarchy_insight_cards,
)

USE_CODE_INSIGHTS = os.environ.get("USE_CODE_INSIGHTS", "true").lower() == "true"


class HierarchyInsightCardAgent(BaseAgent):
    """Code-based hierarchy insight card agent — replaces the LLM ranker.

    Calls compute_level_statistics() (and optionally compute_pvm_decomposition()),
    then formats the results using format_hierarchy_insight_cards().
    No LLM call is made.
    """

    def __init__(self):
        super().__init__(name="hierarchy_code_ranker")

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        current_level = ctx.session.state.get("current_level", 0)
        hierarchy_name = ctx.session.state.get("hierarchy_name")

        print(f"\n[HierarchyInsightCardAgent] Computing Level {current_level} (no LLM)", flush=True)

        # Step 1: Compute level statistics
        try:
            level_stats_json = await compute_level_statistics(
                level=current_level,
                hierarchy_name=hierarchy_name,
            )
            level_stats = json.loads(level_stats_json)
        except Exception as exc:
            error_result = json.dumps({
                "error": f"compute_level_statistics failed: {exc}",
                "insight_cards": [],
                "is_last_level": True,
                "level": current_level,
            })
            yield Event(
                invocation_id=ctx.invocation_id,
                author=self.name,
                actions=EventActions(state_delta={"level_analysis_result": error_result}),
            )
            return

        if "error" in level_stats:
            yield Event(
                invocation_id=ctx.invocation_id,
                author=self.name,
                actions=EventActions(state_delta={"level_analysis_result": level_stats_json}),
            )
            return

        # Step 2: Optionally compute PVM decomposition and Mix Shift Analysis
        pvm_data = None
        mix_data = None
        try:
            from ...data_cache import get_analysis_context
            analysis_ctx = get_analysis_context()
            if analysis_ctx and analysis_ctx.contract:
                has_pvm = any(
                    getattr(m, "pvm_role", None) for m in analysis_ctx.contract.metrics
                )
                if has_pvm:
                    # Determine price/volume metrics from contract
                    price_m = next(
                        (m for m in analysis_ctx.contract.metrics if getattr(m, "pvm_role", None) == "price"),
                        None,
                    )
                    volume_m = next(
                        (m for m in analysis_ctx.contract.metrics if getattr(m, "pvm_role", None) == "volume"),
                        None,
                    )
                    total_m = next(
                        (m for m in analysis_ctx.contract.metrics if getattr(m, "pvm_role", None) == "total"),
                        None,
                    )
                    level_col = level_stats.get("level_name", "item")
                    if price_m and volume_m and total_m:
                        # 2-factor PVM
                        pvm_json = await compute_pvm_decomposition(
                            target_metric=total_m.column,
                            price_metric=price_m.column,
                            volume_metric=volume_m.column,
                            dimension=level_col,
                        )
                        pvm_data = json.loads(pvm_json)
                        
                        # 3-factor Mix Shift (NEW)
                        try:
                            from .tools import compute_mix_shift_analysis
                            mix_json = await compute_mix_shift_analysis(
                                target_metric=total_m.column,
                                price_metric=price_m.column,
                                volume_metric=volume_m.column,
                                segment_dimension=level_col,
                            )
                            mix_data = json.loads(mix_json)
                        except Exception:
                            pass
        except Exception:
            pass  # PVM is optional; proceed without it

        # Step 3: Format insight cards
        result = format_hierarchy_insight_cards(level_stats, pvm_data, mix_data)

        n_cards = len(result.get("insight_cards", []))
        print(
            f"[HierarchyInsightCardAgent] Level {current_level}: "
            f"{n_cards} material insight cards generated\n"
        )

        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            actions=EventActions(state_delta={"level_analysis_result": result}),
        )


# LLM fallback agent (used when USE_CODE_INSIGHTS=false)
_hierarchy_thinking = get_agent_thinking_config("hierarchy_variance_ranker_agent")
_llm_agent = Agent(
    model=get_agent_model("hierarchy_variance_ranker_agent"),
    name="hierarchy_variance_ranker_agent",
    description="Performs recursive variance analysis and Price-Volume-Mix decomposition. [Requires: contract hierarchies or metrics with pvm_role]",
    instruction=HIERARCHY_VARIANCE_RANKER_INSTRUCTION,
    tools=[compute_level_statistics, compute_pvm_decomposition],
    generate_content_config=types.GenerateContentConfig(
        response_modalities=["TEXT"],
        temperature=0.0,
    ),
    output_key="level_analysis_result",
    **({"planner": BuiltInPlanner(thinking_config=_hierarchy_thinking)} if _hierarchy_thinking else {}),
)

class HierarchyRankerWrapper(BaseAgent):
    """Wrapper to dynamically update hierarchy ranker instruction from contract."""
    
    def __init__(self, wrapped_agent):
        super().__init__(name="hierarchy_variance_ranker_agent")
        object.__setattr__(self, 'wrapped_agent', wrapped_agent)
    
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        contract = ctx.session.state.get("dataset_contract")
        if contract:
            display_name = getattr(contract, 'display_name', contract.name)
            materiality = getattr(contract, 'materiality', {})
            var_pct = materiality.get("variance_pct", 5.0)
            var_abs = materiality.get("variance_absolute", 50000.0)
            
            instr = HIERARCHY_VARIANCE_RANKER_INSTRUCTION.format(
                dataset_display_name=display_name,
                variance_pct=var_pct,
                variance_absolute=var_abs
            )
            self.wrapped_agent.instruction = augment_instruction(instr, ctx.session.state)
            print(f"[HierarchyRankerAgent] Instruction updated for contract: {contract.name}")
            
        async for event in self.wrapped_agent.run_async(ctx):
            yield event


root_agent = HierarchyInsightCardAgent() if USE_CODE_INSIGHTS else HierarchyRankerWrapper(_llm_agent)

print(
    f"[HierarchyVarianceRanker] Using "
    f"{'code-based card generator' if USE_CODE_INSIGHTS else 'LLM agent'} "
    f"(USE_CODE_INSIGHTS={USE_CODE_INSIGHTS})"
)

