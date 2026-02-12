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
P&L Analyst Agent - Sequential cost center analysis with parallel deep analysis.

Architecture:
- Cost center-first analysis (dynamically extracted from user request)
- Sequential processing: Each cost center analyzed completely before moving to next
- Parallel data fetch and analysis for optimal performance

Workflow (Dynamic - No Hardcoded Dates or Cost Centers):
1. Cost Center Extraction:
   - cost_center_extractor: Extracts ALL cost center(s) from user request
   - CostCenterParserAgent: Parses extracted cost centers into a list
   
2. Sequential Cost Center Loop:
   For EACH cost center, process completely before moving to next:
   
   a) Sequential Data Fetch (for current cost center):
      - DateInitializer: Calculates date ranges (24mo P&L, 3mo orders)
      - tableau_account_research_ds_agent: Retrieves P&L data (24 months)
      - tableau_ops_metrics_ds_agent: Retrieves ops metrics (24 months)
      - ConditionalOrderDetailsFetchAgent: CONDITIONALLY retrieves order-level detail (3 months) ONLY for contract validation
   
   b) Full Analysis Pipeline (for current cost center):
      - data_validation_agent: Cleans and validates all fetched data
      - parallel_analysis_agent: Runs 6 analysis agents concurrently
      - report_synthesis_agent: Combines all analysis results into executive summary
      - alert_scoring_coordinator: Scores alerts and recommends actions
      - OutputPersistenceAgent: Saves complete analysis to JSON
   
   c) Loop continues with next cost center

Output:
- outputs/cost_center_XXX.json (one per cost center)
- outputs/alerts_payload_ccXXX.json (one per cost center)
- Each file contains: full analysis results, alerts, and recommendations

Performance:
- Data fetch: ~15-20s per cost center (sequential with rate limiting, 3 data sources)
- Analysis: ~30-45s per cost center (6 parallel agents, consolidated from 10)
- Total: ~50-70s per cost center
- Cost centers processed sequentially for clean data isolation
"""

import json
from pathlib import Path
from typing import Dict, Any, AsyncGenerator

from google.adk.agents.llm_agent import Agent as LlmAgent
from google.adk.agents.remote_a2a_agent import AGENT_CARD_WELL_KNOWN_PATH, RemoteA2aAgent
from google.adk.agents.sequential_agent import SequentialAgent
from google.adk.agents.loop_agent import LoopAgent
from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.genai import types

# Ensure parent package (project root) is at the FRONT of sys.path.
# ADK's load_services_module adds pl_analyst_agent/ to sys.path, which contains
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

# Import configuration and prompts
from .prompt import COST_CENTER_EXTRACTOR_INSTRUCTION, REQUEST_ANALYZER_INSTRUCTION_TEMPLATE, SYSTEM_PROMPT
from .tools import calculate_date_ranges, parse_cost_centers, iterate_cost_centers, should_fetch_order_details
from config.model_loader import get_agent_model

# Import analysis agents
# Note: Using importlib for numeric-prefixed module names (Python doesn't allow numeric prefixes in standard imports)
import importlib

_data_validation_module = importlib.import_module('pl_analyst_agent.sub_agents.01_data_validation_agent.agent')
data_validation_agent = _data_validation_module.root_agent

_statistical_insights_module = importlib.import_module('pl_analyst_agent.sub_agents.02_statistical_insights_agent.agent')
statistical_insights_agent = _statistical_insights_module.root_agent

_data_analyst_module = importlib.import_module('pl_analyst_agent.sub_agents.data_analyst_agent')
data_analyst_agent = _data_analyst_module.root_agent

_report_synthesis_module = importlib.import_module('pl_analyst_agent.sub_agents.04_report_synthesis_agent.agent')
report_synthesis_agent = _report_synthesis_module.root_agent

_output_persistence_module = importlib.import_module('pl_analyst_agent.sub_agents.06_output_persistence_agent')
OutputPersistenceAgent = _output_persistence_module.OutputPersistenceAgent

from .sub_agents.testing_data_agent.agent import root_agent as testing_data_agent
# from .renderers.renderer_agent import JsonToMarkdownRendererAgent  # Not used
# from .insights.prioritizer_agent import InsightPrioritizerAgent  # Not used
# from .alerts.alert_scoring_agent import AlertScoringAgent  # Not used
import os

# Authentication and environment setup is handled by config module
from .semantic.models import DatasetContract, AnalysisContext
from .semantic.quality import DataQualityGate
import uuid

class ContractLoader(BaseAgent):
    """Loads the DatasetContract from YAML based on request analysis or default."""
    
    def __init__(self):
        super().__init__(name="contract_loader")
    
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        # For now, default to P&L contract. In Wave 3 (Planning), this will be dynamic.
        contract_path = os.path.join(_project_root, "contracts", "pl_contract.yaml")
        contract = DatasetContract.from_yaml(contract_path)
        
        print(f"[ContractLoader] Loaded contract: {contract.name} v{contract.version}")
        
        # Store in session state as a non-serialized object for sub-agents to use
        ctx.session.state["dataset_contract"] = contract
        
        actions = EventActions(state_delta={"contract_name": contract.name})
        yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=actions)

class AnalysisContextInitializer(BaseAgent):
    """Initializes the AnalysisContext after data is fetched and validated."""
    
    def __init__(self):
        super().__init__(name="analysis_context_initializer")
        
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        import pandas as pd
        from io import StringIO
        
        contract = ctx.session.state.get("dataset_contract")
        pl_data_csv = ctx.session.state.get("validated_pl_data_csv")
        
        if not contract or not pl_data_csv:
            print("[AnalysisContextInitializer] Missing contract or data")
            yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=EventActions())
            return
            
        df = pd.read_csv(StringIO(pl_data_csv))
        
        # Default to first metric and primary dimension for now
        target_metric = contract.metrics[0]
        primary_dim = next(d for d in contract.dimensions if d.role == "primary")
        
        context = AnalysisContext(
            contract=contract,
            df=df,
            target_metric=target_metric,
            primary_dimension=primary_dim,
            run_id=str(uuid.uuid4()),
            max_drill_depth=ctx.session.state.get("max_drill_depth", 3)
        )
        
        # Store in session state and global cache
        ctx.session.state["analysis_context"] = context
        from .sub_agents.data_cache import set_analysis_context
        set_analysis_context(context)
        
        print(f"[AnalysisContextInitializer] Created context for {len(df)} rows. Target: {target_metric.name}")
        
        actions = EventActions(state_delta={"analysis_context_ready": True})
        yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=actions)

# TEST MODE FLAG - Set to True to use CSV data instead of Tableau A2A agents
TEST_MODE = os.environ.get("PL_ANALYST_TEST_MODE", "false").lower() == "true"


# --- A2A Remote Agents (Data Retrieval) ---
# Only initialize A2A agents when NOT in test mode (they make HTTP requests that timeout)

if not TEST_MODE:
    tableau_account_research_ds_agent = RemoteA2aAgent(
        name="tableau_account_research_ds_agent",
        description=(
            "Retrieves MONTHLY P&L DATA from Account Research dataset (6.3M+ GL transactions). "
            "Data Granularity: AGGREGATED by month/period - NOT order-level detail. "
            "Pulls ALL months by default in efficient CSV format via export_bulk_data_tool. "
            "Automatically formats output as time series for analysis pipeline (period: YYYY-MM, amount). "
            "Use for: Monthly trends, variance analysis, historical P&L tracking. "
            "Supports ALL GL accounts dynamically from pl_account_rollup.yaml configuration."
        ),
        agent_card=(
            f"http://localhost:8001/a2a/tableau_account_research_ds_agent{AGENT_CARD_WELL_KNOWN_PATH}"
        ),
    )

    tableau_order_dispatch_revenue_ds_agent = RemoteA2aAgent(
        name="tableau_order_dispatch_revenue_ds_agent",
        description=(
            "Retrieves ORDER-LEVEL DETAIL from Order Dispatch Revenue dataset. "
            "Data Granularity: INDIVIDUAL ORDERS with full detail (stops, miles, tolls, dates, shippers). "
            "Provides query and analysis capabilities for order, dispatch, and revenue metrics. "
            "Use for: Contract validation, billing recovery, order-level analysis, operational metrics."
        ),
        agent_card=(
            f"http://localhost:8001/a2a/tableau_order_dispatch_revenue_ds_agent{AGENT_CARD_WELL_KNOWN_PATH}"
        ),
    )

    tableau_ops_metrics_ds_agent = RemoteA2aAgent(
        name="tableau_ops_metrics_ds_agent",
        description=(
            "Retrieves MONTHLY OPERATIONAL METRICS from Ops Metrics dataset (37M+ records). "
            "Data aggregated by cost center and month. "
            "Metrics include: miles (loaded/empty/total), orders, stops, revenue (total/linehaul/accessorial), "
            "driver pay, fuel consumed, driving/on-duty minutes, truck counts, and service metrics. "
            "Use for: Cost center performance analysis, efficiency metrics, operational trends."
        ),
        agent_card=(
            f"http://localhost:8001/a2a/tableau_ops_metrics_ds_agent{AGENT_CARD_WELL_KNOWN_PATH}"
        ),
    )
else:
    # In TEST_MODE, create placeholder None references (not used in test workflow)
    tableau_account_research_ds_agent = None
    tableau_order_dispatch_revenue_ds_agent = None
    tableau_ops_metrics_ds_agent = None


# --- Helper Agents (Simple Operations Using Tools) ---

class DateInitializer(BaseAgent):
    """Initializes date ranges in state using calculate_date_ranges tool."""
    
    def __init__(self):
        super().__init__(name="date_initializer")
    
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        phase_logger = ctx.session.state.get("phase_logger")
        
        date_ranges = calculate_date_ranges()
        
        if phase_logger:
            phase_logger.log_workflow_transition(
                from_agent="cost_center_loop",
                to_agent="parallel_data_fetch",
                message="Initializing date ranges for data retrieval"
            )
            phase_logger.start_phase(
                phase_name="Data Fetch",
                description="Retrieving P&L, ops metrics, and order details",
                input_data=date_ranges
            )
        
        print(f"\n{'='*80}")
        print(f"[DateInitializer] Date ranges calculated:")
        print(f"  P&L Data: {date_ranges['pl_query_start_date']} to {date_ranges['pl_query_end_date']} (24 months)")
        print(f"  Ops Metrics: {date_ranges['ops_metrics_query_start_date']} to {date_ranges['ops_metrics_query_end_date']} (24 months)")
        print(f"  Order Detail: {date_ranges['order_query_start_date']} to {date_ranges['order_query_end_date']} (3 months)")
        print(f"{'='*80}\n")
        
        # Also provide timeframe object for persistence
        timeframe = {
            "start": date_ranges.get("pl_query_start_date"),
            "end": date_ranges.get("pl_query_end_date"),
        }
        actions = EventActions(state_delta={**date_ranges, "timeframe": timeframe})
        yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=actions)


class CostCenterParserAgent(BaseAgent):
    """Parses cost centers using parse_cost_centers tool."""
    
    def __init__(self):
        super().__init__(name="cost_center_parser")
    
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        raw = ctx.session.state.get("extracted_cost_centers_raw", "[]")
        cost_centers = parse_cost_centers(raw)
        
        print(f"[cost_center_parser]: Parsed {len(cost_centers)} cost centers: {cost_centers}")
        
        actions = EventActions(state_delta={"extracted_cost_centers": cost_centers})
        yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=actions)


class CostCenterIteratorAgent(BaseAgent):
    """Iterates through cost centers using iterate_cost_centers tool."""
    
    def __init__(self):
        super().__init__(name="cost_center_iterator")
    
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        cost_centers = ctx.session.state.get("extracted_cost_centers", [])
        loop_state = ctx.session.state.get("loop", {})
        
        # Use tool to get next cost center
        current_cc, updated_loop_state, is_complete = iterate_cost_centers(cost_centers, loop_state)
        
        if is_complete:
            # Log completion
            phase_logger = ctx.session.state.get("phase_logger")
            if phase_logger:
                phase_logger.log_workflow_transition(
                    from_agent="cost_center_loop",
                    to_agent="root_agent",
                    message=f"All cost centers analyzed. Total: {len(cost_centers)}"
                )
            
            print(f"\n{'='*80}")
            print(f"[CostCenterLoop] All cost centers analyzed: {cost_centers}")
            print(f"{'='*80}\n")
            
            # Signal loop completion by escalating
            yield Event(
                invocation_id=ctx.invocation_id, 
                author=self.name, 
                actions=EventActions(escalate=True)
            )
            return
        
        # Initialize phase logger for this cost center
        from .utils.phase_logger import PhaseLogger
        phase_logger = PhaseLogger(cost_center=current_cc)
        
        # Log start of cost center analysis
        phase_logger.log_workflow_transition(
            from_agent="root_agent",
            to_agent="cost_center_loop",
            message=f"Starting analysis for cost center {current_cc}"
        )
        phase_logger.start_phase(
            phase_name=f"Cost Center {current_cc} Analysis",
            description=f"Complete P&L analysis workflow for cost center {current_cc}",
            input_data={"cost_center": current_cc, "loop_iteration": updated_loop_state.get("index", 0)}
        )
        
        print(f"\n{'='*80}")
        print(f"[CostCenterLoop] Starting analysis for cost center: {current_cc}")
        print(f"  Progress: {updated_loop_state.get('index', 0) + 1} / {len(cost_centers)}")
        print(f"{'='*80}\n")
        
        # Store phase_logger directly on session state (not via state_delta, which gets
        # JSON-serialized to SQLite and fails on non-serializable objects)
        ctx.session.state["phase_logger"] = phase_logger

        # Update state with current cost center and loop state
        actions = EventActions(state_delta={
            "current_cost_center": current_cc,
            "cost_center": current_cc,  # For compatibility
            "loop": updated_loop_state,
        })
        yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=actions)


class ConditionalOrderDetailsFetchAgent(BaseAgent):
    """Conditionally fetches order details based on request type using should_fetch_order_details tool."""
    
    def __init__(self, order_details_agent):
        super().__init__(name="conditional_order_details_fetch")
        # Store agent in __dict__ to avoid Pydantic validation issues
        object.__setattr__(self, 'order_details_agent', order_details_agent)
    
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        request_analysis = ctx.session.state.get("request_analysis", "")
        
        # Use tool to determine if order details are needed
        if should_fetch_order_details(request_analysis):
            # Delegate to the actual agent
            async for event in self.order_details_agent._run_async_impl(ctx):
                yield event
        else:
            # Skip order details fetch
            yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=EventActions())



# --- Request Analyzer (LLM Agent) ---

class RequestAnalyzer(LlmAgent):
    """Analyzes user request to determine analysis type and data needs - fully LLM-driven"""
    
    def __init__(self):
        # No need to load config - chart_of_accounts.yaml has all the hierarchy info
        # The LLM will work with the user request directly
        
        super().__init__(
            name="request_analyzer",
            model=get_agent_model("request_analyzer"),
            instruction=REQUEST_ANALYZER_INSTRUCTION_TEMPLATE,
            output_key="request_analysis",
            generate_content_config=types.GenerateContentConfig(
                response_modalities=["TEXT"],
                temperature=0.0,
            ),
        )


# --- Cost Center Extractor (LLM Agent) ---

cost_center_extractor = LlmAgent(
    name="cost_center_extractor",
    model=get_agent_model("cost_center_extractor"),
    instruction=COST_CENTER_EXTRACTOR_INSTRUCTION,
    output_key="extracted_cost_centers_raw",
    generate_content_config=types.GenerateContentConfig(
        response_modalities=["TEXT"],
        temperature=0.0,
    ),
)


# --- Workflow Orchestration ---

# TEST MODE pass-through validation agent (bypasses data_validation_agent which relies on global cache)
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
        pl_data_csv = ctx.session.state.get("pl_data_csv", "")
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

        # Load and flip revenue signs
        df = pd.read_csv(StringIO(pl_data_csv))

        # Check for gl_account column
        if "gl_account" in df.columns:
            # Flip revenue account signs (accounts starting with 3)
            def is_revenue(gl):
                gl_str = str(gl).strip()
                return gl_str.startswith("3")

            revenue_mask = df["gl_account"].apply(is_revenue)
            df.loc[revenue_mask, "amount"] = df.loc[revenue_mask, "amount"] * -1
            flipped_count = int(revenue_mask.sum())
        else:
            flipped_count = 0

        # Store updated data back
        updated_csv = df.to_csv(index=False)

        # Import data_cache and set the validated CSV
        from .sub_agents.data_cache import set_validated_csv
        set_validated_csv(updated_csv)

        print(f"[TestModeValidation] Data validated and cached:")
        print(f"  Records: {len(df)}")
        print(f"  Revenue signs flipped: {flipped_count}")

        # Output confirmation
        from google.genai.types import Content, Part
        message = f"Data validation complete. {len(df)} records validated, {flipped_count} revenue accounts sign-corrected."

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

        cost_center = ctx.session.state.get("current_cost_center", "Unknown")
        timeframe = ctx.session.state.get("timeframe", {})
        period_str = f"{timeframe.get('start', 'N/A')} to {timeframe.get('end', 'N/A')}"

        # Collect hierarchical analysis results from session state
        level_analyses = {}
        levels_analyzed = []

        # Check for level results stored by data_analyst_agent
        # Key format is "level_{N}_analysis" (e.g., level_2_analysis, level_3_analysis)
        for level in [2, 3, 4, 5]:
            level_key = f"level_{level}_analysis"
            level_data = ctx.session.state.get(level_key)

            if level_data:
                try:
                    parsed = json.loads(level_data) if isinstance(level_data, str) else level_data
                    # Convert to expected format
                    level_analyses[f"level_{level}"] = {
                        "top_drivers": parsed.get("top_items", []),
                        "total_variance_dollar": parsed.get("total_variance_dollar", 0),
                        "variance_explained_pct": parsed.get("variance_explained_pct", 0),
                        "items_aggregated": len(parsed.get("top_items", [])),
                        "top_drivers_identified": parsed.get("items_selected_count", 0),
                    }
                    levels_analyzed.append(level)
                    print(f"[TEST_REPORT_SYNTHESIS] Found level {level} data: {len(parsed.get('top_items', []))} drivers")
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
        # Use importlib for numeric-prefixed module
        import importlib
        _md_module = importlib.import_module('pl_analyst_agent.sub_agents.04_report_synthesis_agent.tools.generate_markdown_report')
        generate_markdown_report = _md_module.generate_markdown_report
        try:
            # Import the tool function directly - it's async
            markdown_report = await generate_markdown_report(
                hierarchical_results=json.dumps(hierarchical_results),
                cost_center=cost_center,
                analysis_period=period_str
            )
        except ImportError:
            # Fallback: generate basic report inline
            markdown_report = self._generate_basic_report(hierarchical_results, cost_center, period_str)

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

    def _generate_basic_report(self, results: dict, cost_center: str, period: str) -> str:
        """Generate a basic markdown report as fallback."""
        from datetime import datetime

        md = []
        md.append(f"# P&L Analysis Report - Cost Center {cost_center}")
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
        md.append("*This report was auto-generated by P&L Analyst Agent*")

        return "\n".join(md)


# Data Fetch Pipeline: Fetches all data sources sequentially for current cost center
# Conditional based on TEST_MODE
if TEST_MODE:
    print("\n" + "="*80)
    print("TEST MODE ENABLED: Using testing_data_agent (CSV file) instead of Tableau A2A agents")
    print("="*80 + "\n")
    
    parallel_data_fetch = SequentialAgent(
        name="parallel_data_fetch",
        sub_agents=[
            DateInitializer(),                                              # Calculate date ranges (24mo P&L, 3mo orders)
            testing_data_agent,                                             # Fetch P&L data from CSV
            # Note: No ops metrics or order details in test mode yet
        ],
        description="TEST MODE: Fetches financial P&L data from CSV file (data/PL-067.csv).",
    )
else:
    parallel_data_fetch = SequentialAgent(
        name="parallel_data_fetch",
        sub_agents=[
            DateInitializer(),                                              # Calculate date ranges (24mo P&L, 3mo orders)
            tableau_account_research_ds_agent,                             # Fetch P&L data (24 months)
            tableau_ops_metrics_ds_agent,                                  # Fetch ops metrics (24 months)
            ConditionalOrderDetailsFetchAgent(tableau_order_dispatch_revenue_ds_agent),  # Conditional order details (3 months)
        ],
        description="Fetches financial P&L data (24 months), monthly ops metrics (24 months), and optionally order details (3 months, contract validation only) with rate limit protection.",
    )

# Create wrapper agents to log when each agent runs
class AgentLogger(BaseAgent):
    """Wrapper to log when an agent starts and completes."""
    
    def __init__(self, wrapped_agent, agent_name):
        super().__init__(name=agent_name)
        object.__setattr__(self, 'wrapped_agent', wrapped_agent)
        object.__setattr__(self, 'agent_name', agent_name)
    
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        print(f"\n{'='*80}")
        print(f"[LOOP] Starting: {self.agent_name}")
        print(f"{'='*80}\n")
        try:
            async for event in self.wrapped_agent.run_async(ctx):
                yield event
        finally:
            print(f"\n{'='*80}")
            print(f"[LOOP] Completed: {self.agent_name} - continuing to next agent")
            print(f"{'='*80}\n")

# Cost Center Analysis: Sequential per-cost-center workflow
# Use TestMode agents in TEST_MODE to bypass global cache and LLM issues
validation_agent = TestModeValidationAgent() if TEST_MODE else data_validation_agent
synthesis_agent = TestModeReportSynthesisAgent() if TEST_MODE else report_synthesis_agent

cost_center_analysis = SequentialAgent(
    name="cost_center_analysis",
    sub_agents=[
        AgentLogger(parallel_data_fetch, "parallel_data_fetch_logger"),
        AgentLogger(validation_agent, "data_validation_agent_logger"),
        AgentLogger(AnalysisContextInitializer(), "analysis_context_initializer_logger"),
        AgentLogger(data_analyst_agent, "data_analyst_agent_logger"),
        AgentLogger(synthesis_agent, "report_synthesis_agent_logger"),
        AgentLogger(OutputPersistenceAgent(level="cost_center"), "output_persistence_agent_logger"),
    ],
    description="Sequential cost center analysis: fetches data, validates, runs hierarchical analysis, synthesizes report, and persists output.",
)

# Cost Center Loop: Iterates across cost centers
cost_center_loop = LoopAgent(
    name="cost_center_loop",
    sub_agents=[
        AgentLogger(CostCenterIteratorAgent(), "cost_center_iterator"),
        cost_center_analysis,
    ],
    description="Dynamic cost center loop: processes each cost center with full analysis pipeline.",
)

# Root Agent: Fully dynamic P&L analyst workflow
request_analyzer = RequestAnalyzer()

root_agent = SequentialAgent(
    name="pl_analyst_agent",
    sub_agents=[
        request_analyzer,           # Analyze request type and determine data needs
        ContractLoader(),           # Load DatasetContract
        cost_center_extractor,      # Extract all cost centers from user message
        CostCenterParserAgent(),    # Parse JSON string into list
        cost_center_loop,           # Loop through cost centers with dynamic conditional workflows
    ],
    description="Fully dynamic P&L Analyst Agent: Analyzes request intent, extracts cost centers, then adapts analysis pipeline based on request type (contract validation vs expense analysis).",
)


# --- Public API Exports ---

__all__ = [
    # Main workflow agent
    "root_agent",
    "cost_center_loop",
    
    # Tableau A2A Remote Agents (Data Retrieval)
    "tableau_account_research_ds_agent",
    "tableau_order_dispatch_revenue_ds_agent",
    "tableau_ops_metrics_ds_agent",
    
    # Verification Helpers
    "verify_tableau_agents",
    "get_tableau_agent_info",
]


# --- Helper Functions ---

def verify_tableau_agents(timeout: int = 5) -> Dict[str, Any]:
    """
    Verify that all 3 Tableau A2A agents are accessible via HTTP.
    
    This function checks:
    1. HTTP connectivity to each agent card
    2. Agent card structure validation
    3. Agent instance properties
    
    Args:
        timeout: HTTP request timeout in seconds (default: 5)
    
    Returns:
        Dictionary with agent status:
        {
            "accessible": bool,  # True if all agents are accessible
            "agents": {
                "agent_name": {
                    "http_status": int,
                    "card_valid": bool,
                    "instance_valid": bool,
                    "error": str or None
                }
            }
        }
    
    Example:
        >>> from pl_analyst.agent import verify_tableau_agents
        >>> status = verify_tableau_agents()
        >>> if status["accessible"]:
        ...     print("All agents ready!")
        ... else:
        ...     print("Some agents failed:", status)
    """
    import requests
    
    agents_to_check = [
        ("tableau_account_research_ds_agent", tableau_account_research_ds_agent),
        ("tableau_order_dispatch_revenue_ds_agent", tableau_order_dispatch_revenue_ds_agent),
        ("tableau_ops_metrics_ds_agent", tableau_ops_metrics_ds_agent),
    ]
    
    results = {
        "accessible": True,
        "agents": {},
    }
    
    for agent_name, agent_instance in agents_to_check:
        agent_status = {
            "http_status": None,
            "card_valid": False,
            "instance_valid": False,
            "error": None,
        }
        
        try:
            # Check agent instance
            if hasattr(agent_instance, 'name') and hasattr(agent_instance, 'description'):
                agent_status["instance_valid"] = True
            else:
                agent_status["error"] = "Agent instance missing required attributes"
                results["accessible"] = False
            
            # Check HTTP connectivity
            agent_card_url = f"http://localhost:8001/a2a/{agent_name}{AGENT_CARD_WELL_KNOWN_PATH}"
            
            response = requests.get(agent_card_url, timeout=timeout)
            agent_status["http_status"] = response.status_code
            
            if response.status_code == 200:
                card_data = response.json()
                # Validate required fields
                required_fields = ['name', 'description', 'capabilities']
                if all(field in card_data for field in required_fields):
                    agent_status["card_valid"] = True
                else:
                    agent_status["error"] = "Agent card missing required fields"
                    results["accessible"] = False
            else:
                agent_status["error"] = f"HTTP {response.status_code}"
                results["accessible"] = False
        
        except requests.exceptions.RequestException as e:
            agent_status["error"] = f"Connection error: {str(e)}"
            results["accessible"] = False
        except Exception as e:
            agent_status["error"] = str(e)
            results["accessible"] = False
        
        results["agents"][agent_name] = agent_status
    
    return results


def get_tableau_agent_info() -> Dict[str, Dict[str, str]]:
    """
    Get basic information about all Tableau A2A agents.
    
    Returns:
        Dictionary mapping agent names to their properties:
        {
            "agent_name": {
                "name": str,
                "description": str,
                "type": str,
                "agent_card": str
            }
        }
    
    Example:
        >>> from pl_analyst.agent import get_tableau_agent_info
        >>> info = get_tableau_agent_info()
        >>> for name, details in info.items():
        ...     print(f"{name}: {details['description'][:50]}...")
    """
    agents = {
        "tableau_account_research_ds_agent": tableau_account_research_ds_agent,
        "tableau_order_dispatch_revenue_ds_agent": tableau_order_dispatch_revenue_ds_agent,
        "tableau_ops_metrics_ds_agent": tableau_ops_metrics_ds_agent,
    }
    
    info = {}
    for agent_name, agent_instance in agents.items():
        info[agent_name] = {
            "name": getattr(agent_instance, 'name', 'Unknown'),
            "description": getattr(agent_instance, 'description', 'No description'),
            "type": type(agent_instance).__name__,
            "agent_card": f"http://localhost:8001/a2a/{agent_name}{AGENT_CARD_WELL_KNOWN_PATH}",
        }
    
    return info
