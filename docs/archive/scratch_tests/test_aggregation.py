#!/usr/bin/env python3
"""Quick test of intelligent data aggregation."""

import os
import time
import pandas as pd
from data_analyst_agent.tools.config_data_loader import load_from_config

# Clear the cache to force fresh load
import sys
if '_config_data_loader_cache' in sys.modules:
    sys.modules['_config_data_loader_cache'].clear()

# Test 1: Load covid data without aggregation (baseline)
print("=" * 70)
print("TEST 1: Load covid_us_counties without aggregation")
print("=" * 70)

# Temporarily disable aggregation to get baseline
os.environ["DATA_ANALYST_AGGREGATION_GRAIN"] = "daily"

start = time.time()
df_no_agg = load_from_config("covid_us_counties")
elapsed_no_agg = time.time() - start

print(f"Rows loaded: {len(df_no_agg):,}")
print(f"Time: {elapsed_no_agg:.2f}s")
print(f"Columns: {list(df_no_agg.columns)}")
print(f"Sample data:\n{df_no_agg.head()}")
print()

# Test 2: Load with weekly aggregation
print("=" * 70)
print("TEST 2: Load covid_us_counties WITH weekly aggregation")
print("=" * 70)

os.environ["DATA_ANALYST_AGGREGATION_GRAIN"] = "weekly"

start = time.time()
df_with_agg = load_from_config("covid_us_counties")
elapsed_with_agg = time.time() - start

print(f"Rows loaded: {len(df_with_agg):,}")
print(f"Time: {elapsed_with_agg:.2f}s")
print(f"Reduction: {(1 - len(df_with_agg) / len(df_no_agg)) * 100:.1f}%")
print(f"Columns: {list(df_with_agg.columns)}")
print(f"Sample data:\n{df_with_agg.head()}")
print()

# Test 3: Verify metrics are correctly aggregated
print("=" * 70)
print("TEST 3: Verify aggregation correctness")
print("=" * 70)

# Get one state's data from both datasets
state_filter = {"state": "California"}

df_no_agg_ca = df_no_agg[df_no_agg["state"] == "California"].copy()
df_with_agg_ca = df_with_agg[df_with_agg["state"] == "California"].copy()

print(f"California - No aggregation: {len(df_no_agg_ca):,} rows")
print(f"California - With aggregation: {len(df_with_agg_ca):,} rows")

# Check total cases sum (should be similar for cumulative data)
if "cases" in df_no_agg_ca.columns:
    # For COVID data, we're dealing with CUMULATIVE values
    # So we should compare max values, not sums
    # Convert to numeric first (data might be strings)
    df_no_agg_ca["cases"] = pd.to_numeric(df_no_agg_ca["cases"], errors="coerce")
    df_with_agg_ca["cases"] = pd.to_numeric(df_with_agg_ca["cases"], errors="coerce")
    
    max_cases_no_agg = df_no_agg_ca["cases"].max()
    max_cases_with_agg = df_with_agg_ca["cases"].max()
    
    print(f"Max cumulative cases (no agg): {max_cases_no_agg:,.0f}")
    print(f"Max cumulative cases (with agg): {max_cases_with_agg:,.0f}")
    print(f"Difference: {abs(max_cases_no_agg - max_cases_with_agg):,.0f}")

print()
print("=" * 70)
print("SUMMARY")
print("=" * 70)
print(f"Aggregation reduced rows by: {(1 - len(df_with_agg) / len(df_no_agg)) * 100:.1f}%")
print(f"Load time improvement: {((elapsed_no_agg - elapsed_with_agg) / elapsed_no_agg * 100):.1f}%")
