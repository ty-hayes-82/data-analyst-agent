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

"""Generate executive 1-pager markdown report from hierarchical analysis results.

Input semantics:
- narrative_results.insight_cards: Primary findings (anomalies, trends, spikes, root causes).
- hierarchical_results.level_N.insight_cards: Drill-down breakdowns for the "Hierarchical Variance
  Analysis" section. When a narrative card already describes regional breakdown (tags like
  regional_distribution, hierarchy), do not duplicate hierarchy level items as insight cards.
  See SCHEMA.md for canonical JSON formats.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

# Tags that indicate derived/contextual insights (explain primary findings)
_DERIVED_TAGS = frozenset({
    "correlation", "leading_indicator", "mix_shift", "hierarchy",
    "cross_metric", "concentration", "operational_link", "anova",
    "variance", "regional_analysis", "market_share", "drill_down",
})

# Patterns that indicate a card adds no value (zero/empty variance)
_ZERO_VARIANCE_PATTERNS = (
    "Variance of $0", "Variance of $0.00", "Variance of 0", 
    "Variance of +0", "Variance of -0", "Variance of +0.00", "Variance of -0.00"
)


def _is_skip_card(card: dict) -> bool:
    """Return True if card should be omitted (zero variance text, empty)."""
    if not card or not isinstance(card, dict):
        return True
    what = str(card.get("what_changed", "")).strip()
    if any(p in what for p in _ZERO_VARIANCE_PATTERNS):
        return True
    
    # Also check evidence for near-zero variance if available
    evidence = card.get("evidence", {})
    if isinstance(evidence, dict):
        # Check multiple possible keys for variance value
        for key in ("variance_dollar", "variance", "variance_amount"):
            var = evidence.get(key)
            if var is not None:
                try:
                    # If we found a variance value and it's effectively zero, skip
                    if abs(float(var)) < 0.001:
                        return True
                except (ValueError, TypeError):
                    continue
            
    return False


def _parse_json_safe(raw):
    """Parse a JSON string or return the value if already parsed. May return dict or list."""
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return {}
    return raw if isinstance(raw, (dict, list)) else {}


# === Metric-aware unit formatting (Spec 029) ===
_METRIC_UNITS_CACHE: Optional[Dict[str, Dict[str, str]]] = None


def _load_metric_units() -> Dict[str, Dict[str, str]]:
    """Load metric display units from config/datasets/<active>/metric_units.yaml."""
    global _METRIC_UNITS_CACHE
    if _METRIC_UNITS_CACHE is not None:
        return _METRIC_UNITS_CACHE
    try:
        from config.dataset_resolver import get_dataset_path_optional
        path = get_dataset_path_optional("metric_units.yaml")
        if path and path.exists():
            import yaml
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            _METRIC_UNITS_CACHE = data.get("metrics", {})
        else:
            _METRIC_UNITS_CACHE = {}
    except Exception:
        _METRIC_UNITS_CACHE = {}
    return _METRIC_UNITS_CACHE


def _resolve_unit(analysis_target: str) -> str:
    """Return unit type for variance display: currency, miles, count, or ratio."""
    units = _load_metric_units()
    cfg = units.get(analysis_target) or units.get(analysis_target.strip())
    if cfg and isinstance(cfg, dict):
        return str(cfg.get("unit", "currency"))
    return "currency"


def _format_variance(value: float, unit: str, analysis_target: Optional[str] = None) -> str:
    """Format variance for display. Uses metric unit map when available."""
    if analysis_target:
        units = _load_metric_units()
        cfg = units.get(analysis_target) or {}
        if isinstance(cfg, dict):
            u = cfg.get("unit", "currency")
            suffix = cfg.get("suffix", "")
            if u == "currency":
                return f"${value:,.0f}"
            if u in ("miles", "count", "ratio") and suffix:
                return f"{value:,.0f} {suffix}"
            if u in ("miles", "count"):
                return f"{value:,.0f}"
    if unit == "currency":
        return f"${value:,.0f}"
    return f"{value:,.0f}"


def _convert_level_list_to_dict(val: list, level_num: int) -> dict:
    """Convert level_N value to expected dict format. Handles:
    - List of full insight cards (have what_changed, title) -> preserve as-is
    - List of raw dimension objects (have variance_dollar or variance) -> convert to cards
    """
    items = [d for d in val if isinstance(d, dict)]
    if not items:
        return {"insight_cards": [], "total_variance_dollar": 0, "level_name": "Region" if level_num == 1 else f"Level {level_num}"}
    first = items[0]
    if first.get("what_changed") is not None and first.get("title"):
        return {
            "insight_cards": items,
            "total_variance_dollar": sum(
                (d.get("evidence") or {}).get("variance_dollar", d.get("variance", d.get("variance_dollar", 0)))
                for d in items
            ),
            "level_name": "Region" if level_num == 1 else f"Level {level_num}",
        }
    return {
        "insight_cards": [
            {
                "title": d.get("dimension", d.get("title", d.get("name", d.get("item", "Unknown")))),
                "what_changed": f"Variance of ${d.get('variance', d.get('variance_dollar', 0)):,.0f}",
                "priority": "low",
            }
            for d in items
        ],
        "total_variance_dollar": sum(d.get("variance", d.get("variance_dollar", 0)) for d in items),
        "level_name": "Region" if level_num == 1 else f"Level {level_num}",
    }


def _normalize_hierarchical_results(parsed) -> dict:
    """
    Normalize hierarchical_results to dict with level_N keys.
    Handles: list of level objects, level_N with list value, HIERARCHICAL_LEVEL_N keys, Level 0/1 keys.
    """
    if isinstance(parsed, list):
        # List format: [{"level": 0, "level_name": "Total", "insight_cards": [...]}, ...]
        out = {}
        for item in parsed:
            if not isinstance(item, dict):
                continue
            lvl = item.get("level", len(out))
            key = f"level_{lvl}"
            out[key] = item
        return out

    if not isinstance(parsed, dict):
        return {}

    # level_0, level_1 with dict values - ensure list values are converted
    if any(k.startswith("level_") for k in parsed.keys()):
        out = {}
        for key, val in parsed.items():
            if not key.startswith("level_"):
                continue
            try:
                lvl = int(key.split("_")[1])
            except (IndexError, ValueError):
                continue
            if isinstance(val, list):
                out[key] = _convert_level_list_to_dict(val, lvl)
            elif isinstance(val, dict):
                out[key] = val
            else:
                parsed_val = _parse_json_safe(val)
                if isinstance(parsed_val, list):
                    out[key] = _convert_level_list_to_dict(parsed_val, lvl)
                elif isinstance(parsed_val, dict):
                    out[key] = parsed_val
        return out if out else parsed

    # HIERARCHICAL_LEVEL_0 -> level_0
    out = {}
    for key, val in parsed.items():
        if key.startswith("HIERARCHICAL_LEVEL_"):
            try:
                lvl = int(key.split("_")[-1])
                out[f"level_{lvl}"] = val if isinstance(val, dict) else _parse_json_safe(val)
            except (IndexError, ValueError):
                pass
        elif key.startswith("Level ") and isinstance(val, dict):
            try:
                lvl = int(key.split()[-1])
                out[f"level_{lvl}"] = val
            except (IndexError, ValueError):
                pass
        elif key.startswith("Level ") and isinstance(val, list):
            try:
                lvl = int(key.split()[-1])
                out[f"level_{lvl}"] = _convert_level_list_to_dict(val, lvl)
            except (IndexError, ValueError):
                pass
    return out if out else parsed


def _collect_insight_cards(level_data: dict) -> list:
    """Return insight_cards from level data regardless of storage format."""
    cards = level_data.get("insight_cards", [])
    if not cards:
        # Fallback: convert top_drivers to card-like dicts
        for d in level_data.get("top_drivers", []) or level_data.get("top_items", []):
            item = d.get("item", "Unknown")
            var_d = d.get("variance_dollar", 0)
            var_p = d.get("variance_pct") # May be None
            is_new = bool(d.get("is_new_from_zero", False))
            
            if is_new:
                pct_str = "new from zero"
            elif var_p is not None:
                pct_str = f"{var_p:+.1f}%"
            else:
                pct_str = "N/A"
                
            cards.append({
                "title": f"{item}: ${var_d:+,.0f} ({pct_str})",
                "what_changed": f"Variance of ${var_d:+,.0f} ({pct_str})",
                "why": d.get("why", ""),
                "priority": d.get("materiality", "LOW").lower(),
                "now_what": "",
            })
    return cards


from data_analyst_agent.utils.env_utils import parse_bool_env


async def generate_markdown_report(
    hierarchical_results: str,
    analysis_target: Optional[str] = None,
    analysis_period: Optional[str] = None,
    statistical_summary: Optional[str] = None,
    narrative_results: Optional[str] = None,
    target_label: Optional[str] = None,
    cost_center: Optional[str] = None,
) -> str:
    """
    Generate executive 1-pager in Markdown format.

    See ../SCHEMA.md for canonical JSON formats. Handles multiple input shapes;
    hierarchical_results supports level_0/level_1 (object or array) and
    HIERARCHICAL_LEVEL_N keys (normalized internally).

    Args:
        hierarchical_results: JSON string with hierarchical analysis results
        analysis_target: Optional analysis target identification (e.g., metric name)
        analysis_period: Optional analysis period
        statistical_summary: Optional JSON string with statistical analysis including
            utilization ratios, degradation alerts, outliers, and trend data
        narrative_results: Optional JSON string from narrative agent
        target_label: Dataset-specific label for the target (from contract)
        cost_center: Optional friendly identifier (overrides analysis_target in output)

    Returns:
        Markdown-formatted report string
    """
    try:
        target_name = cost_center or analysis_target or "unknown"
        # Parse hierarchical results — handles list, dict, and normalised formats.
        # List: [{"level": 0, ...}, {"level": 1, ...}] — normalised to level_N dict.
        # Dict: {"level_0": {...}, "level_1": {...}} or {"HIERARCHICAL_LEVEL_0": {...}}.
        raw = _parse_json_safe(hierarchical_results)
        results = _normalize_hierarchical_results(raw)

        if isinstance(raw, dict) and "level_analyses" in raw:
            # Normalised format from legacy agent
            levels_analyzed = raw.get("levels_analyzed", [])
            level_analyses = raw.get("level_analyses", {})
            drill_down_path = raw.get("drill_down_path", "N/A")
        else:
            # Flat format: {"level_0": {...}, "level_1": {...}} (after normalization)
            level_analyses = {}
            levels_analyzed = []
            for key, val in results.items():
                if key.startswith("level_"):
                    try:
                        lvl_num = int(key.split("_")[1])
                    except (IndexError, ValueError):
                        continue
                    parsed = val if isinstance(val, dict) else _parse_json_safe(val)
                    if parsed:
                        level_analyses[key] = parsed
                        levels_analyzed.append(lvl_num)
            levels_analyzed = sorted(set(levels_analyzed))
            drill_down_path = " -> ".join([f"Level {l}" for l in levels_analyzed]) if levels_analyzed else "N/A"

        # Parse narrative results
        narrative_data = _parse_json_safe(narrative_results) if narrative_results else {}
        narrative_cards: list = narrative_data.get("insight_cards", [])
        narrative_summary: str = narrative_data.get("narrative_summary", "")
        stats_data_for_grain = _parse_json_safe(statistical_summary) if statistical_summary else {}
        summary_stats_for_grain = stats_data_for_grain.get("summary_stats", {}) if isinstance(stats_data_for_grain, dict) else {}
        metadata_for_grain = stats_data_for_grain.get("metadata", {}) if isinstance(stats_data_for_grain, dict) else {}
        temporal_grain = (
            summary_stats_for_grain.get("temporal_grain")
            or metadata_for_grain.get("temporal_grain")
            or "monthly"
        )
        period_label = "week" if temporal_grain == "weekly" else "month"
        short_delta_label = "WoW" if temporal_grain == "weekly" else "MoM"

        # Build markdown report
        label = target_label or "P&L Analysis"
        md = []
        md.append(f"# {label} Report - {target_name}")
        md.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        if analysis_period:
            md.append(f"**Period:** {analysis_period}")
        if cost_center:
            md.append(f"**Cost Center {target_name}**")
        md.append("")

        # === EXECUTIVE SUMMARY ===
        md.append("## Executive Summary")
        md.append("")

        if narrative_summary:
            md.append(narrative_summary)
            md.append("")

        # Get top-level summary from the shallowest level
        unit = _resolve_unit(target_name or "")
        
        # Detect lag metadata
        lag_meta = None
        all_inputs = [hierarchical_results, statistical_summary, narrative_results]
        for inp in all_inputs:
            if not inp: continue
            parsed = _parse_json_safe(inp)
            if isinstance(parsed, dict):
                if "lag_metadata" in parsed and parsed["lag_metadata"]:
                    lag_meta = parsed["lag_metadata"]
                    break
                # Check hierarchical level_0
                l0 = parsed.get("level_0")
                if isinstance(l0, dict) and l0.get("lag_metadata"):
                    lag_meta = l0["lag_metadata"]
                    break
        
        shallowest_level = min(levels_analyzed) if levels_analyzed else None
        if shallowest_level is not None:
            lvl0_data = level_analyses.get(f"level_{shallowest_level}", {})
            total_var = lvl0_data.get("total_variance_dollar", 0)
            if total_var:
                md.append(f"- **Total Variance:** {_format_variance(total_var, unit, target_name)}")
        
        if lag_meta:
            lag_p = lag_meta.get("lag_periods", 0)
            eff_latest = lag_meta.get("effective_latest") or lag_meta.get("effective_latest_period")
            md.append(f"- **Data Maturity:** Lagging ({lag_p} periods lag, analysis through {eff_latest})")
            
        md.append(f"- **Analysis Depth:** {drill_down_path}")
        md.append(f"- **Detected Temporal Grain:** {temporal_grain.title()}")
        md.append("")

        # === INSIGHT CARDS (from NarrativeAgent + Hierarchy drill-downs) ===
        # Narrative cards = primary findings. Hierarchy drill-downs = derived (explain which
        # dimensions cause the trend). When narrative already has regional_distribution/hierarchy
        # tag, omit hierarchy-derived cards from Insight Cards to avoid duplication.
        priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        all_cards = list(narrative_cards) if narrative_cards else []
        if narrative_cards or level_analyses:
            try:
                max_primary = max(3, min(int(os.environ.get("MAX_TOP_CRITICAL_INSIGHTS", "5")), 10))
            except (ValueError, TypeError):
                max_primary = 5
            try:
                max_derived = max(0, min(int(os.environ.get("MAX_DERIVED_INSIGHTS", "3")), 5))
            except (ValueError, TypeError):
                max_derived = 3
            try:
                max_hierarchy_derived = max(0, min(int(os.environ.get("MAX_HIERARCHY_DRILLDOWN_INSIGHTS", "0")), 10))
            except (ValueError, TypeError):
                max_hierarchy_derived = 5
            # Deduplication: if narrative already has regional_distribution card, skip hierarchy
            def _card_tags(c):
                return set(str(t).lower() for t in (c.get("tags") or []))
            has_regional_narrative = any(
                bool(_card_tags(c) & {"regional_distribution", "hierarchy", "regional_analysis"})
                for c in (narrative_cards or [])
                if isinstance(c, dict)
            )
            if has_regional_narrative and max_hierarchy_derived > 0:
                max_hierarchy_derived = 0

            sorted_cards = sorted(
                all_cards,
                key=lambda c: (priority_order.get(str(c.get("priority", "low")).lower(), 3), -c.get("impact_score", 0.0)),
            )
            primary = [c for c in sorted_cards if str(c.get("priority", "")).lower() in ("critical", "high")][:max_primary]
            remaining = [c for c in sorted_cards if c not in primary]
            card_tags = _card_tags
            derived = [c for c in remaining if card_tags(c) & _DERIVED_TAGS][:max_derived]

            # Collect hierarchy drill-down cards (level_1, level_2, ...) as derived—they show
            # which dimensions cause the top-level trend (e.g. East +2557, Central +1809).
            # Skip zero-variance cards. Default 0 = omit (narrative usually covers it).
            hierarchy_derived = []
            for lvl in sorted(levels_analyzed):
                if lvl == 0:
                    continue  # Level 0 is aggregate; drill-downs start at level_1
                lvl_data = level_analyses.get(f"level_{lvl}", {})
                for card in _collect_insight_cards(lvl_data):
                    if _is_skip_card(card):
                        continue
                    if card not in primary and card not in derived and card not in hierarchy_derived:
                        hierarchy_derived.append(card)
                        if len(hierarchy_derived) >= max_hierarchy_derived:
                            break
                if len(hierarchy_derived) >= max_hierarchy_derived:
                    break

            combined_derived = derived + hierarchy_derived
            fallback_limit = max(0, 10 - len(primary) - len(combined_derived))
            fallback = [c for c in remaining if c not in derived][:fallback_limit]
            final_cards = primary + combined_derived + fallback if (primary or combined_derived or fallback) else sorted_cards
            final_cards = [c for c in final_cards if not _is_skip_card(c)]

            md.append("## Insight Cards")
            md.append("")
            for card in final_cards:
                priority = str(card.get("priority", "low")).upper()
                title = card.get("title", "Untitled")
                what = card.get("what_changed", "")
                why = card.get("why", "")
                now_what = card.get("now_what", "")
                root_cause = card.get("root_cause", "")
                tags = ", ".join(card.get("tags", []))

                md.append(f"### [{priority}] {title}")
                if root_cause:
                    md.append(f"**Root Cause:** {root_cause}")
                if what:
                    md.append(f"**What Changed:** {what}")
                if why:
                    md.append(f"**Why:** {why}")
                # no_what / action guidance intentionally omitted per analysis policy
                evidence = card.get("evidence", {})
                if evidence and isinstance(evidence, dict):
                    ev_parts = [f"{k}: {v}" for k, v in list(evidence.items())[:4]]
                    md.append(f"**Evidence:** {' | '.join(ev_parts)}")
                if tags:
                    md.append(f"**Tags:** {tags}")
                md.append("")

        # === HIERARCHICAL VARIANCE DRILL-DOWN ===
        # Omit full section when REPORT_CONDENSED=1 (Exec Summary already has depth)
        condensed = parse_bool_env(os.environ.get("REPORT_CONDENSED", "0"))
        if not condensed:
            md.append("## Hierarchical Drill-Down Path")
            md.append("")
            md.append(f"Analysis Path: **{drill_down_path}**")
            md.append("")
            level_label_map = {
                0: "Total (All Terminals)", 1: "Region", 2: "Terminal", 3: "Sub-Terminal"
            }
            for level in levels_analyzed:
                level_key = f"level_{level}"
                level_data = level_analyses.get(level_key, {})
                level_name = level_data.get("level_name") or level_label_map.get(level, f"Level {level}")
                total_var = level_data.get("total_variance_dollar", 0)

                md.append(f"### Level {level}: {level_name}")
                if total_var:
                    md.append(f"- **Total Variance:** {_format_variance(total_var, unit, target_name)}")

                # Show insight cards from hierarchy agent (skip zero-variance)
                cards = [c for c in _collect_insight_cards(level_data) if not _is_skip_card(c)]
                if cards:
                    for card in cards[:5]:
                        p = str(card.get("priority", "")).upper()
                        t = card.get("title", card.get("item", ""))
                        w = card.get("what_changed", "")
                        prefix = f"[{p}] " if p else ""
                        line = f"- **{prefix}{t}**"
                        if w:
                            line += f" — {w}"
                        md.append(line)
                elif total_var:
                    md.append(f"- Total: {_format_variance(total_var, unit, target_name)}")
                md.append("")

        # === INDEPENDENT LEVEL FINDINGS (spec 035) ===
        # Only rendered when INDEPENDENT_LEVEL_ANALYSIS=true produced net-new findings
        ind_level_results = raw.get("independent_level_results", {}) if isinstance(raw, dict) else {}
        if ind_level_results and not condensed:
            ind_cards_total = 0
            ind_sections = []
            for lvl_key in sorted(ind_level_results.keys()):
                lvl_data = ind_level_results[lvl_key]
                if isinstance(lvl_data, str):
                    lvl_data = _parse_json_safe(lvl_data)
                if not isinstance(lvl_data, dict):
                    continue
                cards = [c for c in _collect_insight_cards(lvl_data) if not _is_skip_card(c)]
                if not cards:
                    continue
                level_name = lvl_data.get("level_name", lvl_key)
                ind_sections.append((level_name, cards))
                ind_cards_total += len(cards)

            if ind_cards_total > 0:
                md.append("## Independent Level Findings")
                md.append(
                    "*These findings were discovered by flat-scanning individual hierarchy levels, "
                    "bypassing the top-down drill-down gate. They represent anomalies that were "
                    "masked at higher levels by offsetting data.*"
                )
                md.append("")
                for level_name, cards in ind_sections:
                    md.append(f"### {level_name} (independent scan)")
                    for card in cards[:5]:
                        p = str(card.get("priority", "")).upper()
                        t = card.get("title", card.get("item", ""))
                        w = card.get("what_changed", "")
                        prefix = f"[{p}] " if p else ""
                        line = f"- **{prefix}{t}**"
                        if w:
                            line += f" — {w}"
                        md.append(line)
                    md.append("")

        # === CROSS-DIMENSION ANALYSIS ===
        cross_dim_results = raw.get("cross_dimension_results", {}) if isinstance(raw, dict) else {}
        if cross_dim_results and not condensed:
            md.append("## Cross-Dimension Analysis")
            md.append("")
            for level_key, dim_results in sorted(cross_dim_results.items()):
                if not isinstance(dim_results, dict):
                    continue
                for dim_name, dim_data_raw in dim_results.items():
                    dim_data = _parse_json_safe(dim_data_raw) if isinstance(dim_data_raw, str) else dim_data_raw
                    if not isinstance(dim_data, dict) or dim_data.get("skipped") or dim_data.get("error"):
                        continue

                    level_num = level_key.replace("level_", "")
                    summary = dim_data.get("summary", {})
                    independence = dim_data.get("independence_test", {})
                    hier_dim = dim_data.get("hierarchy_dimension", f"Level {level_num}")

                    md.append(f"### {hier_dim} x {dim_name} (Level {level_num})")

                    aux_eta = independence.get("auxiliary_eta_squared", 0)
                    inter_eta = independence.get("interaction_eta_squared", 0)
                    inter_p = independence.get("interaction_p_value")

                    if aux_eta > 0 or inter_eta > 0:
                        parts = []
                        if aux_eta > 0.01:
                            parts.append(f"{dim_name} explains {aux_eta:.0%} of variance")
                        if inter_eta > 0.01:
                            sig = f" (p={inter_p:.4f})" if inter_p is not None else ""
                            parts.append(f"interaction effect: {inter_eta:.0%}{sig}")
                        md.append(f"- **ANOVA:** {'; '.join(parts)}")

                    for pattern in dim_data.get("cross_cutting_patterns", [])[:3]:
                        md.append(f"- **{pattern.get('auxiliary_value')}:** {pattern.get('label', '')}")

                    for trend in dim_data.get("trends", [])[:2]:
                        md.append(f"- **Trend:** {trend.get('label', '')}")

                    for cell in dim_data.get("anomalous_cells", [])[:3]:
                        md.append(f"- **Anomaly:** {cell.get('label', '')}")

                    if summary.get("recommendation"):
                        md.append(f"- {summary['recommendation']}")
                    md.append("")

        # === VARIANCE DRIVERS TABLE (legacy format support) ===
        # Only shown when top_drivers format is present
        deepest_level = max(levels_analyzed) if levels_analyzed else None
        if deepest_level is not None:
            deepest_analysis = level_analyses.get(f"level_{deepest_level}", {})
            drivers = deepest_analysis.get("top_drivers", [])
            if drivers:
                md.append("## Variance Drivers")
                md.append("")
                md.append("| Rank | Category/GL | Variance $ | Variance % | Materiality | Cumulative % |")
                md.append("|------|-------------|------------|------------|-------------|--------------|")
                for driver in drivers[:10]:
                    rank = driver.get("rank", "-")
                    item = driver.get("item", "Unknown")
                    var_dollar = driver.get("variance_dollar", 0)
                    var_pct = driver.get("variance_pct")
                    is_new = bool(driver.get("is_new_from_zero", False))
                    materiality = driver.get("materiality", "LOW")
                    cumulative = driver.get("cumulative_pct", 0)
                    
                    if is_new:
                        pct_display = "new"
                    elif var_pct is not None:
                        pct_display = f"{var_pct:+.1f}%"
                    else:
                        pct_display = "N/A"
                        
                    md.append(f"| {rank} | {item} | ${var_dollar:+,.0f} | {pct_display} | {materiality} | {cumulative:.1f}% |")
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

        md.append("## Recommended Actions")
        md.append("")
        actions_added = False
        narrative_actions = narrative_data.get("recommended_actions") if isinstance(narrative_data, dict) else None
        if isinstance(narrative_actions, list):
            for action in narrative_actions[:5]:
                if action:
                    md.append(f"- {action}")
                    actions_added = True
        if not actions_added:
            for card in final_cards:
                action = card.get("now_what") or card.get("recommended_action")
                if action:
                    md.append(f"- {action}")
                    actions_added = True
            if not actions_added:
                md.append("- Continue monitoring key drivers and validate mitigation plans.")
        md.append("")

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

            # Grain-aware trend table (last 13 periods)
            md.append(f"### {period_label.title()}ly Trend")
            md.append("")
            md.append(f"| {period_label.title()} | Miles/Trk | {short_delta_label}% | vs Avg | Status |")
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
                    p_val = trend_info.get("p_value")
                    
                    trend_dir = "increasing" if slope > 0 else "decreasing"
                    
                    if p_val is not None:
                        if p_val < 0.05:
                            sig_label = " (significant)"
                        else:
                            sig_label = " (directional)"
                        md.append(f"- **{metric_label} Trend**: {trend_dir}{sig_label} (slope={slope:.4f}, p={p_val:.4f})")
                    else:
                        md.append(f"- **{metric_label} Trend**: {trend_dir} (slope={slope:.4f}, CV={cv:.3f})")

            if util_alerts:
                md.append(f"- **Degradation Alerts**: {len(util_alerts)} metric(s) below baseline")
                for alert in util_alerts:
                    md.append(f"  - {alert.get('label', alert.get('metric'))}: {alert.get('variance_pct', 0):+.1f}% vs 3M baseline [{alert.get('severity')}]")

            md.append("")

        # === DATA QUALITY NOTES ===
        md.append("## Data Quality & Notes")
        md.append("")
        
        if lag_meta and lag_meta.get("lag_window"):
            window = lag_meta["lag_window"]
            md.append(f"### [SUPPRESSED] Incomplete Data Window")
            md.append(f"Signals from the following periods were suppressed as data is still accumulating: {', '.join(window)}.")
            md.append("")

        md.append(f"- Analysis completed successfully with {len(levels_analyzed)} hierarchy levels")
        md.append(f"- Drill-down path: {drill_down_path}")
        md.append(f"- Temporal grain detected as {temporal_grain} (comparisons interpreted as {short_delta_label})")
        md.append("- All variance calculations use category-specific materiality thresholds")
        if util_ratios:
            md.append(f"- Utilization analysis: {len(util_ratios)} periods, {util_summary.get('metrics_computed', 0)} metrics")
            md.append(f"- Data source: Ops Metrics DS via A2A")
        md.append("")
        md.append("---")
        md.append("*This report was auto-generated by Data Analyst Agent*")

        return "\n".join(md)

    except Exception as e:
        return f"# Error Generating Report\n\nError: {str(e)}"
