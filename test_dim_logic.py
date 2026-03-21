#!/usr/bin/env python3
"""Unit test for dimension aggregation logic using synthetic data."""

import pandas as pd
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from data_analyst_agent.tools.config_data_loader import _perform_dimension_rollup
from data_analyst_agent.utils.contract_cache import load_contract_cached

# Load the covid contract for hierarchy metadata
contract_path = "config/datasets/csv/covid_us_counties/contract.yaml"
contract = load_contract_cached(contract_path)

# Create synthetic test data
data = {
    'date': ['2020-01-01'] * 6 + ['2020-01-08'] * 6,
    'state': ['CA', 'CA', 'CA', 'NY', 'NY', 'NY'] * 2,
    'county': ['Los Angeles', 'San Diego', 'San Francisco', 'New York', 'Kings', 'Queens'] * 2,
    'cases': [100, 50, 30, 200, 75, 60, 150, 70, 40, 250, 90, 80],
    'deaths': [2, 1, 0, 5, 2, 1, 3, 2, 1, 7, 3, 2]
}

df = pd.DataFrame(data)

print("Input DataFrame:")
print(df)
print(f"\nShape: {df.shape}")
print(f"Unique states: {df['state'].nunique()}")
print(f"Unique counties: {df['county'].nunique()}")

# Test aggregation: county → state
print("\n" + "="*80)
print("Testing aggregation: county → state")
print("="*80)

df_agg = _perform_dimension_rollup(
    df=df.copy(),
    contract=contract,
    parent_dim="state",
    child_dims=["county"],
    hierarchy_name="geographic"
)

print("\nAggregated DataFrame:")
print(df_agg)
print(f"\nShape: {df_agg.shape}")
print(f"Columns: {list(df_agg.columns)}")

if "county" in df_agg.columns:
    print("\n❌ FAIL: county column still present")
else:
    print("\n✅ PASS: county column removed")

if "state" in df_agg.columns:
    print(f"Unique states: {df_agg['state'].nunique()}")
    print(f"Unique dates: {df_agg['date'].nunique()}")
    
    # Verify aggregation is correct (cumulative max for cases/deaths)
    ca_2020_01_01 = df_agg[(df_agg['state'] == 'CA') & (df_agg['date'] == '2020-01-01')]
    if not ca_2020_01_01.empty:
        cases_value = ca_2020_01_01['cases'].values[0]
        deaths_value = ca_2020_01_01['deaths'].values[0]
        
        # For cumulative metrics, we should take MAX (not sum)
        # Los Angeles: 100 cases, San Diego: 50, San Francisco: 30
        # Max should be 100 (not 180)
        print(f"\nCA 2020-01-01 cases: {cases_value} (expected: 100 if max, 180 if sum)")
        print(f"CA 2020-01-01 deaths: {deaths_value} (expected: 2 if max, 3 if sum)")
