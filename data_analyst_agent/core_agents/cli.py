"""CLI/test harness helpers."""

from __future__ import annotations

import os
from typing import AsyncGenerator

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions


def _infer_primary_dimension(contract):
    """Infer the primary dimension from contract metadata.
    
    Searches for a dimension with role='primary' in the contract. Falls back
    to the first dimension if no primary role is defined, or 'network' if
    the contract has no dimensions.
    
    Args:
        contract: DatasetContract instance with dimensions metadata.
        
    Returns:
        str: Primary dimension name (e.g., 'line_of_business', 'network').
        
    Example:
        >>> contract = DatasetContract(dimensions=[
        ...     Dimension(name='lob', role='primary'),
        ...     Dimension(name='region', role='secondary')
        ... ])
        >>> _infer_primary_dimension(contract)
        'lob'
    """
    if not contract or not getattr(contract, 'dimensions', None):
        return 'network'
    primary = next((d for d in contract.dimensions if getattr(d, 'role', None) == 'primary'), None)
    return getattr(primary, 'name', None) or contract.dimensions[0].name


def _infer_total_label(contract):
    """Infer the 'total' or 'all' label for the root hierarchy level.
    
    Searches contract hierarchies for a level_names mapping at level 0
    (the root/aggregate level). This label represents "all values combined"
    for the hierarchy (e.g., 'All LOBs', 'Total Network').
    
    Args:
        contract: DatasetContract instance with hierarchies metadata.
        
    Returns:
        str: Total label from first hierarchy with level 0 name, or 'Total'.
        
    Example:
        >>> contract = DatasetContract(hierarchies=[
        ...     Hierarchy(name='lob', level_names={0: 'All LOBs', 1: 'LOB'})
        ... ])
        >>> _infer_total_label(contract)
        'All LOBs'
    """
    if not contract:
        return 'Total'
    hierarchies = getattr(contract, 'hierarchies', None) or []
    for hierarchy in hierarchies:
        level_names = getattr(hierarchy, 'level_names', {}) or {}
        label = level_names.get(0)
        if label:
            return label
    return 'Total'


class CLIParameterInjector(BaseAgent):
    """Injects CLI-provided parameters into session state.
    
    This agent is the primary entry point for command-line and web UI configuration.
    It reads environment variables set by the CLI harness or web server and
    translates them into session state keys used by downstream agents.
    
    Environment Variables Processed:
        DATA_ANALYST_METRICS: Comma-separated list of target metrics
        DATA_ANALYST_DIMENSION: Primary dimension name
        DATA_ANALYST_DIMENSION_VALUE: Dimension value to analyze
        DATA_ANALYST_START_DATE: Override start date (YYYY-MM-DD)
        DATA_ANALYST_END_DATE: Override end date (YYYY-MM-DD)
        DATA_ANALYST_FOCUS: Comma-separated focus directives
        DATA_ANALYST_CUSTOM_FOCUS: Free-text custom focus instruction
        DATA_ANALYST_HIERARCHY: Selected hierarchy name
        DATA_ANALYST_HIERARCHY_LEVELS: Comma-separated hierarchy levels
        DATA_ANALYST_HIERARCHY_FILTERS: JSON-encoded hierarchy filters
        
    Focus Directives:
        - recent_weekly_trends: Last 8 weeks, weekly grain
        - recent_monthly_trends: Last 6 months, monthly grain
        - recent_yearly_trends: Last 3 years, yearly grain
        
    Session State Outputs:
        extracted_targets: List of metric names to analyze
        dimension: Primary dimension name
        dimension_value: Dimension value for filtering
        analysis_focus: List of normalized focus directives
        custom_focus: Sanitized custom focus text (max 500 chars)
        selected_hierarchy: Hierarchy name
        custom_hierarchy_levels: List of level names
        hierarchy_filters: Dict mapping dimension columns to value lists
        request_analysis: Complete parsed request object
        primary_query_start_date: Start date override
        primary_query_end_date: End date override
        timeframe: {start, end} dict for persistence
        
    Example:
        >>> # CLI usage:
        >>> # export DATA_ANALYST_METRICS="revenue,orders"
        >>> # export DATA_ANALYST_DIMENSION="line_of_business"
        >>> # export DATA_ANALYST_DIMENSION_VALUE="Retail"
        >>> # python -m data_analyst_agent
        >>> # After CLIParameterInjector runs:
        >>> ctx.session.state["extracted_targets"]  # ["revenue", "orders"]
        >>> ctx.session.state["dimension"]  # "line_of_business"
    
    Note:
        Custom focus text is sanitized to remove control characters and
        truncated to 500 characters to prevent prompt injection or
        excessive token usage.
    """

    def __init__(self):
        super().__init__(name="cli_parameter_injector")

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        import json as _json

        metrics_raw = os.environ.get("DATA_ANALYST_METRICS", "")
        metrics = [m.strip() for m in metrics_raw.split(",") if m.strip()]
        dim = os.environ.get("DATA_ANALYST_DIMENSION")
        dim_val = os.environ.get("DATA_ANALYST_DIMENSION_VALUE")
        start = os.environ.get("DATA_ANALYST_START_DATE")
        end = os.environ.get("DATA_ANALYST_END_DATE")

        # Analysis focus directives (web UI + CLI)
        focus_raw = os.environ.get("DATA_ANALYST_FOCUS", "")
        analysis_focus = [f.strip().lower() for f in focus_raw.split(",") if f.strip()]
        custom_focus_raw = os.environ.get("DATA_ANALYST_CUSTOM_FOCUS", "")

        def _sanitize_custom_focus(text: str, *, max_len: int = 500) -> str:
            # Remove control chars (incl. newlines/tabs) and collapse whitespace.
            cleaned = "".join(ch if (ch.isprintable() and ch not in "\r\n\t") else " " for ch in (text or ""))
            cleaned = " ".join(cleaned.split())
            return cleaned[:max_len].strip()

        custom_focus = _sanitize_custom_focus(custom_focus_raw) or None

        contract = ctx.session.state.get("dataset_contract")
        display_name = getattr(contract, "display_name", getattr(contract, "name", "dataset")) if contract else "dataset"
        frequency = getattr(getattr(contract, "time", None), "frequency", "weekly")
        target_label = getattr(contract, "target_label", "Metric") if contract else "Metric"

        # Fall back to all metrics from contract when CLI does not specify any
        if not metrics and contract:
            contract_metrics = getattr(contract, "metrics", None) or []
            if contract_metrics:
                metrics = [
                    m.get("name") if isinstance(m, dict) else getattr(m, "name", str(m))
                    for m in contract_metrics
                ]
                print(f"[CLIParameterInjector] No DATA_ANALYST_METRICS -- defaulting to contract metrics: {metrics}")

        state_delta: dict = {}

        # Focus directives (persist in session state for planner + narrative + brief)
        state_delta["analysis_focus"] = analysis_focus
        state_delta["custom_focus"] = custom_focus

        if metrics:
            state_delta["extracted_targets_raw"] = _json.dumps(metrics)
            state_delta["extracted_targets"] = metrics
            state_delta["target_label"] = target_label
            state_delta["target_loop_state"] = {"target_index": -1}
            state_delta["target_loop_complete"] = False

        # Custom hierarchy levels and filters (web UI hierarchy editor)
        hierarchy_name = os.environ.get("DATA_ANALYST_HIERARCHY", "")
        hierarchy_levels_raw = os.environ.get("DATA_ANALYST_HIERARCHY_LEVELS", "")
        hierarchy_levels = [l.strip() for l in hierarchy_levels_raw.split(",") if l.strip()]
        hierarchy_filters_raw = os.environ.get("DATA_ANALYST_HIERARCHY_FILTERS", "")
        hierarchy_filters = {}
        if hierarchy_filters_raw:
            try:
                hierarchy_filters = _json.loads(hierarchy_filters_raw)
            except _json.JSONDecodeError:
                pass

        if hierarchy_name:
            state_delta["selected_hierarchy"] = hierarchy_name
        if hierarchy_levels:
            state_delta["custom_hierarchy_levels"] = hierarchy_levels
        if hierarchy_filters:
            state_delta["hierarchy_filters"] = hierarchy_filters
            first_col = next(iter(hierarchy_filters), None)
            if first_col and isinstance(hierarchy_filters.get(first_col), list) and len(hierarchy_filters[first_col]) == 1:
                print(f"[CLIParameterInjector] Scoping run to {first_col}={hierarchy_filters[first_col][0]}")

        inferred_dim = _infer_primary_dimension(contract)
        inferred_total = _infer_total_label(contract)
        primary_dim = dim or inferred_dim
        primary_val = dim_val or inferred_total

        if primary_dim:
            state_delta["dimension"] = primary_dim
        if primary_val:
            state_delta["dimension_value"] = primary_val

        focus = f"CLI analysis of {', '.join(metrics)}" if metrics else "CLI analysis"
        if analysis_focus:
            focus = f"{focus} (focus={', '.join(analysis_focus)})"
        if custom_focus:
            focus = f"{focus} | custom_focus={custom_focus}"

        data_query = f"Retrieve {frequency} {display_name} for {primary_dim} {primary_val}."
        state_delta["request_analysis"] = {
            "analysis_type": "operational_trend",
            "primary_dimension": primary_dim,
            "primary_dimension_value": primary_val,
            "metrics": metrics,
            "focus": focus,
            "analysis_focus": analysis_focus,
            "custom_focus": custom_focus,
            "hierarchy_filters": hierarchy_filters,
            "needs_supplementary_data": False,
            "description": focus,
            "data_fetch_query_primary": data_query,
            "data_fetch_query_supplementary": None,
        }

        if start or end:
            overrides = {
                "primary_query_start_date": start,
                "primary_query_end_date": end,
                "supplementary_query_start_date": start,
                "supplementary_query_end_date": end,
                "detail_query_start_date": start,
                "detail_query_end_date": end,
            }
            overrides = {k: v for k, v in overrides.items() if v}
            state_delta.update(overrides)
            if start and end:
                state_delta["timeframe"] = {"start": start, "end": end}

        yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=EventActions(state_delta=state_delta))
