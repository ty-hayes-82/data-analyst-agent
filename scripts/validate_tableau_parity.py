import argparse
import asyncio
import json
import os
import sys
import urllib.request
from io import StringIO
from pathlib import Path
from typing import Dict, Any, List, Optional

import pandas as pd

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from data_analyst_agent.sub_agents.tableau_hyper_fetcher.fetcher import TableauHyperFetcher
from google.adk.agents.invocation_context import InvocationContext, Session
from config.dataset_resolver import clear_dataset_cache, get_dataset_path
from data_analyst_agent.semantic.models import DatasetContract

A2A_BASE_URL = os.environ.get("A2A_BASE_URL", "http://localhost:8001")

AGENT_MAPPING = {
    "ops_metrics": "tableau_ops_metrics_ds_agent",
    "account_research": "tableau_account_research_ds_agent",
    "order_dispatch": "tableau_order_dispatch_revenue_ds_agent"
}

# --- Mocking ADK for local fetch ---
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

# --- A2A Fetching ---
def _send_a2a_message(agent_name: str, text: str, timeout: int = 180) -> dict:
    url = f"{A2A_BASE_URL}/a2a/{agent_name}"
    import uuid
    payload = {
        "jsonrpc": "2.0",
        "method": "message/send",
        "params": {
            "message": {
                "messageId": str(uuid.uuid4()),
                "role": "user", 
                "parts": [{"text": text}]
            },
            "metadata": {"session_id": f"parity-test-{agent_name}"}
        },
        "id": 1
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as e:
        print(f"ERROR: A2A request failed for {agent_name}: {e}")
        return {}

async def fetch_a2a(dataset_name: str, date_start: str, date_end: str) -> pd.DataFrame:
    agent_name = AGENT_MAPPING.get(dataset_name)
    if not agent_name:
        raise ValueError(f"No A2A agent mapped for dataset {dataset_name}")

    # Build a command for the agent to export bulk data
    # Note: Using the specific command that test_011 uses.
    prompt = f"Call export_bulk_data_tool with no filters, output_format='csv'."
    if date_start and date_end:
        # A2A often uses year_start, month_start, etc.
        # But for simplicity, we'll try to just tell it the dates.
        prompt = f"Call export_bulk_data_tool with date_start='{date_start}', date_end='{date_end}', output_format='csv'."

    print(f" [A2A] Requesting data for {dataset_name} ({agent_name})...")
    resp = _send_a2a_message(agent_name, prompt)
    
    # A2A responses are usually complex. We need to find the CSV in events.
    events = resp.get("result", {}).get("events", [])
    for event in events:
        delta = event.get("actions", {}).get("state_delta", {})
        if "primary_data_csv" in delta and delta["primary_data_csv"]:
            return pd.read_csv(StringIO(delta["primary_data_csv"]))
    
    print(f" [A2A] No CSV data found in response for {dataset_name}.")
    return pd.DataFrame()

async def fetch_hyper(dataset_name: str, date_start: str, date_end: str) -> pd.DataFrame:
    print(f" [HYPER] Fetching data for {dataset_name} locally...")
    os.environ["ACTIVE_DATASET"] = dataset_name
    clear_dataset_cache()
    
    contract_path = get_dataset_path("contract.yaml")
    contract = DatasetContract.from_yaml(contract_path)
    
    # Force the contract to use tableau_hyper for this fetch
    contract.data_source.type = "tableau_hyper"

    state = {
        "dataset_contract": contract,
        "active_dataset": dataset_name,
        "primary_query_start_date": date_start,
        "primary_query_end_date": date_end,
        "request_analysis": {
            "primary_dimension": "total",
            "primary_dimension_value": "total"
        }
    }
    
    agent = TableauHyperFetcher()
    ctx = MockContext.create(state, agent)
    csv_data = ""
    async for event in agent.run_async(ctx):
        if event.actions and event.actions.state_delta:
            delta = event.actions.state_delta
            if "primary_data_csv" in delta:
                csv_data = delta["primary_data_csv"]
    
    if not csv_data:
        print(f" [HYPER] No CSV data returned by TableauHyperFetcher.")
        return pd.DataFrame()
    return pd.read_csv(StringIO(csv_data))

def compare_results(df_a2a: pd.DataFrame, df_hyper: pd.DataFrame, dataset_name: str):
    print(f"\n{'='*80}")
    print(f" COMPARISON: {dataset_name}")
    print(f"{'='*80}")
    
    if df_a2a.empty:
        print(" [FAIL] A2A dataframe is empty.")
        return False
    if df_hyper.empty:
        print(" [FAIL] Hyper dataframe is empty.")
        return False

    print(f" A2A rows:   {len(df_a2a)}")
    print(f" Hyper rows: {len(df_hyper)}")
    
    # Compare row counts
    if len(df_a2a) != len(df_hyper):
        print(f" [WARN] Row count mismatch: A2A={len(df_a2a)}, Hyper={len(df_hyper)}")
    else:
        print(" [PASS] Row counts match.")

    # Compare column names (normalized)
    a2a_cols = set(df_a2a.columns)
    hyper_cols = set(df_hyper.columns)
    
    common = a2a_cols.intersection(hyper_cols)
    print(f" Common columns: {len(common)}")
    
    # Pick a metric to sum
    # For ops_metrics, total_revenue. For account_research, amount.
    metric = None
    possible_metrics = ["total_revenue", "amount", "TXFAMT", "ttl_est_rev_amt"]
    for m in possible_metrics:
        if m in common:
            metric = m
            break
    
    if metric:
        sum_a2a = df_a2a[metric].sum()
        sum_hyper = df_hyper[metric].sum()
        diff = abs(sum_a2a - sum_hyper)
        pct = (diff / sum_a2a * 100) if sum_a2a != 0 else 0
        
        print(f" Metric: {metric}")
        print(f"  A2A Sum:   {sum_a2a:,.2f}")
        print(f"  Hyper Sum: {sum_hyper:,.2f}")
        print(f"  Diff:      {diff:,.2f} ({pct:.4f}%)")
        
        if pct < 0.1: # 0.1% tolerance
            print(f" [PASS] Metric sums match within 0.1%")
            return True
        else:
            print(f" [FAIL] Metric sums mismatch beyond 0.1%!")
            return False
    else:
        print(" [WARN] No common metric found to compare sums.")
        print(f" A2A columns: {sorted(list(a2a_cols))}")
        print(f" Hyper columns: {sorted(list(hyper_cols))}")
        return len(df_a2a) == len(df_hyper)

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=str, default="ops_metrics", help="Dataset to validate")
    parser.add_argument("--start", type=str, default="2025-01-01", help="Start date")
    parser.add_argument("--end", type=str, default="2025-02-01", help="End date")
    args = parser.parse_args()

    try:
        df_a2a = await fetch_a2a(args.dataset, args.start, args.end)
        df_hyper = await fetch_hyper(args.dataset, args.start, args.end)
        
        compare_results(df_a2a, df_hyper, args.dataset)
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
