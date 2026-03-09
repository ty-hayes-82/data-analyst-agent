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
Data Analyst Agent - Contract-driven analysis pipeline with parallel deep analysis.

Architecture:
- Dimension-target analysis (dynamically extracted from user request)
- Single-pass sequential pipeline with parallel analysis for performance

Workflow:
1. Request Analysis & Target Extraction:
   - ContractLoader: Loads the DatasetContract from config/datasets/<active_dataset>/contract.yaml
   - request_analyzer: Analyzes request intent based on contract capabilities
   - dimension_extractor: Extracts primary dimension target from user message
   - DimensionTargetInitializer: Parses target, initializes session state and logger

2. Analysis Pipeline:
   a) Data Fetch:
      - DateInitializer: Calculates date ranges from contract time configuration
      - ContractDrivenDataFetcher: Retrieves data from the agent specified in the contract
      - A2aNormalizerAgent: Normalizes and validates fetched data

   b) Processing & Analysis:
      - AnalysisContextInitializer: Builds analysis context from contract + data
      - planner_agent: Generates dynamic execution plan
      - DynamicParallelAnalysisAgent: Runs selected analysis agents concurrently
      - narrative_agent: Generates semantic insight cards
      - ConditionalAlertScoringAgent: Conditionally scores alerts
      - report_synthesis_agent: Combines all results into executive summary
      - OutputPersistenceAgent: Saves complete analysis to JSON/Markdown
"""

import json
import time
from pathlib import Path
from typing import Dict, Any, AsyncGenerator

# Ensure parent package (project root) is at the FRONT of sys.path.
# ADK's load_services_module adds data_analyst_agent/ to sys.path, which contains
# config.py (a module). Without this fix, `import config` finds that file instead
# of the project-level config/ package (directory).
import sys as _sys
from pathlib import Path as _Path
_project_root = str(_Path(__file__).parent.parent)
if _project_root in _sys.path:
    _sys.path.remove(_project_root)
_sys.path.insert(0, _project_root)

# Clear any stale 'config' module that was loaded from the wrong location
if 'config' in _sys.modules and not hasattr(_sys.modules['config'], '__path__'):
    del _sys.modules['config']
    for _key in list(_sys.modules):
        if _key.startswith('config.'):
            del _sys.modules[_key]

# --- CRITICAL: AUTH SETUP FIRST ---
# Import configuration and prompts BEFORE any ADK agents
# to ensure environment variables are set correctly for the GenAI client.
from .config import config
from .utils.json_utils import safe_parse_json
from .utils.timing_utils import TimedAgentWrapper
from .prompt import SYSTEM_PROMPT
from .tools import calculate_date_ranges, should_fetch_supplementary_data, iterate_analysis_targets
from config.model_loader import get_agent_model, get_agent_thinking_config

# Now import ADK agents
from google.adk.agents.sequential_agent import SequentialAgent
from google.adk.agents.parallel_agent import ParallelAgent
from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.loop_agent import LoopAgent
from google.adk.agents.invocation_context import InvocationContext
from pydantic import Field
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.genai import types

# Import analysis sub-agents
from .sub_agents.statistical_insights_agent.agent import root_agent as statistical_insights_agent
from .sub_agents.hierarchical_analysis_agent import root_agent as hierarchical_analysis_agent
from .sub_agents.planner_agent.agent import root_agent as planner_agent
from .sub_agents.narrative_agent.agent import root_agent as narrative_agent
from .sub_agents.dynamic_parallel_agent import DynamicParallelAnalysisAgent
from .sub_agents.report_synthesis_agent.agent import root_agent as report_synthesis_agent
from .sub_agents.alert_scoring_agent.agent import root_agent as alert_scoring_coordinator
from .sub_agents.output_persistence_agent import OutputPersistenceAgent
from .sub_agents.testing_data_agent.agent import root_agent as testing_data_agent
from .sub_agents.validation_csv_fetcher import ValidationCSVFetcher
from .sub_agents.config_csv_fetcher import ConfigCSVFetcher
from .core_agents.loaders import (
    ContractLoader,
    AnalysisContextInitializer,
    DateInitializer,
    ConditionalOrderDetailsFetchAgent,
)
import os

# Authentication and environment setup is handled by config module
from .semantic.models import DatasetContract, AnalysisContext
from .semantic.quality import DataQualityGate
import uuid



class DataSourceProxyAgent(BaseAgent):
    """
    Proxy agent that sends a clean, specific query to a data source agent
    to avoid refusals based on irrelevant parts of the original user query.
    """
    query_key: str
    
    def __init__(self, agent, query_key):
        super().__init__(name=f"proxy_{agent.name}", query_key=query_key)
        # Store agent in __dict__ to avoid Pydantic issues
        object.__setattr__(self, 'agent', agent)
        
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        from google.adk.sessions.session import Session
        from google.genai.types import Content, Part
        import uuid
        
        print(f"[{self.name}] Entering _run_async_impl")
        # Get clean query from request analysis
        req_analysis_raw = ctx.session.state.get("request_analysis", {})
        req_analysis = safe_parse_json(req_analysis_raw)
        
        clean_query = req_analysis.get(self.query_key)

        # Resolve actual date ranges from session state (set by DateInitializer).
        # These are always appended to the query so the remote agent never needs to
        # ask follow-up questions about the time period.
        start = ctx.session.state.get("primary_query_start_date", "24 months ago")
        end = ctx.session.state.get("primary_query_end_date", "today")

        if not clean_query:
            # Fallback when the RequestAnalyzer did not provide a specific key.
            dim = req_analysis.get("primary_dimension", "unknown_dimension")
            val = req_analysis.get("primary_dimension_value", "unknown_value")
            
            # Get display name from contract for more natural fallback query
            contract = ctx.session.state.get("dataset_contract")
            ds_label = getattr(contract, 'display_name', 'data') if contract else 'data'

            clean_query = f"Retrieve monthly {ds_label} for {dim} '{val}'."

        # Always append the authoritative date range so the remote agent has complete context.
        date_suffix = f" Time period: {start} to {end}. Return all available rows."
        if start not in clean_query and end not in clean_query:
            clean_query = clean_query.rstrip(".") + "." + date_suffix
            
        print(f"[{self.name}] Sending clean query: {clean_query}")
        
        # Create a temporary session with ONLY the clean query
        print(f"[{self.name}] Creating temporary session...")
        temp_session = await ctx.session_service.create_session(
            app_name=f"temp_{self.agent.name}", 
            user_id=ctx.session.user_id
        )
        
        temp_session.events.append(Event(
            invocation_id="clean_input",
            author="user",
            content=Content(role="user", parts=[Part(text=clean_query)])
        ))
        
        # Also copy dates into temp session state if needed
        temp_session.state.update({
            k: v for k, v in ctx.session.state.items() 
            if "date" in k or "period" in k or "time" in k
        })
        
        temp_ctx = InvocationContext(
            agent=self.agent,
            session=temp_session,
            session_service=ctx.session_service,
            invocation_id=str(uuid.uuid4()),
            run_config=ctx.run_config
        )
        
        print(f"[{self.name}] Calling agent.run_async...")
        final_content = ""
        event_count = 0
        async for event in self.agent.run_async(temp_ctx):
            event_count += 1
            # print(f"[{self.name}] Received event {event_count}: {type(event)}")
            
            # Yield the event so it shows up in the main pipeline output
            yield event
            
            # Capture content for state syncing
            if event.content and event.content.role == "model":
                for part in event.content.parts:
                    if part.text:
                        final_content += part.text
                    elif part.function_call:
                        print(f"[{self.name}] Event {event_count} has function_call: {part.function_call.name}")
                    else:
                        print(f"[{self.name}] Event {event_count} has unknown part type")
        
        print(f"[{self.name}] Loop finished after {event_count} events")
        print(f"[{self.name}] Temp session state keys: {list(temp_session.state.keys())}")
        result_key = f"{self.agent.name}_result"
        
        # Priority 1: Check if it's already in the state
        if result_key in temp_session.state:
            ctx.session.state[result_key] = temp_session.state[result_key]
            print(f"[{self.name}] Synced {result_key} from state ({len(str(temp_session.state[result_key]))} bytes)")
        # Priority 2: Use captured content
        elif final_content:
            ctx.session.state[result_key] = final_content
            print(f"[{self.name}] Synced {result_key} from captured content ({len(final_content)} bytes)")
        else:
            print(f"[{self.name}] WARNING: {result_key} not found and no content captured")
        
        print(f"[{self.name}] Done.")

# ---------------------------------------------------------------------------
# Mode flags
#
# LIVE_MODE (default)
#   Uses Tableau A2A agents to pull from Hyper/Tableau server.  Full agent
#   pipeline runs (planner, statistical analysis, hierarchy, narrative,
#   synthesis).
#
# VALIDATION_CSV_MODE  (DATA_ANALYST_VALIDATION_CSV_MODE=true)
#   Uses ValidationCSVFetcher to load data/validation_data.csv.  The full
#   agent pipeline runs identically to LIVE_MODE — only the data-source
#   step is swapped.  No A2A server required.
#
#   Forces ACTIVE_DATASET=validation_ops.  Optional companion env vars:
#     DATA_ANALYST_EXCLUDE_PARTIAL_WEEK - "true" to drop the in-progress week
#
# TEST_MODE  (DATA_ANALYST_TEST_MODE=true)
#   Uses TestingDataAgent with sample CSVs and a simplified
#   TestModeReportSynthesisAgent.  Intended for unit/integration testing
#   only — NOT for production analysis runs.
#
# Priority when multiple flags are set: VALIDATION_CSV_MODE > TEST_MODE > LIVE
# ---------------------------------------------------------------------------
VALIDATION_CSV_MODE = (
    os.environ.get("DATA_ANALYST_VALIDATION_CSV_MODE", "false").lower() == "true"
)
TEST_MODE = (
    os.environ.get("DATA_ANALYST_TEST_MODE", "false").lower() == "true"
    and not VALIDATION_CSV_MODE   # VALIDATION_CSV_MODE takes priority
)

if VALIDATION_CSV_MODE:
    os.environ.setdefault("ACTIVE_DATASET", "validation_ops")


# --- A2A Remote Agents (Data Retrieval) ---
# --- Helper Agents (Simple Operations Using Tools) ---

class CLIParameterInjector(BaseAgent):
    """Injects pre-validated CLI parameters into session state.

    Reads from environment variables set by ``__main__.py``:
      DATA_ANALYST_METRICS         - comma-separated metric names
      DATA_ANALYST_DIMENSION       - dimension name (region, terminal)
      DATA_ANALYST_DIMENSION_VALUE - specific dimension value
      DATA_ANALYST_START_DATE      - YYYY-MM-DD start
      DATA_ANALYST_END_DATE        - YYYY-MM-DD end
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

        contract = ctx.session.state.get("dataset_contract")
        display_name = getattr(contract, "display_name", getattr(contract, "name", "dataset")) if contract else "dataset"
        frequency = getattr(contract.time, "frequency", "weekly") if contract and hasattr(contract, "time") else "weekly"
        target_label = getattr(contract, "target_label", "Metric") if contract else "Metric"

        state_delta = {}

        # -- Targets (replaces dimension_extractor + DimensionTargetInitializer)
        if metrics:
            print(f"[CLIParameterInjector] Metrics: {metrics}")
            state_delta["extracted_targets_raw"] = _json.dumps(metrics)
            state_delta["extracted_targets"] = metrics
            state_delta["target_label"] = target_label
            state_delta["target_loop_state"] = {"target_index": -1}
            state_delta["target_loop_complete"] = False

        # -- Request analysis (replaces request_analyzer)
        primary_dim = dim or "terminal"
        primary_val = dim_val or "Total"
        focus = f"CLI analysis of {', '.join(metrics)}" if metrics else "CLI analysis"
        data_query = f"Retrieve {frequency} {display_name} for {primary_dim} {primary_val}."

        state_delta["request_analysis"] = {
            "analysis_type": "operational_trend",
            "primary_dimension": primary_dim,
            "primary_dimension_value": primary_val,
            "metrics": metrics,
            "focus": focus,
            "needs_supplementary_data": False,
            "description": focus,
            "data_fetch_query_primary": data_query,
            "data_fetch_query_supplementary": None,
        }

        # -- Dates (optional overrides; DateInitializer fills defaults otherwise)
        if start or end:
            print(f"[CLIParameterInjector] Date override: {start or '(default)'} to {end or '(default)'}")
            date_ranges = {
                "primary_query_start_date": start,
                "primary_query_end_date": end,
                "supplementary_query_start_date": start,
                "supplementary_query_end_date": end,
                "detail_query_start_date": start,
                "detail_query_end_date": end,
            }
            date_ranges = {k: v for k, v in date_ranges.items() if v}
            state_delta.update(date_ranges)
            if start and end:
                state_delta["timeframe"] = {"start": start, "end": end}

        if dim:
            print(f"[CLIParameterInjector] Dimension: {dim}={dim_val or '(all)'}")

        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            actions=EventActions(state_delta=state_delta),
        )







# --- Workflow Orchestration ---

# TEST MODE pass-through validation agent (applies sign corrections from contract)
class TestModeValidationAgent(BaseAgent):
    """
    Pass-through validation agent for TEST MODE.

    TestingDataAgent already validates and stores data in session state.
    This agent just confirms the data is ready and flips revenue signs.
    """

    def __init__(self):
        super().__init__(name="test_mode_validation_agent")

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        import pandas as pd
        from io import StringIO

        # Get data from session state (where TestingDataAgent stored it)
        pl_data_csv = ctx.session.state.get("primary_data_csv", "")
        data_summary = ctx.session.state.get("data_summary", {})

        if not pl_data_csv:
            print("[TestModeValidation] ERROR: No P&L data found in session state")
            from google.genai.types import Content, Part
            yield Event(
                invocation_id=ctx.invocation_id,
                author=self.name,
                content=Content(role="model", parts=[Part(text='{"status": "fatal_no_data", "error": "No data in session state"}')])
            )
            return

        # Load and apply sign correction policies
        df = pd.read_csv(StringIO(pl_data_csv))
        
        contract = ctx.session.state.get("dataset_contract")
        if contract:
            from .semantic.policies import PolicyEngine
            engine = PolicyEngine(contract)
            df = engine.apply_sign_correction(df)
            print(f"[TestModeValidation] Applied sign correction policies from contract: {contract.name}")
        else:
            print("[TestModeValidation] WARNING: No contract found. Skipping sign correction.")

        # Store updated data back
        updated_csv = df.to_csv(index=False)

        # Import data_cache and set the validated CSV
        from .sub_agents.data_cache import set_validated_csv
        set_validated_csv(updated_csv)

        print(f"[TestModeValidation] Data validated and cached:")
        print(f"  Records: {len(df)}")

        # Output confirmation
        from google.genai.types import Content, Part
        message = f"Data validation complete. {len(df)} records validated using contract policies."

        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            content=Content(role="model", parts=[Part(text=message)]),
            actions=EventActions(state_delta={"validated_pl_data_csv": updated_csv})
        )


class TestModeReportSynthesisAgent(BaseAgent):
    """
    Report synthesis agent for TEST MODE.

    Reads hierarchical analysis results from session state and generates
    a proper markdown report using the generate_markdown_report tool.
    """

    def __init__(self):
        super().__init__(name="test_mode_report_synthesis_agent")

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        import json
        from datetime import datetime
        from google.genai.types import Content, Part

        print(f"\n{'='*80}")
        print(f"[TEST_REPORT_SYNTHESIS] Starting report synthesis")
        print(f"{'='*80}\n")

        analysis_target = ctx.session.state.get("current_analysis_target", "Unknown")
        timeframe = ctx.session.state.get("timeframe", {})
        period_str = f"{timeframe.get('start', 'N/A')} to {timeframe.get('end', 'N/A')}"

        # Collect hierarchical analysis results from session state
        level_analyses = {}
        levels_analyzed = []
        
        # Check for level results stored by hierarchical_analysis_agent
        da_result_raw = ctx.session.state.get("data_analyst_result")
        da_result = safe_parse_json(da_result_raw) if da_result_raw else {}
        level_results_from_da = da_result.get("level_results", {})

        for level in [0, 1, 2, 3, 4, 5]:
            level_key = f"level_{level}_analysis"
            level_data = ctx.session.state.get(level_key) or level_results_from_da.get(level_key)

            if level_data:
                try:
                    parsed = safe_parse_json(level_data)
                    # Handle both raw tool output (top_drivers) and agent output (insight_cards)
                    top_drivers = parsed.get("top_drivers") or parsed.get("top_items") or []
                    insight_cards = parsed.get("insight_cards", [])
                    
                    # Convert to expected format
                    level_analyses[f"level_{level}"] = {
                        "top_drivers": top_drivers,
                        "insight_cards": insight_cards,
                        "total_variance_dollar": parsed.get("total_variance_dollar", 0),
                        "variance_explained_pct": parsed.get("variance_explained_pct", 0),
                        "items_aggregated": len(top_drivers) if top_drivers else len(insight_cards),
                        "top_drivers_identified": len(top_drivers) if top_drivers else len(insight_cards),
                    }
                    levels_analyzed.append(level)
                except (json.JSONDecodeError, TypeError) as e:
                    print(f"[TEST_REPORT_SYNTHESIS] Warning: Could not parse level {level}: {e}")

        # Build hierarchical results structure
        drill_down_path = " -> ".join([f"Level {l}" for l in sorted(levels_analyzed)]) if levels_analyzed else "N/A"

        hierarchical_results = {
            "levels_analyzed": sorted(levels_analyzed),
            "level_analyses": level_analyses,
            "drill_down_path": drill_down_path,
        }

        print(f"[TEST_REPORT_SYNTHESIS] Levels analyzed: {levels_analyzed}")
        print(f"[TEST_REPORT_SYNTHESIS] Drill-down path: {drill_down_path}")

        # Generate markdown report
        from .sub_agents.report_synthesis_agent.tools.generate_markdown_report import generate_markdown_report
        try:
            # Import the tool function directly - it's async
            markdown_report = await generate_markdown_report(
                hierarchical_results=json.dumps(hierarchical_results),
                analysis_target=analysis_target,
                analysis_period=period_str
            )
        except ImportError:
            # Fallback: generate basic report inline
            markdown_report = self._generate_basic_report(hierarchical_results, analysis_target, period_str)

        print(f"[TEST_REPORT_SYNTHESIS] Generated report ({len(markdown_report)} chars)")
        print(f"{'='*80}")

        # Store report in session state
        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            content=Content(role="model", parts=[Part(text=markdown_report)]),
            actions=EventActions(state_delta={
                "report_synthesis_result": markdown_report,
                "hierarchical_results": hierarchical_results
            })
        )

    def _generate_basic_report(self, results: dict, analysis_target: str, period: str) -> str:
        """Generate a basic markdown report as fallback."""
        from datetime import datetime

        md = []
        md.append(f"# Analysis Report - {analysis_target}")
        md.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        md.append(f"**Period:** {period}")
        md.append("")

        levels_analyzed = results.get("levels_analyzed", [])
        level_analyses = results.get("level_analyses", {})
        drill_down_path = results.get("drill_down_path", "N/A")

        # Executive Summary
        md.append("## Executive Summary")
        md.append("")
        md.append(f"- **Analysis Depth:** {drill_down_path}")
        md.append(f"- **Levels Analyzed:** {len(levels_analyzed)}")
        md.append("")

        # Variance Drivers
        md.append("## Variance Drivers")
        md.append("")

        all_drivers = []
        for level_key, level_data in level_analyses.items():
            for driver in level_data.get("top_drivers", []):
                if driver not in all_drivers:
                    all_drivers.append(driver)

        if all_drivers:
            md.append("| Rank | Category | Variance $ | Variance % | Materiality |")
            md.append("|------|----------|------------|------------|-------------|")
            for i, driver in enumerate(all_drivers[:10], 1):
                item = driver.get("item", "Unknown")
                var_dollar = driver.get("variance_dollar", 0)
                var_pct = driver.get("variance_pct", 0)
                materiality = driver.get("materiality", "LOW")
                md.append(f"| {i} | {item} | ${var_dollar:+,.0f} | {var_pct:+.1f}% | {materiality} |")
        else:
            md.append("*No variance drivers identified*")

        md.append("")
        md.append("## Recommended Actions")
        md.append("")

        actions = []
        for driver in all_drivers:
            if driver.get("materiality") == "HIGH":
                name = driver.get("item", "Unknown")
                var_dollar = driver.get("variance_dollar", 0)
                if var_dollar > 0:
                    actions.append(f"Investigate increase in {name} (+${abs(var_dollar):,.0f})")
                else:
                    actions.append(f"Investigate decrease in {name} (${var_dollar:,.0f})")

        if actions:
            for i, action in enumerate(actions[:5], 1):
                md.append(f"{i}. {action}")
        else:
            md.append("1. No high-materiality variances requiring immediate action")
            md.append("2. Continue monitoring trends for emerging patterns")

        md.append("")
        md.append("---")
        md.append("*This report was auto-generated by Data Analyst Agent*")

        return "\n".join(md)


class ContractDrivenDataFetcher(BaseAgent):
    """Fetches primary data using the agent specified in the DatasetContract."""
    
    def __init__(self):
        super().__init__(name="contract_driven_data_fetcher")
        
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        contract = ctx.session.state.get("dataset_contract")
        if not contract or not contract.data_source or not contract.data_source.agent:
            print("[ContractDrivenDataFetcher] No agent specified in contract. Skipping.")
            yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=EventActions())
            return
            
        agent_name = contract.data_source.agent
        
        # Registry of available agents
        agents = {
            "tableau_account_research_ds_agent": tableau_account_research_ds_agent,
            "tableau_ops_metrics_ds_agent": tableau_ops_metrics_ds_agent,
            "tableau_order_dispatch_revenue_ds_agent": tableau_order_dispatch_revenue_ds_agent,
        }
        
        target_agent = agents.get(agent_name)
        if not target_agent:
            print(f"[ContractDrivenDataFetcher] ERROR: Agent '{agent_name}' not found in registry.")
            yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=EventActions())
            return
            
        print(f"[ContractDrivenDataFetcher] Fetching data using agent: {agent_name}")
        
        # Reuse DataSourceProxyAgent logic to call the agent
        # We use a standard query key "data_fetch_query_primary" which the RequestAnalyzer 
        # should now provide generically.
        proxy = DataSourceProxyAgent(target_agent, "data_fetch_query_primary")
        async for event in proxy.run_async(ctx):
            yield event
            
        # The proxy stores the result in f"{agent_name}_result"
        # We'll sync it to a generic key for the normalizer
        result_key = f"{agent_name}_result"
        if result_key in ctx.session.state:
            ctx.session.state["primary_data_raw"] = ctx.session.state[result_key]
            print(f"[ContractDrivenDataFetcher] Data moved to primary_data_raw ({len(str(ctx.session.state['primary_data_raw']))} bytes)")

class UniversalDataFetcher(BaseAgent):
    """Generic data fetcher that handles both local Hyper and local CSV files."""

    def __init__(self):
        super().__init__(name="universal_data_fetcher")

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        # --- OPTIMIZATION: Avoid redundant fetches if data is already in state ---
        if ctx.session.state.get("primary_data_csv") or ctx.session.state.get("validated_pl_data_csv"):
            print("[UniversalDataFetcher] Data already present in session state. Skipping redundant fetch.")
            yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=EventActions())
            return

        contract = ctx.session.state.get("dataset_contract")
        if not contract:
            print("[UniversalDataFetcher] ERROR: No contract found in state.")
            yield Event(invocation_id=ctx.invocation_id, author=self.name)
            return

        source_type = (contract.data_source.type or "tableau_hyper") if contract.data_source else "tableau_hyper"
        print(f"[UniversalDataFetcher] data_source.type = '{source_type}'")

        if source_type == "csv":
            fetcher = ConfigCSVFetcher()
        elif source_type == "tableau_hyper":
            from .sub_agents.tableau_hyper_fetcher import TableauHyperFetcher
            fetcher = TableauHyperFetcher()
        else:
            # Default fallback to Hyper if unspecified
            from .sub_agents.tableau_hyper_fetcher import TableauHyperFetcher
            fetcher = TableauHyperFetcher()

        async for event in fetcher.run_async(ctx):
            yield event


# ---------------------------------------------------------------------------
# Data Fetch Pipeline — branch based on active mode
# ---------------------------------------------------------------------------
print("\n" + "="*80)

if VALIDATION_CSV_MODE:
    print("VALIDATION CSV MODE: data/validation_data.csv  ->  full agent pipeline")
    print(f"  ACTIVE_DATASET   : {os.environ.get('ACTIVE_DATASET', 'validation_ops')}")
    print(f"  EXCLUDE_PARTIAL  : {os.environ.get('DATA_ANALYST_EXCLUDE_PARTIAL_WEEK', 'false')}")
    print("  Pipeline         : ContractLoader -> Planner -> Stats -> Hierarchy -> Narrative -> Synthesis")
    print("="*80 + "\n")

    data_fetch_workflow = SequentialAgent(
        name="data_fetch_workflow",
        sub_agents=[
            DateInitializer(),          # Calculate standard date ranges
            ValidationCSVFetcher(),     # Load metric slice from validation_data.csv
        ],
        description=(
            "VALIDATION CSV MODE: loads data/validation_data.csv for the current "
            "analysis target, then hands off to the full analysis pipeline."
        ),
    )

elif TEST_MODE:
    print("TEST MODE: TestingDataAgent (sample CSVs) + simplified synthesis")
    print("="*80 + "\n")

    from .sub_agents.testing_data_agent.agent import TestingDataAgent
    dynamic_testing_agent = TestingDataAgent()

    data_fetch_workflow = SequentialAgent(
        name="parallel_data_fetch",
        sub_agents=[
            DateInitializer(),
            dynamic_testing_agent,
        ],
        description="TEST MODE: Fetches data from sample CSV files.",
    )

else:
    print("LIVE MODE: contract-driven data fetch (tableau_hyper / csv)")
    print("="*80 + "\n")

    data_fetch_workflow = SequentialAgent(
        name="data_fetch_workflow",
        sub_agents=[
            DateInitializer(),
            UniversalDataFetcher(),
        ],
        description=(
            "Fetches data using the source type declared in the dataset contract. "
            "Routes to TableauHyperFetcher (local Hyper) or ConfigCSVFetcher (local CSV) "
            "based on data_source.type."
        ),
    )

print(f"[INIT] data_fetch_workflow sub_agents: {[a.name for a in data_fetch_workflow.sub_agents]}")

class ConditionalAlertScoringAgent(BaseAgent):
    """Only runs alert scoring if selected by the planner."""
    alert_agent: Any = Field(None, exclude=True)
    
    def __init__(self, alert_agent):
        super().__init__(name="conditional_alert_scoring")
        object.__setattr__(self, 'alert_agent', alert_agent)
        
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        plan_raw = ctx.session.state.get("execution_plan", {})
        plan = safe_parse_json(plan_raw)
            
        selected_agents = [a.get("name") for a in plan.get("selected_agents", [])]
        
        if "alert_scoring_coordinator" in selected_agents and self.alert_agent:
            print("[ConditionalAlertScoring] Alert scoring selected by planner. Executing...")
            async for event in self.alert_agent.run_async(ctx):
                yield event
        else:
            print("[ConditionalAlertScoring] Alert scoring skipped by planner.")
            yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=EventActions())

# Analysis Pipeline: Sequential workflow for the analysis target
# TEST_MODE uses a simplified synthesis agent; VALIDATION_CSV_MODE and LIVE
# both use the real report_synthesis_agent so the full pipeline runs.
synthesis_agent = TestModeReportSynthesisAgent() if TEST_MODE else report_synthesis_agent

cc_analysis_sub_agents = [
    TimedAgentWrapper(AnalysisContextInitializer()),
    TimedAgentWrapper(planner_agent),
    TimedAgentWrapper(DynamicParallelAnalysisAgent()),
    TimedAgentWrapper(narrative_agent),
    TimedAgentWrapper(ConditionalAlertScoringAgent(alert_scoring_coordinator)),
    TimedAgentWrapper(synthesis_agent),
    TimedAgentWrapper(OutputPersistenceAgent(level="dimension_value")),
]

for agent in cc_analysis_sub_agents:
    if hasattr(agent, 'parent') and agent.parent is not None:
        object.__setattr__(agent, 'parent', None)

target_analysis_pipeline = SequentialAgent(
    name="target_analysis_pipeline",
    sub_agents=cc_analysis_sub_agents,
    description="Sequential analysis pipeline for a specific target value: fetches data, initializes context, plans execution, runs dynamic analysis, synthesizes report, and persists output.",
)
print(f"[INIT] target_analysis_pipeline sub_agents: {[a.name for a in target_analysis_pipeline.sub_agents]}")


class TargetIteratorAgent(BaseAgent):
    """Iterates through extracted analysis targets for loop control and initializes per-target resources."""
    
    def __init__(self):
        super().__init__(name="target_iterator")
        
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        # Handle parallel loop case: if target is provided via ctx.loop_target
        loop_target = getattr(ctx, "loop_target", None)
        if loop_target:
            target = loop_target
            new_state = {} # Not used in parallel
            complete = False
        else:
            extracted_targets = ctx.session.state.get("extracted_targets", [])
            loop_state = ctx.session.state.get("target_loop_state")
            target_label = ctx.session.state.get("target_label", "Analysis Target")
            
            target, new_state, complete = iterate_analysis_targets(
                extracted_targets=extracted_targets,
                loop_state=loop_state,
                target_label=target_label
            )
        
        if not target or complete:
            # Signal loop exit via escalation
            yield Event(
                invocation_id=ctx.invocation_id, 
                author=self.name, 
                actions=EventActions(state_delta={"target_loop_complete": True}, escalate=True)
            )
            return

        # Initialize phase logger for this specific analysis target
        from .utils.phase_logger import PhaseLogger
        phase_logger = PhaseLogger(dimension_value=target)
        
        phase_logger.log_workflow_transition(
            from_agent="root_agent",
            to_agent="target_analysis",
            message=f"Starting analysis for {target}"
        )
        phase_logger.start_phase(
            phase_name=f"{target} Analysis",
            description=f"Complete analysis workflow for {target}",
            input_data={"target": target}
        )
        
        print(f"\n{'='*80}")
        print(f"[TargetIterator] Starting analysis loop for: {target}")
        print(f"{'='*80}\n")
        
        # Store phase_logger directly on session state (not via state_delta)
        ctx.session.state["phase_logger"] = phase_logger
        
        state_delta = {
            "target_loop_state": new_state,
            "target_loop_complete": False,
            "current_analysis_target": target,
            "dimension_value": target,
            "primary_target_value": target,
        }
        
        # Also set directly in session state for reliability
        ctx.session.state["current_analysis_target"] = target
        ctx.session.state["dimension_value"] = target
        ctx.session.state["primary_target_value"] = target
        
        yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=EventActions(state_delta=state_delta))


def create_target_analysis_pipeline():
    """Factory to create a fresh pipeline for parallel execution."""
    from .sub_agents.dynamic_parallel_agent import DynamicParallelAnalysisAgent
    from .sub_agents.output_persistence_agent.agent import OutputPersistenceAgent
    from .sub_agents.report_synthesis_agent.agent import create_report_synthesis_agent
    from .sub_agents.narrative_agent.agent import create_narrative_agent
    from .sub_agents.alert_scoring_agent.agent import root_agent as alert_scoring_agent
    from .sub_agents.planner_agent.agent import RuleBasedPlanner
    
    pipeline = SequentialAgent(
        name="target_analysis_pipeline",
        sub_agents=[
            TimedAgentWrapper(AnalysisContextInitializer()),
            TimedAgentWrapper(RuleBasedPlanner()),
            TimedAgentWrapper(DynamicParallelAnalysisAgent()),
            TimedAgentWrapper(create_narrative_agent()),
            TimedAgentWrapper(alert_scoring_agent),
            TimedAgentWrapper(create_report_synthesis_agent()),
            TimedAgentWrapper(OutputPersistenceAgent(level="dimension_value")),
        ]
    )
    # Clear parents to allow re-assignment in parallel runner
    for agent in pipeline.sub_agents:
        if hasattr(agent, 'parent') and agent.parent is not None:
            object.__setattr__(agent, 'parent', None)
    return pipeline

def _read_parallel_cap() -> int:
    """Return the MAX_PARALLEL_METRICS cap from env. 0 = unlimited."""
    raw = os.environ.get("MAX_PARALLEL_METRICS", "4").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 4


class ParallelDimensionTargetAgent(BaseAgent):
    """Executes the analysis pipeline for all dimension targets with a
    configurable concurrency cap.

    MAX_PARALLEL_METRICS env var controls how many per-metric pipelines
    run simultaneously:
      0  — unlimited (original behaviour, all fire at once)
      1  — fully sequential (safest for tight quota accounts)
      2  — default: two at a time, balances speed vs quota pressure
      N  — at most N pipelines run concurrently
    """

    def __init__(self):
        super().__init__(name="parallel_dimension_target_analysis")

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        import asyncio
        import copy
        import re

        targets = ctx.session.state.get("extracted_targets", [])
        if not targets:
            print("[ParallelDimensionTargetAnalysis] No targets to analyze.")
            yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=EventActions())
            return

        cap = _read_parallel_cap()
        effective_cap = cap if (cap > 0 and cap < len(targets)) else len(targets)
        mode = "sequential" if effective_cap == 1 else f"parallel (cap={effective_cap})"
        print(
            f"[ParallelDimensionTargetAnalysis] {len(targets)} target(s), "
            f"MAX_PARALLEL_METRICS={cap} -> running {mode}"
        )

        from google.adk.sessions.session import Session
        from google.adk.agents.invocation_context import InvocationContext as _IC
        from google.adk.agents.run_config import RunConfig
        from .sub_agents.data_cache import current_session_id
        from .utils.phase_logger import PhaseLogger

        # ------------------------------------------------------------------
        # Build one isolated (session, pipeline) pair per target. These are
        # plain data objects, not ADK agents — we drive them ourselves with
        # asyncio so the semaphore can throttle when they start.
        # ------------------------------------------------------------------
        class SingleTargetRunner(BaseAgent):
            target_val: str
            inner_pipeline: BaseAgent = Field(..., exclude=True)

            def __init__(self, t, p):
                safe_name = re.sub(r'_+', '_', re.sub(r'[^a-zA-Z0-9_]', '_', str(t))).strip('_')
                super().__init__(name=f"run_{safe_name}", target_val=t, inner_pipeline=p)

            async def _run_async_impl(self, inner_ctx: _IC) -> AsyncGenerator[Event, None]:
                session_id = getattr(inner_ctx.session, "id", str(__import__('uuid').uuid4()))
                isolated_id = f"{session_id}_{self.target_val.replace('/', '_').replace(' ', '_')}"
                token = current_session_id.set(isolated_id)

                isolated_session = Session(
                    id=isolated_id,
                    app_name=inner_ctx.session.app_name,
                    user_id=inner_ctx.session.user_id,
                    state=copy.deepcopy(inner_ctx.session.state),
                    events=copy.deepcopy(inner_ctx.session.events),
                )
                new_ctx = _IC(
                    agent=self.inner_pipeline,
                    session=isolated_session,
                    session_service=inner_ctx.session_service,
                    invocation_id=inner_ctx.invocation_id,
                    run_config=inner_ctx.run_config or RunConfig(),
                )
                new_ctx.session.state["current_analysis_target"] = self.target_val
                new_ctx.session.state["dimension_value"] = self.target_val
                new_ctx.session.state["primary_target_value"] = self.target_val
                new_ctx.session.state["phase_logger"] = PhaseLogger(dimension_value=self.target_val)

                print(f"[ParallelTarget] Starting: {self.target_val}")
                try:
                    async for event in self.inner_pipeline.run_async(new_ctx):
                        if event.actions and event.actions.state_delta:
                            new_ctx.session.state.update(event.actions.state_delta)
                        yield event
                    print(f"[ParallelTarget] Completed: {self.target_val}")
                except Exception as pipeline_err:
                    import traceback
                    print(f"[ParallelTarget] ERROR for {self.target_val}: {pipeline_err}")
                    traceback.print_exc()
                    yield Event(
                        invocation_id=inner_ctx.invocation_id,
                        author=self.name,
                        actions=EventActions(
                            state_delta={f"pipeline_error_{self.target_val}": str(pipeline_err)}
                        ),
                    )
                finally:
                    current_session_id.reset(token)

        runners = [SingleTargetRunner(t, create_target_analysis_pipeline()) for t in targets]
        for r in runners:
            if hasattr(r, 'parent') and r.parent is not None:
                object.__setattr__(r, 'parent', None)

        # ------------------------------------------------------------------
        # Execute with semaphore: yield events as they come to avoid 
        # silence during the analysis.interleaving will occur but streaming 
        # is maintained.
        # ------------------------------------------------------------------
        sem = asyncio.Semaphore(effective_cap)
        event_queue = asyncio.Queue()

        async def _run_target_task(runner: SingleTargetRunner):
            try:
                async with sem:
                    # Run the pipeline and push all events to the shared queue
                    async for event in runner.run_async(ctx):
                        await event_queue.put(event)
            except Exception as e:
                import traceback
                print(f"[ParallelDimensionTargetAnalysis] FATAL for {runner.target_val}: {e}")
                traceback.print_exc()
            finally:
                # Mark this specific runner as finished
                await event_queue.put(None)

        # Start all tasks in the background
        for r in runners:
            asyncio.create_task(_run_target_task(r))

        # Stream events from the queue until all runners are finished
        finished_runners = 0
        while finished_runners < len(runners):
            event = await event_queue.get()
            if event is None:
                finished_runners += 1
            else:
                yield event


# Root Agent: Dynamic analyst workflow

from .sub_agents.executive_brief_agent.agent import CrossMetricExecutiveBriefAgent
from .sub_agents.weather_context_agent import root_agent as weather_context_agent

root_sub_agents = [
    TimedAgentWrapper(ContractLoader()),
    TimedAgentWrapper(CLIParameterInjector()),
    TimedAgentWrapper(data_fetch_workflow),
    ParallelDimensionTargetAgent(),
    TimedAgentWrapper(weather_context_agent),
    TimedAgentWrapper(CrossMetricExecutiveBriefAgent()),
]

for agent in root_sub_agents:
    if hasattr(agent, 'parent') and agent.parent is not None:
        object.__setattr__(agent, 'parent', None)

root_agent = SequentialAgent(
    name="data_analyst_agent",
    sub_agents=root_sub_agents,
    description="Dynamic Analyst Agent: Analyzes request intent, extracts dimension targets, then runs a full analysis pipeline (data fetch, context initialization, analysis, synthesis, persistence).",
)


# --- Public API Exports ---

__all__ = [
    # Main workflow agent
    "root_agent",
]


async def run_analysis(query: str):
    """Run the complete analysis pipeline for a given query."""
    from google.adk.agents.invocation_context import InvocationContext
    from google.adk.agents.run_config import RunConfig
    from google.adk.sessions.in_memory_session_service import InMemorySessionService
    import uuid
    import os
    
    # --- PRE-FLIGHT AUTH CHECK (T031) ---
    if os.getenv("DATA_ANALYST_TEST_MODE") != "true":
        print("Checking LLM connectivity...", end=" ", flush=True)
        try:
            from google import genai
            # Use Vertex AI if configured, otherwise default to Google AI (API Key)
            use_vertex = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "False").lower() == "true"
            client = genai.Client(vertexai=use_vertex)
            
            model = get_agent_model("narrative_agent")
            # Rapid connectivity test
            client.models.generate_content(
                model=model, 
                contents="ping", 
                config=types.GenerateContentConfig(max_output_tokens=1)
            )
            print("OK")
        except Exception as e:
            # If we were trying Vertex and it failed, maybe try Google AI as fallback if key exists
            if use_vertex and os.getenv("GOOGLE_API_KEY"):
                try:
                    client = genai.Client(vertexai=False)
                    client.models.generate_content(
                        model=model, 
                        contents="ping", 
                        config=types.GenerateContentConfig(max_output_tokens=1)
                    )
                    print("OK (via API Key fallback)")
                except Exception:
                    print(f"FAILED\n\nERROR: LLM authentication failed for both Vertex AI and Google AI. {str(e)}")
                    sys.exit(1)
            else:
                print(f"FAILED\n\nERROR: LLM authentication failed. {str(e)}")
                print("\nCheck your .env file for a valid GOOGLE_API_KEY or service-account.json.")
                sys.exit(1)
            
    # Initialize session infrastructure
    session_service = InMemorySessionService()
    session = await session_service.create_session(app_name="pl_analyst", user_id="cli_user")
    
    # Load global report configuration (as fallback for contract-specific settings)
    max_drill_depth = 3
    try:
        import yaml
        config_path = Path(__file__).resolve().parent.parent / "config" / "report_config.yaml"
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                report_cfg = yaml.safe_load(f) or {}
                max_drill_depth = report_cfg.get("analysis", {}).get("max_drill_depth", 3)
    except Exception as e:
        print(f"[INIT] Warning: Failed to load report_config.yaml: {e}")

    # Set the input query in session state
    session.state.update({
        "user_message": query,
        "max_drill_depth": max_drill_depth  # Global fallback
    })
    
    # Add initial user message to session events so LLM agents can see it
    from google.genai.types import Content, Part
    from google.adk.events.event import Event
    if not session.events:
        session.events = []
    
    session.events.append(Event(
        invocation_id="initial",
        author="user",
        content=Content(role="user", parts=[Part(text=query)])  # uses augmented query with metric names injected
    ))
    
    # Create invocation context with required fields
    ctx = InvocationContext(
        agent=root_agent,
        session=session,
        session_service=session_service,
        invocation_id=str(uuid.uuid4()),
        run_config=RunConfig()
    )
    
    print(f"\n{'='*80}")
    print(f"Starting Analysis Pipeline")
    print(f"Query: {query}")
    print(f"Mode: {'TEST (Mocks)' if os.getenv('DATA_ANALYST_TEST_MODE') == 'true' else 'LIVE (A2A)'}")
    print(f"{'='*80}\n")
    
    async for event in root_agent.run_async(ctx):
        # Manually update session state from event actions if SequentialAgent didn't do it
        if event.actions and event.actions.state_delta:
            ctx.session.state.update(event.actions.state_delta)
            
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    print(part.text, flush=True)
                if hasattr(part, 'function_call') and part.function_call:
                    print(f"\n[Tool Call] {part.function_call.name}({part.function_call.args})", flush=True)
                if hasattr(part, 'function_response') and part.function_response:
                    print(f"\n[Tool Result] {part.function_response.name} -> {part.function_response.response}", flush=True)


if __name__ == "__main__":
    import asyncio

    metrics = os.environ.get("DATA_ANALYST_METRICS", "")
    query = os.environ.get("DATA_ANALYST_QUERY", "")
    if not query:
        parts = [f"Analyze {metrics.replace(',', ' and ')}"] if metrics else ["Analyze performance variance"]
        dim_val = os.environ.get("DATA_ANALYST_DIMENSION_VALUE")
        if dim_val:
            parts.append(f"for {dim_val}")
        query = " ".join(parts)

    try:
        asyncio.run(run_analysis(query))
    except KeyboardInterrupt:
        print("\nAnalysis cancelled by user.")
    except Exception as e:
        print(f"\nAnalysis failed: {str(e)}")
        import traceback
        traceback.print_exc()
