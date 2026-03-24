#!/usr/bin/env python3
"""Quick test of dimension aggregation logic."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from data_analyst_agent.tools.config_data_loader import load_from_config

# Enable aggregation
os.environ["DATA_ANALYST_AGGREGATION_GRAIN"] = "weekly"

print("Loading covid_us_counties with state filter (should aggregate county→state)...")
df = load_from_config(
    "covid_us_counties",
    dimension_filters={"state": "California"},
    metric_filter="cases"
)

print(f"\nShape: {df.shape}")
print(f"Columns: {list(df.columns)}")
print(f"\nSample:")
print(df.head())

if "county" in df.columns:
    print(f"\n❌ FAIL: county column still present (not aggregated)")
    print(f"Unique counties: {df['county'].nunique()}")
else:
    print(f"\n✅ PASS: county column removed (aggregated to state level)")

if "state" in df.columns:
    print(f"Unique states: {df['state'].nunique()}")
    print(f"State value: {df['state'].unique()}")
