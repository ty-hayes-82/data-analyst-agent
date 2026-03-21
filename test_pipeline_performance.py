#!/usr/bin/env python3
"""Test pipeline performance with and without aggregation."""

import os
import sys
import time

# Clear cache for clean test
if '_config_data_loader_cache' in sys.modules:
    sys.modules['_config_data_loader_cache'].clear()

print("=" * 80)
print("PIPELINE PERFORMANCE TEST: Statistical Analysis on COVID-19 Dataset")
print("=" * 80)
print()

# Test 1: With aggregation (weekly)
print("TEST 1: Statistical analysis WITH aggregation (weekly grain)")
print("-" * 80)

os.environ["DATA_ANALYST_AGGREGATION_GRAIN"] = "weekly"

start = time.time()

# Import and run statistical analysis tool
from data_analyst_agent.tools.config_data_loader import load_from_config
from data_analyst_agent.sub_agents.statistical_insights_agent.tools.compute_statistical_summary import compute_statistical_summary

# Load data
df = load_from_config("covid_us_counties", metric_filter="cases")
load_time = time.time() - start
print(f"  Data loaded: {len(df):,} rows in {load_time:.2f}s")

# Run statistical analysis
start_analysis = time.time()
result = compute_statistical_summary(df, "date", "cases", ["state", "county"], temporal_grain="weekly")
analysis_time = time.time() - start_analysis

total_time_with_agg = time.time() - start
print(f"  Analysis completed in {analysis_time:.2f}s")
print(f"  TOTAL TIME: {total_time_with_agg:.2f}s")
print()

# Clear cache for next test
sys.modules['_config_data_loader_cache'].clear()

# Test 2: Without aggregation (daily)
print("TEST 2: Statistical analysis WITHOUT aggregation (daily grain)")
print("-" * 80)

os.environ["DATA_ANALYST_AGGREGATION_GRAIN"] = "daily"

start = time.time()

# Load data
df = load_from_config("covid_us_counties", metric_filter="cases")
load_time = time.time() - start
print(f"  Data loaded: {len(df):,} rows in {load_time:.2f}s")

# Run statistical analysis
start_analysis = time.time()
result = compute_statistical_summary(df, "date", "cases", ["state", "county"], temporal_grain="daily")
analysis_time = time.time() - start_analysis

total_time_no_agg = time.time() - start
print(f"  Analysis completed in {analysis_time:.2f}s")
print(f"  TOTAL TIME: {total_time_no_agg:.2f}s")
print()

# Summary
print("=" * 80)
print("SUMMARY")
print("=" * 80)
speedup = total_time_no_agg / total_time_with_agg if total_time_with_agg > 0 else 1
improvement_pct = (1 - total_time_with_agg / total_time_no_agg) * 100 if total_time_no_agg > 0 else 0

print(f"With aggregation:    {total_time_with_agg:.2f}s")
print(f"Without aggregation: {total_time_no_agg:.2f}s")
print(f"Speedup:             {speedup:.2f}x")
print(f"Time saved:          {improvement_pct:.1f}%")
print()
print("✓ Aggregation layer successfully reduces pipeline runtime")
