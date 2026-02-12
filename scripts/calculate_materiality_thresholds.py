# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Calculate Empirical Materiality Thresholds

Analyzes historical P&L data to calculate category-specific materiality thresholds
based on actual variance distributions.

Usage:
    # From CSV file (test mode)
    python scripts/calculate_materiality_thresholds.py --data-source csv --csv-file data/PL-067-REVENUE-ONLY.csv
    
    # From Tableau (production)
    python scripts/calculate_materiality_thresholds.py --data-source tableau --months 24
"""

import sys
import argparse
import yaml
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List
import pandas as pd
import numpy as np

# Add parent directory to path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from config.chart_loader import get_account_category


def calculate_variance_statistics(
    df: pd.DataFrame,
    category: str
) -> Dict[str, Any]:
    """
    Calculate variance statistics for a category.
    
    Args:
        df: DataFrame with columns: period, gl_account, amount, canonical_category
        category: Category to analyze
    
    Returns:
        Dict with percentile thresholds and CV metrics
    """
    # Filter to category
    category_df = df[df["canonical_category"] == category].copy()
    
    if len(category_df) == 0:
        return None
    
    # Calculate YoY and MoM variances per GL
    variances = []
    
    for gl_account in category_df["gl_account"].unique():
        gl_df = category_df[category_df["gl_account"] == gl_account].sort_values("period")
        
        if len(gl_df) < 2:
            continue
        
        amounts = gl_df["amount"].values
        periods = gl_df["period"].values
        
        # Month-over-Month variances
        for i in range(1, len(amounts)):
            if amounts[i-1] != 0:
                mom_variance_pct = abs((amounts[i] - amounts[i-1]) / amounts[i-1] * 100)
                mom_variance_dollar = abs(amounts[i] - amounts[i-1])
                variances.append({
                    "type": "mom",
                    "variance_pct": mom_variance_pct,
                    "variance_dollar": mom_variance_dollar,
                    "gl_account": gl_account
                })
        
        # Year-over-Year variances (if enough data)
        if len(amounts) >= 13:
            for i in range(12, len(amounts)):
                if amounts[i-12] != 0:
                    yoy_variance_pct = abs((amounts[i] - amounts[i-12]) / amounts[i-12] * 100)
                    yoy_variance_dollar = abs(amounts[i] - amounts[i-12])
                    variances.append({
                        "type": "yoy",
                        "variance_pct": yoy_variance_pct,
                        "variance_dollar": yoy_variance_dollar,
                        "gl_account": gl_account
                    })
    
    if not variances:
        return None
    
    # Convert to DataFrame for analysis
    var_df = pd.DataFrame(variances)
    
    # Calculate statistics
    pct_values = var_df["variance_pct"].values
    dollar_values = var_df["variance_dollar"].values
    
    # Coefficient of Variation (volatility measure)
    cv = np.std(dollar_values) / np.mean(dollar_values) if np.mean(dollar_values) > 0 else 0
    
    # Percentile-based thresholds
    p75_pct = np.percentile(pct_values, 75)
    p75_dollar = np.percentile(dollar_values, 75)
    p90_pct = np.percentile(pct_values, 90)
    p90_dollar = np.percentile(dollar_values, 90)
    
    # Adjust for volatile categories (CV > 0.8)
    is_volatile = cv > 0.8
    if is_volatile:
        p75_pct *= 1.5
        p75_dollar *= 1.5
    
    return {
        "variance_pct": round(p75_pct, 1),
        "variance_dollar": int(round(p75_dollar, -3)),  # Round to nearest 1000
        "cv": round(cv, 2),
        "is_volatile": is_volatile,
        "sample_size": len(variances),
        "gl_count": len(category_df["gl_account"].unique()),
        "stats": {
            "p75_pct": round(p75_pct, 1),
            "p90_pct": round(p90_pct, 1),
            "p75_dollar": int(round(p75_dollar, -3)),
            "p90_dollar": int(round(p90_dollar, -3)),
            "mean_pct": round(np.mean(pct_values), 1),
            "median_pct": round(np.median(pct_values), 1),
            "mean_dollar": int(round(np.mean(dollar_values), -3)),
            "median_dollar": int(round(np.median(dollar_values), -3))
        }
    }


def load_data_from_csv(csv_file: str) -> pd.DataFrame:
    """Load P&L data from CSV file (wide format with period columns)."""
    print(f"Loading data from CSV: {csv_file}")
    
    df = pd.read_csv(csv_file)
    
    # Detect period columns (format: "2024 - 07")
    period_cols = [col for col in df.columns if " - " in col and any(char.isdigit() for char in col)]
    
    if not period_cols:
        raise ValueError("No period columns found. Expected format: '2024 - 07'")
    
    # Check for required ID columns
    if "Account Nbr" not in df.columns:
        raise ValueError("CSV must contain 'Account Nbr' column")
    
    # Filter to rows with Account Nbr (exclude ops metrics rows)
    pl_data = df[df["Account Nbr"].notna()].copy()
    
    # Melt to long format
    id_cols = ["Account Nbr", "level_1", "level_2", "level_3", "level_4"]
    id_cols = [col for col in id_cols if col in pl_data.columns]
    
    melted = pl_data.melt(
        id_vars=id_cols,
        value_vars=period_cols,
        var_name="period_raw",
        value_name="amount"
    )
    
    # Clean period format (remove spaces: "2024 - 07" -> "2024-07")
    melted["period"] = melted["period_raw"].str.replace(" ", "")
    
    # Clean amount (remove commas, convert to float)
    melted["amount"] = melted["amount"].astype(str).str.replace(",", "").str.replace('"', "")
    melted["amount"] = pd.to_numeric(melted["amount"], errors="coerce").fillna(0)
    
    # Rename Account Nbr to gl_account
    melted = melted.rename(columns={"Account Nbr": "gl_account"})
    
    # Add canonical_category from chart loader
    melted["canonical_category"] = melted["gl_account"].apply(get_account_category)
    
    # Filter out None categories and zero amounts
    melted = melted[melted["canonical_category"].notna()].copy()
    melted = melted[melted["amount"] != 0].copy()
    
    print(f"Loaded {len(melted)} records with {melted['gl_account'].nunique()} GL accounts")
    print(f"Period range: {melted['period'].min()} to {melted['period'].max()}")
    print(f"Categories: {sorted(melted['canonical_category'].unique())}")
    
    return melted


def load_data_from_tableau() -> pd.DataFrame:
    """Load P&L data from Tableau A2A agent (not implemented yet)."""
    raise NotImplementedError(
        "Tableau data source not yet implemented. Use --data-source csv for now."
    )


def generate_empirical_config(
    data_df: pd.DataFrame,
    output_file: str
):
    """Generate empirical materiality thresholds config."""
    print("\nCalculating empirical thresholds by category...")
    
    categories = sorted(data_df["canonical_category"].unique())
    category_overrides = {}
    
    for category in categories:
        stats = calculate_variance_statistics(data_df, category)
        
        if stats is None:
            print(f"  ⚠️  Skipping {category}: insufficient data")
            continue
        
        rationale = (
            f"P75 variance: {stats['stats']['p75_pct']}%, "
            f"${stats['stats']['p75_dollar']:,} based on {stats['gl_count']} GLs"
        )
        if stats["is_volatile"]:
            rationale += f"; CV={stats['cv']} (volatile, threshold increased 1.5x)"
        
        category_overrides[category] = {
            "variance_pct": float(stats["variance_pct"]),
            "variance_dollar": int(stats["variance_dollar"]),
            "rationale": rationale
        }
        
        print(f"  ✓ {category}: ±{stats['variance_pct']}%, ±${stats['variance_dollar']:,}")
    
    # Build config structure
    config = {
        "generation_date": datetime.now().strftime("%Y-%m-%d"),
        "data_period": f"{data_df['period'].min()} to {data_df['period'].max()}",
        "total_records": len(data_df),
        "global_defaults": {
            "variance_pct": 5.0,
            "variance_dollar": 50000,
            "top_categories_count": 5,
            "cumulative_variance_pct": 80
        },
        "category_overrides": category_overrides,
        "gl_overrides": {
            "4560-06": {
                "variance_pct": 3.0,
                "variance_dollar": 25000,
                "rationale": "Critical toll expense account, lower threshold for early detection"
            }
        }
    }
    
    # Write to file
    output_path = project_root / output_file
    with open(output_path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
    
    print(f"\n✅ Empirical thresholds saved to: {output_path}")
    print(f"   Total categories: {len(category_overrides)}")
    print(f"   Data period: {config['data_period']}")
    
    return config


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Calculate empirical materiality thresholds from historical data"
    )
    parser.add_argument(
        "--data-source",
        choices=["csv", "tableau"],
        default="csv",
        help="Data source (csv or tableau)"
    )
    parser.add_argument(
        "--csv-file",
        default="data/PL-067-REVENUE-ONLY.csv",
        help="CSV file path (if data-source=csv)"
    )
    parser.add_argument(
        "--months",
        type=int,
        default=24,
        help="Number of months of history to analyze"
    )
    parser.add_argument(
        "--output",
        default="config/materiality_thresholds_empirical.yaml",
        help="Output YAML file path"
    )
    
    args = parser.parse_args()
    
    try:
        # Load data
        if args.data_source == "csv":
            data_df = load_data_from_csv(args.csv_file)
        else:
            data_df = load_data_from_tableau()
        
        # Generate config
        config = generate_empirical_config(data_df, args.output)
        
        print("\n" + "="*80)
        print("NEXT STEPS:")
        print("="*80)
        print("1. Review the generated thresholds in config/materiality_thresholds_empirical.yaml")
        print("2. Edit config/materiality_config.yaml and set: use_empirical: true")
        print("3. Run: python test_efficient_workflow.py")
        print("4. Verify that new thresholds are applied correctly")
        print("="*80)
        
    except Exception as e:
        print(f"\n❌ ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

