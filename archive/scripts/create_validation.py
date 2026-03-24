"""
Generate validation datapoints for the Data Analyst Agent pipeline.

Produces pre-computed expected results that the ADK agents should reproduce.
These serve as ground truth for validating each sub-agent independently.
"""
import pandas as pd
import numpy as np
import json
from pathlib import Path

DATA_DIR = Path("/data/data-analyst-agent/data/synthetic")
OUT_DIR = Path("/data/data-analyst-agent/data/validation")
OUT_DIR.mkdir(parents=True, exist_ok=True)

df = pd.read_csv(DATA_DIR / "synthetic_hierarchical_trade_dataset_250k.csv")
gt = pd.read_csv(DATA_DIR / "synthetic_hierarchical_trade_dataset_ground_truth_summary.csv")

print(f"Loaded {len(df):,} rows, {len(gt)} ground truth scenarios")

# ============================================================================
# 1. SMALL TEST FIXTURES (100-500 rows for fast unit tests)
# ============================================================================

# Fixture A: Weekly imports, West region, CA, LAX only, all commodities (contains anomaly A1)
fixture_a = df[
    (df["grain"] == "weekly") &
    (df["flow"] == "imports") &
    (df["region"] == "West") &
    (df["state"] == "CA") &
    (df["port_code"] == "LAX")
].copy()
fixture_a.to_csv(OUT_DIR / "fixture_a_lax_imports_weekly.csv", index=False)
print(f"Fixture A (LAX imports weekly): {len(fixture_a)} rows")

# Fixture B: Monthly exports, South, TX, HOU only (contains anomaly B1)
fixture_b = df[
    (df["grain"] == "monthly") &
    (df["flow"] == "exports") &
    (df["region"] == "South") &
    (df["state"] == "TX") &
    (df["port_code"] == "HOU")
].copy()
fixture_b.to_csv(OUT_DIR / "fixture_b_hou_exports_monthly.csv", index=False)
print(f"Fixture B (HOU exports monthly): {len(fixture_b)} rows")

# Fixture C: Minimal — single hs4, single port, weekly (for ultra-fast tests)
fixture_c = df[
    (df["grain"] == "weekly") &
    (df["flow"] == "imports") &
    (df["state"] == "CA") &
    (df["port_code"] == "LAX") &
    (df["hs4"] == "8542")
].copy()
fixture_c.to_csv(OUT_DIR / "fixture_c_minimal_lax_8542.csv", index=False)
print(f"Fixture C (minimal LAX/8542): {len(fixture_c)} rows")

# ============================================================================
# 2. HIERARCHY VARIANCE VALIDATION (what HierarchyVarianceAgent should find)
# ============================================================================

validations = {}

# Level 0: Total — overall variance between 2024 and 2023
weekly = df[df["grain"] == "weekly"].copy()
weekly["period_end"] = pd.to_datetime(weekly["period_end"])

y2024 = weekly[weekly["year"] == 2024]["trade_value_usd"].sum()
y2023 = weekly[weekly["year"] == 2023]["trade_value_usd"].sum()
total_variance_pct = ((y2024 - y2023) / y2023) * 100

validations["total_yoy_variance"] = {
    "description": "Total trade value YoY variance 2024 vs 2023 (weekly grain)",
    "y2024_total": round(y2024, 2),
    "y2023_total": round(y2023, 2),
    "variance_pct": round(total_variance_pct, 2),
    "expected_direction": "positive (annual growth trend of 3.5%)"
}

# Level 1: By flow — which direction (imports vs exports) drives more variance?
for flow in ["imports", "exports"]:
    f24 = weekly[(weekly["year"] == 2024) & (weekly["flow"] == flow)]["trade_value_usd"].sum()
    f23 = weekly[(weekly["year"] == 2023) & (weekly["flow"] == flow)]["trade_value_usd"].sum()
    validations[f"flow_{flow}_yoy"] = {
        "y2024": round(f24, 2),
        "y2023": round(f23, 2),
        "variance_pct": round(((f24 - f23) / f23) * 100, 2),
    }

# Level 2: By region — rank regions by absolute variance contribution
region_variances = []
for region in ["West", "South", "Midwest", "Northeast"]:
    r24 = weekly[(weekly["year"] == 2024) & (weekly["region"] == region)]["trade_value_usd"].sum()
    r23 = weekly[(weekly["year"] == 2023) & (weekly["region"] == region)]["trade_value_usd"].sum()
    region_variances.append({
        "region": region,
        "y2024": round(r24, 2),
        "y2023": round(r23, 2),
        "abs_variance": round(r24 - r23, 2),
        "variance_pct": round(((r24 - r23) / r23) * 100, 2),
    })
region_variances.sort(key=lambda x: abs(x["abs_variance"]), reverse=True)
validations["region_variance_ranking"] = region_variances

# Level 3: By state within top region
top_region = region_variances[0]["region"]
state_variances = []
for state in weekly[weekly["region"] == top_region]["state"].unique():
    s24 = weekly[(weekly["year"] == 2024) & (weekly["state"] == state)]["trade_value_usd"].sum()
    s23 = weekly[(weekly["year"] == 2023) & (weekly["state"] == state)]["trade_value_usd"].sum()
    state_variances.append({
        "state": state,
        "y2024": round(s24, 2),
        "y2023": round(s23, 2),
        "abs_variance": round(s24 - s23, 2),
        "variance_pct": round(((s24 - s23) / s23) * 100, 2),
    })
state_variances.sort(key=lambda x: abs(x["abs_variance"]), reverse=True)
validations["state_variance_in_top_region"] = {
    "region": top_region,
    "states": state_variances
}

# ============================================================================
# 3. ANOMALY DETECTION VALIDATION (what StatisticalInsightsAgent should find)
# ============================================================================

anomaly_validations = []
for _, row in gt.iterrows():
    scenario = row["scenario_id"]
    anomaly_rows = df[df["scenario_id"] == scenario]

    # Compute the average anomaly magnitude vs baseline
    if len(anomaly_rows) > 0:
        grain = row["grain"]

        # Get the non-anomaly rows for the same hierarchy path for comparison
        sample = anomaly_rows.iloc[0]
        baseline_mask = (
            (df["grain"] == grain) &
            (df["anomaly_flag"] == 0) &
            (df["flow"] == sample["flow"]) &
            (df["region"] == sample["region"]) &
            (df["state"] == sample["state"]) &
            (df["port_code"] == sample["port_code"]) &
            (df["hs2"] == str(sample["hs2"]))
        )
        baseline = df[baseline_mask]

        if len(baseline) > 0:
            avg_anomaly = anomaly_rows["trade_value_usd"].mean()
            avg_baseline = baseline["trade_value_usd"].mean()
            deviation_pct = ((avg_anomaly - avg_baseline) / avg_baseline) * 100
        else:
            avg_anomaly = anomaly_rows["trade_value_usd"].mean()
            avg_baseline = None
            deviation_pct = None

        anomaly_validations.append({
            "scenario_id": scenario,
            "grain": grain,
            "anomaly_type": row["anomaly_type"],
            "direction": row["anomaly_direction"],
            "severity": row["anomaly_severity"],
            "rows_impacted": int(row["rows_impacted"]),
            "first_period": row["first_period"],
            "last_period": row["last_period"],
            "avg_anomaly_value": round(float(avg_anomaly), 2),
            "avg_baseline_value": round(float(avg_baseline), 2) if avg_baseline else None,
            "deviation_pct": round(float(deviation_pct), 2) if deviation_pct else None,
            "ground_truth_insight": row["ground_truth_insight"],
        })

validations["anomaly_scenarios"] = anomaly_validations

# ============================================================================
# 4. SEASONAL PATTERN VALIDATION (what SeasonalBaselineAgent should verify)
# ============================================================================

# Monthly seasonality — compute average trade value by month across all years
monthly = df[df["grain"] == "monthly"].copy()
monthly["period_end"] = pd.to_datetime(monthly["period_end"])
monthly_avg = monthly.groupby("month")["trade_value_usd"].mean()
peak_month = int(monthly_avg.idxmax())
trough_month = int(monthly_avg.idxmin())
seasonal_amplitude = ((monthly_avg.max() - monthly_avg.min()) / monthly_avg.mean()) * 100

validations["seasonal_pattern"] = {
    "description": "Monthly seasonality in trade values",
    "peak_month": peak_month,
    "trough_month": trough_month,
    "seasonal_amplitude_pct": round(float(seasonal_amplitude), 2),
    "monthly_averages": {int(k): round(float(v), 2) for k, v in monthly_avg.items()},
}

# ============================================================================
# 5. AGGREGATION VALIDATION (basic sanity checks)
# ============================================================================

validations["aggregation_checks"] = {
    "total_rows": len(df),
    "weekly_rows": len(df[df["grain"] == "weekly"]),
    "monthly_rows": len(df[df["grain"] == "monthly"]),
    "total_trade_value": round(float(df["trade_value_usd"].sum()), 2),
    "weekly_trade_value": round(float(df[df["grain"] == "weekly"]["trade_value_usd"].sum()), 2),
    "monthly_trade_value": round(float(df[df["grain"] == "monthly"]["trade_value_usd"].sum()), 2),
    "unique_flows": sorted(df["flow"].unique().tolist()),
    "unique_regions": sorted(df["region"].unique().tolist()),
    "unique_states": sorted(df["state"].unique().tolist()),
    "unique_ports": sorted(df["port_code"].unique().tolist()),
    "unique_hs2": sorted(df["hs2"].unique().tolist()),
    "unique_hs4": sorted(df["hs4"].unique().tolist()),
    "anomaly_rows": int(df["anomaly_flag"].sum()),
    "non_anomaly_rows": int((df["anomaly_flag"] == 0).sum()),
}

# ============================================================================
# 6. WRITE OUTPUTS
# ============================================================================

# Full validation JSON
with open(OUT_DIR / "validation_datapoints.json", "w") as f:
    json.dump(validations, f, indent=2, default=str)
print(f"\nValidation datapoints written to {OUT_DIR / 'validation_datapoints.json'}")

# Summary for agents to read quickly
summary = f"""# Validation Datapoints Summary

## Quick Checks
- Total rows: {validations['aggregation_checks']['total_rows']:,}
- Weekly: {validations['aggregation_checks']['weekly_rows']:,} | Monthly: {validations['aggregation_checks']['monthly_rows']:,}
- Total trade value: ${validations['aggregation_checks']['total_trade_value']:,.2f}
- Anomaly rows: {validations['aggregation_checks']['anomaly_rows']}

## YoY Variance (2024 vs 2023, weekly grain)
- Total: {validations['total_yoy_variance']['variance_pct']}% (expected positive ~3.5% annual growth)
- Imports: {validations['flow_imports_yoy']['variance_pct']}%
- Exports: {validations['flow_exports_yoy']['variance_pct']}%

## Region Ranking (by absolute variance contribution)
"""
for rv in region_variances:
    summary += f"- {rv['region']}: ${rv['abs_variance']:,.0f} ({rv['variance_pct']:.1f}%)\n"

summary += f"""
## Anomaly Scenarios (6 embedded)
"""
for av in anomaly_validations:
    summary += f"- {av['scenario_id']} ({av['grain']}): {av['anomaly_type']} {av['direction']}, {av['severity']} severity, {av['rows_impacted']} rows, deviation {av['deviation_pct']}%\n"

summary += f"""
## Seasonal Pattern (monthly grain)
- Peak month: {peak_month}
- Trough month: {trough_month}
- Amplitude: {seasonal_amplitude:.1f}%

## Test Fixtures
- fixture_a_lax_imports_weekly.csv — {len(fixture_a)} rows (contains A1 anomaly)
- fixture_b_hou_exports_monthly.csv — {len(fixture_b)} rows (contains B1 anomaly)
- fixture_c_minimal_lax_8542.csv — {len(fixture_c)} rows (minimal, single HS4)
"""

with open(OUT_DIR / "VALIDATION_SUMMARY.md", "w") as f:
    f.write(summary)
print(f"Summary written to {OUT_DIR / 'VALIDATION_SUMMARY.md'}")

print("\nDone. Files created:")
for p in sorted(OUT_DIR.iterdir()):
    print(f"  {p.name} ({p.stat().st_size:,} bytes)")
