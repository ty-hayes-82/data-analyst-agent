#!/usr/bin/env python3
"""Test dimension aggregation on covid_us_counties dataset."""

import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from data_analyst_agent.tools.config_data_loader import load_from_config


def test_national_level():
    """Test national-level aggregation (no filters)."""
    print("\n" + "="*80)
    print("TEST 1: National-level (no dimension filters)")
    print("="*80)
    
    # Enable aggregation
    os.environ["DATA_ANALYST_AGGREGATION_GRAIN"] = "weekly"
    
    # Load with no dimension filters → should aggregate county → state
    df = load_from_config("covid_us_counties", metric_filter="cases")
    
    print(f"\nResult shape: {df.shape}")
    print(f"Columns: {df.columns.tolist()}")
    print(f"\nFirst few rows:")
    print(df.head(10))
    
    # Check if county column is present (it should be removed after aggregation)
    has_county = "county" in df.columns
    has_state = "state" in df.columns
    
    print(f"\nHas county column: {has_county} (should be False)")
    print(f"Has state column: {has_state} (should be True)")
    
    if has_state and "date" in df.columns:
        print(f"Unique states: {df['state'].nunique()}")
        print(f"Unique dates: {df['date'].nunique()}")
        print(f"Expected rows: ~{df['state'].nunique() * df['date'].nunique()}")
    
    return df


def test_state_level():
    """Test state-level aggregation (filter by state)."""
    print("\n" + "="*80)
    print("TEST 2: State-level (filter state=California)")
    print("="*80)
    
    os.environ["DATA_ANALYST_AGGREGATION_GRAIN"] = "weekly"
    
    # Load with state filter → should still aggregate county → state for California
    df = load_from_config(
        "covid_us_counties",
        dimension_filters={"state": "California"},
        metric_filter="cases"
    )
    
    print(f"\nResult shape: {df.shape}")
    print(f"Columns: {df.columns.tolist()}")
    print(f"\nFirst few rows:")
    print(df.head(10))
    
    has_county = "county" in df.columns
    has_state = "state" in df.columns
    
    print(f"\nHas county column: {has_county} (should be False)")
    print(f"Has state column: {has_state} (should be True)")
    
    if has_state:
        print(f"Unique states: {df['state'].nunique()} (should be 1)")
        print(f"State values: {df['state'].unique()}")
    
    return df


def test_county_level():
    """Test county-level (filter by county)."""
    print("\n" + "="*80)
    print("TEST 3: County-level (filter county=Los Angeles)")
    print("="*80)
    
    os.environ["DATA_ANALYST_AGGREGATION_GRAIN"] = "weekly"
    
    # Load with county filter → should NOT aggregate (already at leaf level)
    df = load_from_config(
        "covid_us_counties",
        dimension_filters={"county": "Los Angeles", "state": "California"},
        metric_filter="cases"
    )
    
    print(f"\nResult shape: {df.shape}")
    print(f"Columns: {df.columns.tolist()}")
    print(f"\nFirst few rows:")
    print(df.head(10))
    
    has_county = "county" in df.columns
    has_state = "state" in df.columns
    
    print(f"\nHas county column: {has_county} (should be True)")
    print(f"Has state column: {has_state} (should be True)")
    
    if has_county:
        print(f"Unique counties: {df['county'].nunique()} (should be 1)")
        print(f"County values: {df['county'].unique()}")
    
    return df


if __name__ == "__main__":
    try:
        df1 = test_national_level()
        df2 = test_state_level()
        df3 = test_county_level()
        
        print("\n" + "="*80)
        print("SUMMARY")
        print("="*80)
        print(f"National level rows: {len(df1):,}")
        print(f"State level rows (CA): {len(df2):,}")
        print(f"County level rows (LA): {len(df3):,}")
        print("\nAll tests completed successfully!")
        
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
