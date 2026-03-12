"""Public entry point for hierarchy level statistics."""

from __future__ import annotations

from typing import Optional

from data_analyst_agent.sub_agents.data_cache import resolve_data_and_columns  # re-export for legacy patch sites

from data_analyst_agent.sub_agents.hierarchy_variance_agent.tools.level_stats import core as _core


async def compute_level_statistics(
    level: int,
    analysis_period: str = "latest",
    variance_type: str = "yoy",
    top_n: int = 10,
    cumulative_threshold: float = 80.0,
    hierarchy_name: Optional[str] = None,
) -> str:
    """Compute statistics and variance attribution for a specific hierarchy level.
    
    This tool analyzes a single level of the contract-defined hierarchy (e.g.,
    level 0 = Total, level 1 = LOBs, level 2 = Stores) and identifies which
    entities at that level are driving the most variance.
    
    Use Cases:
        - Level 0: Overall performance summary (total variance, trend)
        - Level 1: Which LOBs/Divisions drove the variance?
        - Level 2: Which Stores/Terminals within LOBs drove the variance?
        - Drill-down analysis: From aggregate to granular drivers
    
    Args:
        level: Hierarchy level to analyze (0 = top/total, 1+ = lower levels).
            Level 0 returns aggregate summary.
            Level 1+ returns entity-level breakdown (e.g., LOBs, Stores).
        analysis_period: Period to analyze. "latest" or specific period (YYYY-MM).
            Default "latest".
        variance_type: Comparison type. "mom" (month-over-month) or "yoy"
            (year-over-year). Default "yoy".
        top_n: Number of top variance drivers to return. Default 10.
            Ranked by absolute variance dollar magnitude.
        cumulative_threshold: Cumulative variance % threshold for reporting.
            Default 80.0. Returns entities until cumulative variance reaches
            this percentage of total variance (Pareto principle).
        hierarchy_name: Optional hierarchy name from contract. If None, uses
            first hierarchy in contract or infers from primary dimension.
    
    Returns:
        JSON string with:
            level: Level number analyzed
            level_name: Human-readable level name (e.g., "LOB", "Store")
            total_variance_dollar: Total variance for the level
            total_variance_pct: Total variance as % of prior value
            current_total: Current period total
            prior_total: Prior period total
            entity_count: Number of entities at this level
            top_drivers: List of top N entities by variance magnitude:
                - entity: Entity identifier
                - entity_name: Display name
                - current_value, prior_value: Values for both periods
                - variance_dollar, variance_pct: Variance magnitude
                - share_of_total_variance: % of total variance
                - cumulative_variance: Running cumulative %
            insight_cards: List of formatted insight cards (if level < max_drill)
            drill_recommendation: {
                should_drill: Boolean
                next_level: Next level number to analyze
                next_level_name: Next level name
                reason: Why/why not to drill deeper
            }
        
        Or {"error": "...", "traceback": "..."} on exception
    
    Raises:
        ValueError: Via resolve_data_and_columns if context/data resolution fails
        or if requested level exceeds max_drill_depth.
    
    Example:
        >>> # Analyze LOB level (level 1):
        >>> result = await compute_level_statistics(level=1, variance_type="yoy", top_n=5)
        >>> # Returns: {
        >>> #   "level": 1,
        >>> #   "level_name": "Line of Business",
        >>> #   "total_variance_dollar": 1500000,
        >>> #   "top_drivers": [
        >>> #     {
        >>> #       "entity": "lob_retail",
        >>> #       "entity_name": "Retail",
        >>> #       "variance_dollar": 800000,
        >>> #       "variance_pct": 12.5,
        >>> #       "share_of_total_variance": 53.3,
        >>> #       "cumulative_variance": 53.3
        >>> #     },
        >>> #     ...
        >>> #   ],
        >>> #   "drill_recommendation": {
        >>> #     "should_drill": true,
        >>> #     "next_level": 2,
        >>> #     "next_level_name": "Store",
        >>> #     "reason": "Retail has high variance; drill to Store level"
        >>> #   }
        >>> # }
    
    Note:
        - Wraps core implementation with error boundary (returns error JSON on exception)
        - Hierarchies defined in contract hierarchies section
        - Level 0 always represents the aggregate/total
        - Cumulative threshold implements Pareto analysis (80/20 rule)
        - Drill recommendation based on MIN_DRILL_IMPACT_SCORE threshold (0.15)
    """
    import json as _json
    import traceback as _tb
    _core.resolve_data_and_columns = resolve_data_and_columns
    try:
        return await _core.compute_level_statistics_impl(
            level=level,
            analysis_period=analysis_period,
            variance_type=variance_type,
            top_n=top_n,
            cumulative_threshold=cumulative_threshold,
            hierarchy_name=hierarchy_name,
        )
    except Exception as exc:
        _tb.print_exc()
        return _json.dumps({
            "error": "ComputationFailed",
            "level": level,
            "message": str(exc),
            "traceback": _tb.format_exc(),
        }, indent=2)
