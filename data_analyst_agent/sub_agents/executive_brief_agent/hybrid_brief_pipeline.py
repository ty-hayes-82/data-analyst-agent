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

from .brief_format import render_flat_ceo_brief_markdown
from .prompt import get_ceo_section_contract


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

    client = genai.Client()
    meta: dict[str, Any] = {"pass0_count": len(signals)}

    if skip_curation:
        curated = signals[:max_curated]
        thesis = "Mixed operational signals (deterministic top signals; curation skipped)."
        meta["pass1_skipped"] = True
    else:
        pool = signals[:top_signals]
        curation = pass1_curate(client, lite_model, totals, pool, max_curated)
        meta["pass1_elapsed"] = curation.get("_elapsed")
        meta["curation"] = {k: v for k, v in curation.items() if k != "_elapsed"}
        kept_rows = curation.get("kept", [])
        curated = merge_pass1_kept_into_signals(signals, kept_rows)
        if not curated:
            curated = signals[:max_curated]
        thesis = str(curation.get("narrative_thesis", "Mixed operational signals."))

    flat_brief = pass2_brief(client, pro_model, totals, curated, thesis, analysis_period)
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
    md_heading = f"{grain_label} Performance Overview"
    md = render_flat_ceo_brief_markdown(
        flat_brief,
        heading=md_heading,
        analysis_period=analysis_period,
        outlook_heading=outlook_title,
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
