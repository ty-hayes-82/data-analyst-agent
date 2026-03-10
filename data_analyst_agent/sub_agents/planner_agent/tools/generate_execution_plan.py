import json
from typing import List, Dict, Any, Optional
from ...data_cache import get_analysis_context

# ---------------------------------------------------------------------------
# Keyword-based plan refinement (used by RuleBasedPlanner)
# ---------------------------------------------------------------------------

# Maps query keywords to analysis agents that should be force-included
_KEYWORD_AGENT_MAP: dict[str, str] = {
    # Focus modes (env-driven / UI)
    "recent_weekly_trends": "statistical_insights_agent",
    "recent_monthly_trends": "statistical_insights_agent",
    "anomaly_detection": "statistical_insights_agent",
    "outlier_investigation": "statistical_insights_agent",
    "seasonal_patterns": "seasonal_baseline_agent",
    "yoy_comparison": "hierarchical_analysis_agent",
    "forecasting": "statistical_insights_agent",
    "revenue_gap_analysis": "alert_scoring_coordinator",

    # Natural-language keywords
    "seasonal": "seasonal_baseline_agent",
    "season": "seasonal_baseline_agent",
    "trend": "statistical_insights_agent",
    "alert": "alert_scoring_coordinator",
    "billing": "alert_scoring_coordinator",
    "recover": "alert_scoring_coordinator",
    "leakage": "alert_scoring_coordinator",
    "hierarchy": "hierarchical_analysis_agent",
    "drill": "hierarchical_analysis_agent",
    "variance": "hierarchical_analysis_agent",
    "pvm": "hierarchical_analysis_agent",
    "breakdown": "hierarchical_analysis_agent",
    "statistic": "statistical_insights_agent",
    "outlier": "statistical_insights_agent",
    "anomal": "statistical_insights_agent",
    "correlation": "statistical_insights_agent",
    "volatil": "statistical_insights_agent",
    "forecast": "statistical_insights_agent",
}


def refine_plan(baseline_agents: list[dict], user_query: str) -> list[dict]:
    """
    Refine a baseline execution plan using keyword matching on the user query.

    Adds agents that the user explicitly mentioned but are not yet in the plan.
    Does not remove agents — only adds.

    Args:
        baseline_agents: List of {"name": str, "justification": str} dicts from
                         generate_execution_plan().
        user_query:      The raw user query string.

    Returns:
        Refined list of agent dicts (may have additional entries).
    """
    query_lower = user_query.lower()
    existing_names = {a["name"] for a in baseline_agents}

    for keyword, agent_name in _KEYWORD_AGENT_MAP.items():
        if keyword in query_lower and agent_name not in existing_names:
            baseline_agents.append({
                "name": agent_name,
                "justification": f"User query mentions '{keyword}' — force-including {agent_name}.",
            })
            existing_names.add(agent_name)

    return baseline_agents

async def generate_execution_plan() -> str:
    """
    Generates an execution plan based on the AnalysisContext and DatasetContract.
    
    This tool applies deterministic rules to decide which sub-agents are needed.
    
    Returns:
        A JSON string containing the list of required agents and their justifications.
    """
    ctx = get_analysis_context()
    if not ctx:
        return json.dumps({"error": "No AnalysisContext found", "agents": []})
    
    contract = ctx.contract
    df = ctx.df
    
    plan = {
        "recommended_agents": [],
        "context_summary": {
            "contract": contract.name,
            "periods": len(df[contract.time.column].unique()) if contract.time.column in df.columns else 0,
            "rows": len(df)
        }
    }
    
    # Rule 1: Always include Data Validation (usually handled by main loop, but we list it for completeness)
    # Actually, the main loop handles Validation before Planning. 
    # So we plan the ANALYSIS phase.
    
    # Rule 2: Hierarchical Drill-Down (Default if hierarchies exist)
    if contract.hierarchies:
        plan["recommended_agents"].append({
            "name": "hierarchical_analysis_agent",
            "justification": f"Contract defines {len(contract.hierarchies)} hierarchy/hierarchies."
        })
    
    # Rule 3: Statistical Insights (Default if we have time-series data)
    num_periods = plan["context_summary"]["periods"]
    if num_periods >= 2:
        plan["recommended_agents"].append({
            "name": "statistical_insights_agent",
            "justification": f"Data contains {num_periods} periods, enabling variance analysis."
        })
        
    # Rule 4: Seasonal Baseline (Requires 18+ months)
    # Skip when statistical_insights_agent is selected - it already includes seasonal analysis
    agent_names = {a["name"] for a in plan["recommended_agents"]}
    if num_periods >= 18 and "statistical_insights_agent" not in agent_names:
        plan["recommended_agents"].append({
            "name": "seasonal_baseline_agent",
            "justification": f"Data contains {num_periods} periods, enabling STL seasonal adjustment."
        })
    elif num_periods < 18:
        plan["context_summary"]["seasonal_skipped"] = f"Insufficient data ({num_periods} < 18 periods)"

    # Rule 5: PVM Decomposition (Requires PVM roles)
    if any(m.pvm_role for m in contract.metrics):
        plan["recommended_agents"].append({
            "name": "pvm_decomposition", # Note: Currently part of hierarchy_variance_ranker
            "justification": "Contract defines PVM roles for metrics."
        })
        
    # Rule 6: Alert Scoring (Always recommended if we have any analysis)
    if plan["recommended_agents"]:
        plan["recommended_agents"].append({
            "name": "alert_scoring_coordinator",
            "justification": "Required to prioritize findings from analysis agents."
        })
        
    return json.dumps(plan, indent=2)
