"""Loader and initializer agents extracted from agent.py."""

from __future__ import annotations

from typing import AsyncGenerator, Dict, Any
import os
import uuid
from io import StringIO
from pathlib import Path

import pandas as pd

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions

from ..semantic.models import AnalysisContext, DatasetContract
from ..utils.dimension_filters import extract_dimension_filters
from ..utils.json_utils import safe_parse_json
from ..utils.temporal_grain import (
    detect_temporal_grain,
    describe_analysis_period,
    normalize_temporal_grain,
    temporal_grain_to_period_unit,
)
from ..sub_agents.data_cache import set_analysis_context
from ..tools import calculate_date_ranges, should_fetch_supplementary_data

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _to_timestamp(value):
    if not value:
        return None
    ts = pd.to_datetime(value, errors="coerce")
    if isinstance(ts, pd.Series):
        ts = ts.iloc[0]
    if pd.isna(ts):
        return None
    return ts


def _clamp_analysis_end_date(ctx, df, contract):
    time_cfg = getattr(contract, 'time', None) if contract else None
    if not time_cfg:
        return None
    time_col = getattr(time_cfg, 'column', None)
    if not time_col or time_col not in df.columns:
        return None
    time_format = getattr(time_cfg, 'format', '%Y-%m-%d')

    parsed = pd.to_datetime(df[time_col], format=time_format, errors='coerce')
    if parsed.notna().any():
        observed_ts = parsed.max()
        observed_label = observed_ts.strftime(time_format)
    else:
        fallback = pd.to_datetime(df[time_col], errors='coerce')
        if fallback.notna().any():
            observed_ts = fallback.max()
            observed_label = observed_ts.strftime(time_format)
        else:
            observed_ts = None
            non_null = df[time_col].dropna()
            observed_label = str(non_null.max()) if not non_null.empty else None

    timeframe = ctx.session.state.get('timeframe')
    if not isinstance(timeframe, dict):
        timeframe = {}
    requested_end = ctx.session.state.get('primary_query_end_date') or timeframe.get('end')
    requested_ts = _to_timestamp(requested_end)

    final_label = None
    if requested_ts is not None and observed_ts is not None:
        if requested_ts <= observed_ts:
            final_label = requested_ts.strftime(time_format)
        else:
            final_label = observed_label
            if requested_end:
                print(f"[AnalysisContextInitializer] Clamped end date {requested_end} -> {final_label} (data max {observed_label})")
    elif requested_ts is not None:
        final_label = requested_end
    else:
        final_label = observed_label

    if observed_label:
        ctx.session.state['latest_observed_period'] = observed_label

    if final_label:
        timeframe['end'] = final_label
        ctx.session.state['timeframe'] = timeframe
        for key in ('primary_query_end_date', 'supplementary_query_end_date', 'detail_query_end_date'):
            ctx.session.state[key] = final_label

    return final_label


class ContractLoader(BaseAgent):
    """Loads the DatasetContract from config/datasets/<active_dataset>/contract.yaml.
    
    This agent is the first step in the analysis pipeline. It:
    1. Resolves the active dataset from environment variable or config
    2. Loads the contract YAML (with caching for performance)
    3. Stores the parsed contract in session.state["dataset_contract"]
    
    The contract defines all dataset metadata including:
    - Metrics and dimensions
    - Time configuration
    - Hierarchies
    - Materiality thresholds
    - Data source location
    
    Session State Output:
        dataset_contract: Parsed DatasetContract instance
        active_dataset: Dataset identifier string
        contract_name: Human-readable contract name
        
    Example:
        >>> # Automatically run as first stage in root_agent pipeline
        >>> # After execution, contract available at:
        >>> contract = ctx.session.state["dataset_contract"]
    """

    def __init__(self):
        super().__init__(name="contract_loader")

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        import sys
        from config.dataset_resolver import get_active_dataset, get_dataset_path
        from ..utils.contract_cache import load_contract_cached

        dataset_name = get_active_dataset()

        # Primary path: config/datasets/<dataset>/contract.yaml
        dimension_filters: Dict[str, Any] = {}
        hierarchy_filters: Dict[str, Any] = {}

        try:
            contract_path = get_dataset_path("contract.yaml")
        except FileNotFoundError:
            # Backward-compatible fallback to the old contracts/ directory
            legacy_filename = f"{dataset_name}_contract.yaml"
            legacy_path = _PROJECT_ROOT / "contracts" / legacy_filename
            if legacy_path.exists():
                print(
                    f"[ContractLoader] DEPRECATED: Loading contract from legacy path "
                    f"contracts/{legacy_filename}. Move to config/datasets/{dataset_name}/contract.yaml.",
                    file=sys.stderr,
                )
                contract_path = legacy_path
            else:
                raise FileNotFoundError(
                    f"[ContractLoader] Contract not found for dataset '{dataset_name}'. "
                    f"Expected: config/datasets/{dataset_name}/contract.yaml"
                )

        contract = load_contract_cached(contract_path)

        from ..logging_config import logger
        logger.info("Loaded contract", extra={
            "agent": "ContractLoader",
            "contract_name": contract.name,
            "contract_version": contract.version,
            "dataset": dataset_name
        })

        ctx.session.state["dataset_contract"] = contract
        ctx.session.state["active_dataset"] = dataset_name

        actions = EventActions(state_delta={"contract_name": contract.name, "active_dataset": dataset_name})
        yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=actions)

class AnalysisContextInitializer(BaseAgent):
    """Initializes the AnalysisContext after data is fetched and validated.
    
    This critical agent bridges raw data and the analysis pipeline. It:
    1. Loads primary CSV data from session state
    2. Applies dimension and hierarchy filters
    3. Performs optional temporal aggregation based on focus directives
    4. Validates data schema against contract requirements
    5. Detects temporal grain (daily/weekly/monthly)
    6. Constructs the AnalysisContext object for downstream agents
    
    The AnalysisContext is the central data structure used by all analysis agents.
    It contains the DataFrame, target metric, primary dimension, temporal metadata,
    and filter state.
    
    Session State Inputs:
        dataset_contract: Contract loaded by ContractLoader
        primary_data_csv: CSV string from data fetcher
        focus_temporal_grain: Optional grain override ("weekly", "monthly", "yearly")
        request_analysis: Parsed request with metrics/dimensions
        dimension: Override dimension name
        dimension_value: Override dimension value for filtering
        hierarchy_filters: Multi-value filters from web UI
        
    Session State Outputs:
        analysis_context: Complete AnalysisContext instance
        temporal_grain: Detected or overridden grain
        temporal_grain_confidence: Detection confidence score
        time_frequency: Contract time frequency
        analysis_period: Human-readable period description
        dimension_filters: Applied dimension filters
        
    Example:
        >>> # After data fetch, this agent creates analysis_context:
        >>> context = ctx.session.state["analysis_context"]
        >>> print(context.df.shape)  # Filtered and aggregated DataFrame
        >>> print(context.temporal_grain)  # "monthly"
    """
    
    def __init__(self):
        super().__init__(name="analysis_context_initializer")
        
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        import pandas as pd
        from io import StringIO
        import json
        
        contract = ctx.session.state.get("dataset_contract")
        csv_data = ctx.session.state.get("primary_data_csv") or ctx.session.state.get("validated_pl_data_csv")
        
        if not contract or not csv_data:
            print("[AnalysisContextInitializer] Missing contract or data")
            yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=EventActions())
            return
            
        try:
            df = pd.read_csv(StringIO(csv_data))
            
            # --- OPTIMIZATION: Filter data to requested dimension value if pre-fetched ---
            # This allows pulling more data up front (e.g. all LOBs) and filtering here.
            req_analysis_raw = ctx.session.state.get("request_analysis", {})
            req_analysis = safe_parse_json(req_analysis_raw)
            override_dimension = ctx.session.state.get("dimension")
            override_value = ctx.session.state.get("dimension_value")
            dimension_filters = extract_dimension_filters(
                contract,
                request_analysis=req_analysis,
                candidates=[
                    (req_analysis.get("primary_dimension"), override_value),
                    (override_dimension, override_value),
                ],
            )

            primary_filter = next(iter(dimension_filters.items()), None)
            if primary_filter:
                filter_column, filter_value = primary_filter
                if filter_column in df.columns:
                    before_count = len(df)
                    filter_series = df[filter_column].astype(str)
                    filter_value_str = str(filter_value)
                    filtered_df = df[filter_series == filter_value_str]
                    # Guardrail: when target iteration is metric-based, dimension filters can
                    # accidentally reference the wrong semantic space (e.g., flow='trade_value_usd').
                    # In that case skip the filter instead of zeroing out the dataset.
                    if filtered_df.empty and before_count > 0:
                        print(
                            f"[AnalysisContextInitializer] Skipping filter {filter_column}='{filter_value}' "
                            f"because it matched 0/{before_count} rows."
                        )
                    else:
                        if len(filtered_df) < before_count:
                            print(
                                f"[AnalysisContextInitializer] Filtered in-memory data for {filter_column}='{filter_value}': {before_count} -> {len(filtered_df)} rows"
                            )
                        df = filtered_df
            # Apply hierarchy filters (multi-value from web UI)
            raw_hierarchy_filters = ctx.session.state.get("hierarchy_filters", {})
            hierarchy_filters = raw_hierarchy_filters if isinstance(raw_hierarchy_filters, dict) else {}
            if hierarchy_filters:
                for filter_col, filter_values in hierarchy_filters.items():
                    if filter_col in df.columns and isinstance(filter_values, list) and filter_values:
                        before = len(df)
                        df = df[df[filter_col].astype(str).isin([str(v) for v in filter_values])]
                        print(f"[AnalysisContextInitializer] Hierarchy filter {filter_col} in {filter_values}: {before} -> {len(df)} rows")

            # --- TEMPORAL AGGREGATION based on focus directive ---
            focus_temporal_grain = ctx.session.state.get("focus_temporal_grain")
            if focus_temporal_grain and focus_temporal_grain in ["weekly", "monthly", "yearly"]:
                from ..utils.temporal_aggregation import aggregate_to_temporal_grain
                
                time_cfg = getattr(contract, "time", None)
                time_col = time_cfg.column if time_cfg else None
                time_format = getattr(time_cfg, "format", "%Y-%m-%d") if time_cfg else "%Y-%m-%d"
                
                # Get metric columns for aggregation
                metric_columns = [m.column for m in contract.metrics if hasattr(m, 'column') and m.column]
                
                # Get dimension columns to preserve (exclude time column)
                dimension_columns = [d.column for d in contract.dimensions 
                                     if hasattr(d, 'column') and d.column and d.column != time_col]
                
                if time_col and metric_columns:
                    print(f"\n{'='*80}")
                    print(f"[AnalysisContextInitializer] Applying temporal aggregation: {focus_temporal_grain}")
                    print(f"  Time column: {time_col}")
                    print(f"  Metrics: {', '.join(metric_columns)}")
                    print(f"  Dimensions: {', '.join(dimension_columns)}")
                    print(f"{'='*80}\n")
                    
                    df = aggregate_to_temporal_grain(
                        df=df,
                        time_column=time_col,
                        target_grain=focus_temporal_grain,
                        metric_columns=metric_columns,
                        dimension_columns=dimension_columns,
                        time_format=time_format,
                    )
                    
                    # Persist the temporal grain to session state for downstream agents (NarrativeAgent, ExecutiveBrief)
                    ctx.session.state["temporal_grain"] = focus_temporal_grain
                    print(f"[AnalysisContextInitializer] Set temporal_grain in session state: {focus_temporal_grain}")
                else:
                    print(f"[AnalysisContextInitializer] WARNING: Cannot apply temporal aggregation (missing time_col or metrics)")

        except Exception as e:
            print(f"[AnalysisContextInitializer] ERROR: Failed to parse CSV: {e}")
            import traceback
            traceback.print_exc()
            yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=EventActions())
            return

        # --- FOLDED VALIDATION LOGIC ---
        validation_errors = []
        
        # 1. Row check
        if df.empty:
            validation_errors.append("Primary data is empty (0 rows).")

        # 2. Schema check (metrics and dimensions)
        for metric in contract.metrics:
            if metric.column and metric.type == "additive" and metric.column not in df.columns:
                validation_errors.append(f"Required metric column '{metric.column}' missing.")
        
        # 3. Time column check
        if contract.time.column not in df.columns:
            validation_errors.append(f"Required time column '{contract.time.column}' missing.")

        if validation_errors:
            print(f"[AnalysisContextInitializer] FATAL VALIDATION ERRORS:\n" + "\n".join(validation_errors))
            # Optional: yield a fatal event if the errors are too severe
            # For now, we'll log them and attempt to build the context anyway (or stop if empty)
            if df.empty:
                yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=EventActions())
                return

        final_period_end = _clamp_analysis_end_date(ctx, df, contract)

        # Determine target metric and primary dimension from request analysis if available
        # Priority: current_analysis_target (from loop/parallel) > req_analysis metrics
        req_analysis_raw = ctx.session.state.get("request_analysis", {})
        req_analysis = safe_parse_json(req_analysis_raw)
        
        target_metric = None
        current_target = ctx.session.state.get("current_analysis_target")
        
        if current_target:
            try:
                target_metric = contract.get_metric(current_target)
            except (KeyError, AttributeError):
                pass
        
        if not target_metric:
            requested_metrics = req_analysis.get("metrics", [])
            if requested_metrics:
                # Try to find the first requested metric in the contract
                for m_name in requested_metrics:
                    try:
                        target_metric = contract.get_metric(m_name)
                        break
                    except (KeyError, AttributeError):
                        continue
        
        if not target_metric:
            # Default to first metric from contract
            target_metric = contract.metrics[0]
            
        primary_dim = None
        requested_dim = req_analysis.get("primary_dimension")
        if requested_dim:
            try:
                primary_dim = contract.get_dimension(requested_dim)
            except (KeyError, AttributeError):
                pass
                
        if not primary_dim:
            # Default to first dimension with role "primary"
            primary_dim = next((d for d in contract.dimensions if d.role == "primary"), contract.dimensions[0])
        
        # Determine max drill depth: env > contract > state > default
        max_drill_depth = 3
        env_depth = os.environ.get("DATA_ANALYST_MAX_DRILL_DEPTH")
        if env_depth and env_depth.strip().isdigit():
            max_drill_depth = int(env_depth.strip())
            print(f"[ConfigOverride] max_drill_depth={max_drill_depth} (from env)")
        elif contract and hasattr(contract, "reporting") and contract.reporting:
            max_drill_depth = contract.reporting.max_drill_depth
        else:
            max_drill_depth = ctx.session.state.get("max_drill_depth", 3)

        # Detect temporal grain using deterministic overrides that honor the contract frequency first.
        # PRIORITY: If temporal_grain was already set by aggregation, RESPECT IT - do not overwrite
        
        # Extract contract metadata needed for both branches
        time_cfg = getattr(contract, "time", None) if contract else None
        time_col = time_cfg.column if time_cfg else None
        raw_time_frequency = getattr(time_cfg, "frequency", None) if time_cfg else None
        contract_frequency = normalize_temporal_grain(raw_time_frequency)
        
        # Get env override - define BEFORE if/else to avoid UnboundLocalError
        env_time_frequency = normalize_temporal_grain(os.environ.get("DATA_ANALYST_TIME_FREQUENCY"))
        canonical_frequency = env_time_frequency if env_time_frequency != "unknown" else contract_frequency
        
        existing_grain = ctx.session.state.get("temporal_grain")
        
        if existing_grain and existing_grain in ["weekly", "monthly", "yearly"]:
            # Use aggregated grain, don't overwrite
            temporal_grain = existing_grain
            grain_source = "aggregation"
            grain_confidence = 1.0
            detected_anchor = "aggregated"
            periods_analyzed = 0
            print(f"[TemporalGrain] USING AGGREGATION GRAIN: {temporal_grain} (set earlier by temporal aggregation)")
        else:
            # Proceed with standard detection
            grain_result = detect_temporal_grain(df[time_col]) if time_col and time_col in df.columns else None

            contract_override = normalize_temporal_grain(
                getattr(time_cfg, "temporal_grain_override", None) if time_cfg else None
            )
            env_grain = normalize_temporal_grain(os.environ.get("TEMPORAL_GRAIN"))

            if canonical_frequency != "unknown":
                temporal_grain = canonical_frequency
                grain_source = "time_frequency_env" if env_time_frequency != "unknown" else "contract_frequency"
            elif contract_override != "unknown":
                temporal_grain = contract_override
                grain_source = "contract_override"
            elif env_grain != "unknown":
                temporal_grain = env_grain
                grain_source = "env"
            elif grain_result and grain_result.temporal_grain in ("weekly", "monthly"):
                temporal_grain = grain_result.temporal_grain
                grain_source = "detected"
            else:
                temporal_grain = "monthly"
                grain_source = "fallback"

            if grain_source in {"time_frequency_env", "contract_override", "contract_frequency"}:
                grain_confidence = 1.0
            elif grain_source == "detected":
                grain_confidence = float(grain_result.detection_confidence) if grain_result else 0.0
            else:
                grain_confidence = 0.0
            detected_anchor = grain_result.detected_anchor if grain_result else "unknown"
            periods_analyzed = int(grain_result.periods_analyzed) if grain_result else 0

        print(
            f"[TemporalGrain] detected={temporal_grain} source={grain_source} "
            f"confidence={grain_confidence:.2f} periods={periods_analyzed} "
            f"(contract={contract_frequency or 'unknown'})"
        )
        if grain_source == "fallback":
            print("[TemporalGrain] WARNING: Ambiguous cadence; defaulting to monthly.")

        effective_time_frequency = canonical_frequency if canonical_frequency != "unknown" else None
        ctx.session.state["time_frequency"] = effective_time_frequency or raw_time_frequency
        ctx.session.state["dimension_filters"] = dimension_filters
        ctx.session.state["hierarchy_filters"] = hierarchy_filters

        context = AnalysisContext(
            contract=contract,
            df=df,
            target_metric=target_metric,
            primary_dimension=primary_dim,
            run_id=str(uuid.uuid4()),
            max_drill_depth=max_drill_depth,
            temporal_grain=temporal_grain,
            temporal_grain_confidence=grain_confidence,
            detected_anchor=detected_anchor,
            period_end_column=time_col,
            time_frequency=ctx.session.state["time_frequency"],
            dimension_filters=dimension_filters,
            hierarchy_filters=hierarchy_filters,
        )
        
        # Store in session state and global cache
        ctx.session.state["analysis_context"] = context
        from ..sub_agents.data_cache import set_analysis_context
        # Use session ID for cache isolation in parallel runs
        session_id = getattr(ctx.session, "id", None)
        set_analysis_context(context, session_id=session_id)
        
        print(f"[AnalysisContextInitializer] Created context for {len(df)} rows. Target: {target_metric.name}")

        period_end_value = final_period_end or ctx.session.state.get("primary_query_end_date")
        frequency_for_period = ctx.session.state.get("time_frequency") or raw_time_frequency
        if period_end_value:
            analysis_period = describe_analysis_period(
                period_end_value,
                frequency_for_period,
                temporal_grain,
            )
        else:
            fallback_unit = temporal_grain_to_period_unit(temporal_grain)
            analysis_period = (
                f"the {fallback_unit} ending" if fallback_unit != "period" else "the most recent period"
            )
        ctx.session.state["analysis_period"] = analysis_period

        actions = EventActions(state_delta={
            "analysis_context_ready": True,
            "temporal_grain": temporal_grain,
            "temporal_grain_confidence": grain_confidence,
            "temporal_grain_source": grain_source,
            "time_frequency": ctx.session.state["time_frequency"],
            "analysis_period": analysis_period,
        })

        yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=actions)

class DateInitializer(BaseAgent):
    """Initializes date ranges in state using calculate_date_ranges tool.
    
    This agent calculates the date ranges for data retrieval based on:
    1. Focus directives (e.g., "recent_monthly_trends" → last 6 months)
    2. CLI overrides (--start-date, --end-date)
    3. Default ranges from calculate_date_ranges tool
    
    Priority order:
    - CLI overrides (highest priority)
    - Focus directive date ranges
    - Tool-calculated defaults
    
    Focus directive mappings:
    - recent_weekly_trends: Last 8 weeks, weekly grain
    - recent_monthly_trends: Last 6 months, monthly grain
    - recent_yearly_trends: Last 3 years, yearly grain
    
    Session State Inputs:
        analysis_focus: List of focus directive strings
        primary_query_start_date: Optional CLI override
        primary_query_end_date: Optional CLI override
        
    Session State Outputs:
        primary_query_start_date: Start date for primary query
        primary_query_end_date: End date for primary query
        supplementary_query_start_date: Start for supplementary data
        supplementary_query_end_date: End for supplementary data
        detail_query_start_date: Start for detail query
        detail_query_end_date: End for detail query
        focus_temporal_grain: Temporal grain from focus directive
        timeframe: {start, end} dict for persistence
        
    Example:
        >>> # With focus directive:
        >>> ctx.session.state["analysis_focus"] = ["recent_monthly_trends"]
        >>> # After DateInitializer runs:
        >>> print(ctx.session.state["focus_temporal_grain"])  # "monthly"
        >>> print(ctx.session.state["primary_query_start_date"])  # "2025-09-12" (6 months ago)
    """
    
    def __init__(self):
        super().__init__(name="date_initializer")
    
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        from datetime import datetime, timedelta
        
        phase_logger = ctx.session.state.get("phase_logger")
        
        # Get defaults from tool
        date_ranges = calculate_date_ranges()
        
        # Check for focus directives and adjust date ranges accordingly
        analysis_focus = ctx.session.state.get("analysis_focus", [])
        focus_applied = False
        temporal_grain_override = None
        
        if analysis_focus:
            today = datetime.now()
            focus_str = analysis_focus[0] if isinstance(analysis_focus, list) and analysis_focus else str(analysis_focus)
            
            # Map focus directives to date ranges and temporal grains
            focus_config = {
                "recent_weekly_trends": {
                    "weeks": 8,
                    "grain": "weekly",
                    "description": "last 8 weeks"
                },
                "recent_monthly_trends": {
                    "months": 6,
                    "grain": "monthly",
                    "description": "last 6 months"
                },
                "recent_yearly_trends": {
                    "years": 3,
                    "grain": "yearly",
                    "description": "last 3 years"
                },
            }
            
            config = focus_config.get(focus_str.lower())
            if config:
                if "weeks" in config:
                    start_date = (today - timedelta(weeks=config["weeks"])).strftime("%Y-%m-%d")
                elif "months" in config:
                    start_date = (today - timedelta(days=config["months"] * 30)).strftime("%Y-%m-%d")
                elif "years" in config:
                    start_date = (today - timedelta(days=config["years"] * 365)).strftime("%Y-%m-%d")
                
                end_date = today.strftime("%Y-%m-%d")
                
                # Apply focus-based date range
                date_ranges["primary_query_start_date"] = start_date
                date_ranges["primary_query_end_date"] = end_date
                date_ranges["supplementary_query_start_date"] = start_date
                date_ranges["supplementary_query_end_date"] = end_date
                date_ranges["detail_query_start_date"] = start_date
                date_ranges["detail_query_end_date"] = end_date
                
                temporal_grain_override = config["grain"]
                focus_applied = True
                
                print(f"\n{'='*80}")
                print(f"[DateInitializer] FOCUS DIRECTIVE APPLIED: {focus_str}")
                print(f"  Adjusted date range: {config['description']}")
                print(f"  Start: {start_date} | End: {end_date}")
                print(f"  Temporal grain: {temporal_grain_override}")
                print(f"{'='*80}\n")
        
        # Respect existing overrides in session state (e.g. from CLI) - these take priority over focus
        for key in date_ranges.keys():
            existing_override = ctx.session.state.get(key)
            if existing_override and key in ["primary_query_start_date", "primary_query_end_date", 
                                              "supplementary_query_start_date", "supplementary_query_end_date",
                                              "detail_query_start_date", "detail_query_end_date"]:
                date_ranges[key] = existing_override
                if focus_applied:
                    print(f"[DateInitializer] WARNING: CLI override for {key} takes precedence over focus directive")
        
        if phase_logger:
            phase_logger.log_workflow_transition(
                from_agent="analysis_root",
                to_agent="data_fetch",
                message="Initializing date ranges for data retrieval"
            )
            phase_logger.start_phase(
                phase_name="Data Fetch",
                description="Retrieving dataset-specific primary and supplementary metrics",
                input_data=date_ranges
            )
        
        if not focus_applied:
            print(f"\n{'='*80}")
            print(f"[DateInitializer] Date ranges (including overrides):")
            print(f"  Primary: {date_ranges['primary_query_start_date']} to {date_ranges['primary_query_end_date']}")
            print(f"  Supplementary: {date_ranges['supplementary_query_start_date']} to {date_ranges['supplementary_query_end_date']}")
            print(f"  Detail: {date_ranges['detail_query_start_date']} to {date_ranges['detail_query_end_date']}")
            print(f"{'='*80}\n")
        
        # Store temporal grain override if focus was applied
        state_delta = {**date_ranges}
        if temporal_grain_override:
            state_delta["focus_temporal_grain"] = temporal_grain_override
        
        # Also provide timeframe object for persistence
        timeframe = {
            "start": date_ranges.get("primary_query_start_date"),
            "end": date_ranges.get("primary_query_end_date"),
        }
        state_delta["timeframe"] = timeframe
        
        actions = EventActions(state_delta=state_delta)
        yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=actions)
        print(f"[DateInitializer] Done yielding event")

class ConditionalOrderDetailsFetchAgent(BaseAgent):
    """Conditionally fetches order details based on request type.
    
    This agent acts as a smart gate for supplementary data fetching. It uses
    the should_fetch_supplementary_data tool to determine whether the request
    requires detailed transactional data (e.g., order-level details) or can
    proceed with aggregate metrics alone.
    
    This optimization prevents unnecessary data loading for high-level trend
    analyses that don't require granular transaction details.
    
    Session State Inputs:
        request_analysis: Parsed request with analysis type and requirements
        
    Behavior:
        - If should_fetch_supplementary_data returns True: delegates to order_details_agent
        - Otherwise: yields empty event to skip the fetch stage
        
    Example:
        >>> # Request requiring order details (drill-down analysis):
        >>> request = {"analysis_type": "store_performance_deep_dive", ...}
        >>> # Agent will fetch order details
        
        >>> # Request not requiring details (high-level trend):
        >>> request = {"analysis_type": "operational_trend", ...}
        >>> # Agent will skip order details fetch
    """
    
    def __init__(self, order_details_agent):
        super().__init__(name="conditional_order_details_fetch")
        # Store agent in __dict__ to avoid Pydantic validation issues
        object.__setattr__(self, 'order_details_agent', order_details_agent)
    
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        request_analysis = ctx.session.state.get("request_analysis", "")
        
        # Use tool to determine if order details are needed
        if should_fetch_supplementary_data(request_analysis):
            # Delegate to the actual agent
            async for event in self.order_details_agent._run_async_impl(ctx):
                yield event
        else:
            # Skip order details fetch
            yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=EventActions())
