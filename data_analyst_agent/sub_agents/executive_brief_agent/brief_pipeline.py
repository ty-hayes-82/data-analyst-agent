"""Three-step CEO brief pipeline: deterministic ranking, Flash-Lite curation, Pro synthesis.

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
from .brief_format import render_flat_ceo_brief_markdown, render_flat_ceo_brief_html
from .prompt import get_ceo_section_contract, is_billing_auditor_style


def _grain_display_label(canonical_grain: str) -> str:
    return {
        "monthly": "Monthly",
        "weekly": "Weekly",
        "yearly": "Annual",
        "daily": "Daily",
    }.get((canonical_grain or "weekly").lower(), "Weekly")


def flat_ceo_to_executive_structure(
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
        "pipeline": True,
        "pass2_flat": flat_clean,
    }


def run_brief_sync(
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
    contract: Any = None,
    days_in_period: int = 7,
    kpi_rows: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], str, dict[str, Any]]:
    """
    Run Pass 0 (code), optional Pass 1 (Flash-Lite), Pass 2 (Pro).

    Returns:
        executive_structure: header/body JSON for persistence
        markdown: rendered CEO brief
        meta: timings and optional curation payload
    """
    if not json_data:
        raise ValueError("CEO brief requires metric JSON payloads")

    ranker = SignalRanker(json_data, contract=contract, days_in_period=days_in_period)
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
        executive_empty = flat_ceo_to_executive_structure(
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

    # Ensure KPI signals are included in curated list (they may have been dropped by Flash Lite)
    curated_ids = {s["id"] for s in curated}
    kpi_signals = [s for s in signals if s.get("source") == "derived_kpi_signal" and s["id"] not in curated_ids]
    if kpi_signals:
        # Build deterministic metric_description for KPI signals
        from data_analyst_agent.brief_utils import _build_deterministic_metric_description
        for s in kpi_signals:
            s["metric_description"] = _build_deterministic_metric_description(s)
            s["clean_name"] = s.get("title", "")
            s["dimension"] = s.get("entity", "Network")
        curated = kpi_signals + curated
        print(f"[BRIEF] Added {len(kpi_signals)} KPI signals to curated list")

    # Ensure regional (L1) signals are included — they may have been dropped by Flash Lite
    regional_signals = [s for s in signals if s.get("source") == "hierarchy_level_1" and s["id"] not in curated_ids]
    if regional_signals:
        from data_analyst_agent.brief_utils import _build_deterministic_metric_description
        for s in regional_signals:
            s["metric_description"] = _build_deterministic_metric_description(s)
            s["clean_name"] = s.get("title", "")
            s["dimension"] = s.get("entity", "Network")
        curated_ids_after_kpi = {s["id"] for s in curated}
        new_regional = [s for s in regional_signals if s["id"] not in curated_ids_after_kpi]
        if new_regional:
            curated.extend(new_regional)
            print(f"[BRIEF] Added {len(new_regional)} regional (L1) signals to curated list")

    # Note: metric_description for ALL curated signals is now deterministic
    # (computed in merge_pass1_kept_into_signals, not from Flash Lite)

    flat_brief = pass2_brief(client, pro_model, totals, curated, thesis, analysis_period,
                             contract=contract, json_data=json_data, days_in_period=days_in_period)
    if flat_brief is None:
        raise ValueError("pass2_brief returned None")
    meta["pass2_elapsed"] = flat_brief.get("_elapsed")

    contract = get_ceo_section_contract(canonical_grain)
    outlook_title = next(
        (s["title"] for s in contract if s["title"].lower().startswith("next")),
        "Next-week outlook",
    )

    executive = flat_ceo_to_executive_structure(
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
    # Use pre-computed KPI rows from agent.py (has supplemented totals for ALL metrics)
    # Fall back to KPI signals if not provided
    if not kpi_rows:
        kpi_rows = []
        for s in signals:
            if s.get("source") == "derived_kpi_signal" and s.get("current_value") is not None:
                kpi_rows.append({
                    "name": s.get("title", ""),
                    "display_name": s.get("title", ""),
                    "value": s.get("current_value"),
                    "prior_value": s.get("prior_value"),
                    "change_pct": s.get("var_pct"),
                    "format": "currency" if "$" in s.get("detail", "") else (
                        "percentage" if "%" in s.get("title", "") else "float"
                    ),
                })

    md = render_flat_ceo_brief_markdown(
        flat_brief,
        heading=md_heading,
        analysis_period=analysis_period,
        outlook_heading=outlook_title,
        persona="billing_auditor" if is_billing_auditor_style() else "ceo",
        kpi_rows=kpi_rows if kpi_rows else None,
    )

    html = render_flat_ceo_brief_html(
        flat_brief,
        heading=md_heading,
        analysis_period=analysis_period,
        outlook_heading=outlook_title,
        kpi_rows=kpi_rows if kpi_rows else None,
        generated_date=period_end,
    )

    meta["html"] = html
    return executive, md, meta


def _filter_json_data_to_entity(json_data: dict[str, Any], entity: str) -> dict[str, Any]:
    """Return a shallow copy of json_data with hierarchy cards filtered to *entity*.

    Keeps L0 (network totals for context), filters L1 to only cards matching
    *entity*, and removes L2+ cards entirely (parentage is not encoded in the
    payload, so we can't determine which terminals belong to which region).
    """
    prefix = "Level 1 Variance Driver: "
    filtered: dict[str, Any] = {}
    for metric_name, payload in json_data.items():
        p = dict(payload)  # shallow copy of the metric payload
        ha = p.get("hierarchical_analysis")
        if not isinstance(ha, dict):
            filtered[metric_name] = p
            continue
        ha = dict(ha)  # shallow copy
        # Filter L1 cards to only the target entity
        l1 = ha.get("level_1")
        if isinstance(l1, dict):
            l1 = dict(l1)
            cards = l1.get("insight_cards") or []
            if isinstance(cards, list):
                l1["insight_cards"] = [
                    c for c in cards
                    if isinstance(c, dict)
                    and c.get("title", "").replace(prefix, "").strip() == entity
                ]
            ha["level_1"] = l1
        # Remove L2+ cards — they are terminals/locations whose region parentage
        # is not encoded, so including them bleeds other-region insights into this brief
        for level_key in list(ha.keys()):
            if level_key.startswith("level_") and level_key not in ("level_0", "level_1"):
                ha[level_key] = {}
        p["hierarchical_analysis"] = ha
        filtered[metric_name] = p
    return filtered


def _extract_entity_totals(
    json_data: dict[str, Any], entity: str,
) -> tuple[dict[str, float], dict[str, float]]:
    """Extract current/prior base-metric totals from L1 cards matching *entity*."""
    prefix = "Level 1 Variance Driver: "
    current_totals: dict[str, float] = {}
    prior_totals: dict[str, float] = {}
    for metric_name, payload in json_data.items():
        ha = payload.get("hierarchical_analysis")
        if not isinstance(ha, dict):
            continue
        l1 = ha.get("level_1")
        if not isinstance(l1, dict):
            continue
        for card in l1.get("insight_cards") or []:
            if not isinstance(card, dict):
                continue
            title = card.get("title", "").replace(prefix, "").strip()
            if title != entity:
                continue
            ev = card.get("evidence") if isinstance(card.get("evidence"), dict) else {}
            if ev.get("current") is not None:
                current_totals[metric_name] = float(ev["current"])
            if ev.get("prior") is not None:
                prior_totals[metric_name] = float(ev["prior"])
    return current_totals, prior_totals


def run_scoped_brief_sync(
    json_data: dict[str, Any],
    entity: str,
    *,
    analysis_period: str,
    period_end: str,
    canonical_grain: str,
    lite_model: str,
    pro_model: str,
    contract: Any = None,
    days_in_period: int = 7,
) -> tuple[dict[str, Any], str, str, dict[str, Any]]:
    """Run the 3-pass brief pipeline scoped to a single region entity.

    Returns (executive_json, markdown, html, meta).
    """
    from .kpi_calculator import compute_derived_kpis_from_contract

    if not json_data:
        raise ValueError("scoped brief requires metric JSON payloads")

    # --- 1. Filter json_data to the target region ---
    filtered_json = _filter_json_data_to_entity(json_data, entity)

    # --- 2. Compute per-region base metric totals & KPIs ---
    region_current, region_prior = _extract_entity_totals(json_data, entity)
    kpi_rows: list[dict[str, Any]] = []
    if region_current and contract:
        kpi_rows = compute_derived_kpis_from_contract(
            contract, region_current, region_prior, days_in_period,
        )

    # Build totals dict (same shape as BriefUtils.get_network_totals) for Pass 2
    totals: dict[str, Any] = {}
    for m, cur in region_current.items():
        pri = region_prior.get(m)
        var_dollar = (cur - pri) if pri is not None else 0
        var_pct = ((var_dollar / abs(pri)) * 100) if pri else 0
        totals[m] = {
            "current": cur,
            "prior": pri,
            "var_pct": var_pct,
            "var_dollar": var_dollar,
        }

    # --- 3. Pass 0 — deterministic signal extraction on filtered data ---
    ranker = SignalRanker(filtered_json, contract=contract, days_in_period=days_in_period)
    signals = ranker.extract_all()

    # Filter signals to only those relevant to this entity or network-level
    entity_lower = entity.lower()
    signals = [
        s for s in signals
        if not s.get("entity")  # network-level signals (no entity)
        or s["entity"].lower() == entity_lower  # this region
        or s["entity"].lower() == "network"  # explicitly network
        or s.get("source") == "derived_kpi_signal"  # KPIs always included
    ]

    if not signals:
        flat_brief = {
            "bottom_line": (
                f"No ranked signals were extracted for the {entity} region this period; "
                "metric outputs may lack hierarchy cards, statistical summaries, or material variance."
            ),
            "what_moved": [
                {
                    "label": "Summary",
                    "line": (
                        f"No deterministic signals passed Pass 0 for {entity}; verify per-metric "
                        "JSON includes hierarchical_analysis and statistics."
                    ),
                }
            ],
            "trend_status": ["No trend signals available."],
            "where_it_came_from": {
                "positive": f"N/A — no {entity} drivers extracted.",
                "drag": f"N/A — no {entity} drivers extracted.",
                "watch_item": "",
            },
            "why_it_matters": (
                f"Without Pass 0 signals the {entity} region brief cannot be grounded in "
                "automated variance drivers."
            ),
            "next_week_outlook": (
                "Re-run after validating data extracts and hierarchy drill-down."
            ),
            "leadership_focus": [
                f"Validate that metric runs produce hierarchy and stats for {entity} before synthesis.",
            ],
            "_elapsed": 0.0,
        }
        contract_obj = get_ceo_section_contract(canonical_grain)
        outlook_title = next(
            (s["title"] for s in contract_obj if s["title"].lower().startswith("next")),
            "Next-week outlook",
        )
        grain_label = _grain_display_label(canonical_grain)
        heading = f"{entity} Region — {grain_label} Performance Overview"
        exec_struct = flat_ceo_to_executive_structure(
            flat_brief, period_end=period_end,
            outlook_title=outlook_title, canonical_grain=canonical_grain,
        )
        md = render_flat_ceo_brief_markdown(
            flat_brief, heading=heading, analysis_period=analysis_period,
            outlook_heading=outlook_title, persona="ceo",
        )
        html = render_flat_ceo_brief_html(
            flat_brief, heading=heading, analysis_period=analysis_period,
            outlook_heading=outlook_title, generated_date=period_end,
        )
        meta_empty: dict[str, Any] = {
            "pass0_count": 0, "pass1_skipped": True,
            "empty_signals": True, "entity": entity, "html": html,
        }
        return exec_struct, md, html, meta_empty

    # --- 4. Pass 1 — curation (skip if ≤ 5 signals) ---
    client = genai.Client()
    meta: dict[str, Any] = {"pass0_count": len(signals), "entity": entity}
    max_curated = 8

    if len(signals) <= 5:
        curated = signals
        thesis = f"Mixed operational signals for the {entity} region (curation skipped — ≤ 5 signals)."
        meta["pass1_skipped"] = True
    else:
        pool = signals[:20]
        curation = pass1_curate(client, lite_model, totals, pool, max_curated)
        if curation is None:
            raise ValueError("pass1_curate returned None")
        meta["pass1_elapsed"] = curation.get("_elapsed")
        meta["curation"] = {k: v for k, v in curation.items() if k != "_elapsed"}
        kept_rows = curation.get("kept", [])
        curated = merge_pass1_kept_into_signals(signals, kept_rows)
        if not curated:
            curated = signals[:max_curated]
        thesis = str(curation.get("narrative_thesis", f"Mixed operational signals for {entity}."))

    # --- 5. Re-inject KPI signals (same pattern as network brief) ---
    curated_ids = {s["id"] for s in curated}
    kpi_signals = [
        s for s in signals
        if s.get("source") == "derived_kpi_signal" and s["id"] not in curated_ids
    ]
    if kpi_signals:
        from data_analyst_agent.brief_utils import _build_deterministic_metric_description
        for s in kpi_signals:
            s["metric_description"] = _build_deterministic_metric_description(s)
            s["clean_name"] = s.get("title", "")
            s["dimension"] = s.get("entity", entity)
        curated = kpi_signals + curated
        print(f"[SCOPED-{entity}] Added {len(kpi_signals)} KPI signals to curated list")

    regional_signals = [
        s for s in signals
        if s.get("source") == "hierarchy_level_1" and s["id"] not in curated_ids
    ]
    if regional_signals:
        from data_analyst_agent.brief_utils import _build_deterministic_metric_description
        for s in regional_signals:
            s["metric_description"] = _build_deterministic_metric_description(s)
            s["clean_name"] = s.get("title", "")
            s["dimension"] = s.get("entity", entity)
        curated_ids_after_kpi = {s["id"] for s in curated}
        new_regional = [s for s in regional_signals if s["id"] not in curated_ids_after_kpi]
        if new_regional:
            curated.extend(new_regional)
            print(f"[SCOPED-{entity}] Added {len(new_regional)} regional (L1) signals to curated list")

    # --- 6. Pass 2 — Pro synthesis ---
    scoped_period = f"{entity} region for the {analysis_period}"
    flat_brief = pass2_brief(
        client, pro_model, totals, curated, thesis, scoped_period,
        contract=contract, json_data=filtered_json, days_in_period=days_in_period,
    )
    if flat_brief is None:
        raise ValueError("pass2_brief returned None")
    meta["pass2_elapsed"] = flat_brief.get("_elapsed")

    # --- 7. Render ---
    section_contract = get_ceo_section_contract(canonical_grain)
    outlook_title = next(
        (s["title"] for s in section_contract if s["title"].lower().startswith("next")),
        "Next-week outlook",
    )

    executive = flat_ceo_to_executive_structure(
        flat_brief, period_end=period_end,
        outlook_title=outlook_title, canonical_grain=canonical_grain,
    )

    grain_label = _grain_display_label(canonical_grain)
    heading = f"{entity} Region — {grain_label} Performance Overview"

    # Fall back to KPI signals if contract-based kpi_rows are empty
    if not kpi_rows:
        kpi_rows = []
        for s in signals:
            if s.get("source") == "derived_kpi_signal" and s.get("current_value") is not None:
                kpi_rows.append({
                    "name": s.get("title", ""),
                    "display_name": s.get("title", ""),
                    "value": s.get("current_value"),
                    "prior_value": s.get("prior_value"),
                    "change_pct": s.get("var_pct"),
                    "format": "currency" if "$" in s.get("detail", "") else (
                        "percentage" if "%" in s.get("title", "") else "float"
                    ),
                })

    md = render_flat_ceo_brief_markdown(
        flat_brief, heading=heading, analysis_period=analysis_period,
        outlook_heading=outlook_title, persona="ceo",
        kpi_rows=kpi_rows if kpi_rows else None,
    )
    html = render_flat_ceo_brief_html(
        flat_brief, heading=heading, analysis_period=analysis_period,
        outlook_heading=outlook_title,
        kpi_rows=kpi_rows if kpi_rows else None,
        generated_date=period_end,
    )

    meta["html"] = html
    return executive, md, html, meta


async def run_scoped_brief_async(
    json_data: dict[str, Any],
    entity: str,
    **kwargs: Any,
) -> tuple[dict[str, Any], str, str, dict[str, Any]]:
    """Async wrapper for run_scoped_brief_sync."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, lambda: run_scoped_brief_sync(json_data, entity, **kwargs),
    )


async def run_brief_async(
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
    contract: Any = None,
    days_in_period: int = 7,
    kpi_rows: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], str, dict[str, Any]]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        lambda: run_brief_sync(
            json_data,
            analysis_period=analysis_period,
            period_end=period_end,
            canonical_grain=canonical_grain,
            top_signals=top_signals,
            max_curated=max_curated,
            skip_curation=skip_curation,
            lite_model=lite_model,
            pro_model=pro_model,
            contract=contract,
            days_in_period=days_in_period,
            kpi_rows=kpi_rows,
        ),
    )


def save_brief_artifacts(outputs_dir: Path, meta: dict[str, Any]) -> None:
    """Write brief debug JSON next to the brief (optional)."""
    try:
        # Move brief metadata to meta/ subfolder if in standardized run dir
        meta_dir = outputs_dir / "meta" if os.getenv("DATA_ANALYST_OUTPUT_DIR") else outputs_dir
        if meta_dir != outputs_dir:
            meta_dir.mkdir(parents=True, exist_ok=True)

        path = meta_dir / "brief_pipeline_meta.json"
        path.write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")
    except OSError:
        pass


async def generate_insights_report_async(meta: dict[str, Any]) -> str:
    """Generate a simple MD file listing all top insights from brief metadata using Flash-Lite."""
    curation = meta.get("curation")
    if not curation or not curation.get("kept"):
        return ""

    # 'brief_curator' is the agent that uses 'brief' tier (3.1 flash lite)
    model_name = get_agent_model("brief_curator")
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
    - **MetricName - Dimension**: One-line explanation of the core insight, its likely cause, and its business implication. Statistics (e.g., ±X.X% WoW | current vs prior).
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
        print(f"[BRIEF] Failed to generate insights report: {e}")
        return ""


async def save_brief_artifacts_async(outputs_dir: Path, meta: dict[str, Any]) -> None:
    """Write brief debug JSON and the insights MD report next to the brief."""
    # First save the JSON metadata (sync)
    save_brief_artifacts(outputs_dir, meta)

    # Then generate and save the insights report (async)
    insights_md = await generate_insights_report_async(meta)
    if insights_md:
        try:
            # Place in deliverables/ if in standardized run dir, else outputs_dir
            target_dir = outputs_dir / "deliverables" if os.getenv("DATA_ANALYST_OUTPUT_DIR") else outputs_dir
            if target_dir != outputs_dir:
                target_dir.mkdir(parents=True, exist_ok=True)
                
            path = target_dir / "insights.md"
            path.write_text(insights_md, encoding="utf-8")
            print(f"[BRIEF] Saved curation insights report to {path.name} (in {target_dir.name}/)")
        except OSError as e:
            print(f"[BRIEF] Error saving insights report: {e}")
