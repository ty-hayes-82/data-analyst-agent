#!/usr/bin/env python3
"""
Validate the ops_metrics_weekly validation dataset.
"""

import pandas as pd
from pathlib import Path

DATA_FILE = Path("/data/data-analyst-agent/data/validation/ops_metrics_weekly_validation.csv")

def validate_structure(df):
    """Validate dataset structure matches contract."""
    print("=" * 60)
    print("STRUCTURE VALIDATION")
    print("=" * 60)
    
    required_cols = ['cal_dt', 'gl_rgn_nm', 'gl_div_nm', 'ops_ln_of_bus_nm',
                     'ttl_rev_amt', 'lh_rev_amt', 'fuel_srchrg_rev_amt', 'acsrl_rev_amt',
                     'ordr_cnt', 'ordr_miles', 'truck_count', 'dh_miles']
    
    missing_cols = set(required_cols) - set(df.columns)
    if missing_cols:
        print(f"✗ Missing columns: {missing_cols}")
        return False
    else:
        print(f"✓ All {len(required_cols)} required columns present")
    
    # Check dimensions
    regions = df['gl_rgn_nm'].unique()
    divisions = df['gl_div_nm'].unique()
    business_lines = df['ops_ln_of_bus_nm'].unique()
    
    print(f"✓ Regions: {len(regions)} - {list(regions)}")
    print(f"✓ Divisions: {len(divisions)} - {list(divisions)}")
    print(f"✓ Business Lines: {len(business_lines)} - {list(business_lines)}")
    
    # Check date range
    date_range = pd.to_datetime(df['cal_dt'])
    print(f"✓ Date range: {date_range.min().date()} to {date_range.max().date()} ({len(date_range.unique())} unique days)")
    
    # Check for nulls
    null_counts = df.isnull().sum()
    if null_counts.sum() > 0:
        print(f"✗ Found nulls: {null_counts[null_counts > 0]}")
        return False
    else:
        print(f"✓ No null values")
    
    return True

def inspect_anomalies(df):
    """Inspect each known anomaly to verify it's present."""
    print("\n" + "=" * 60)
    print("ANOMALY INSPECTION")
    print("=" * 60)
    
    # Convert date to datetime for filtering
    df['cal_dt'] = pd.to_datetime(df['cal_dt'])
    
    # Anomaly 1: Revenue Drop (Days 45-48, East)
    print("\n1. Revenue Drop (Feb 15-18, East)")
    baseline_east = df[(df['cal_dt'] >= '2024-02-01') & (df['cal_dt'] < '2024-02-15') & (df['gl_rgn_nm'] == 'East')]
    anomaly1 = df[(df['cal_dt'] >= '2024-02-15') & (df['cal_dt'] <= '2024-02-18') & (df['gl_rgn_nm'] == 'East')]
    
    baseline_rev = baseline_east['ttl_rev_amt'].mean()
    anomaly_rev = anomaly1['ttl_rev_amt'].mean()
    ratio = anomaly_rev / baseline_rev if baseline_rev > 0 else 0
    
    print(f"   Baseline revenue: ${baseline_rev:,.2f}")
    print(f"   Anomaly revenue:  ${anomaly_rev:,.2f}")
    print(f"   Ratio: {ratio:.1%} (expected ~30%)")
    print(f"   ✓ Detected" if 0.25 < ratio < 0.35 else "   ✗ NOT detected")
    
    # Anomaly 2: Deadhead Spike (Days 63-65, East-Northeast)
    print("\n2. Deadhead Spike (Mar 4-6, East-Northeast)")
    baseline_dh = df[(df['cal_dt'] >= '2024-02-26') & (df['cal_dt'] < '2024-03-04') & (df['gl_div_nm'] == 'East-Northeast')]
    baseline_dh = baseline_dh[baseline_dh['cal_dt'].dt.dayofweek < 5]  # Weekdays only for fair comparison
    anomaly2 = df[(df['cal_dt'] >= '2024-03-04') & (df['cal_dt'] <= '2024-03-06') & (df['gl_div_nm'] == 'East-Northeast')]
    
    baseline_miles = baseline_dh['dh_miles'].mean()
    anomaly_miles = anomaly2['dh_miles'].mean()
    ratio = anomaly_miles / baseline_miles if baseline_miles > 0 else 0
    
    print(f"   Baseline deadhead: {baseline_miles:,.1f} miles")
    print(f"   Anomaly deadhead:  {anomaly_miles:,.1f} miles")
    print(f"   Ratio: {ratio:.1f}x (expected ~3.0x)")
    print(f"   ✓ Detected" if 2.5 < ratio < 3.5 else "   ✗ NOT detected")
    
    # Anomaly 3: Sustained Order Drop (Days 70-85, Dedicated)
    print("\n3. Order Volume Drop (Mar 11-26, Dedicated)")
    baseline_orders = df[(df['cal_dt'] >= '2024-03-01') & (df['cal_dt'] < '2024-03-11') & (df['ops_ln_of_bus_nm'] == 'Dedicated')]
    anomaly3 = df[(df['cal_dt'] >= '2024-03-11') & (df['cal_dt'] <= '2024-03-26') & (df['ops_ln_of_bus_nm'] == 'Dedicated')]
    
    baseline_cnt = baseline_orders['ordr_cnt'].mean()
    anomaly_cnt = anomaly3['ordr_cnt'].mean()
    ratio = anomaly_cnt / baseline_cnt if baseline_cnt > 0 else 0
    
    print(f"   Baseline orders: {baseline_cnt:,.1f}")
    print(f"   Anomaly orders:  {anomaly_cnt:,.1f}")
    print(f"   Ratio: {ratio:.1%} (expected ~60%)")
    print(f"   Duration: {len(anomaly3['cal_dt'].unique())} days (expected 16)")
    print(f"   ✓ Detected" if 0.55 < ratio < 0.65 else "   ✗ NOT detected")
    
    # Anomaly 4: Fuel Surcharge Zero (Days 29-34, West)
    print("\n4. Fuel Surcharge Zero (Jan 30 - Feb 4, West)")
    baseline_fuel = df[(df['cal_dt'] >= '2024-01-20') & (df['cal_dt'] < '2024-01-30') & (df['gl_rgn_nm'] == 'West')]
    anomaly4 = df[(df['cal_dt'] >= '2024-01-30') & (df['cal_dt'] <= '2024-02-04') & (df['gl_rgn_nm'] == 'West')]
    
    baseline_fuel_amt = baseline_fuel['fuel_srchrg_rev_amt'].mean()
    anomaly_fuel_amt = anomaly4['fuel_srchrg_rev_amt'].mean()
    
    print(f"   Baseline fuel surcharge: ${baseline_fuel_amt:,.2f}")
    print(f"   Anomaly fuel surcharge:  ${anomaly_fuel_amt:,.2f}")
    print(f"   ✓ Detected" if anomaly_fuel_amt < 100 else "   ✗ NOT detected")
    
    # Anomaly 5: Weekend Spike (Day 54, all regions)
    print("\n5. Weekend Spike (Feb 24, Saturday, all regions)")
    # Get day 54 (Feb 24, 2024)
    target_date = pd.Timestamp('2024-02-24')
    anomaly5 = df[df['cal_dt'] == target_date]
    
    # Compare to other Saturdays
    df['day_of_week'] = df['cal_dt'].dt.dayofweek
    other_saturdays = df[(df['day_of_week'] == 5) & (df['cal_dt'] != target_date)]
    
    anomaly_orders = anomaly5['ordr_cnt'].mean()
    saturday_baseline = other_saturdays['ordr_cnt'].mean()
    ratio = anomaly_orders / saturday_baseline if saturday_baseline > 0 else 0
    
    print(f"   Typical Saturday orders: {saturday_baseline:,.1f}")
    print(f"   Anomaly Saturday orders: {anomaly_orders:,.1f}")
    print(f"   Ratio: {ratio:.1f}x (expected ~2.0x)")
    print(f"   ✓ Detected" if 1.8 < ratio < 2.2 else "   ✗ NOT detected")
    
    # Anomaly 6: Truck Count Drop (Days 55-60, Central-Midwest)
    print("\n6. Truck Count Drop (Feb 25 - Mar 1, Central-Midwest)")
    baseline_trucks = df[(df['cal_dt'] >= '2024-02-15') & (df['cal_dt'] < '2024-02-25') & (df['gl_div_nm'] == 'Central-Midwest')]
    anomaly6 = df[(df['cal_dt'] >= '2024-02-25') & (df['cal_dt'] <= '2024-03-01') & (df['gl_div_nm'] == 'Central-Midwest')]
    
    baseline_truck_cnt = baseline_trucks['truck_count'].mean()
    anomaly_truck_cnt = anomaly6['truck_count'].mean()
    ratio = anomaly_truck_cnt / baseline_truck_cnt if baseline_truck_cnt > 0 else 0
    
    print(f"   Baseline trucks: {baseline_truck_cnt:,.1f}")
    print(f"   Anomaly trucks:  {anomaly_truck_cnt:,.1f}")
    print(f"   Ratio: {ratio:.1%} (expected ~75%)")
    print(f"   ✓ Detected" if 0.70 < ratio < 0.80 else "   ✗ NOT detected")

def main():
    """Main validation."""
    
    print("\n" + "=" * 60)
    print("VALIDATION DATASET CHECK")
    print("=" * 60)
    print(f"File: {DATA_FILE}")
    
    # Load dataset
    if not DATA_FILE.exists():
        print(f"✗ File not found: {DATA_FILE}")
        return False
    
    df = pd.read_csv(DATA_FILE)
    print(f"✓ Loaded {len(df)} rows, {len(df.columns)} columns")
    
    # Run validations
    structure_valid = validate_structure(df)
    
    if structure_valid:
        inspect_anomalies(df)
    
    print("\n" + "=" * 60)
    print("VALIDATION COMPLETE")
    print("=" * 60)
    
    return structure_valid

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
