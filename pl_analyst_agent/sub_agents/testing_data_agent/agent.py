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
Testing Data Agent - Loads P&L data from CSV file for testing.
Mimics tableau_account_research_ds_agent but uses local CSV file (PL-067.csv).
"""

import json
import pandas as pd
from pathlib import Path
from typing import AsyncGenerator

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.genai.types import Content, Part

# Import shared data cache
from ..data_cache import set_validated_csv, set_ops_metrics_csv


class TestingDataAgent(BaseAgent):
    """
    Testing data agent that loads P&L data from CSV file.
    
    Mimics the behavior of tableau_account_research_ds_agent but reads from
    a local CSV file (data/PL-067.csv) for testing purposes.
    """
    
    def __init__(self, csv_file_path: str = "data/PL-067-REVENUE-ONLY.csv"):
        super().__init__(name="testing_data_agent")
        self._csv_file_path = csv_file_path
        
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        """Load P&L data and ops metrics from CSV and format for analysis pipeline."""
        
        # Get request parameters from state
        cost_center = ctx.session.state.get("current_cost_center", "067")
        pl_query_start_date = ctx.session.state.get("pl_query_start_date", "2024-07")
        pl_query_end_date = ctx.session.state.get("pl_query_end_date", "2025-09")

        # Test-only guardrails: enforce CC and CSV file
        if str(cost_center).lstrip("0") != "67":
            raise ValueError("Test mode is locked to cost center 067. Adjust your request or disable test mode.")
        if not self._csv_file_path.endswith("PL-067-REVENUE-ONLY.csv"):
            self._csv_file_path = "data/PL-067-REVENUE-ONLY.csv"
        
        print(f"\n{'='*80}")
        print(f"[TestingDataAgent] Loading P&L data and ops metrics from CSV")
        print(f"  CSV File: {self._csv_file_path}")
        print(f"  Cost Center: {cost_center}")
        print(f"  Date Range: {pl_query_start_date} to {pl_query_end_date}")
        print(f"{'='*80}\n")
        
        try:
            # Read CSV file
            csv_path = Path(self._csv_file_path)
            if not csv_path.exists():
                # Try relative to project root
                csv_path = Path(__file__).parent.parent.parent.parent / self._csv_file_path
            
            if not csv_path.exists():
                error_msg = f"CSV file not found: {self._csv_file_path}"
                print(f"[TestingDataAgent] ERROR: {error_msg}")
                yield Event(
                    invocation_id=ctx.invocation_id,
                    author=self.name,
                    content=Content(role="model", parts=[Part(text=error_msg)]),
                    actions=EventActions(
                        state_delta={"pl_data_json": "", "ops_metrics_json": ""}
                    )
                )
                return
            
            # Load CSV
            df = pd.read_csv(csv_path)
            
            # Extract period columns (format: "2024 - 07")
            period_cols = [col for col in df.columns if " - " in col and any(char.isdigit() for char in col)]
            
            # Split into P&L data (rows with Account Nbr) and ops metrics (rows without Account Nbr)
            pl_data = df[df["Account Nbr"].notna()].copy()
            ops_data = df[df["Account Nbr"].isna()].copy()
            
            # === Process P&L Data ===
            id_cols = ["DIV", "LOB", "GL_CC", "Account Nbr", "level_1", "level_2", "level_3", "level_4", "CTDESC"]
            
            melted_pl = pl_data.melt(
                id_vars=id_cols,
                value_vars=period_cols,
                var_name="period_raw",
                value_name="amount"
            )
            
            # Clean period format (remove spaces, convert "2024 - 07" to "2024-07")
            melted_pl["period"] = melted_pl["period_raw"].str.replace(" ", "")
            
            # Clean amount (remove commas, convert to float)
            melted_pl["amount"] = melted_pl["amount"].astype(str).str.replace(",", "").str.replace('"', "")
            melted_pl["amount"] = pd.to_numeric(melted_pl["amount"], errors="coerce").fillna(0)
            
            # Filter to requested date range
            melted_pl = melted_pl[
                (melted_pl["period"] >= pl_query_start_date) & 
                (melted_pl["period"] <= pl_query_end_date)
            ]
            
            # Filter to cost center (handle both string and integer cost centers)
            melted_pl["GL_CC_str"] = melted_pl["GL_CC"].astype(str).str.lstrip("0")
            target_cc_str = str(cost_center).lstrip("0")
            melted_pl = melted_pl[melted_pl["GL_CC_str"] == target_cc_str]
            
            # Create CSV output format for P&L data
            output_pl = melted_pl[[
                "period", 
                "Account Nbr", 
                "CTDESC", 
                "amount",
                "level_1",
                "level_2",
                "level_3",
                "level_4"
            ]].copy()
            
            # Rename columns to match expected format
            output_pl = output_pl.rename(columns={
                "Account Nbr": "gl_account",
                "CTDESC": "account_name"
            })
            
            # Create JSON output format for P&L data (matching tableau agent format)
            pl_records = []
            for _, row in output_pl.iterrows():
                pl_records.append({
                    "period": row["period"],
                    "gl_account": row["gl_account"],
                    "account_name": row["account_name"],
                    "amount": float(row["amount"]),
                    "level_1": row["level_1"],
                    "level_2": row["level_2"],
                    "level_3": row["level_3"],
                    "level_4": row["level_4"],
                    "cost_center": str(cost_center)
                })
            
            json_output_pl = json.dumps({"time_series": pl_records}, indent=2)
            
            # === Process Ops Metrics ===
            ops_id_cols = ["DIV", "LOB", "GL_CC", "CTDESC"]
            
            melted_ops = ops_data.melt(
                id_vars=ops_id_cols,
                value_vars=period_cols,
                var_name="period_raw",
                value_name="value"
            )
            
            # Clean period format
            melted_ops["period"] = melted_ops["period_raw"].str.replace(" ", "")
            
            # Clean value (remove commas, convert to float)
            melted_ops["value"] = melted_ops["value"].astype(str).str.replace(",", "").str.replace('"', "")
            melted_ops["value"] = pd.to_numeric(melted_ops["value"], errors="coerce").fillna(0)
            
            # Filter to requested date range
            melted_ops = melted_ops[
                (melted_ops["period"] >= pl_query_start_date) & 
                (melted_ops["period"] <= pl_query_end_date)
            ]
            
            # Filter to cost center
            melted_ops["GL_CC_str"] = melted_ops["GL_CC"].astype(str).str.lstrip("0")
            melted_ops = melted_ops[melted_ops["GL_CC_str"] == target_cc_str]
            
            # Create CSV output format for ops metrics
            output_ops = melted_ops[[
                "period",
                "CTDESC",
                "value"
            ]].copy()
            
            output_ops.columns = ["period", "metric_name", "value"]
            output_ops["cost_center"] = cost_center
            
            # Create JSON output format for ops metrics  
            ops_records = []
            for _, row in output_ops.iterrows():
                ops_records.append({
                    "period": row["period"],
                    "metric_name": row["metric_name"],
                    "value": float(row["value"]),
                    "cost_center": str(cost_center)
                })
            
            json_output_ops = json.dumps({"time_series": ops_records}, indent=2)
            
            # Log summary
            pl_accounts = output_pl["gl_account"].nunique()
            pl_periods = output_pl["period"].nunique()
            pl_rows = len(output_pl)
            
            ops_metrics = output_ops["metric_name"].nunique()
            ops_periods = output_ops["period"].nunique()
            ops_rows = len(output_ops)
            
            print(f"[TestingDataAgent] P&L Data loaded:")
            print(f"  Total rows: {pl_rows}")
            print(f"  Unique accounts: {pl_accounts}")
            print(f"  Unique periods: {pl_periods}")
            if pl_rows > 0:
                print(f"  Period range: {output_pl['period'].min()} to {output_pl['period'].max()}")
            print()
            
            print(f"[TestingDataAgent] Ops Metrics loaded:")
            print(f"  Total rows: {ops_rows}")
            print(f"  Unique metrics: {ops_metrics}")
            print(f"  Unique periods: {ops_periods}")
            if ops_rows > 0:
                print(f"  Period range: {output_ops['period'].min()} to {output_ops['period'].max()}")
            print()
            
            # Store data in session state for efficient access
            # Convert to CSV format for downstream tools
            pl_csv = output_pl.to_csv(index=False)
            ops_csv = output_ops.to_csv(index=False)
            
            # ALSO store in global cache for tool access
            set_validated_csv(pl_csv)
            set_ops_metrics_csv(ops_csv)
            
            # Return concise summary (not full data in conversation history)
            message = f"""[TestingDataAgent] Data loaded and stored in session state.

Summary:
- P&L Data: {pl_rows} records ({pl_accounts} GL accounts x {pl_periods} periods)
  Period range: {output_pl['period'].min()} to {output_pl['period'].max()}
  
- Ops Metrics: {ops_rows} records ({ops_metrics} metrics x {ops_periods} periods)
  Period range: {output_ops['period'].min()} to {output_ops['period'].max()}

Data is ready for validation and analysis."""
            
            yield Event(
                invocation_id=ctx.invocation_id,
                author=self.name,
                content=Content(role="model", parts=[Part(text=message)]),
                actions=EventActions(
                    state_delta={
                        "pl_data_csv": pl_csv,
                        "ops_metrics_csv": ops_csv,
                        "validated_pl_data_csv": pl_csv,  # Also store as validated for direct access by level_analyzer
                        "pl_data_json": json_output_pl,
                        "ops_metrics_json": json_output_ops,
                        "data_summary": {
                            "pl_rows": pl_rows,
                            "pl_accounts": pl_accounts,
                            "pl_periods": pl_periods,
                            "ops_rows": ops_rows,
                            "ops_metrics": ops_metrics,
                            "ops_periods": ops_periods,
                        }
                    }
                )
            )
            
        except Exception as e:
            error_msg = f"Error loading CSV: {str(e)}"
            print(f"[TestingDataAgent] ERROR: {error_msg}")
            import traceback
            traceback.print_exc()
            
            yield Event(
                invocation_id=ctx.invocation_id,
                author=self.name,
                content=Content(role="model", parts=[Part(text=error_msg)]),
                actions=EventActions(
                    state_delta={"pl_data_json": "", "ops_metrics_json": ""}
                )
            )


# Create singleton instance
root_agent = TestingDataAgent()

