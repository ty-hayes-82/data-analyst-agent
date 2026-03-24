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

from pathlib import Path

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
from .utils.timing_utils import TimedAgentWrapper

# Now import ADK agents
from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.sequential_agent import SequentialAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.genai import types
from typing import AsyncGenerator

# Import analysis sub-agents
from .sub_agents.statistical_insights_agent.agent import root_agent as statistical_insights_agent
from .sub_agents.hierarchical_analysis_agent import root_agent as hierarchical_analysis_agent
from .sub_agents.planner_agent.agent import root_agent as planner_agent
from .sub_agents.dynamic_parallel_agent import DynamicParallelAnalysisAgent
from .sub_agents.report_synthesis_agent.agent import root_agent as report_synthesis_agent
from .sub_agents.alert_scoring_agent.agent import root_agent as alert_scoring_coordinator
from .sub_agents.output_persistence_agent import OutputPersistenceAgent
from .sub_agents.validation_csv_fetcher import ValidationCSVFetcher
from .sub_agents.config_csv_fetcher import ConfigCSVFetcher
from .core_agents.loaders import (
    ContractLoader,
    AnalysisContextInitializer,
    DateInitializer,
)
from .core_agents.cli import CLIParameterInjector
from .core_agents.test_mode import TestModeReportSynthesisAgent
from .core_agents.fetchers import UniversalDataFetcher
from .core_agents.alerting import ConditionalAlertScoringAgent
from .core_agents.narrative_gate import create_conditional_narrative_agent
from .core_agents.targets import ParallelDimensionTargetAgent
import os

# Authentication and environment setup is handled by config module


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


# --- Workflow Orchestration ---

# TEST MODE pass-through validation agent (applies sign corrections from contract)


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


# Analysis Pipeline: Sequential workflow for the analysis target
# TEST_MODE uses a simplified synthesis agent; VALIDATION_CSV_MODE and LIVE
# both use the real report_synthesis_agent so the full pipeline runs.
synthesis_agent = TestModeReportSynthesisAgent() if TEST_MODE else report_synthesis_agent

cc_analysis_sub_agents = [
    TimedAgentWrapper(AnalysisContextInitializer()),
    TimedAgentWrapper(planner_agent),
    TimedAgentWrapper(DynamicParallelAnalysisAgent()),
    TimedAgentWrapper(ConditionalAlertScoringAgent(alert_scoring_coordinator)),
    TimedAgentWrapper(create_conditional_narrative_agent()),
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


# Root Agent: Dynamic analyst workflow

from .sub_agents.executive_brief_agent.agent import CrossMetricExecutiveBriefAgent
from .sub_agents.weather_context_agent import root_agent as weather_context_agent


class _OutputDirInitializer(BaseAgent):
    """Sets DATA_ANALYST_OUTPUT_DIR so all agents write to one directory per run."""

    def __init__(self):
        super().__init__(name="output_dir_initializer")

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        import os as _os
        from datetime import datetime as _dt
        from pathlib import Path as _P
        from google.adk.events.event import Event as _Ev
        from google.adk.events.event_actions import EventActions as _EA
        if _os.getenv("DATA_ANALYST_OUTPUT_DIR"):
            print(f"[OutputDir] Already set: {_os.getenv('DATA_ANALYST_OUTPUT_DIR')}")
            yield _Ev(invocation_id=ctx.invocation_id, author=self.name, actions=_EA())
            return
        contract = ctx.session.state.get("dataset_contract")
        ds = getattr(contract, "name", "unknown").replace(" ", "_").lower() if contract else "unknown"
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        preferred_dir = _P("outputs") / ds / ts
        run_dir_path = preferred_dir
        state_delta = {}
        try:
            run_dir_path.mkdir(parents=True, exist_ok=True)
        except PermissionError as exc:
            fallback_dir = (
                _P("outputs")
                / f"user_{_os.getenv('USER', 'node')}"
                / ds
                / ts
            )
            fallback_dir.mkdir(parents=True, exist_ok=True)
            run_dir_path = fallback_dir
            error_msg = (
                f"Permission denied for {preferred_dir}. "
                f"Fell back to {run_dir_path}."
            )
            print(f"[OutputDir] WARNING: {error_msg}")
            state_delta["output_dir_initializer_error"] = error_msg
        run_dir = str(run_dir_path)
        _os.environ["DATA_ANALYST_OUTPUT_DIR"] = run_dir
        print(f"[OutputDir] Set DATA_ANALYST_OUTPUT_DIR={run_dir}")
        state_delta["output_dir"] = run_dir
        yield _Ev(invocation_id=ctx.invocation_id, author=self.name, actions=_EA(
            state_delta=state_delta
        ))

root_sub_agents = [
    TimedAgentWrapper(ContractLoader()),
    TimedAgentWrapper(CLIParameterInjector()),
    TimedAgentWrapper(_OutputDirInitializer()),
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


def _safe_console_str(value: object) -> str:
    """Avoid UnicodeEncodeError on Windows consoles (e.g. cp1252) when printing tool payloads."""
    import sys

    text = str(value)
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        text.encode(enc, errors="strict")
        return text
    except UnicodeEncodeError:
        return text.encode(enc, errors="replace").decode(enc, errors="replace")


async def run_analysis(query: str):
    """Run the complete analysis pipeline for a given query."""
    from google.adk.agents.invocation_context import InvocationContext
    from google.adk.agents.run_config import RunConfig
    from google.adk.sessions.in_memory_session_service import InMemorySessionService
    from config.model_loader import get_agent_model
    import os
    import sys
    import uuid
    import yaml

    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError, AttributeError):
            pass

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
                    print(_safe_console_str(part.text), flush=True)
                if hasattr(part, 'function_call') and part.function_call:
                    print(
                        f"\n[Tool Call] {part.function_call.name}({_safe_console_str(part.function_call.args)})",
                        flush=True,
                    )
                if hasattr(part, 'function_response') and part.function_response:
                    print(
                        f"\n[Tool Result] {part.function_response.name} -> "
                        f"{_safe_console_str(part.function_response.response)}",
                        flush=True,
                    )


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
