#!/usr/bin/env python3
"""
Generate synthetic validation dataset for ops_metrics_weekly with embedded known anomalies.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path

# Set random seed for reproducibility
np.random.seed(42)

# Configuration
START_DATE = datetime(2024, 1, 1)
NUM_DAYS = 90
OUTPUT_DIR = Path("/data/data-analyst-agent/data/validation")
OUTPUT_FILE = OUTPUT_DIR / "ops_metrics_weekly_validation.csv"

# Dimension structure
REGIONS = ["East", "Central", "West"]
DIVISIONS = {
    "East": ["East-Northeast", "East-Southeast"],
    "Central": ["Central-Midwest", "Central-South"],
    "West": ["West-Mountain", "West-Pacific"]
}
BUSINESS_LINES = ["Dedicated", "Regional"]

# Baseline values (realistic daily averages per region-division-business_line combo)
BASELINE = {
    "ttl_rev_amt": {"mean": 120000, "std": 15000},
    "lh_rev_amt": {"mean": 70000, "std": 8000},
    "fuel_srchrg_rev_amt": {"mean": 30000, "std": 3000},
    "acsrl_rev_amt": {"mean": 20000, "std": 2500},
    "ordr_cnt": {"mean": 250, "std": 30},
    "ordr_miles": {"mean": 15000, "std": 2000},
    "truck_count": {"mean": 80, "std": 5},
    "dh_miles": {"mean": 3000, "std": 400}
}

def generate_baseline_value(metric, day_of_week, noise_factor=0.1):
    """Generate baseline value with weekly pattern and noise."""
    base_mean = BASELINE[metric]["mean"]
    base_std = BASELINE[metric]["std"]
    
    # Weekend reduction (Saturday=5, Sunday=6)
    weekend_factor = 0.6 if day_of_week in [5, 6] else 1.0
    
    # Add noise
    noise = np.random.normal(0, base_std * noise_factor)
    value = base_mean * weekend_factor + noise
    
    return max(0, value)

def apply_anomalies(df):
    """Embed the 6 known anomalies into the dataset."""
    
    # Anomaly 1: Revenue Drop (Days 45-48, East region)
    mask1 = (df['day_num'] >= 45) & (df['day_num'] <= 48) & (df['gl_rgn_nm'] == 'East')
    df.loc[mask1, 'ttl_rev_amt'] *= 0.30
    df.loc[mask1, 'lh_rev_amt'] *= 0.30
    df.loc[mask1, 'fuel_srchrg_rev_amt'] *= 0.30
    df.loc[mask1, 'acsrl_rev_amt'] *= 0.30
    print(f"Anomaly 1 applied: {mask1.sum()} rows affected (Revenue Drop)")
    
    # Anomaly 2: Spike in Deadhead Miles (Days 63-65, East-Northeast division)
    # Days 63-65 = March 4-6 (Mon-Wed) - weekdays for consistent 3x effect
    mask2 = (df['day_num'] >= 63) & (df['day_num'] <= 65) & (df['gl_div_nm'] == 'East-Northeast')
    df.loc[mask2, 'dh_miles'] *= 3.0
    print(f"Anomaly 2 applied: {mask2.sum()} rows affected (Deadhead Spike)")
    
    # Anomaly 3: Sustained Order Volume Drop (Days 70-85, Dedicated business line)
    mask3 = (df['day_num'] >= 70) & (df['day_num'] <= 85) & (df['ops_ln_of_bus_nm'] == 'Dedicated')
    df.loc[mask3, 'ordr_cnt'] *= 0.60
    df.loc[mask3, 'ttl_rev_amt'] *= 0.60
    df.loc[mask3, 'lh_rev_amt'] *= 0.60
    df.loc[mask3, 'fuel_srchrg_rev_amt'] *= 0.60
    df.loc[mask3, 'acsrl_rev_amt'] *= 0.60
    print(f"Anomaly 3 applied: {mask3.sum()} rows affected (Order Volume Drop)")
    
    # Anomaly 4: Fuel Surcharge Anomaly (Days 29-34, West region)
    # Days 29-34 = Jan 30 - Feb 4 (6 days)
    mask4 = (df['day_num'] >= 29) & (df['day_num'] <= 34) & (df['gl_rgn_nm'] == 'West')
    original_fuel = df.loc[mask4, 'fuel_srchrg_rev_amt'].copy()
    df.loc[mask4, 'fuel_srchrg_rev_amt'] = 0
    # Adjust total revenue to reflect missing fuel surcharge
    df.loc[mask4, 'ttl_rev_amt'] -= original_fuel
    print(f"Anomaly 4 applied: {mask4.sum()} rows affected (Fuel Surcharge Zero)")
    
    # Anomaly 5: Weekend Spike (Day 50, Saturday, all regions)
    # Day 50 from Jan 1, 2024 is Feb 19, 2024 - need to check if it's Saturday
    target_date = START_DATE + timedelta(days=49)  # 0-indexed
    if target_date.weekday() != 5:  # Adjust to next Saturday
        days_to_saturday = (5 - target_date.weekday()) % 7
        target_day = 49 + days_to_saturday
    else:
        target_day = 49
    
    mask5 = (df['day_num'] == target_day)
    df.loc[mask5, 'ordr_cnt'] *= 2.0
    print(f"Anomaly 5 applied: {mask5.sum()} rows affected (Weekend Spike, day {target_day})")
    
    # Anomaly 6: Truck Count Drop (Days 55-60, Central-Midwest division)
    mask6 = (df['day_num'] >= 55) & (df['day_num'] <= 60) & (df['gl_div_nm'] == 'Central-Midwest')
    df.loc[mask6, 'truck_count'] *= 0.75
    df.loc[mask6, 'ordr_miles'] *= 0.75
    df.loc[mask6, 'ordr_cnt'] *= 0.75
    df.loc[mask6, 'ttl_rev_amt'] *= 0.75
    df.loc[mask6, 'lh_rev_amt'] *= 0.75
    df.loc[mask6, 'fuel_srchrg_rev_amt'] *= 0.75
    df.loc[mask6, 'acsrl_rev_amt'] *= 0.75
    print(f"Anomaly 6 applied: {mask6.sum()} rows affected (Truck Count Drop)")
    
    return df

def generate_dataset():
    """Generate the complete synthetic dataset."""
    
    rows = []
    
    for day_num in range(NUM_DAYS):
        current_date = START_DATE + timedelta(days=day_num)
        day_of_week = current_date.weekday()
        
        for region in REGIONS:
            for division in DIVISIONS[region]:
                for business_line in BUSINESS_LINES:
                    
                    # Generate baseline metrics
                    row = {
                        'cal_dt': current_date.strftime('%Y-%m-%d'),
                        'day_num': day_num,  # Helper for anomaly application
                        'gl_rgn_nm': region,
                        'gl_div_nm': division,
                        'ops_ln_of_bus_nm': business_line,
                    }
                    
                    # Generate each metric
                    for metric in BASELINE.keys():
                        row[metric] = generate_baseline_value(metric, day_of_week)
                    
                    # Ensure revenue components sum correctly (with small tolerance)
                    revenue_components = row['lh_rev_amt'] + row['fuel_srchrg_rev_amt'] + row['acsrl_rev_amt']
                    row['ttl_rev_amt'] = revenue_components * np.random.uniform(0.98, 1.02)
                    
                    rows.append(row)
    
    df = pd.DataFrame(rows)
    
    # Apply anomalies
    df = apply_anomalies(df)
    
    # Drop the helper column
    df = df.drop(columns=['day_num'])
    
    # Round numeric columns
    numeric_cols = ['ttl_rev_amt', 'lh_rev_amt', 'fuel_srchrg_rev_amt', 'acsrl_rev_amt', 
                    'ordr_cnt', 'ordr_miles', 'truck_count', 'dh_miles']
    for col in numeric_cols:
        if col.endswith('_amt'):
            df[col] = df[col].round(2)
        else:
            df[col] = df[col].round(1)
    
    return df

def main():
    """Main execution."""
    
    print("Generating validation dataset for ops_metrics_weekly...")
    print(f"Date range: {START_DATE.date()} to {(START_DATE + timedelta(days=NUM_DAYS-1)).date()}")
    print(f"Dimensions: {len(REGIONS)} regions × {len(DIVISIONS['East'])} divisions × {len(BUSINESS_LINES)} business lines")
    print(f"Total rows expected: {NUM_DAYS * len(REGIONS) * 2 * len(BUSINESS_LINES)} = {NUM_DAYS * 12}")
    print()
    
    # Generate dataset
    df = generate_dataset()
    
    print(f"\nDataset generated: {len(df)} rows")
    print(f"Date range: {df['cal_dt'].min()} to {df['cal_dt'].max()}")
    print(f"\nColumn summary:")
    print(df.dtypes)
    print(f"\nFirst few rows:")
    print(df.head(10))
    
    # Save to CSV
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_FILE, index=False)
    print(f"\n✓ Dataset saved to: {OUTPUT_FILE}")
    print(f"  File size: {OUTPUT_FILE.stat().st_size / 1024:.1f} KB")
    
    # Summary statistics
    print(f"\nSummary statistics:")
    print(df[['ttl_rev_amt', 'ordr_cnt', 'truck_count', 'dh_miles']].describe())
    
    return df

if __name__ == "__main__":
    df = main()
