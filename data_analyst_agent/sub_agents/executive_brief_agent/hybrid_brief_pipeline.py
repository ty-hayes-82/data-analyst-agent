"""Three-step hybrid CEO brief: deterministic ranking, Flash-Lite curation, Pro synthesis.

Models (see config/agent_models.yaml): Pass1 tier ``brief`` (gemini-3.1-flash-lite-preview),
Pass2 tier ``pro`` (gemini-3.1-pro-preview).

Used by CrossMetricExecutiveBriefAgent when EXECUTIVE_BRIEF_STYLE=ceo and
EXECUTIVE_BRIEF_USE_HYBRID_PIPELINE is true (default).
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from data_analyst_agent.brief_utils import (
    BriefUtils,
    SignalRanker,
    merge_pass1_kept_into_signals,
    pass1_curate,
    pass2_brief,
)
from google import genai
from google.genai import types

from config.model_loader import get_agent_model
from .brief_format import render_flat_ceo_brief_markdown
from .prompt import get_ceo_section_contract, is_billing_auditor_style


def _grain_display_label(canonical_grain: str) -> str:
    return {
        "monthly": "Monthly",
        "weekly": "Weekly",
        "yearly": "Annual",
        "daily": "Daily",
    }.get((canonical_grain or "weekly").lower(), "Weekly")


def flat_hybrid_ceo_to_executive_structure(
    flat: dict[str, Any],
    *,
    period_end: str,
    outlook_title: str,
    canonical_grain: str,
) -> dict[str, Any]:
    """Map pass2 flat CEO JSON into header/body/sections for brief.json and _format_brief."""
    flat_clean = {k: v for k, v in flat.items() if not str(k).startswith("_")}
    grain_label = _grain_display_label(canonical_grain)
    pe = str(period_end).split(" ")[0]
    if is_billing_auditor_style():
        header_title = f"Billing Assurance {grain_label} Brief: {pe}"
    else:
        header_title = f"CEO {grain_label} Performance Brief: {pe}"

    where = flat_clean.get("where_it_came_from") or {}
    where_insights: list[dict[str, str]] = []
    if isinstance(where, dict):
        if where.get("positive"):
            where_insights.append({"title": "Positive", "details": str(where["positive"])})
        if where.get("drag"):
            where_insights.append({"title": "Drag", "details": str(where["drag"])})
        if where.get("watch_item"):
            where_insights.append({"title": "Watch item", "details": str(where["watch_item"])})

    what_moved: list[dict[str, str]] = []
    for wm in flat_clean.get("what_moved") or []:
        if isinstance(wm, dict):
            what_moved.append(
                {
                    "title": str(wm.get("label", "Metric")),
                    "details": str(wm.get("line", "")),
                }
            )

    trends: list[dict[str, str]] = []
    for i, t in enumerate(flat_clean.get("trend_status") or []):
        trends.append({"title": f"Trend {i + 1}", "details": str(t)})

    leadership: list[dict[str, str]] = []
    for i, a in enumerate(flat_clean.get("leadership_focus") or []):
        leadership.append({"title": f"Focus {i + 1}", "details": str(a)})

    return {
        "header": {
            "title": header_title,
            "summary": str(flat_clean.get("bottom_line", "")),
        },
        "body": {
            "sections": [
                {"title": "What moved the business", "content": "", "insights": what_moved},
                {"title": "Trend status", "content": "", "insights": trends},
                {"title": "Where it came from", "content": "", "insights": where_insights},
                {
                    "title": "Why it matters",
                    "content": str(flat_clean.get("why_it_matters", "")),
                    "insights": [],
                },
                {
                    "title": outlook_title,
                    "content": str(flat_clean.get("next_week_outlook", "")),
                    "insights": [],
                },
                {"title": "Leadership focus", "content": "", "insights": leadership},
            ],
        },
        "hybrid_pipeline": True,
        "hybrid_pass2_flat": flat_clean,
    }


def run_hybrid_ceo_brief_sync(
    json_data: dict[str, Any],
    *,
    analysis_period: str,
    period_end: str,
    canonical_grain: str,
    top_signals: int,
    max_curated: int,
    skip_curation: bool,
    lite_model: str,
    pro_model: str,
) -> tuple[dict[str, Any], str, dict[str, Any]]:
    """
    Run Pass 0 (code), optional Pass 1 (Flash-Lite), Pass 2 (Pro).

    Returns:
        executive_structure: header/body JSON for persistence
        markdown: rendered CEO brief
        meta: timings and optional curation payload
    """
    if not json_data:
        raise ValueError("hybrid CEO brief requires metric JSON payloads")

    ranker = SignalRanker(json_data)
    signals = ranker.extract_all()
    totals = BriefUtils.get_network_totals(json_data)

    if not signals:
        if is_billing_auditor_style():
            flat_brief = {
                "bottom_line": (
                    "No ranked toll signals were extracted for this period; cannot prioritize "
                    "customers or lanes for billing review until hierarchy and stats populate."
                ),
                "what_moved": [
                    {
                        "label": "Summary",
                        "line": (
                            "No deterministic signals passed Pass 0; verify per-metric JSON includes "
                            "hierarchical_analysis and statistics."
                        ),
                    }
                ],
                "trend_status": ["No billing drift signals available."],
                "where_it_came_from": {
                    "positive": "N/A — no customer or lane drivers extracted.",
                    "drag": "N/A — no customer or lane drivers extracted.",
                    "watch_item": "",
                },
                "why_it_matters": (
                    "Without Pass 0 signals, the billing assurance brief cannot list review targets; "
                    "confirm extracts and analysis completed for each toll metric."
                ),
                "next_week_outlook": (
                    "Re-run after validating Hyper extract, date window, and row limits; then sample "
                    "top shipper/lane tiers from the contract."
                ),
                "leadership_focus": [
                    "Confirm pipeline produced hierarchy cards and stats before relying on this brief for audit.",
                ],
                "_elapsed": 0.0,
            }
        else:
            flat_brief = {
                "bottom_line": (
                    "No ranked signals were extracted for this period; metric outputs may lack "
                    "hierarchy cards, statistical summaries, or material variance."
                ),
                "what_moved": [
                    {
                        "label": "Summary",
                        "line": (
                            "No deterministic signals passed Pass 0; verify per-metric JSON includes "
                            "hierarchical_analysis and statistics."
                        ),
                    }
                ],
                "trend_status": ["No trend signals available."],
                "where_it_came_from": {
                    "positive": "N/A — no regional or entity drivers extracted.",
                    "drag": "N/A — no regional or entity drivers extracted.",
                    "watch_item": "",
                },
                "why_it_matters": (
                    "Without Pass 0 signals, the CEO brief cannot be grounded in automated variance drivers; "
                    "confirm analysis pipelines completed for each metric."
                ),
                "next_week_outlook": (
                    "Re-run after validating data extracts, hierarchy drill-down, and time window configuration."
                ),
                "leadership_focus": [
                    "Validate that metric runs produce hierarchy and stats before executive synthesis.",
                ],
                "_elapsed": 0.0,
            }
        meta_empty: dict[str, Any] = {
            "pass0_count": 0,
            "pass1_skipped": True,
            "empty_signals": True,
        }
        contract_early = get_ceo_section_contract(canonical_grain)
        outlook_early = next(
            (s["title"] for s in contract_early if s["title"].lower().startswith("next")),
            "Next-week outlook",
        )
        executive_empty = flat_hybrid_ceo_to_executive_structure(
            flat_brief,
            period_end=period_end,
            outlook_title=outlook_early,
            canonical_grain=canonical_grain,
        )
        grain_early = _grain_display_label(canonical_grain)
        md_empty = render_flat_ceo_brief_markdown(
            flat_brief,
            heading=(
                f"{grain_early} Billing Assurance Review"
                if is_billing_auditor_style()
                else f"{grain_early} Performance Overview"
            ),
            analysis_period=analysis_period,
            outlook_heading=outlook_early,
            persona="billing_auditor" if is_billing_auditor_style() else "ceo",
        )
        return executive_empty, md_empty, meta_empty

    client = genai.Client()
    meta: dict[str, Any] = {"pass0_count": len(signals)}

    if skip_curation:
        curated = signals[:max_curated]
        thesis = "Mixed operational signals (deterministic top signals; curation skipped)."
        meta["pass1_skipped"] = True
    else:
        pool = signals[:top_signals]
        curation = pass1_curate(client, lite_model, totals, pool, max_curated)
        if curation is None:
            raise ValueError("pass1_curate returned None")
        meta["pass1_elapsed"] = curation.get("_elapsed")
        meta["curation"] = {k: v for k, v in curation.items() if k != "_elapsed"}
        kept_rows = curation.get("kept", [])
        curated = merge_pass1_kept_into_signals(signals, kept_rows)
        if not curated:
            curated = signals[:max_curated]
        thesis = str(curation.get("narrative_thesis", "Mixed operational signals."))

    flat_brief = pass2_brief(client, pro_model, totals, curated, thesis, analysis_period)
    if flat_brief is None:
        raise ValueError("pass2_brief returned None")
    meta["pass2_elapsed"] = flat_brief.get("_elapsed")

    contract = get_ceo_section_contract(canonical_grain)
    outlook_title = next(
        (s["title"] for s in contract if s["title"].lower().startswith("next")),
        "Next-week outlook",
    )

    executive = flat_hybrid_ceo_to_executive_structure(
        flat_brief,
        period_end=period_end,
        outlook_title=outlook_title,
        canonical_grain=canonical_grain,
    )

    grain_label = _grain_display_label(canonical_grain)
    md_heading = (
        f"{grain_label} Billing Assurance Review"
        if is_billing_auditor_style()
        else f"{grain_label} Performance Overview"
    )
    md = render_flat_ceo_brief_markdown(
        flat_brief,
        heading=md_heading,
        analysis_period=analysis_period,
        outlook_heading=outlook_title,
        persona="billing_auditor" if is_billing_auditor_style() else "ceo",
    )

    return executive, md, meta


async def run_hybrid_ceo_brief_async(
    json_data: dict[str, Any],
    *,
    analysis_period: str,
    period_end: str,
    canonical_grain: str,
    top_signals: int,
    max_curated: int,
    skip_curation: bool,
    lite_model: str,
    pro_model: str,
) -> tuple[dict[str, Any], str, dict[str, Any]]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        lambda: run_hybrid_ceo_brief_sync(
            json_data,
            analysis_period=analysis_period,
            period_end=period_end,
            canonical_grain=canonical_grain,
            top_signals=top_signals,
            max_curated=max_curated,
            skip_curation=skip_curation,
            lite_model=lite_model,
            pro_model=pro_model,
        ),
    )


def save_hybrid_artifacts(outputs_dir: Path, meta: dict[str, Any]) -> None:
    """Write hybrid debug JSON next to the brief (optional)."""
    try:
        # Move hybrid metadata to meta/ subfolder if in standardized run dir
        meta_dir = outputs_dir / "meta" if os.getenv("DATA_ANALYST_OUTPUT_DIR") else outputs_dir
        if meta_dir != outputs_dir:
            meta_dir.mkdir(parents=True, exist_ok=True)
            
        path = meta_dir / "hybrid_brief_pipeline_meta.json"
        path.write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")
    except OSError:
        pass


async def generate_hybrid_insights_report_async(meta: dict[str, Any]) -> str:
    """Generate a simple MD file listing all top insights from hybrid metadata using Flash-Lite."""
    curation = meta.get("curation")
    if not curation or not curation.get("kept"):
        return ""

    # 'executive_brief_hybrid_curator' is the agent that uses 'brief' tier (3.1 flash lite)
    model_name = get_agent_model("executive_brief_hybrid_curator")
    client = genai.Client()
    
    kept = curation.get("kept", [])
    thesis = curation.get("narrative_thesis", "No thesis provided.")
    
    _aud = os.environ.get("EXECUTIVE_BRIEF_STYLE", "").lower() == "billing_auditor"
    _title = (
        "# Top Billing Review Candidates"
        if _aud
        else "# Top Operational Insights Summary"
    )
    _role = (
        "You are a billing auditor summarizing which customers, shippers, or lanes to review for toll "
        "billing accuracy (revenue vs expense vs recommended toll)."
        if _aud
        else "You are an executive operations analyst. Your task is to create a structured Markdown summary of the top operational insights for the CEO."
    )
    _group = (
        "Group by category (e.g. Revenue, Cost alignment, Lane anomaly, Customer concentration)."
        if _aud
        else "Organize the 'kept' insights by their 'category' (e.g., Revenue, Efficiency, Capacity)."
    )
    prompt = f"""
{_role}

### DATA SOURCE (JSON)
{json.dumps(curation, indent=2)}

### OUTPUT REQUIREMENTS
1.  **Title**: {_title}
2.  **Summary Section**: Include the "narrative_thesis" as a bolded summary at the top.
3.  **Grouped Insights**: {_group}
4.  **Ranking**: Within each category, list insights in ascending order of their 'rank'.
5.  **Insight Format**: Use a single line for each insight in this exact format:
    - **MetricName - Dimension**: One-line explanation of the core insight and its business implication. Statistics (e.g., ±X.X% WoW | current vs prior).
    - Example: **Total Revenue - Location: Manteno**: Revenue impact in Manteno aligns with the sharp drop in miles. -95.3% WoW | $10.1K vs $214.2K
    - *Note*: Extract the statistics part (e.g., "-95.3% WoW | $10.1K vs $214.2K") from the 'metric_description' field.
6.  **Tone**: Professional, crisp, and analytical.
7.  **Constraint**: Do NOT include 'dropped' signals. ONLY the 'kept' signals. Do NOT include the rank number (e.g., [Rank #3]) in the output.
8.  **Output**: Return ONLY the Markdown content. No preamble or markdown code fences.
"""

    try:
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.1,
            )
        )
        return response.text.strip()
    except Exception as e:
        print(f"[HYBRID] Failed to generate insights report: {e}")
        return ""


async def save_hybrid_artifacts_async(outputs_dir: Path, meta: dict[str, Any]) -> None:
    """Write hybrid debug JSON and the new insights MD report next to the brief."""
    # First save the JSON metadata (sync)
    save_hybrid_artifacts(outputs_dir, meta)
    
    # Then generate and save the insights report (async)
    insights_md = await generate_hybrid_insights_report_async(meta)
    if insights_md:
        try:
            # Place in deliverables/ if in standardized run dir, else outputs_dir
            target_dir = outputs_dir / "deliverables" if os.getenv("DATA_ANALYST_OUTPUT_DIR") else outputs_dir
            if target_dir != outputs_dir:
                target_dir.mkdir(parents=True, exist_ok=True)
                
            path = target_dir / "hybrid_insights.md"
            path.write_text(insights_md, encoding="utf-8")
            print(f"[HYBRID] Saved curation insights report to {path.name} (in {target_dir.name}/)")
        except OSError as e:
            print(f"[HYBRID] Error saving insights report: {e}")
