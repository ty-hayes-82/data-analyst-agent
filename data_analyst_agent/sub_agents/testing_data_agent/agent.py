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
Testing Data Agent - Loads data from CSV files for testing multiple datasets.
"""

import json
import pandas as pd
import os
from pathlib import Path
from typing import AsyncGenerator

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.genai.types import Content, Part

# Import shared data cache
from ..data_cache import set_validated_csv, set_supplementary_data_csv
from ...tools.validation_data_loader import load_validation_data


class TestingDataAgent(BaseAgent):
    """
    Testing data agent that loads data from CSV files based on the selected contract.
    """
    
    def __init__(self, csv_file_path: str = "data/PL-067-REVENUE-ONLY.csv"):
        super().__init__(name="testing_data_agent")
        self._csv_file_path = csv_file_path
        
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        """Load data from CSV and format for analysis pipeline based on contract."""
        print(f"\n{'='*80}")
        print(f"[TestingDataAgent] Starting _run_async_impl")
        print(f"[TestingDataAgent] analysis_target in state: {ctx.session.state.get('current_analysis_target')}")
        print(f"{'='*80}\n")
        
        # Get context from session state
        analysis_target = (
            ctx.session.state.get("current_analysis_target", "067")
        )
        pl_query_start_date = ctx.session.state.get("primary_query_start_date", "2024-01-01")
        pl_query_end_date = ctx.session.state.get("primary_query_end_date", "2025-12-31")
        
        # Get selected contract to determine which CSV to load
        contract = ctx.session.state.get("dataset_contract")
        contract_name = contract.name if contract else "P&L Dataset"
        target_label = getattr(contract, "target_label", "Analysis Target") if contract else "Analysis Target"
        
        # Validation Ops uses its own wide-to-long ETL loader; short-circuit here
        # before the generic CSV loading path which uses a comma separator.
        if contract_name == "Validation Ops":
            # Read optional env-var overrides set by --metric / --exclude-partial-week CLI flags
            _metric_env = os.environ.get("DATA_ANALYST_METRIC_FILTER", "").strip()
            _metric_filter: "str | None" = _metric_env if _metric_env else None
            _exclude_partial = (
                os.environ.get("DATA_ANALYST_EXCLUDE_PARTIAL_WEEK", "false").lower() == "true"
            )

            print(f"\n{'='*80}")
            print(f"[TestingDataAgent] Loading data for contract: {contract_name}")
            print(f"  Source             : data/validation_data.csv (wide-to-long ETL)")
            print(f"  metric_filter      : {_metric_filter or '(all)'}")
            print(f"  exclude_partial_wk : {_exclude_partial}")
            print(f"{'='*80}\n")
            try:
                req_analysis = ctx.session.state.get("request_analysis", {})
                if isinstance(req_analysis, str):
                    import json as _json
                    try:
                        req_analysis = _json.loads(req_analysis)
                    except Exception:
                        req_analysis = {}

                primary_dim = req_analysis.get("primary_dimension", "terminal")
                primary_val = req_analysis.get("primary_dimension_value") or analysis_target

                # Values that mean "no specific filter — load everything"
                _UNFILTERED = {"067", "unknown", "all", "total", "none", ""}

                # Route the extracted value to the correct filter dimension.
                # Avoid double-filtering (e.g. passing "Central" as both region AND terminal).
                if primary_dim == "region":
                    region_val = primary_val if str(primary_val).lower() not in _UNFILTERED else None
                    terminal_val = None
                elif primary_dim == "terminal":
                    region_val = None
                    terminal_val = primary_val if str(primary_val).lower() not in _UNFILTERED else None
                else:
                    region_val = None
                    terminal_val = None

                final_df = load_validation_data(
                    region_filter=region_val,
                    terminal_filter=terminal_val,
                    metric_filter=_metric_filter,
                    exclude_partial_week=_exclude_partial,
                )

                csv_data = final_df.to_csv(index=False)
                set_validated_csv(csv_data)

                state_delta = {
                    "primary_data_csv": csv_data,
                    "validated_pl_data_csv": csv_data,
                    "data_summary": {
                        "total_rows": len(final_df),
                        "terminals": int(final_df["terminal"].nunique()),
                        "metrics": int(final_df["metric"].nunique()),
                        "weeks": int(final_df["week_ending"].nunique()),
                        "metric_filter": _metric_filter or "(all)",
                        "exclude_partial_week": _exclude_partial,
                    },
                }
                message = (
                    f"[TestingDataAgent] Loaded {len(final_df):,} rows from Validation Ops "
                    f"({final_df['terminal'].nunique()} terminals, "
                    f"{final_df['metric'].nunique()} metrics, "
                    f"{final_df['week_ending'].nunique()} weeks"
                    + (f", metric_filter={_metric_filter}" if _metric_filter else "")
                    + (", partial week excluded" if _exclude_partial else "")
                    + ")."
                )
                print(f"[TestingDataAgent] {message}")
                yield Event(
                    invocation_id=ctx.invocation_id,
                    author=self.name,
                    content=Content(role="model", parts=[Part(text=message)]),
                    actions=EventActions(state_delta=state_delta),
                )
            except Exception as e:
                print(f"[TestingDataAgent] ERROR loading Validation Ops data: {e}")
                import traceback
                traceback.print_exc()
                yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=EventActions())
            return

        # Determine CSV file based on contract
        csv_file = self._csv_file_path
        if contract_name == "Ops Metrics":
            # Check if we are doing LOB analysis
            primary_dim = ctx.session.state.get("request_analysis", {}).get("primary_dimension", "dimension_value")
            if primary_dim == "lob" or analysis_target == "Line Haul":
                csv_file = "data/ops_metrics_line_haul_sample.csv"
            else:
                csv_file = "data/ops_metrics_067_sample.csv"
        elif contract_name == "Order Dispatch Revenue":
            csv_file = "data/order_dispatch_067_sample.csv"
        else:
            # Default to P&L
            csv_file = "data/PL-067-REVENUE-ONLY.csv"

        print(f"\n{'='*80}")
        print(f"[TestingDataAgent] Loading data for contract: {contract_name}")
        print(f"  CSV File: {csv_file}")
        print(f"  {target_label}: {analysis_target}")
        print(f"{'='*80}\n")
        
        try:
            # Resolve absolute path
            abs_path = os.path.abspath(csv_file)
            print(f"[TestingDataAgent] Initial abs_path: {abs_path}")
            if not os.path.exists(abs_path):
                # Try relative to project root
                project_root = Path(__file__).parent.parent.parent.parent
                abs_path = str(project_root / csv_file)
                print(f"[TestingDataAgent] Project-relative abs_path: {abs_path}")
                
            if not os.path.exists(abs_path):
                error_msg = f"CSV file not found at {abs_path}"
                print(f"[TestingDataAgent] ERROR: {error_msg}")
                yield Event(
                    invocation_id=ctx.invocation_id,
                    author=self.name,
                    content=Content(role="model", parts=[Part(text=error_msg)]),
                    actions=EventActions(state_delta={"primary_data_csv": "", "supplementary_data_csv": ""})
                )
                return

            # Load data
            df = pd.read_csv(abs_path)
            
            if contract_name == "Account Research" or contract_name == "P&L Dataset":
                # Process P&L data (wide to long)
                period_cols = [c for c in df.columns if "202" in c and "-" in c]
                id_cols = [c for c in df.columns if c not in period_cols]
                
                melted = df.melt(id_vars=id_cols, value_vars=period_cols, var_name="period_raw", value_name="amount")
                melted["period"] = melted["period_raw"].str.replace(" ", "")
                
                # Clean amount
                melted["amount"] = melted["amount"].astype(str).str.replace(",", "").str.replace('"', "")
                melted["amount"] = pd.to_numeric(melted["amount"], errors="coerce").fillna(0)
                
                # Rename columns
                melted = melted.rename(columns={"Account Nbr": "gl_account", "CTDESC": "account_name"})
                melted["dimension_value"] = str(analysis_target)
                
                # Filter
                target_cc_str = str(analysis_target).lstrip("0")
                melted["_dim_temp"] = melted["dimension_value"].astype(str).str.lstrip("0")
                final_df = melted[melted["_dim_temp"] == target_cc_str].copy().drop(columns=["_dim_temp"])
                
                # Cache
                pl_csv = final_df.to_csv(index=False)
                set_validated_csv(pl_csv)
                
                state_delta = {
                    "primary_data_csv": pl_csv,
                    "validated_pl_data_csv": pl_csv,
                    "data_summary": {
                        "pl_rows": len(final_df),
                        "pl_accounts": final_df["gl_account"].nunique()
                    }
                }
                message = f"[TestingDataAgent] Loaded {len(final_df)} records for {target_label} {analysis_target}."
            else:
                # Generic processing for Ops/Order data (already long format)
                primary_dim = ctx.session.state.get("request_analysis", {}).get("primary_dimension", "dimension_value")
                primary_val = ctx.session.state.get("request_analysis", {}).get("primary_dimension_value", analysis_target)
                
                if primary_dim == "lob" or primary_val == "Line Haul":
                    lob_col = next((c for c in df.columns if "lob" in c.lower() or "ln_of_bus" in c.lower()), None)
                    if lob_col:
                        final_df = df[df[lob_col].astype(str).str.lower() == str(primary_val).lower()].copy()
                    else:
                        final_df = df.copy()
                else:
                    cc_col = next((c for c in df.columns if "dimension_value" in c.lower() or "cst_ctr" in c.lower() or "icc_cst_ctr_cd" in c.lower()), None)
                    if cc_col:
                        target_cc_str = str(analysis_target).lstrip("0")
                        df["_cc_temp"] = df[cc_col].astype(str).str.lstrip("0")
                        final_df = df[df["_cc_temp"] == target_cc_str].copy().drop(columns=["_cc_temp"])
                    else:
                        final_df = df.copy()
                    
                # Cache
                csv_data = final_df.to_csv(index=False)
                if contract_name == "Ops Metrics":
                    set_supplementary_data_csv(csv_data)
                    state_delta = {
                        "supplementary_data_csv": csv_data,
                        "primary_data_csv": csv_data, # Use as pl_data for common analysis tools
                        "validated_pl_data_csv": csv_data
                    }
                else:
                    set_validated_csv(csv_data)
                    state_delta = {"primary_data_csv": csv_data, "validated_pl_data_csv": csv_data}
                    
                state_delta["data_summary"] = {"total_rows": len(final_df)}
                message = f"[TestingDataAgent] Loaded {len(final_df)} records from {contract_name} for {target_label} {analysis_target}."

            print(f"[TestingDataAgent] {message}")
            yield Event(
                invocation_id=ctx.invocation_id,
                author=self.name,
                content=Content(role="model", parts=[Part(text=message)]),
                actions=EventActions(state_delta=state_delta)
            )
            
        except Exception as e:
            print(f"[TestingDataAgent] ERROR: {e}")
            import traceback
            traceback.print_exc()
            yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=EventActions())


# Create singleton instance
root_agent = TestingDataAgent()
