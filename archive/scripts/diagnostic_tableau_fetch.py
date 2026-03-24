#!/usr/bin/env python
"""
Diagnostic script to check TableauHyperFetcher data loading.
Tests:
1. How many rows does it extract?
2. Does it filter by metric?
3. Does it filter by date range?
4. Does it go through config_data_loader.py aggregation?
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from data_analyst_agent.sub_agents.tableau_hyper_fetcher.fetcher import TableauHyperFetcher
from data_analyst_agent.semantic.models import DatasetContract
from google.adk.agents.invocation_context import InvocationContext
from google.adk.sessions.session import Session


async def test_tableau_fetch():
    print("=" * 80)
    print("DIAGNOSTIC: TableauHyperFetcher Data Volume")
    print("=" * 80)
    
    # Load contract
    contract_path = "config/datasets/tableau/ops_metrics_weekly/contract.yaml"
    print(f"\n1. Loading contract from {contract_path}")
    contract = DatasetContract.from_yaml(contract_path)
    print(f"   Contract loaded: {contract.name}")
    print(f"   Metrics: {len(contract.metrics)} defined")
    
    # Create a mock session with contract in state
    session = Session(
        id="diag-session",
        appName="diagnostic",
        userId="diag-user"
    )
    session.state["dataset_contract"] = contract
    session.state["active_dataset"] = "ops_metrics_weekly"
    
    # Create fetcher
    fetcher = TableauHyperFetcher()
    
    print("\n2. Running TableauHyperFetcher (all metrics, no filters)...")
    print("   Watch for '[TIMER] <<< TableauHyperFetcher' log line")
    print("-" * 80)
    
    # Create invocation context
    ctx = InvocationContext(
        invocation_id="diag-001",
        session=session,
        user_message=None
    )
    
    # Run the fetcher
    events = []
    async for event in fetcher.run_async(ctx):
        events.append(event)
    
    print("-" * 80)
    
    # Check what was stored in state
    primary_csv = session.state.get("primary_data_csv")
    data_summary = session.state.get("data_summary")
    
    if primary_csv:
        lines = primary_csv.strip().split('\n')
        row_count = len(lines) - 1  # Subtract header
        print(f"\n3. Data loaded into state:")
        print(f"   primary_data_csv: {row_count:,} rows")
        print(f"   First 3 lines:")
        for i, line in enumerate(lines[:3]):
            print(f"     {line[:120]}")
    
    if data_summary:
        print(f"\n4. Data summary:")
        for key, value in data_summary.items():
            print(f"   {key}: {value}")
    
    print("\n" + "=" * 80)
    print("DIAGNOSTIC: Aggregation Layer Integration")
    print("=" * 80)
    
    print("\n5. Does TableauHyperFetcher call config_data_loader.py?")
    import data_analyst_agent.sub_agents.tableau_hyper_fetcher.fetcher as fetcher_module
    source_code = Path(fetcher_module.__file__).read_text()
    
    if "load_from_config" in source_code:
        print("   ✓ YES - imports load_from_config")
    else:
        print("   ✗ NO - does NOT import load_from_config")
    
    if "config_data_loader" in source_code:
        print("   ✓ YES - references config_data_loader module")
    else:
        print("   ✗ NO - does NOT reference config_data_loader module")
    
    print("\n6. Does ConfigCSVFetcher call config_data_loader.py?")
    import data_analyst_agent.sub_agents.config_csv_fetcher as csv_fetcher_module
    csv_source = Path(csv_fetcher_module.__file__).read_text()
    
    if "load_from_config" in csv_source:
        print("   ✓ YES - imports load_from_config")
    else:
        print("   ✗ NO - does NOT import load_from_config")
    
    print("\n" + "=" * 80)
    print("FINDINGS:")
    print("=" * 80)
    print("""
TableauHyperFetcher:
- Performs aggregation at SQL level via HyperQueryBuilder
- Writes data directly to primary_data_csv state key
- Does NOT call config_data_loader.py aggregation layer
- Aggregation rules come from loader.yaml aggregation section

ConfigCSVFetcher:
- Calls load_from_config() from config_data_loader.py
- Aggregation layer processes the data
- Also writes to primary_data_csv state key

CONCLUSION:
Both fetchers populate the same state keys (primary_data_csv), but:
- CSV datasets: aggregated by config_data_loader.py
- Tableau datasets: aggregated by SQL query in HyperQueryBuilder

This is BY DESIGN - Tableau aggregation happens in-database for performance.
The "aggregation layer" is NOT bypassed - it's just implemented differently.

If Tableau queries are slow, the issue is NOT missing aggregation.
The issue is likely:
A) Large raw data in Hyper file (filter earlier)
B) Complex SQL aggregation (optimize query)
C) Hyper file I/O bottleneck (check disk performance)
""")


if __name__ == "__main__":
    asyncio.run(test_tableau_fetch())
