"""Cross dimension section builder."""

from __future__ import annotations

from typing import List

from ..parsing import parse_json_safe


def build_cross_dimension_section(cross_dim_results: dict | None, condensed: bool) -> List[str]:
    if condensed or not cross_dim_results:
        return []

    lines: List[str] = ["## Cross-Dimension Analysis", ""]

    for level_key, dim_results in sorted(cross_dim_results.items()):
        if not isinstance(dim_results, dict):
            continue
        for dim_name, dim_data_raw in dim_results.items():
            dim_data = parse_json_safe(dim_data_raw) if isinstance(dim_data_raw, str) else dim_data_raw
            if not isinstance(dim_data, dict) or dim_data.get("skipped") or dim_data.get("error"):
                continue

            level_num = level_key.replace("level_", "")
            summary = dim_data.get("summary", {})
            independence = dim_data.get("independence_test", {})
            hier_dim = dim_data.get("hierarchy_dimension", f"Level {level_num}")

            lines.append(f"### {hier_dim} x {dim_name} (Level {level_num})")

            aux_eta = independence.get("auxiliary_eta_squared", 0)
            inter_eta = independence.get("interaction_eta_squared", 0)
            inter_p = independence.get("interaction_p_value")

            parts = []
            if aux_eta > 0.01:
                parts.append(f"{dim_name} explains {aux_eta:.0%} of variance")
            if inter_eta > 0.01:
                sig = f" (p={inter_p:.4f})" if inter_p is not None else ""
                parts.append(f"interaction effect: {inter_eta:.0%}{sig}")
            if parts:
                lines.append(f"- **ANOVA:** {'; '.join(parts)}")

            for pattern in dim_data.get("cross_cutting_patterns", [])[:3]:
                lines.append(f"- **{pattern.get('auxiliary_value')}:** {pattern.get('label', '')}")

            for trend in dim_data.get("trends", [])[:2]:
                lines.append(f"- **Trend:** {trend.get('label', '')}")

            for cell in dim_data.get("anomalous_cells", [])[:3]:
                lines.append(f"- **Anomaly:** {cell.get('label', '')}")

            if summary.get("recommendation"):
                lines.append(f"- {summary['recommendation']}")
            lines.append("")

    return lines
