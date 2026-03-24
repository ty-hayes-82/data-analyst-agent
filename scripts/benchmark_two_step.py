"""Two-step executive brief pipeline benchmark (v2).

Step 1: Flash-Lite condenses ALL metrics into a clean structured summary.
Step 2: 3.1 Pro synthesizes the final CEO brief using a schema with named keys.

Changes from v1:
- Step 1 prompt requires ALL metrics (no filtering), adds unit types, requests contradictions
- Step 2 uses a flat CEO schema (bottom_line, what_moved, etc.) instead of generic sections[]
- Pre-computed network totals with correct units injected into Step 2
- Pre-computed contradiction flags injected into Step 2
- JSON output example + anti-pattern guardrails in Step 2 system instruction
- No scoring -- stores raw inputs and outputs for manual review.
"""

import os
import sys
import json
import time
import asyncio
from pathlib import Path
from dataclasses import dataclass, asdict, field
from typing import Any, Dict, List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from data_analyst_agent.config import config
from google import genai
from google.genai import types

from data_analyst_agent.sub_agents.executive_brief_agent.report_utils import (
    _build_slim_digest_from_json,
)

FLASH_LITE = "gemini-3.1-flash-lite-preview"
FLASH = "gemini-3-flash-preview"
PRO = "gemini-3.1-pro-preview"

STEP2_MODEL = os.environ.get("STEP2_MODEL", PRO)

CACHE_DIR = (
    PROJECT_ROOT
    / "outputs" / "ops_metrics_ds" / "lob_ref" / "Line_Haul"
    / "20260323_115554" / ".cache"
)
CACHE_PATH = CACHE_DIR / "digest.json"

ITERATIONS = 3

METRIC_META = {
    "ttl_rev_xf_sr_amt": {"label": "Total Revenue xFSR",    "unit": "currency", "category": "Revenue / yield",     "fmt": "$"},
    "lrpm":              {"label": "LRPM",                   "unit": "currency", "category": "Revenue / yield",     "fmt": "$"},
    "trpm":              {"label": "TRPM",                   "unit": "currency", "category": "Revenue / yield",     "fmt": "$"},
    "rev_trk_day":       {"label": "Rev/Trk/Day",           "unit": "currency", "category": "Productivity",        "fmt": "$"},
    "total_miles_rpt":   {"label": "Total Miles",           "unit": "miles",    "category": "Productivity",        "fmt": ""},
    "miles_trk_wk":      {"label": "Miles/Trk/Wk",         "unit": "miles",    "category": "Productivity",        "fmt": ""},
    "avg_loh":           {"label": "Avg LOH",               "unit": "miles",    "category": "Productivity",        "fmt": ""},
    "truck_count_avg":   {"label": "Truck Count",           "unit": "count",    "category": "Capacity",            "fmt": ""},
    "deadhead_pct":      {"label": "Deadhead %",            "unit": "percentage","category": "Network efficiency", "fmt": "%"},
}


def _fmt_value(val, metric_name: str) -> str:
    """Format a value using the correct unit for its metric."""
    if val is None:
        return "N/A"
    meta = METRIC_META.get(metric_name, {})
    unit = meta.get("unit", "")
    if unit == "currency":
        abs_val = abs(val)
        sign = "-" if val < 0 else ""
        if abs_val >= 1_000_000:
            return f"{sign}${abs_val/1_000_000:.1f}M"
        if abs_val >= 1_000:
            return f"{sign}${abs_val/1_000:.1f}K"
        return f"{sign}${abs_val:,.2f}"
    if unit == "percentage":
        return f"{val:.1f}%"
    if unit == "miles":
        abs_val = abs(val)
        sign = "-" if val < 0 else ""
        if abs_val >= 1_000_000:
            return f"{sign}{abs_val/1_000_000:.1f}M"
        if abs_val >= 1_000:
            return f"{sign}{abs_val/1_000:.1f}K"
        return f"{sign}{abs_val:,.0f}"
    if unit == "count":
        abs_val = abs(val)
        sign = "-" if val < 0 else ""
        if abs_val >= 1_000:
            return f"{sign}{abs_val/1_000:.1f}K"
        return f"{sign}{abs_val:,.0f}"
    return f"{val}"


def _fmt_change(val, metric_name: str) -> str:
    """Format a change value with +/- sign."""
    if val is None:
        return "N/A"
    meta = METRIC_META.get(metric_name, {})
    unit = meta.get("unit", "")
    sign = "+" if val >= 0 else ""
    if unit == "currency":
        abs_val = abs(val)
        if abs_val >= 1_000_000:
            return f"{sign}${val/1_000_000:.1f}M"
        if abs_val >= 1_000:
            return f"{sign}${val/1_000:.1f}K"
        return f"{sign}${val:,.2f}"
    if unit == "percentage":
        return f"{sign}{val:.1f} pts"
    if unit == "miles":
        abs_val = abs(val)
        if abs_val >= 1_000_000:
            return f"{sign}{val/1_000_000:.1f}M mi"
        if abs_val >= 1_000:
            return f"{sign}{val/1_000:.1f}K mi"
        return f"{sign}{val:,.0f} mi"
    if unit == "count":
        abs_val = abs(val)
        if abs_val >= 1_000:
            return f"{sign}{val/1_000:.1f}K"
        return f"{sign}{val:,.0f}"
    return f"{sign}{val}"


# ---------------------------------------------------------------------------
# Change 1: New CEO response schema with named keys
# ---------------------------------------------------------------------------

def _build_ceo_brief_schema() -> types.Schema:
    return types.Schema(
        type=types.Type.OBJECT,
        properties={
            "bottom_line": types.Schema(
                type=types.Type.STRING,
                description="2 sentences. First = verdict with thesis. Second = the 'but' (what the headline hides about quality).",
            ),
            "what_moved": types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(type=types.Type.STRING),
                min_items=3, max_items=4,
                description="Each item: 'Label: value, change, context'. Terse fragments, NOT sentences.",
            ),
            "trend_status": types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(type=types.Type.STRING),
                min_items=2, max_items=4,
                description="One-line items. Embed classification: positive momentum, developing trend, persistent issue, one-week noise, watchable.",
            ),
            "where_it_came_from": types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "positive": types.Schema(type=types.Type.STRING, description="Region / Terminal -- reason with numbers"),
                    "drag": types.Schema(type=types.Type.STRING, description="Region / Terminal -- reason with numbers"),
                    "watch": types.Schema(type=types.Type.STRING, description="Region / Terminal -- reason with numbers"),
                },
                required=["positive", "drag", "watch"],
            ),
            "why_it_matters": types.Schema(
                type=types.Type.STRING,
                description="1 sentence connecting execution to earnings quality. Opinionated.",
            ),
            "outlook": types.Schema(
                type=types.Type.STRING,
                description="1-2 conditional sentences about next week.",
            ),
            "leadership_focus": types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(type=types.Type.STRING),
                min_items=3, max_items=3,
                description="Imperative verb first. Under 12 words. DECISIONS not analysis. Never use Investigate/Analyze/Monitor/Review.",
            ),
        },
        required=["bottom_line", "what_moved", "trend_status",
                   "where_it_came_from", "why_it_matters", "outlook",
                   "leadership_focus"],
    )

CEO_BRIEF_SCHEMA = _build_ceo_brief_schema()


# ---------------------------------------------------------------------------
# Data sanitization
# ---------------------------------------------------------------------------

def sanitize_json_data(json_data: Dict[str, Any]) -> Dict[str, Any]:
    cleaned = {}
    for metric, payload in json_data.items():
        p = json.loads(json.dumps(payload))
        if "alert_scoring" in p.get("analysis", {}):
            ab = p["analysis"]["alert_scoring"]
            ab.pop("all_scored_alerts", None)
            ab.pop("suppressed_alerts", None)
        h = p.get("hierarchical_analysis", {})
        for level in ("level_1", "level_2"):
            if level in h:
                drivers = h[level].get("top_drivers", [])
                h[level]["top_drivers"] = [
                    d for d in drivers
                    if not (d.get("item") == "Corporate" and d.get("share_current", 1.0) < 0.01)
                ]

        def _clean(obj):
            if isinstance(obj, float):
                if obj != obj or obj == float("inf") or obj == float("-inf"):
                    return None
                return obj
            if isinstance(obj, dict):
                return {k: _clean(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_clean(x) for x in obj]
            return obj

        cleaned[metric] = _clean(p)
    return cleaned


# ---------------------------------------------------------------------------
# Change 2: Pre-compute network totals with correct units
# ---------------------------------------------------------------------------

def build_network_totals(json_data: Dict[str, Any]) -> str:
    lines = []
    for metric in sorted(json_data.keys()):
        payload = json_data[metric]
        h = payload.get("hierarchical_analysis", {})
        l0 = h.get("level_0", {})
        drivers = l0.get("top_drivers", [])
        if not drivers:
            continue
        d = drivers[0]
        current = d.get("current")
        variance = d.get("variance_dollar")
        pct = d.get("variance_pct")
        if current is None:
            continue
        meta = METRIC_META.get(metric, {})
        label = meta.get("label", metric)
        curr_s = _fmt_value(current, metric)
        var_s = _fmt_change(variance, metric) if variance is not None else "N/A"
        pct_s = f"{pct:+.1f}%" if pct is not None else ""
        lines.append(f"  {label} ({metric}): {curr_s} ({var_s}, {pct_s} WoW)")
    return "NETWORK TOTALS (cite these EXACT numbers):\n" + "\n".join(lines)


# ---------------------------------------------------------------------------
# Change 4: Pre-compute contradiction flags
# ---------------------------------------------------------------------------

def build_contradiction_flags(json_data: Dict[str, Any]) -> str:
    flags = []

    dh_data = json_data.get("deadhead_pct", {}).get("hierarchical_analysis", {})
    mi_data = json_data.get("total_miles_rpt", {}).get("hierarchical_analysis", {})
    rev_data = json_data.get("ttl_rev_xf_sr_amt", {}).get("hierarchical_analysis", {})

    def _driver_map(h_data, level="level_2"):
        return {d["item"]: d for d in h_data.get(level, {}).get("top_drivers", [])}

    dh_drivers = _driver_map(dh_data)
    mi_drivers = _driver_map(mi_data)
    rev_drivers = _driver_map(rev_data)

    for terminal in set(dh_drivers) & set(mi_drivers):
        dh_pct = dh_drivers[terminal].get("variance_pct", 0)
        mi_pct = mi_drivers[terminal].get("variance_pct", 0)
        if dh_pct is None or mi_pct is None:
            continue
        if (dh_pct > 10 and mi_pct > 10):
            flags.append(
                f"  {terminal}: deadhead {dh_pct:+.1f}% AND miles {mi_pct:+.1f}% "
                f"-- more miles but also more empty running, explain mechanism"
            )
        if (dh_pct > 10 and mi_pct < -10):
            flags.append(
                f"  {terminal}: deadhead {dh_pct:+.1f}% while miles {mi_pct:+.1f}% "
                f"-- fewer miles but worse routing, explain mechanism"
            )

    for terminal in set(rev_drivers) & set(mi_drivers):
        rev_pct = rev_drivers[terminal].get("variance_pct", 0)
        mi_pct = mi_drivers[terminal].get("variance_pct", 0)
        if rev_pct is None or mi_pct is None:
            continue
        if abs(rev_pct - mi_pct) > 15 and abs(rev_pct) > 10:
            flags.append(
                f"  {terminal}: revenue {rev_pct:+.1f}% vs miles {mi_pct:+.1f}% "
                f"-- revenue/volume divergence signals yield shift"
            )

    # Derived KPI vs raw metric: LRPM/TRPM declining while revenue stable
    for kpi_name, raw_name in [("lrpm", "ttl_rev_xf_sr_amt"), ("trpm", "ttl_rev_xf_sr_amt")]:
        kpi = json_data.get(kpi_name, {}).get("hierarchical_analysis", {}).get("level_0", {}).get("top_drivers", [])
        raw = json_data.get(raw_name, {}).get("hierarchical_analysis", {}).get("level_0", {}).get("top_drivers", [])
        if kpi and raw:
            kpi_pct = kpi[0].get("variance_pct", 0)
            raw_pct = raw[0].get("variance_pct", 0)
            if kpi_pct is not None and raw_pct is not None:
                if abs(kpi_pct) < 1 and abs(raw_pct) > 1:
                    flags.append(
                        f"  {kpi_name.upper()} {kpi_pct:+.1f}% vs Revenue {raw_pct:+.1f}% "
                        f"-- yield holding while volume drops, explain mechanism"
                    )

    if not flags:
        return ""
    return "CROSS-METRIC CONTRADICTIONS (you MUST explain each):\n" + "\n".join(flags)


# ---------------------------------------------------------------------------
# Step 1 prompt: Flash-Lite condenses ALL metrics (no filtering)
# ---------------------------------------------------------------------------

STEP1_SYSTEM = """You are a data analyst preparing a condensed briefing packet for a COO's chief of staff.

Your job: take raw operational insight cards and produce a CLEAN, STRUCTURED summary.
You are NOT writing the brief. You are organizing the evidence so a strategist can write it.

OUTPUT: valid JSON matching the schema below. First character must be `{`.

RULES:
1. Summarize ALL metrics -- even those with small network-level variance. Small yield changes (LRPM, TRPM) carry major strategic signal even at -0.4%.
2. Preserve ALL numbers EXACTLY as they appear. Never round, recompute, or estimate.
3. Drop any entity named "Corporate" with share < 1%.
4. If a numeric value is Infinity, NaN, or null, flag it in data_quality_flags and exclude from facts.
5. For each metric, extract: network-level current value, WoW change (absolute + %), and top 2-3 terminal drivers.
6. Use the CORRECT UNIT for each metric (provided in the input). Do NOT use "$" for miles, percentages, or counts.
7. Group related metrics into cross_metric_stories (e.g., deadhead_pct + total_miles_rpt, or lrpm + trpm + ttl_rev_xf_sr_amt).
8. Actively look for CONTRADICTIONS between metrics and flag them explicitly.
9. Rank the top 3-5 findings by CEO-level business impact.

JSON SCHEMA:
{
  "period": "week ending YYYY-MM-DD",
  "metric_summaries": [
    {
      "metric": "human-readable metric name",
      "metric_key": "raw metric key",
      "unit": "currency|miles|count|percentage|rate",
      "network_total": {"current": "formatted value", "change": "+/-X", "change_pct": "+/-X.X%"},
      "top_drivers": [
        {"entity": "Name", "change": "+/-X", "change_pct": "+/-X.X%", "share": "X.X%"}
      ],
      "severity": "CRITICAL|HIGH|MEDIUM|LOW",
      "key_insight": "one-sentence finding"
    }
  ],
  "cross_metric_stories": [
    {"title": "short label", "metrics_involved": ["m1", "m2"], "narrative": "one sentence connecting them"}
  ],
  "contradictions": [
    {"metrics": ["m1", "m2"], "entity": "terminal or network", "description": "what conflicts and why it matters"}
  ],
  "top_findings": [
    {"rank": 1, "finding": "one sentence", "evidence": "metric: number"}
  ],
  "data_quality_flags": ["any Infinity/NaN/null issues found"]
}
"""


# ---------------------------------------------------------------------------
# Step 2 prompt: Pro synthesizes brief (Changes 3 + 5)
# ---------------------------------------------------------------------------

STEP2_SYSTEM_TEMPLATE = """# CEO PERFORMANCE BRIEF

You are the COO's chief of staff writing a 60-second mobile brief. You have strong opinions about what matters. You never hedge.

Synthesizing {metric_count} metrics for {analysis_period}.

Output: valid JSON matching the enforced schema. First char `{{`, last char `}}`.

## CRITICAL RULES
- Comparison basis: WoW (week-over-week vs prior week). Say "WoW", "vs prior week", "next week".
- EVERY number must come VERBATIM from the data analyst's summary. Do NOT compute your own.
- DERIVED KPIs (LRPM, TRPM, Rev/Trk/Day, Miles/Trk/Wk, Avg LOH, Deadhead %) carry strategic signal even when small. Cite at least 3 by name and exact value.
- If two metrics contradict (flagged in CROSS-METRIC CONTRADICTIONS), you MUST explain the mechanism -- do not present both without connecting them.
- Emphasize the UNIQUE story of this week's metric mix.

## YOUR VOICE

GOLD STANDARD -- match this EXACTLY:
```
bottom_line: "The week was softer on revenue and worse underneath. Total revenue fell to $54.8M (-4.1% WoW), but the decline was yield-driven -- loaded miles only dropped 2.5% while revenue dropped 4.1%, meaning we moved almost the same freight for less money."

what_moved: [
  "Revenue / yield: LH revenue $44.5M, -3.7% WoW, yield compressing faster than volume",
  "Network efficiency: East deadhead +5.7% WoW, despite fewer total miles",
  "Volume: Rail orders +10.8% WoW, but Rail revenue -5.4% -- taking volume at lower rates",
  "Capacity: Truck count flat, loaded miles -2.5% -- underutilized fleet"
]

trend_status: [
  "Revenue contraction is a persistent issue, now down for multiple consecutive weeks",
  "East deadhead is a developing trend, rising even as network activity declines",
  "Rail yield compression is watchable -- volume up but revenue down is a pricing red flag"
]

where_it_came_from: {{
  "positive": "Rail / Intermodal -- order volume +10.8%, absorbing network share",
  "drag": "East / Columbus -- deadhead +18.5% and revenue -14.0%, worst terminal in the network",
  "watch": "Jurupa Valley -- loaded miles -9.8%, revenue -6.9%, significant capacity underutilization"
}}

why_it_matters: "The business is losing yield faster than it is losing volume, which means we are either conceding pricing or shifting mix toward lower-margin freight -- both compress margins even if volume stabilizes."

outlook: "If yield continues to compress while deadhead rises in the East, margin erosion will accelerate regardless of volume trends."

leadership_focus: [
  "Halt rate concessions on East freight immediately",
  "Intervene on Columbus deadhead -- worst efficiency in network",
  "Renegotiate Rail pricing to confirm new volume is margin-accretive"
]
```

KEY PATTERNS:
- bottom_line has a THESIS: "yield-driven" -- not just "the week was poor"
- what_moved uses CROSS-METRIC insight: "loaded miles -2.5% while revenue -4.1%"
- what_moved lines are TERSE FRAGMENTS: "Label: value, change, context" -- NOT full sentences
- trend_status embeds classification naturally: "is a persistent issue", "is watchable"
- leadership items are DECISIONS with imperative verbs: "Halt", "Intervene", "Renegotiate"

## EXAMPLE OUTPUT (different data -- match this JSON structure EXACTLY)
```json
{{
  "bottom_line": "Revenue improved but the gain was lower quality. Total revenue rose to $54.8M (+2.1% WoW), but the gain was deadhead-driven -- loaded miles grew 4.2% while revenue only grew 2.1%, meaning we hauled more freight for less per mile.",
  "what_moved": [
    "Revenue / yield: LRPM $2.48, -1.9%, compressing despite volume gains",
    "Productivity: Rev/Trk/Day $3,081, +3.4%, driven by Lathrop surge",
    "Network efficiency: Deadhead 14.1%, +0.8 pts, highest in 6 weeks",
    "Capacity: Truck count flat, loaded miles +4.2% -- fleet running harder"
  ],
  "trend_status": [
    "Yield compression is a developing trend, now down two consecutive weeks",
    "East deadhead is a persistent issue, rising even as total miles decline",
    "Lathrop productivity surge is one-week noise until confirmed"
  ],
  "where_it_came_from": {{
    "positive": "Central / Gary -- revenue +12.3% and miles +10.8%, strongest terminal",
    "drag": "East / Columbus -- deadhead +18.5% and revenue -14.0%, worst in network",
    "watch": "Jurupa Valley -- loaded miles -9.8%, capacity underutilization risk"
  }},
  "why_it_matters": "We are growing revenue by running the fleet harder, not smarter -- that works until deadhead costs eat the margin gain.",
  "outlook": "If deadhead normalizes in the East next week, the volume gains become real; if not, margin erosion will accelerate despite top-line growth.",
  "leadership_focus": [
    "Halt rate concessions on East freight immediately",
    "Rebalance Columbus lanes to cut deadhead below 15%",
    "Confirm Lathrop volume is margin-accretive before adding capacity"
  ]
}}
```

## STRUCTURE

**bottom_line**: 2 sentences. First = verdict with thesis. Second = the "but" (what headline hides).

**what_moved**: 3-4 items. Each = "Label: value, change, context". TERSE FRAGMENTS, not sentences.

**trend_status**: 2-4 one-line items. Embed classification: positive momentum, developing trend, persistent issue, one-week noise, watchable.

**where_it_came_from**: exactly 1 positive, 1 drag, 1 watch. Format: "Region / Terminal -- reason with numbers"

**why_it_matters**: 1 sentence. Connects execution to earnings quality. Opinionated.

**outlook**: 1-2 sentences. Conditional. Use "next week".

**leadership_focus**: exactly 3 items. Imperative verb first. Under 12 words. DECISIONS, not analysis.

## GUARDRAILS
- Use ONLY data from the analyst summary. Do NOT invent numbers.
- Network total revenue is ~$23M. Do NOT cite $9-10M as network revenue.
- Use "$" ONLY for currency metrics. Deadhead is a percentage, not dollars.
- When citing a variance: "grew BY $X" or "declined BY $X" -- NOT "grew TO $X"
- Revenue/cost totals must include both absolute AND % change: "-$432K (-1.8%)"

LEADERSHIP ANTI-PATTERNS (automatic reject if any appear):
- "Investigate..." / "Analyze..." / "Monitor..." / "Review..." = REJECTED
- "Prioritize strategies for..." = REJECTED
- Any item over 12 words = REJECTED
GOOD: "Halt Manteno low-margin freight until productivity recovers"
BAD: "Investigate root causes of the Manteno decline"
"""


# ---------------------------------------------------------------------------
# Build Step 1 user message
# ---------------------------------------------------------------------------

def build_step1_user_message(cache_data: dict) -> str:
    json_data = cache_data.get("json_data", {})
    cleaned = sanitize_json_data(json_data)
    metric_names = cache_data.get("metric_names", [])
    period_end = cache_data.get("period_end", "2026-03-14")

    # Priority 1: metrics/ subfolder
    # Priority 2: root
    metrics_dir = run_dir / "metrics"
    search_dirs = [metrics_dir, run_dir] if metrics_dir.exists() else [run_dir]
    
    processed_files = set()
    for s_dir in search_dirs:
        for md_file in sorted(s_dir.glob("metric_*.md")):
            if md_file.name in processed_files:
                continue
            name = md_file.stem.replace("metric_", "").replace("_", " ").replace("-", "/")
            reports[name] = md_file.read_text(encoding="utf-8")
            processed_files.add(md_file.name)

    unit = cache_data.get("presentation_unit")
    slim_digest = _build_slim_digest_from_json(reports, cleaned, unit)

    # Build hierarchy snapshot with CORRECT units
    hierarchy_lines = []
    for metric in sorted(cleaned.keys()):
        payload = cleaned[metric]
        h = payload.get("hierarchical_analysis", {})
        l0 = h.get("level_0", {})
        total_drivers = l0.get("top_drivers", [])
        if not total_drivers:
            continue
        total = total_drivers[0]
        curr = _fmt_value(total.get("current"), metric)
        var = _fmt_change(total.get("variance_dollar"), metric)
        pct = total.get("variance_pct", 0)
        meta = METRIC_META.get(metric, {})
        label = meta.get("label", metric)
        unit_type = meta.get("unit", "unknown")
        line = f"  {label} ({metric}) [{unit_type}]: {curr} ({var}, {pct:+.1f}% WoW)"

        l2 = h.get("level_2", {})
        drivers = l2.get("top_drivers", [])[:3]
        if drivers:
            parts = []
            for d in drivers:
                nm = d.get("item", "?")
                dv = _fmt_change(d.get("variance_dollar"), metric)
                dp = d.get("variance_pct", 0)
                sh = d.get("share_current", 0)
                parts.append(f"{nm} {dv} ({dp:+.1f}%, share {sh:.1%})")
            line += "\n    Drivers: " + " | ".join(parts)
        hierarchy_lines.append(line)

    alerts_lines = []
    for metric in sorted(cleaned.keys()):
        payload = cleaned[metric]
        alerts = payload.get("analysis", {}).get("alert_scoring", {}).get("top_alerts", [])
        for a in alerts:
            pri = a.get("priority", "").upper()
            if pri in ("CRITICAL", "HIGH"):
                dim = a.get("dimension_value", "")
                vpct = a.get("variance_pct", 0)
                alerts_lines.append(f"  [{pri}] {metric} / {dim}: {vpct:+.1f}%")

    # Metric unit reference for Flash-Lite
    unit_ref_lines = []
    for m in sorted(metric_names):
        meta = METRIC_META.get(m, {})
        label = meta.get("label", m)
        unit_type = meta.get("unit", "unknown")
        fmt_hint = {"currency": "use $", "percentage": "use % or pts", "miles": "use miles/mi", "count": "use count"}.get(unit_type, "")
        unit_ref_lines.append(f"  {m}: {label} [{unit_type}] -- {fmt_hint}")

    msg_parts = [
        f"Week ending: {period_end}",
        f"Dataset: Line Haul operations",
        f"Metrics ({len(metric_names)}): {', '.join(sorted(metric_names))}",
        "",
        "METRIC UNITS (use the correct unit for each metric, never use $ for non-currency):",
        "\n".join(unit_ref_lines),
        "",
        "=== EXECUTIVE DIGEST (slim, from statistical analysis) ===",
        slim_digest,
        "",
        "=== HIERARCHY SNAPSHOT (network totals + top terminal drivers) ===",
        "\n".join(hierarchy_lines),
        "",
        "=== HIGH-PRIORITY ALERTS ===",
        "\n".join(alerts_lines) if alerts_lines else "(none)",
        "",
        "IMPORTANT: Summarize ALL 9 metrics in metric_summaries, including LRPM, TRPM, avg_loh, miles_trk_wk, and truck_count_avg even if their network variance is small.",
        "Small yield changes in LRPM/TRPM carry major strategic signal.",
        "",
        "Produce the clean JSON summary now.",
    ]
    return "\n".join(msg_parts)


# ---------------------------------------------------------------------------
# Build Step 2 user message (with network totals + contradictions)
# ---------------------------------------------------------------------------

def build_step2_user_message(step1_output: str, cache_data: dict) -> str:
    json_data = cache_data.get("json_data", {})
    cleaned = sanitize_json_data(json_data)
    metric_names = cache_data.get("metric_names", [])
    period_end = cache_data.get("period_end", "2026-03-14")

    network_totals = build_network_totals(cleaned)
    contradictions = build_contradiction_flags(cleaned)

    parts = [
        "COMPARISON BASIS: WoW (week-over-week vs prior week).",
        f"Week ending: {period_end}",
        f"Metrics: {', '.join(sorted(metric_names))}",
        "Dataset: Line Haul operations",
        "",
        network_totals,
        "",
    ]
    if contradictions:
        parts.append(contradictions)
        parts.append("")

    parts.extend([
        "Below is the DATA ANALYST'S STRUCTURED SUMMARY of this week's operational data.",
        "Every number was extracted verbatim from source data -- treat as ground truth.",
        "",
        step1_output,
        "",
        "Generate the CEO brief JSON matching the enforced schema.",
    ])
    return "\n".join(parts)


def build_step2_instruction(cache_data: dict) -> str:
    metric_names = cache_data.get("metric_names", [])
    analysis_period = cache_data.get("analysis_period", "Dec 07, 2025 - Mar 14, 2026")
    return STEP2_SYSTEM_TEMPLATE.format(
        metric_count=len(metric_names),
        analysis_period=analysis_period,
    )


# ---------------------------------------------------------------------------
# LLM call helper
# ---------------------------------------------------------------------------

async def call_llm(client, model: str, system: str, user_msg: str,
                    response_schema=None, thinking_config=None,
                    timeout: int = 120) -> tuple[str, int]:
    cfg_kwargs: dict[str, Any] = {
        "system_instruction": system,
        "temperature": 0.2,
    }
    if response_schema:
        cfg_kwargs["response_mime_type"] = "application/json"
        cfg_kwargs["response_schema"] = response_schema
    if thinking_config:
        cfg_kwargs["thinking_config"] = thinking_config

    gen_config = types.GenerateContentConfig(**cfg_kwargs)

    t0 = time.perf_counter()
    response = await asyncio.wait_for(
        asyncio.to_thread(
            client.models.generate_content,
            model=model,
            contents=user_msg,
            config=gen_config,
        ),
        timeout=timeout,
    )
    ms = int((time.perf_counter() - t0) * 1000)
    return response.text or "", ms


# ---------------------------------------------------------------------------
# Thinking level configurations to benchmark
# ---------------------------------------------------------------------------

THINKING_LEVELS: list[dict[str, Any]] = [
    {"label": "off",      "budget": 0,     "desc": "No thinking (instant)"},
    {"label": "low",      "budget": 1024,  "desc": "Brief logical check"},
    {"label": "medium",   "budget": 8192,  "desc": "Balanced reasoning"},
    {"label": "adaptive", "budget": None,  "desc": "Model decides (default)"},
]


def _make_thinking_config(budget: int | None):
    """Build a ThinkingConfig or None for adaptive/default."""
    if budget is None:
        return None
    return types.ThinkingConfig(thinking_budget=budget)


def _strip_fences(raw: str) -> str:
    """Remove markdown code fences from LLM output."""
    import re
    stripped = re.sub(r"^```(?:json)?\s*", "", raw)
    return re.sub(r"\s*```$", "", stripped)


def _try_parse_json(raw: str) -> tuple[bool, dict | None]:
    """Attempt to parse JSON from raw LLM output, stripping fences if needed."""
    try:
        return True, json.loads(raw)
    except Exception:
        try:
            return True, json.loads(_strip_fences(raw))
        except Exception:
            return False, None


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

async def run_pipeline():
    print(f"Loading cache from {CACHE_PATH}")
    cache_data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    client = genai.Client(vertexai=True)

    step1_system = STEP1_SYSTEM
    step1_user = build_step1_user_message(cache_data)
    step2_system = build_step2_instruction(cache_data)

    print(f"\nStep 1 payload: {len(step1_system) + len(step1_user):,} chars "
          f"(system={len(step1_system)}, user={len(step1_user)})")
    print(f"Step 2 system instruction: {len(step2_system):,} chars")
    print(f"Model Step 1: {FLASH_LITE}")
    print(f"Model Step 2: {STEP2_MODEL}")
    print(f"Schema: Named CEO keys (bottom_line, what_moved, etc.)")

    # Show pre-computed blocks
    json_data = sanitize_json_data(cache_data.get("json_data", {}))
    print(f"\nNetwork totals block: {len(build_network_totals(json_data))} chars")
    contradictions = build_contradiction_flags(json_data)
    print(f"Contradiction flags: {len(contradictions)} chars")
    if contradictions:
        print(contradictions)

    # Determine which thinking levels to test
    level_filter = os.environ.get("THINKING_LEVELS", "").strip()
    if level_filter:
        labels = [l.strip() for l in level_filter.split(",")]
        levels = [t for t in THINKING_LEVELS if t["label"] in labels]
    else:
        levels = THINKING_LEVELS

    print(f"\nThinking levels to test: {[l['label'] for l in levels]}")
    print(f"Iterations per level: {ITERATIONS}")
    print()

    all_results: list[dict] = []

    # Run Step 1 once per iteration (shared across thinking levels)
    step1_cache: dict[int, dict] = {}

    for i in range(1, ITERATIONS + 1):
        print(f"{'='*60}")
        print(f"ITERATION {i} -- Step 1 (Flash-Lite, shared)")
        print(f"{'='*60}")

        try:
            raw1, ms1 = await call_llm(client, FLASH_LITE, step1_system, step1_user, timeout=120)
            parse1, s1_obj = _try_parse_json(raw1)

            n_metrics = n_stories = n_contradictions = 0
            if s1_obj:
                n_metrics = len(s1_obj.get("metric_summaries", []))
                n_stories = len(s1_obj.get("cross_metric_stories", []))
                n_contradictions = len(s1_obj.get("contradictions", []))

            step1_result = {
                "model": FLASH_LITE,
                "latency_ms": ms1,
                "instruction_chars": len(step1_system),
                "user_message_chars": len(step1_user),
                "output_chars": len(raw1),
                "json_parse_ok": parse1,
                "metrics_found": n_metrics,
                "instruction": step1_system,
                "user_message": step1_user,
                "raw_response": raw1,
            }
            step1_cache[i] = step1_result
            print(f"  {ms1}ms, {len(raw1)} chars, JSON={parse1}, Metrics: {n_metrics}/9, "
                  f"Stories: {n_stories}, Contradictions: {n_contradictions}")

        except Exception as e:
            print(f"  Step 1 ERROR: {e}")
            step1_cache[i] = {"error": str(e)}
            for level in levels:
                all_results.append({
                    "iteration": i,
                    "thinking_level": level["label"],
                    "thinking_budget": level["budget"],
                    "step1": {"error": str(e)},
                    "step2": {"error": "skipped (step 1 failed)"},
                })
            continue

        # Now run Step 2 with each thinking level
        step2_user = build_step2_user_message(raw1, cache_data)

        for level in levels:
            label = level["label"]
            budget = level["budget"]
            tc = _make_thinking_config(budget)

            print(f"\n  Step 2 [{label}] thinking_budget={budget} ...")
            pipeline: dict[str, Any] = {
                "iteration": i,
                "thinking_level": label,
                "thinking_budget": budget,
                "step1": step1_result,
            }

            try:
                raw2, ms2 = await call_llm(
                    client, STEP2_MODEL, step2_system, step2_user,
                    response_schema=CEO_BRIEF_SCHEMA,
                    thinking_config=tc,
                    timeout=180,
                )
                parse2, brief = _try_parse_json(raw2)
                n_wm = len(brief.get("what_moved", [])) if brief else 0
                n_lf = len(brief.get("leadership_focus", [])) if brief else 0
                has_bl = "bottom_line" in brief if brief else False

                print(f"    {ms2}ms, {len(raw2)} chars, JSON={parse2}")
                print(f"    Schema: bottom_line={has_bl}, what_moved={n_wm}, leadership_focus={n_lf}")

                pipeline["step2"] = {
                    "model": STEP2_MODEL,
                    "thinking_level": label,
                    "thinking_budget": budget,
                    "latency_ms": ms2,
                    "instruction_chars": len(step2_system),
                    "user_message_chars": len(step2_user),
                    "output_chars": len(raw2),
                    "json_parse_ok": parse2,
                    "instruction": step2_system,
                    "user_message": step2_user,
                    "raw_response": raw2,
                }
            except Exception as e:
                print(f"    Step 2 [{label}] ERROR: {e}")
                pipeline["step2"] = {"error": str(e), "thinking_level": label}

            pipeline["total_latency_ms"] = (
                pipeline.get("step1", {}).get("latency_ms", 0)
                + pipeline.get("step2", {}).get("latency_ms", 0)
            )
            print(f"    Total: {pipeline['total_latency_ms']}ms")
            all_results.append(pipeline)

    # -- Save --
    out_dir = PROJECT_ROOT / "outputs" / "benchmarks"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    out_file = out_dir / f"two_step_thinking_benchmark_{ts}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)

    print(f"\nResults saved to {out_file}")

    # -- Summary table --
    print("\n" + "=" * 100)
    print(f"{'Iter':<5} {'Level':<10} {'Budget':>8} {'S1 (ms)':>9} {'S2 (ms)':>9} {'Total':>9} "
          f"{'S1 OK':>6} {'S2 OK':>6} {'Metrics':>8} {'S2 Chars':>9}")
    print("-" * 100)
    for r in all_results:
        s1 = r.get("step1", {})
        s2 = r.get("step2", {})
        print(
            f"{r['iteration']:<5} "
            f"{r.get('thinking_level', '?'):<10} "
            f"{str(r.get('thinking_budget', '?')):>8} "
            f"{s1.get('latency_ms', '-'):>9} "
            f"{s2.get('latency_ms', '-'):>9} "
            f"{r.get('total_latency_ms', '-'):>9} "
            f"{str(s1.get('json_parse_ok', '-')):>6} "
            f"{str(s2.get('json_parse_ok', '-')):>6} "
            f"{s1.get('metrics_found', '?'):>8} "
            f"{s2.get('output_chars', '-'):>9}"
        )
    print("=" * 100)


if __name__ == "__main__":
    asyncio.run(run_pipeline())
