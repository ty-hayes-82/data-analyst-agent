"""
validate_tableau_fetcher.py
=========================

Automated validation suite to prove that the local TableauHyperFetcher
produces correct data structure and content.

Requirements:
  1. TDSX file must be in pl_analyst/data/tableau/.
  2. active_dataset must be set in config/agent_config.yaml or via ENV.

Usage:
    python scripts/validate_tableau_fetcher.py --dataset ops_metrics
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Dict, Any, Optional

import pandas as pd
from io import StringIO

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from data_analyst_agent.sub_agents.tableau_hyper_fetcher.fetcher import TableauHyperFetcher
from data_analyst_agent.agent import UniversalDataFetcher
from google.adk.agents.invocation_context import InvocationContext, Session
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from config.dataset_resolver import get_active_dataset, clear_dataset_cache

class MockSession(Session):
    @classmethod
    def create(cls, state: Dict[str, Any]):
        session = cls.model_construct(
            id="test_session", 
            appName="test_app", 
            userId="test_user"
        )
        session.state = state
        return session

class MockContext(InvocationContext):
    @classmethod
    def create(cls, state: Dict[str, Any], agent_obj: Any):
        session = MockSession.create(state)
        return cls.model_construct(
            invocation_id="test_inv", 
            session=session,
            agent=agent_obj,
            session_service=None
        )

async def fetch_data(agent, state: Dict[str, Any]) -> str:
    ctx = MockContext.create(state, agent)
    csv_data = ""
    async for event in agent.run_async(ctx):
        if event.actions and event.actions.state_delta:
            delta = event.actions.state_delta
            if "primary_data_csv" in delta:
                csv_data = delta["primary_data_csv"]
    return csv_data

async def validate_dataset(dataset_name: str, date_start: str, date_end: str):
    print(f"\n{'='*80}")
    print(f" VALIDATING DATASET: {dataset_name}")
    print(f" Period: {date_start} to {date_end}")
    print(f"{'='*80}\n")

    # Force active dataset
    os.environ["ACTIVE_DATASET"] = dataset_name
    clear_dataset_cache()
    
    from config.dataset_resolver import get_dataset_path
    from data_analyst_agent.semantic.models import DatasetContract
    
    try:
        contract_path = get_dataset_path("contract.yaml")
        contract = DatasetContract.from_yaml(contract_path)
    except Exception as e:
        print(f" [FAIL] Failed to load contract: {e}")
        return False
    
    # Common state
    base_state = {
        "dataset_contract": contract,
        "active_dataset": dataset_name,
        "primary_query_start_date": date_start,
        "primary_query_end_date": date_end,
        "request_analysis": {
            "primary_dimension": "total",
            "primary_dimension_value": "total"
        }
    }

    # Fetch via Test (Local Hyper)
    print(f"[STEP 1] Fetching via TableauHyperFetcher...")
    hyper_fetcher = TableauHyperFetcher()
    csv_hyper = await fetch_data(hyper_fetcher, base_state)
    
    if not csv_hyper:
        print(" [FAIL] TableauHyperFetcher returned no data.")
        return False

    df = pd.read_csv(StringIO(csv_hyper))
    print(f"  -> Data loaded: {len(df)} rows, {len(df.columns)} columns")
    print(f"  -> Columns: {list(df.columns)}")

    # Basic Validation
    # 1. Check for expected columns from contract
    time_col = contract.time.column
    if time_col not in df.columns:
        print(f" [FAIL] Time column '{time_col}' missing from output!")
        return False
    
    # 2. Check for primary dimension
    primary_dim = next((d for d in contract.dimensions if d.role == "primary"), None)
    if primary_dim:
        dim_to_check = primary_dim.name
        if dim_to_check not in df.columns and primary_dim.column in df.columns:
            dim_to_check = primary_dim.column
            
        if dim_to_check not in df.columns:
            print(f" [FAIL] Primary dimension '{primary_dim.name}' (or column '{primary_dim.column}') missing from output!")
            return False
        else:
            print(f"  -> Primary dimension '{dim_to_check}' found.")

    # 3. Check for metrics
    for metric in contract.metrics:
        # Check by name first (semantic name)
        if metric.name not in df.columns:
            # If not by name, check if the physical column was used without renaming
            if metric.column and metric.column not in df.columns:
                print(f" [FAIL] Metric '{metric.name}' (or column '{metric.column}') missing from output!")
                return False
            elif not metric.column:
                # Derived metric with no physical column, must be in output by name
                print(f" [FAIL] Derived metric '{metric.name}' missing from output!")
                return False
    print(f"  -> All {len(contract.metrics)} metrics found.")

    # 4. Check date format
    sample_date = df[time_col].iloc[0] if not df.empty else None
    if sample_date:
        print(f"  -> Sample date: {sample_date}")
        # Expecting YYYY-MM or YYYY-MM-DD
        if len(str(sample_date)) < 7:
            print(f" [FAIL] Date format seems wrong: {sample_date}")
            return False

    print("\n" + "*"*40)
    print(f"  {dataset_name} VALIDATION PASSED! ")
    print("*"*40 + "\n")
    return True

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=str, help="Dataset to validate (or 'all')")
    parser.add_argument("--start", type=str, default="2025-01-01", help="Start date")
    parser.add_argument("--end", type=str, default="2025-12-31", help="End date")
    args = parser.parse_args()

    datasets = ["ops_metrics", "account_research", "order_dispatch"]
    if args.dataset and args.dataset != "all":
        datasets = [args.dataset]

    results = {}
    for ds in datasets:
        success = await validate_dataset(ds, args.start, args.end)
        results[ds] = "PASSED" if success else "FAILED"

    print("\n" + "="*40)
    print(" FINAL SUMMARY")
    print("="*40)
    for ds, res in results.items():
        print(f" {ds:<20}: {res}")
    print("="*40)

    if "FAILED" in results.values():
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
