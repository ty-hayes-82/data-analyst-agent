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
Operational ratio analysis - calculates KPIs and detects efficiency degradation.

Now config-driven via ops_metrics_ratios_config.yaml and pl_ratios_config.yaml.

Computes both P&L ratios (margin, fuel/revenue, cost/revenue) and
operational utilization ratios (miles/truck, deadhead%, LRPM, orders/truck).
"""

import json
import pandas as pd
import numpy as np
from typing import Dict, Any, List, Optional
from io import StringIO


def _load_ratios_configs() -> tuple:
    """Load both ratio config files. Returns (ops_config, pl_config)."""
    try:
        from config.ratios_config_loader import load_ops_metrics_config, load_pl_ratios_config
        return load_ops_metrics_config(), load_pl_ratios_config()
    except Exception:
        return None, None


def _compute_utilization_ratios(ops_df: pd.DataFrame, ops_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compute utilization ratios from ops metrics CSV using config definitions.

    Args:
        ops_df: DataFrame with columns [period, metric_name, value, cost_center]
        ops_config: Loaded ops_metrics_ratios_config

    Returns:
        Dict with per-period ratios, trend analysis, and degradation alerts.
    """
    metrics_config = ops_config.get("metrics", {})
    outlier_cfg = ops_config.get("outlier_detection", {"method": "stdev", "threshold": 1.5})

    # Pivot ops data: rows=period, columns=metric_name, values=value
    pivot = ops_df.pivot_table(index="period", columns="metric_name", values="value", aggfunc="sum")
    pivot = pivot.sort_index()

    periods = list(pivot.index)
    utilization_data = []

    for period in periods:
        row = pivot.loc[period]
        entry = {"period": period}

        # Loaded Miles
        loaded_miles = float(row.get("Loaded Miles", row.get("loaded_miles", 0)) or 0)
        empty_miles = float(row.get("Empty Miles", row.get("empty_miles", 0)) or 0)
        truck_count = float(row.get("Truck Count", row.get("truck_count", 0)) or 0)
        orders = float(row.get("Order Count", row.get("orders", row.get("order_count", 0))) or 0)
        revenue = float(row.get("Revenue xFuel", row.get("total_revenue", 0)) or 0)
        fuel = float(row.get("Fuel Surcharge", row.get("fuel_surcharge", 0)) or 0)

        entry["loaded_miles"] = loaded_miles
        entry["empty_miles"] = empty_miles
        entry["truck_count"] = truck_count
        entry["orders"] = orders

        # miles_per_truck
        if truck_count > 0:
            entry["miles_per_truck"] = round(loaded_miles / truck_count, 2)
            entry["orders_per_truck"] = round(orders / truck_count, 2)
        else:
            entry["miles_per_truck"] = 0
            entry["orders_per_truck"] = 0

        # deadhead_pct
        total_miles = loaded_miles + empty_miles
        if total_miles > 0:
            entry["deadhead_pct"] = round((empty_miles / total_miles) * 100, 2)
        else:
            entry["deadhead_pct"] = 0

        # lrpm
        if loaded_miles > 0:
            net_revenue = revenue - fuel
            entry["lrpm"] = round(net_revenue / loaded_miles, 4)
        else:
            entry["lrpm"] = 0

        utilization_data.append(entry)

    if not utilization_data:
        return {"utilization_ratios": [], "utilization_degradation_alerts": [], "utilization_summary": {}}

    util_df = pd.DataFrame(utilization_data)

    # Trend analysis: WoW % change, slope
    ratio_cols = ["miles_per_truck", "deadhead_pct", "lrpm", "orders_per_truck"]
    trend_data = {}

    for col in ratio_cols:
        if col not in util_df.columns:
            continue
        series = util_df[col].values
        non_zero = series[series != 0]

        if len(non_zero) < 3:
            continue

        # WoW changes
        wow_changes = []
        for i in range(1, len(series)):
            if series[i - 1] != 0:
                wow_changes.append(round((series[i] - series[i - 1]) / abs(series[i - 1]) * 100, 2))
            else:
                wow_changes.append(0)

        # Summary stats
        mean_val = float(np.mean(non_zero))
        std_val = float(np.std(non_zero))
        cv = round(std_val / abs(mean_val), 4) if mean_val != 0 else 0

        # Slope (linear regression over indices)
        x = np.arange(len(non_zero))
        if len(x) >= 2:
            slope = float(np.polyfit(x, non_zero, 1)[0])
        else:
            slope = 0

        trend_data[col] = {
            "mean": round(mean_val, 4),
            "std": round(std_val, 4),
            "cv": cv,
            "min": round(float(np.min(non_zero)), 4),
            "max": round(float(np.max(non_zero)), 4),
            "current": round(float(series[-1]), 4),
            "slope": round(slope, 6),
            "wow_changes": wow_changes[-6:],  # Last 6 WoW changes
        }

    # Degradation detection: current vs 3-period baseline
    degradation_alerts = []
    if len(util_df) >= 4:
        latest = util_df.iloc[-1]
        baseline_df = util_df.iloc[-4:-1]

        for col in ratio_cols:
            if col not in util_df.columns:
                continue

            metric_cfg = metrics_config.get(col, {})
            thresholds = metric_cfg.get("thresholds", {})
            degrade_pct = thresholds.get("degradation_pct", 5.0)
            high_pct = thresholds.get("high_severity_pct", 10.0)
            direction = metric_cfg.get("direction", "higher_is_better")

            current_val = float(latest[col])
            baseline_val = float(baseline_df[col].mean())

            if baseline_val == 0:
                continue

            variance_pct = (current_val - baseline_val) / abs(baseline_val) * 100

            # Determine if degraded based on direction
            is_degraded = False
            if direction == "higher_is_better":
                is_degraded = variance_pct < -degrade_pct
            elif direction == "lower_is_better":
                is_degraded = variance_pct > degrade_pct

            if is_degraded:
                severity = "HIGH" if abs(variance_pct) > high_pct else "MEDIUM"
                degradation_alerts.append({
                    "metric": col,
                    "label": metric_cfg.get("label", col),
                    "current": round(current_val, 4),
                    "baseline_3m": round(baseline_val, 4),
                    "variance_pct": round(variance_pct, 2),
                    "direction": direction,
                    "severity": severity,
                    "period": str(latest["period"]),
                })

    # Outlier flagging
    outlier_threshold = outlier_cfg.get("threshold", 1.5)
    outlier_weeks = []
    for col in ratio_cols:
        if col not in util_df.columns:
            continue
        series = util_df[col].values
        non_zero = series[series != 0]
        if len(non_zero) < 5:
            continue

        mean_val = np.mean(non_zero)
        std_val = np.std(non_zero)
        if std_val == 0:
            continue

        for i, val in enumerate(series):
            if val == 0:
                continue
            z = abs(val - mean_val) / std_val
            if z > outlier_threshold:
                outlier_weeks.append({
                    "period": str(util_df.iloc[i]["period"]),
                    "metric": col,
                    "value": round(float(val), 4),
                    "z_score": round(float(z), 2),
                    "mean": round(float(mean_val), 4),
                })

    utilization_summary = {
        "periods_analyzed": len(utilization_data),
        "metrics_computed": len([c for c in ratio_cols if c in util_df.columns]),
        "degradation_count": len(degradation_alerts),
        "outlier_count": len(outlier_weeks),
        "trend_analysis": trend_data,
    }

    return {
        "utilization_ratios": utilization_data,
        "utilization_degradation_alerts": degradation_alerts,
        "utilization_outliers": outlier_weeks,
        "utilization_summary": utilization_summary,
    }


async def compute_operational_ratios(ops_metrics_available: bool = True) -> str:
    """
    Calculate operational KPIs and detect degradation.

    Computes both P&L ratios and ops utilization ratios (config-driven).

    Key ratios:
    - P&L: margin_pct, fuel_to_revenue_pct, cost_to_revenue_pct
    - Utilization: miles_per_truck, deadhead_pct, lrpm, orders_per_truck

    Detects degradation by comparing current vs 3-month baseline using
    thresholds from ops_metrics_ratios_config.yaml and pl_ratios_config.yaml.

    Args:
        ops_metrics_available: Whether ops metrics data is available

    Returns:
        JSON string with:
        - ratios: P&L KPIs per period
        - utilization_ratios: Ops utilization KPIs per period
        - degradation_alerts: All ratios that degraded vs baseline
        - summary: Overall ratio health
    """
    # Import here to avoid circular dependencies
    from ...data_cache import get_validated_csv, get_ops_metrics_csv

    try:
        csv_data = get_validated_csv()
        if not csv_data:
            return json.dumps({"error": "No validated CSV data found in cache"}, indent=2)

        # Parse CSV
        df = pd.read_csv(StringIO(csv_data))

        # Ensure numeric amount column
        df['amount'] = pd.to_numeric(df['amount'], errors='coerce').fillna(0)

        # Need at least 6 periods for meaningful ratio analysis
        periods_available = len(df['period'].unique())
        if periods_available < 6:
            return json.dumps({
                "warning": "InsufficientDataForRatios",
                "message": f"Ratio analysis requires at least 6 periods. Only {periods_available} available.",
                "ratios": [],
                "degradation_alerts": [],
                "summary": {"periods_analyzed": 0, "degradation_count": 0}
            }, indent=2)

        # Load config for account classification
        ops_config, pl_config = _load_ratios_configs()

        # Get account classification keywords from config (with fallbacks)
        if pl_config:
            acct_class = pl_config.get("account_classification", {})
            revenue_keywords = acct_class.get("revenue_keywords", ['revenue', 'sales', 'income'])
            cost_keywords = acct_class.get("cost_keywords", ['cost', 'expense', 'cogs'])
            fuel_keywords = acct_class.get("fuel_keywords", ['fuel', 'surcharge'])
        else:
            revenue_keywords = ['revenue', 'sales', 'income']
            cost_keywords = ['cost', 'expense', 'cogs']
            fuel_keywords = ['fuel', 'surcharge']

        # Group accounts by type
        revenue_accounts = []
        cost_accounts = []
        fuel_accounts = []

        for account in df['gl_account'].unique():
            account_name = df[df['gl_account'] == account]['account_name'].iloc[0].lower()

            if any(kw in account_name for kw in fuel_keywords):
                fuel_accounts.append(account)
            elif any(kw in account_name for kw in revenue_keywords):
                revenue_accounts.append(account)
            elif any(kw in account_name for kw in cost_keywords):
                cost_accounts.append(account)

        # Calculate P&L ratios per period
        periods = sorted(df['period'].unique())
        ratio_data = []
        degradation_alerts = []

        for period in periods:
            period_df = df[df['period'] == period]

            # Calculate totals
            total_revenue = period_df[period_df['gl_account'].isin(revenue_accounts)]['amount'].sum()
            total_costs = period_df[period_df['gl_account'].isin(cost_accounts)]['amount'].sum()
            total_fuel = period_df[period_df['gl_account'].isin(fuel_accounts)]['amount'].sum()

            # Calculate ratios
            margin_pct = ((total_revenue - total_costs) / total_revenue * 100) if total_revenue != 0 else 0
            fuel_to_revenue_pct = (abs(total_fuel) / total_revenue * 100) if total_revenue != 0 else 0
            cost_to_revenue_pct = (abs(total_costs) / total_revenue * 100) if total_revenue != 0 else 0

            ratio_data.append({
                'period': period,
                'total_revenue': float(total_revenue),
                'total_costs': float(total_costs),
                'total_fuel': float(total_fuel),
                'margin_pct': float(margin_pct),
                'fuel_to_revenue_pct': float(fuel_to_revenue_pct),
                'cost_to_revenue_pct': float(cost_to_revenue_pct)
            })

        # Convert to DataFrame for easier analysis
        ratios_df = pd.DataFrame(ratio_data)

        # Analyze P&L degradation (compare latest period to 3-month baseline)
        if len(ratios_df) >= 4:
            latest_period = ratios_df.iloc[-1]
            baseline_periods = ratios_df.iloc[-4:-1]  # Previous 3 months

            # Get thresholds from config
            pl_metrics = pl_config.get("metrics", {}) if pl_config else {}
            ratio_col_configs = {
                'margin_pct': pl_metrics.get('margin_pct', {'direction': 'higher_is_better', 'thresholds': {'degradation_pct': 2.0, 'high_severity_pct': 5.0}}),
                'fuel_to_revenue_pct': pl_metrics.get('fuel_to_revenue_pct', {'direction': 'lower_is_better', 'thresholds': {'degradation_pct': 2.0, 'high_severity_pct': 5.0}}),
                'cost_to_revenue_pct': pl_metrics.get('cost_to_revenue_pct', {'direction': 'lower_is_better', 'thresholds': {'degradation_pct': 2.0, 'high_severity_pct': 5.0}}),
            }

            for ratio_col, cfg in ratio_col_configs.items():
                current = latest_period[ratio_col]
                baseline = baseline_periods[ratio_col].mean()
                variance = current - baseline
                variance_pct = (variance / abs(baseline) * 100) if baseline != 0 else 0

                direction = cfg.get('direction', 'higher_is_better')
                degrade_thr = cfg.get('thresholds', {}).get('degradation_pct', 2.0)
                high_thr = cfg.get('thresholds', {}).get('high_severity_pct', 5.0)

                is_degraded = False
                if direction == 'higher_is_better':
                    is_degraded = variance < -degrade_thr
                else:
                    is_degraded = variance > degrade_thr

                if is_degraded:
                    degradation_alerts.append({
                        'period': latest_period['period'],
                        'ratio_name': ratio_col,
                        'label': cfg.get('label', ratio_col),
                        'current_value': float(current),
                        'baseline_value': float(baseline),
                        'variance': float(variance),
                        'variance_pct': float(variance_pct),
                        'severity': 'HIGH' if abs(variance) > high_thr else 'MEDIUM',
                        'category': 'pl_ratio_degradation',
                    })

        # Calculate YoY and MoM variances for each ratio
        ratio_variances = []
        if len(ratios_df) >= 13:  # Need 13+ periods for YoY
            for i in range(12, len(ratios_df)):
                current_row = ratios_df.iloc[i]
                yoy_row = ratios_df.iloc[i-12]

                for ratio_col in ['margin_pct', 'fuel_to_revenue_pct', 'cost_to_revenue_pct']:
                    yoy_variance = current_row[ratio_col] - yoy_row[ratio_col]

                    ratio_variances.append({
                        'period': current_row['period'],
                        'ratio_name': ratio_col,
                        'current': float(current_row[ratio_col]),
                        'yoy': float(yoy_row[ratio_col]),
                        'yoy_variance': float(yoy_variance)
                    })

        # === Ops Utilization Ratios (config-driven) ===
        utilization_result = {}
        if ops_metrics_available:
            ops_csv = get_ops_metrics_csv()
            if ops_csv and ops_config:
                try:
                    ops_df = pd.read_csv(StringIO(ops_csv))
                    ops_df['value'] = pd.to_numeric(ops_df['value'], errors='coerce').fillna(0)
                    utilization_result = _compute_utilization_ratios(ops_df, ops_config)

                    # Merge utilization degradation alerts
                    for alert in utilization_result.get("utilization_degradation_alerts", []):
                        alert["category"] = "utilization_degradation"
                        degradation_alerts.append(alert)
                except Exception as e:
                    utilization_result = {"utilization_error": str(e)}

        # Summary
        total_degradations = len(degradation_alerts)
        high_severity_count = sum(1 for alert in degradation_alerts if alert.get('severity') == 'HIGH')

        result = {
            "ratios": ratio_data,
            "ratio_variances": ratio_variances,
            "degradation_alerts": degradation_alerts,
            "utilization_ratios": utilization_result.get("utilization_ratios", []),
            "utilization_degradation_alerts": utilization_result.get("utilization_degradation_alerts", []),
            "utilization_outliers": utilization_result.get("utilization_outliers", []),
            "utilization_summary": utilization_result.get("utilization_summary", {}),
            "summary": {
                "periods_analyzed": len(periods),
                "revenue_accounts_count": len(revenue_accounts),
                "cost_accounts_count": len(cost_accounts),
                "fuel_accounts_count": len(fuel_accounts),
                "degradation_count": total_degradations,
                "high_severity_degradations": high_severity_count,
                "current_margin_pct": float(ratios_df.iloc[-1]['margin_pct']) if len(ratios_df) > 0 else 0,
                "has_utilization_data": bool(utilization_result.get("utilization_ratios")),
                "utilization_metrics_count": utilization_result.get("utilization_summary", {}).get("metrics_computed", 0),
            }
        }

        return json.dumps(result, indent=2)

    except Exception as e:
        return json.dumps({
            "error": "RatioAnalysisFailed",
            "message": f"Failed to compute operational ratios: {str(e)}",
            "ratios": [],
            "degradation_alerts": [],
            "summary": {"periods_analyzed": 0, "degradation_count": 0}
        }, indent=2)
