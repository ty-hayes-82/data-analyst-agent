"""Hierarchical analysis agent assembly."""

from __future__ import annotations

from google.adk.agents.loop_agent import LoopAgent
from google.adk.agents.sequential_agent import SequentialAgent

from ..hierarchy_variance_agent.agent import root_agent as hierarchy_variance_ranker_agent
from .cross_dimension import CrossDimensionAnalysisStep
from .decisions import (
    DrillDownDecisionAgent,
    DrillDownDecisionFunction,
    FocusAwareDrillDownDecision,
    ProcessDrillDownDecision,
)
from .finalization import FinalizeAnalysisResults
from .independent_level import IndependentLevelAnalysisAgent
from .initialization import InitializeHierarchicalLoop
from .logging_wrappers import (
    HierarchyRankerLoggingWrapper,
    HierarchyRankerResultLogger,
)
from .settings import (
    INDEPENDENT_LEVEL_ANALYSIS,
    INDEPENDENT_LEVEL_MAX_CARDS,
    USE_CODE_INSIGHTS,
)

print(
    f"[HierarchicalAnalysis] Using "
    f"{'code-based drill-down decisions' if USE_CODE_INSIGHTS else 'LLM drill-down decisions'} "
    f"(USE_CODE_INSIGHTS={USE_CODE_INSIGHTS})"
)

_drill_down_decision = (
    DrillDownDecisionFunction() if USE_CODE_INSIGHTS else FocusAwareDrillDownDecision()
)

hierarchical_drill_down_loop = LoopAgent(
    name="hierarchical_drill_down_loop",
    sub_agents=[
        HierarchyRankerLoggingWrapper(),
        hierarchy_variance_ranker_agent,
        HierarchyRankerResultLogger(),
        CrossDimensionAnalysisStep(),
        _drill_down_decision,
        ProcessDrillDownDecision(),
    ],
    description=(
        "Iterative hierarchical analysis: Level 0 -> N with materiality-based drill-down "
        "decisions. Automatically skips duplicate levels."
    ),
)

print(
    f"[HierarchicalAnalysis] Independent level analysis "
    f"{'ENABLED' if INDEPENDENT_LEVEL_ANALYSIS else 'disabled'} "
    f"(INDEPENDENT_LEVEL_ANALYSIS={INDEPENDENT_LEVEL_ANALYSIS}, "
    f"max_cards={INDEPENDENT_LEVEL_MAX_CARDS})"
)

root_agent = SequentialAgent(
    name="hierarchical_analysis_agent",
    sub_agents=[
        InitializeHierarchicalLoop(),
        hierarchical_drill_down_loop,
        IndependentLevelAnalysisAgent(),
        FinalizeAnalysisResults(),
    ],
    description=(
        "Hierarchical drill-down orchestrator: Pass 0 standard drill + optional independent "
        "flat scans per level."
    ),
)

__all__ = ["root_agent", "hierarchical_drill_down_loop"]
