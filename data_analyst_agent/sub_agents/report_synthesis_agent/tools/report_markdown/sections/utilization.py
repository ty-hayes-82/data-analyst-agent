"""Operational efficiency/utilization section."""

from __future__ import annotations

from typing import Dict, List, Tuple


def build_utilization_section(
    stats_data: dict,
    period_label: str,
    short_delta_label: str,
) -> Tuple[List[str], Dict[str, object]]:
    util_ratios = stats_data.get("utilization_ratios", []) or []
    util_alerts = stats_data.get("utilization_degradation_alerts", []) or []
    util_outliers = stats_data.get("utilization_outliers", []) or []
    util_summary = stats_data.get("utilization_summary", {}) or {}
    trend_analysis = util_summary.get("trend_analysis", {}) if isinstance(util_summary, dict) else {}

    if not util_ratios:
        return [], {
            "util_ratios": util_ratios,
            "util_summary": util_summary,
        }

    lines: List[str] = ["## Operational Efficiency Dashboard", ""]

    latest_util = util_ratios[-1]
    kpi_metrics = [
        ("Miles/Truck", "miles_per_truck", ""),
        ("Deadhead %", "deadhead_pct", "%"),
        ("LRPM", "lrpm", "$"),
        ("Orders/Truck", "orders_per_truck", ""),
    ]

    lines.append("| Metric | Current | 3M Avg | Variance | Status |")
    lines.append("|--------|---------|--------|----------|--------|")

    for label, key, prefix in kpi_metrics:
        current_val = latest_util.get(key, 0)
        trend_info = trend_analysis.get(key, {})
        mean_val = trend_info.get("mean", current_val)
        variance_pct = round((current_val - mean_val) / abs(mean_val) * 100, 1) if mean_val else 0

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
        lines.append(f"| {label} | {cur_str} | {avg_str} | {var_str} | {status} |")

    lines.append("")
    lines.append(f"### {period_label.title()}ly Trend")
    lines.append("")
    lines.append(f"| {period_label.title()} | Miles/Trk | {short_delta_label}% | vs Avg | Status |")
    lines.append("|------|-----------|------|--------|--------|")

    mpt_trend = trend_analysis.get("miles_per_truck", {})
    mpt_mean = mpt_trend.get("mean", 0)

    for entry in util_ratios[-13:]:
        period = entry.get("period", "")
        mpt = entry.get("miles_per_truck", 0)
        vs_avg = round((mpt - mpt_mean) / abs(mpt_mean) * 100, 1) if mpt_mean else 0
        status = "OK" if vs_avg >= -5 else ("WARNING" if vs_avg >= -10 else "DEGRADED")
        lines.append(f"| {period} | {mpt:,.0f} | - | {vs_avg:+.1f}% | {status} |")

    lines.append("")
    lines.append("### Statistical Insights")
    lines.append("")

    if util_outliers:
        lines.append(f"- **Outliers**: {len(util_outliers)} outlier period(s) flagged")
        for outlier in util_outliers[:3]:
            lines.append(
                f"  - {outlier.get('period')}: {outlier.get('metric')} = {outlier.get('value'):,.2f} (z={outlier.get('z_score'):.1f})"
            )

    for metric_key, metric_label in [("miles_per_truck", "Miles/Truck"), ("deadhead_pct", "Deadhead %")]:
        trend_info = trend_analysis.get(metric_key, {})
        if not trend_info:
            continue
        slope = trend_info.get("slope", 0)
        cv = trend_info.get("cv", 0)
        p_val = trend_info.get("p_value")
        direction = "increasing" if slope > 0 else "decreasing"
        if p_val is not None:
            sig_label = " (significant)" if p_val < 0.05 else " (directional)"
            lines.append(f"- **{metric_label} Trend**: {direction}{sig_label} (slope={slope:.4f}, p={p_val:.4f})")
        else:
            lines.append(f"- **{metric_label} Trend**: {direction} (slope={slope:.4f}, CV={cv:.3f})")

    if util_alerts:
        lines.append(f"- **Degradation Alerts**: {len(util_alerts)} metric(s) below baseline")
        for alert in util_alerts:
            lines.append(
                f"  - {alert.get('label', alert.get('metric'))}: {alert.get('variance_pct', 0):+.1f}% vs 3M baseline [{alert.get('severity')}]"
            )

    lines.append("")
    return lines, {
        "util_ratios": util_ratios,
        "util_summary": util_summary,
    }
