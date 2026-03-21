#!/usr/bin/env python3
"""Test dimension aggregation integration with config_data_loader."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# Test 1: No dimension filter (should aggregate to state level)
print("="*80)
print("TEST 1: No dimension filters (national level)")
print("="*80)

from data_analyst_agent.tools import config_data_loader

# Clear cache
if hasattr(config_data_loader, '_cache'):
    config_data_loader._cache.clear()

# Enable weekly aggregation
os.environ["DATA_ANALYST_AGGREGATION_GRAIN"] = "weekly"

# Monkey-patch to add debug logging
original_aggregate_dimensional = config_data_loader._aggregate_dimensional_grain

def debug_aggregate_dimensional(df, contract, dimension_filters):
    print(f"\n[DEBUG] _aggregate_dimensional_grain called:")
    print(f"  Input rows: {len(df):,}")
    print(f"  Dimension filters: {dimension_filters}")
    print(f"  Has hierarchies: {bool(contract.hierarchies)}")
    if contract.hierarchies:
        for h in contract.hierarchies:
            print(f"    Hierarchy: {h.name}, children: {h.children}")
    
    result = original_aggregate_dimensional(df, contract, dimension_filters)
    
    print(f"  Output rows: {len(result):,}")
    print(f"  Output columns: {list(result.columns)}")
    
    return result

config_data_loader._aggregate_dimensional_grain = debug_aggregate_dimensional

# Load data
df = config_data_loader.load_from_config(
    "covid_us_counties",
    dimension_filters={},  # No filters
    metric_filter="cases"
)

print(f"\n[RESULT] Final DataFrame shape: {df.shape}")
print(f"[RESULT] Has county column: {'county' in df.columns}")
print(f"[RESULT] Has state column: {'state' in df.columns}")

if 'state' in df.columns and 'date' in df.columns:
    print(f"[RESULT] Unique states: {df['state'].nunique()}")
    print(f"[RESULT] Unique dates: {df['date'].nunique()}")
    print(f"[RESULT] Total rows: {len(df):,}")
