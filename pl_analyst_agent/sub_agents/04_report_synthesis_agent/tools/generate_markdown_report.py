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

"""Generate executive 1-pager markdown report from hierarchical analysis results."""

import json
from datetime import datetime
from typing import Dict, Any, List, Optional


async def generate_markdown_report(
    hierarchical_results: str,
    cost_center: str,
    analysis_period: Optional[str] = None,
    statistical_summary: Optional[str] = None
) -> str:
    """
    Generate executive 1-pager in Markdown format.

    Args:
        hierarchical_results: JSON string with hierarchical analysis results
        cost_center: Cost center code
        analysis_period: Optional analysis period
        statistical_summary: Optional JSON string with statistical analysis including
            utilization ratios, degradation alerts, outliers, and trend data

    Returns:
        Markdown-formatted report string
    """
    try:
        # Parse hierarchical results
        results = json.loads(hierarchical_results) if isinstance(hierarchical_results, str) else hierarchical_results

        # Extract key data
        levels_analyzed = results.get("levels_analyzed", [])
        level_analyses = results.get("level_analyses", {})
        drill_down_path = results.get("drill_down_path", "N/A")

        # Build markdown report
        md = []
        md.append(f"# P&L Analysis Report - Cost Center {cost_center}")
        md.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        if analysis_period:
            md.append(f"**Period:** {analysis_period}")
        md.append("")

        # === EXECUTIVE SUMMARY ===
        md.append("## Executive Summary")
        md.append("")

        # Get Level 2 summary for top-level insights
        level_2 = level_analyses.get("level_2", {})
        total_variance = level_2.get("total_variance_dollar", 0)
        top_drivers = level_2.get("top_drivers", [])[:3]

        if total_variance != 0:
            md.append(f"- **Total Variance:** ${total_variance:,.0f}")

        if top_drivers:
            md.append(f"- **Top Drivers:** {len(top_drivers)} categories explain {level_2.get('variance_explained_pct', 0):.0f}% of variance")
            for driver in top_drivers[:2]:
                name = driver.get("item", "Unknown")
                var_dollar = driver.get("variance_dollar", 0)
                var_pct = driver.get("variance_pct", 0)
                materiality = driver.get("materiality", "LOW")
                md.append(f"  - {name}: ${var_dollar:+,.0f} ({var_pct:+.1f}%) [{materiality}]")

        md.append(f"- **Analysis Depth:** {drill_down_path}")
        md.append("")

        # === VARIANCE DRIVERS TABLE ===
        md.append("## Variance Drivers")
        md.append("")

        # Use the most detailed level analyzed
        deepest_level = max(levels_analyzed) if levels_analyzed else 2
        deepest_analysis = level_analyses.get(f"level_{deepest_level}", {})
        drivers = deepest_analysis.get("top_drivers", [])

        if drivers:
            md.append("| Rank | Category/GL | Variance $ | Variance % | Materiality | Cumulative % |")
            md.append("|------|-------------|------------|------------|-------------|--------------|")

            for driver in drivers[:10]:  # Top 10
                rank = driver.get("rank", "-")
                item = driver.get("item", "Unknown")
                var_dollar = driver.get("variance_dollar", 0)
                var_pct = driver.get("variance_pct", 0)
                materiality = driver.get("materiality", "LOW")
                cumulative = driver.get("cumulative_pct", 0)

                md.append(f"| {rank} | {item} | ${var_dollar:+,.0f} | {var_pct:+.1f}% | {materiality} | {cumulative:.1f}% |")
        else:
            md.append("*No variance drivers identified*")

        md.append("")

        # === DRILL-DOWN PATH ===
        md.append("## Hierarchical Drill-Down Path")
        md.append("")
        md.append(f"Analysis Path: **{drill_down_path}**")
        md.append("")

        for level in levels_analyzed:
            level_key = f"level_{level}"
            level_data = level_analyses.get(level_key, {})

            level_names = {2: "High-Level Categories", 3: "Sub-Categories", 4: "GL Account Detail"}
            md.append(f"### Level {level}: {level_names.get(level, f'Level {level}')}")
            md.append("")
            md.append(f"- **Items Analyzed:** {level_data.get('items_aggregated', 0)}")
            md.append(f"- **Top Drivers:** {level_data.get('top_drivers_identified', 0)}")
            md.append(f"- **Total Variance:** ${level_data.get('total_variance_dollar', 0):,.0f}")
            md.append(f"- **Variance Explained:** {level_data.get('variance_explained_pct', 0):.1f}%")

            # Show top 3 at each level
            top_3 = level_data.get("top_drivers", [])[:3]
            if top_3:
                md.append("")
                md.append("**Top 3 Drivers:**")
                for driver in top_3:
                    name = driver.get("item", "Unknown")
                    var_dollar = driver.get("variance_dollar", 0)
                    var_pct = driver.get("variance_pct", 0)
                    materiality = driver.get("materiality", "LOW")
                    md.append(f"- {name}: ${var_dollar:+,.0f} ({var_pct:+.1f}%) [{materiality}]")

            md.append("")

        # === UTILIZATION DEEP-DIVE (if statistical_summary has utilization data) ===
        stats_data = {}
        if statistical_summary:
            try:
                stats_data = json.loads(statistical_summary) if isinstance(statistical_summary, str) else statistical_summary
            except (json.JSONDecodeError, TypeError):
                pass

        util_ratios = stats_data.get("utilization_ratios", [])
        util_alerts = stats_data.get("utilization_degradation_alerts", [])
        util_outliers = stats_data.get("utilization_outliers", [])
        util_summary = stats_data.get("utilization_summary", {})
        trend_analysis = util_summary.get("trend_analysis", {})

        if util_ratios:
            md.append("## Operational Efficiency Dashboard")
            md.append("")

            # Build KPI summary table from the latest period
            latest_util = util_ratios[-1] if util_ratios else {}
            kpi_metrics = [
                ("Miles/Truck", "miles_per_truck", ""),
                ("Deadhead %", "deadhead_pct", "%"),
                ("LRPM", "lrpm", "$"),
                ("Orders/Truck", "orders_per_truck", ""),
            ]

            md.append("| Metric | Current | 3M Avg | Variance | Status |")
            md.append("|--------|---------|--------|----------|--------|")

            for label, key, prefix in kpi_metrics:
                current_val = latest_util.get(key, 0)
                trend_info = trend_analysis.get(key, {})
                mean_val = trend_info.get("mean", current_val)

                if mean_val != 0:
                    variance_pct = round((current_val - mean_val) / abs(mean_val) * 100, 1)
                else:
                    variance_pct = 0

                # Determine status
                status = "OK"
                for alert in util_alerts:
                    if alert.get("metric") == key:
                        status = alert.get("severity", "WARNING")
                        break

                if prefix == "$":
                    cur_str = f"${current_val:,.2f}"
                    avg_str = f"${mean_val:,.2f}"
                elif prefix == "%":
                    cur_str = f"{current_val:.1f}%"
                    avg_str = f"{mean_val:.1f}%"
                else:
                    cur_str = f"{current_val:,.1f}"
                    avg_str = f"{mean_val:,.1f}"

                var_str = f"{variance_pct:+.1f}%"
                md.append(f"| {label} | {cur_str} | {avg_str} | {var_str} | {status} |")

            md.append("")

            # Weekly trend table (last 13 periods)
            md.append("### Weekly Trend")
            md.append("")
            md.append("| Week | Miles/Trk | WoW% | vs Avg | Status |")
            md.append("|------|-----------|------|--------|--------|")

            mpt_trend = trend_analysis.get("miles_per_truck", {})
            mpt_mean = mpt_trend.get("mean", 0)

            for entry in util_ratios[-13:]:
                period = entry.get("period", "")
                mpt = entry.get("miles_per_truck", 0)
                vs_avg = round((mpt - mpt_mean) / abs(mpt_mean) * 100, 1) if mpt_mean != 0 else 0
                status = "OK" if vs_avg >= -5 else ("WARNING" if vs_avg >= -10 else "DEGRADED")
                md.append(f"| {period} | {mpt:,.0f} | - | {vs_avg:+.1f}% | {status} |")

            md.append("")

            # Statistical insights section
            md.append("### Statistical Insights")
            md.append("")

            if util_outliers:
                outlier_count = len(util_outliers)
                md.append(f"- **Outliers**: {outlier_count} outlier period(s) flagged")
                for outlier in util_outliers[:3]:
                    md.append(f"  - {outlier.get('period')}: {outlier.get('metric')} = {outlier.get('value'):,.2f} (z={outlier.get('z_score'):.1f})")

            for metric_key, metric_label in [("miles_per_truck", "Miles/Truck"), ("deadhead_pct", "Deadhead %")]:
                trend_info = trend_analysis.get(metric_key, {})
                if trend_info:
                    slope = trend_info.get("slope", 0)
                    cv = trend_info.get("cv", 0)
                    trend_dir = "increasing" if slope > 0 else "decreasing"
                    md.append(f"- **{metric_label} Trend**: {trend_dir} (slope={slope:.4f}, CV={cv:.3f})")

            if util_alerts:
                md.append(f"- **Degradation Alerts**: {len(util_alerts)} metric(s) below baseline")
                for alert in util_alerts:
                    md.append(f"  - {alert.get('label', alert.get('metric'))}: {alert.get('variance_pct', 0):+.1f}% vs 3M baseline [{alert.get('severity')}]")

            md.append("")

        # === RECOMMENDED ACTIONS ===
        md.append("## Recommended Actions")
        md.append("")

        # Build action list from HIGH materiality items
        actions = []
        for level_key, level_data in level_analyses.items():
            for driver in level_data.get("top_drivers", []):
                if driver.get("materiality") == "HIGH":
                    name = driver.get("item", "Unknown")
                    var_dollar = driver.get("variance_dollar", 0)
                    var_pct = driver.get("variance_pct", 0)

                    if var_dollar > 0:
                        action = f"Investigate increase in {name} (+${abs(var_dollar):,.0f}, +{var_pct:.1f}%)"
                    else:
                        action = f"Investigate decrease in {name} (${var_dollar:,.0f}, {var_pct:.1f}%)"

                    if action not in actions:
                        actions.append(action)

        # Add utilization-based actions
        for alert in util_alerts:
            if alert.get("severity") == "HIGH":
                metric_label = alert.get("label", alert.get("metric", "Unknown"))
                var_pct = alert.get("variance_pct", 0)
                action = f"Investigate {metric_label} degradation ({var_pct:+.1f}% vs 3M baseline)"
                if action not in actions:
                    actions.append(action)

        if actions:
            for i, action in enumerate(actions[:5], 1):
                md.append(f"{i}. {action}")
        else:
            md.append("1. No high-materiality variances requiring immediate action")
            md.append("2. Continue monitoring trends for emerging patterns")

        md.append("")

        # === DATA QUALITY NOTES ===
        md.append("## Data Quality & Notes")
        md.append("")
        md.append(f"- Analysis completed successfully with {len(levels_analyzed)} hierarchy levels")
        md.append(f"- Drill-down path: {drill_down_path}")
        md.append("- All variance calculations use category-specific materiality thresholds")
        if util_ratios:
            md.append(f"- Utilization analysis: {len(util_ratios)} periods, {util_summary.get('metrics_computed', 0)} metrics")
            md.append(f"- Data source: Ops Metrics DS via A2A")
        md.append("")
        md.append("---")
        md.append("*This report was auto-generated by P&L Analyst Agent*")

        return "\n".join(md)

    except Exception as e:
        return f"# Error Generating Report\n\nError: {str(e)}"
