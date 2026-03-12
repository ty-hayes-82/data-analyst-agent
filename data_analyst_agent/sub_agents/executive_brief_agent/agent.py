"""
Cross-Metric Executive Brief Agent

Runs after all per-metric analysis pipelines complete. Reads every metric_*.md
report from the outputs directory, feeds them to an LLM, and produces a
structured one-page executive brief saved as outputs/executive_brief_<date>.md.

Spec 029: Prefers metric_*.json when available for richer digest (cross-entity
table, temporal anchors, more insight cards).

Spec 031: Writes executive_brief_input_cache.json before LLM call for iterative
refinement with different prompts/models via regenerate script.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google import genai
from google.genai import types

from config.model_loader import get_agent_model, get_agent_thinking_config
from .prompt import (
    EXECUTIVE_BRIEF_INSTRUCTION,
    SCOPED_BRIEF_PREAMBLE,
    load_dataset_specific_append,
    load_prompt_variant,
)
from ...utils import parse_bool_env
from ...utils.stub_guard import contains_stub_content
from ...utils.contract_summary import (
    build_contract_metadata,
    format_contract_context,
    format_contract_reference_block,
)
from ...utils.focus_directives import (
    augment_instruction,
    focus_block as build_focus_block,
    focus_lines as get_focus_lines,
)
from ...utils.temporal_grain import (
    normalize_temporal_grain,
    temporal_grain_to_period_unit,
    temporal_grain_to_short_delta_label,
)
from .prompt_utils import (
    _build_structured_fallback_markdown,
    _build_weather_context_block,
    _format_analysis_period,
    _format_brief_with_fallback,
    _write_executive_brief_cache,
    build_structured_fallback_brief,
    collect_recommendations_from_reports,
    SECTION_FALLBACK_TEXT,
    _apply_unit_to_text,
)
from .severity_guard import has_critical_or_high_findings, build_severity_enforcement_block
from .report_utils import (
    _build_digest,
    _build_digest_from_json,
    _collect_metric_json_data,
    _collect_metric_reports,
)
from .scope_utils import (
    _build_scoped_digest,
    _discover_level_entities,
    _load_hierarchy_level_mapping,
    _sanitize_entity_name,
    derive_scope_level_labels,
)


class ExecutiveBriefConfig:
    """Centralized configuration for Executive Brief agent behavior.
    
    All retry logic, timeouts, and timing parameters controlled through
    environment variables with sensible defaults.
    """
    
    @staticmethod
    def max_llm_retries() -> int:
        """Maximum attempts for LLM brief generation (network-level)."""
        return _parse_positive_int_env("EXECUTIVE_BRIEF_MAX_RETRIES", 3)
    
    @staticmethod
    def max_scoped_retries() -> int:
        """Maximum attempts for scoped brief generation.
        
        Scoped briefs often have less signal and fail more frequently.
        Default is 2 (vs 3 for network brief) to reduce wasted retry time.
        Set EXECUTIVE_BRIEF_MAX_SCOPED_RETRIES=3 to match network behavior.
        """
        return _parse_positive_int_env("EXECUTIVE_BRIEF_MAX_SCOPED_RETRIES", 2)
    
    @staticmethod
    def llm_timeout_seconds() -> float:
        """Timeout for individual LLM generate_content calls."""
        try:
            value = os.getenv("EXECUTIVE_BRIEF_TIMEOUT")
            if value is None:
                return 300.0
            return float(value)
        except (TypeError, ValueError):
            return 300.0
    
    @staticmethod
    def retry_delay_seconds() -> float:
        """Delay between retry attempts."""
        try:
            value = os.getenv("EXECUTIVE_BRIEF_RETRY_DELAY")
            if value is None:
                return 5.0
            return float(value)
        except (TypeError, ValueError):
            return 5.0


BRIEF_CONFIG = ExecutiveBriefConfig()


def _parse_positive_int_env(var_name: str, default: int) -> int:
    value = os.getenv(var_name)
    if value is None:
        return default
    try:
        parsed = int(str(value).strip())
        return parsed if parsed > 0 else default
    except (TypeError, ValueError):
        return default


def _max_scoped_briefs() -> int:
    """Return the current scoped brief cap (reads env each call)."""
    return _parse_positive_int_env("EXECUTIVE_BRIEF_MAX_SCOPED_BRIEFS", 3)


def _scope_concurrency_limit() -> int:
    """Return semaphore size for scoped brief fan-out (>=1)."""
    return max(1, _parse_positive_int_env("EXECUTIVE_BRIEF_SCOPE_CONCURRENCY", 3))



def _ensure_card_titles(card_list: list[dict[str, Any]] | None, prefix: str) -> None:
    if not isinstance(card_list, list):
        return
    for idx, card in enumerate(card_list, 1):
        if not isinstance(card, dict):
            continue
        title = (card.get("title") or "").strip()
        if title:
            continue
        fallback = (
            card.get("item")
            or card.get("item_name")
            or card.get("level_name")
            or card.get("dimension_value")
            or card.get("what_changed")
            or prefix
        )
        fallback = str(fallback).strip() or prefix
        suffix = f" (Insight {idx})" if idx > 1 else ""
        card["title"] = f"{prefix}: {fallback}{suffix}" if prefix and not fallback.lower().startswith(prefix.lower()) else f"{fallback}{suffix}".strip()


def _ensure_block_titles(block: Any, prefix: str) -> Any:
    was_str = isinstance(block, str)
    data = block
    if was_str:
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            return block
    if isinstance(data, dict):
        _ensure_card_titles(data.get("insight_cards"), prefix)
    return json.dumps(data) if was_str else data


_JSON_OBJECT_START = re.compile(r"\{")


def _parse_brief_json_payload(raw_text: str) -> dict[str, Any]:
    """Parse the LLM response into a JSON object, tolerating stray prose.

    Models occasionally prepend acknowledgements ("Sure, here you go") or append
    extra sentences even when response_mime_type requests JSON. This helper
    strips code fences beforehand (handled by caller) and then attempts to load
    the object directly. If that fails, it scans for the first opening brace and
    lets json.JSONDecoder.raw_decode consume just the JSON object, ignoring any
    prefix/suffix text. Raises ValueError when the decoded payload is not an
    object so upstream logic can trigger structured fallbacks.
    """

    cleaned = (raw_text or "").strip()
    if not cleaned:
        raise json.JSONDecodeError("Empty response payload", raw_text or "", 0)

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        decoder = json.JSONDecoder()
        for match in _JSON_OBJECT_START.finditer(cleaned):
            try:
                obj, _ = decoder.raw_decode(cleaned[match.start():])
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                return obj
        raise exc

    if not isinstance(parsed, dict):
        raise ValueError(
            f"Executive brief response must be a JSON object, received {type(parsed).__name__}"
        )

    return parsed


_TEMPORAL_COMPARISON_PRIORITY = {
    "daily": [
        "current day vs prior day (DoD)",
        "current day vs rolling 7-day average",
        "current day vs same day prior year (YoY)",
        "other supported comparisons (lower priority)",
    ],
    "weekly": [
        "current week vs prior week (WoW)",
        "current week vs rolling 4-week average",
        "other supported comparisons (lower priority)",
    ],
    "monthly": [
        "current month vs prior month (MoM)",
        "current month vs rolling 3-month average",
        "current month vs same month prior year (YoY)",
        "other supported comparisons (lower priority)",
    ],
    "quarterly": [
        "current quarter vs prior quarter (QoQ)",
        "current quarter vs rolling 4-quarter average",
        "current quarter vs same quarter prior year (YoY)",
        "other supported comparisons (lower priority)",
    ],
    "yearly": [
        "current year vs prior year (YoY)",
        "current year vs rolling 3-year average",
        "other supported comparisons (lower priority)",
    ],
    "unknown": [
        "current period vs prior period (PoP)",
        "current period vs rolling multi-period average",
        "other supported comparisons (lower priority)",
    ],
}


def _default_comparison_basis(grain: str) -> str:
    canonical = normalize_temporal_grain(grain)
    period_unit = temporal_grain_to_period_unit(canonical)
    short_delta = temporal_grain_to_short_delta_label(canonical)
    if short_delta == "PoP":
        return f"vs prior {period_unit}" if period_unit != "period" else "vs prior period (PoP)"
    return f"vs prior {period_unit} ({short_delta})"


def _build_comparison_priority(grain: str) -> list[str]:
    canonical = normalize_temporal_grain(grain)
    return _TEMPORAL_COMPARISON_PRIORITY.get(canonical, _TEMPORAL_COMPARISON_PRIORITY["unknown"])


def _is_placeholder_markdown(markdown: str, used_fallback: bool = False) -> bool:
    """Detect fallback or stubbed markdown content."""
    if used_fallback:
        return True
    text = (markdown or "").strip()
    if not text:
        return True
    normalized = text.lower()
    if SECTION_FALLBACK_TEXT.lower() in normalized:
        return True
    return contains_stub_content(text)


def _backfill_missing_titles(json_data: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    for metric_name, payload in json_data.items():
        prefix = str(metric_name).strip() or "Insight"
        narrative = payload.get("narrative_results")
        if narrative:
            payload["narrative_results"] = _ensure_block_titles(narrative, prefix)
        hier = payload.get("hierarchical_analysis")
        if isinstance(hier, dict):
            for key in list(hier.keys()):
                block = hier.get(key)
                if isinstance(block, (dict, str)):
                    hier[key] = _ensure_block_titles(block, f"{prefix} {key}")
            indep = hier.get("independent_level_results")
            if isinstance(indep, dict):
                for key in list(indep.keys()):
                    block = indep.get(key)
                    if isinstance(block, (dict, str)):
                        indep[key] = _ensure_block_titles(block, f"{prefix} {key}")
        analysis = payload.get("analysis")
        if isinstance(analysis, dict):
            _ensure_card_titles(analysis.get("insight_cards"), prefix)
            alert_block = analysis.get("alert_scoring") or {}
            if isinstance(alert_block, dict):
                _ensure_card_titles(alert_block.get("top_alerts"), f"{prefix} Alert")
    return json_data


def _build_brief_response_schema() -> types.Schema:
    insight_schema = types.Schema(
        type=types.Type.OBJECT,
        properties={
            "title": types.Schema(type=types.Type.STRING),
            "details": types.Schema(type=types.Type.STRING),
        },
        required=["title", "details"],
    )
    section_schema = types.Schema(
        type=types.Type.OBJECT,
        properties={
            "title": types.Schema(type=types.Type.STRING),
            "content": types.Schema(type=types.Type.STRING),
            "insights": types.Schema(
                type=types.Type.ARRAY,
                items=insight_schema,
            ),
        },
        required=["title", "content", "insights"],
    )
    return types.Schema(
        type=types.Type.OBJECT,
        properties={
            "header": types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "title": types.Schema(type=types.Type.STRING),
                    "summary": types.Schema(type=types.Type.STRING),
                },
                required=["title", "summary"],
            ),
            "body": types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "sections": types.Schema(
                        type=types.Type.ARRAY,
                        min_items=1,
                        items=section_schema,
                    ),
                },
                required=["sections"],
            ),
        },
        required=["header", "body"],
    )



def _contract_presentation_unit(contract: Any | None) -> str | None:
    if not contract:
        return None
    presentation = getattr(contract, "presentation", None)
    unit = None
    if isinstance(presentation, dict):
        unit = presentation.get("unit")
    elif presentation is not None:
        unit = getattr(presentation, "unit", None)
    if unit is None:
        return None
    text_value = str(unit).strip()
    return text_value or None

EXECUTIVE_BRIEF_RESPONSE_SCHEMA = _build_brief_response_schema()


NETWORK_SECTION_CONTRACT = [
    {"title": "Executive Summary", "mode": "content"},
    {"title": "Key Findings", "mode": "insights"},
    {"title": "Recommended Actions", "mode": "insights_min_2"},
]

SCOPED_SECTION_CONTRACT = [
    {"title": "Executive Summary", "mode": "content"},
    {"title": "Scope Overview", "mode": "content"},
    {"title": "Key Findings", "mode": "insights"},
    {"title": "Recommended Actions", "mode": "insights_min_2"},
]

TOP_INSIGHT_MIN_COUNT = 3


def _apply_section_contract(brief: dict, section_contract: list[dict[str, str]]) -> dict:
    """Ensure the LLM JSON matches the required section titles/order."""
    header = brief.setdefault("header", {})
    header_title = str(header.get("title") or "").strip()
    header_summary = str(header.get("summary") or "").strip()
    header["title"] = header_title or "Executive Brief"
    header["summary"] = header_summary or SECTION_FALLBACK_TEXT

    body = brief.setdefault("body", {})
    existing_sections = {}
    for raw in body.get("sections", []) or []:
        if isinstance(raw, dict):
            title = str(raw.get("title") or "").strip()
            if title:
                existing_sections[title] = raw

    def _placeholder_insight(section_title: str, idx: int) -> dict[str, str]:
        suffix = f" {idx + 1}" if idx else ""
        return {
            "title": f"{section_title} insight{suffix}".strip(),
            "details": SECTION_FALLBACK_TEXT,
        }

    normalized = []
    for spec in section_contract:
        title = spec["title"]
        src = existing_sections.get(title, {})
        content = str(src.get("content") or "").strip()
        insights_raw = src.get("insights") if isinstance(src, dict) else None
        mode = spec.get("mode", "content")

        if mode == "insights" or mode == "insights_min_2":
            insights: list[dict[str, str]] = []
            if isinstance(insights_raw, list):
                for item in insights_raw:
                    if not isinstance(item, dict):
                        continue
                    entry_title = str(item.get("title") or "").strip()
                    entry_details = str(item.get("details") or "").strip()
                    if not entry_title and not entry_details:
                        continue
                    insights.append(
                        {
                            "title": entry_title or f"{title} insight",
                            "details": entry_details or SECTION_FALLBACK_TEXT,
                        }
                    )
            # Determine minimum required insights
            if title == "Key Findings":
                required = TOP_INSIGHT_MIN_COUNT
            elif mode == "insights_min_2":
                required = 2
            else:
                required = 1
            
            if not insights:
                insights.append(_placeholder_insight(title, 0))
            while len(insights) < required:
                insights.append(_placeholder_insight(title, len(insights)))

            normalized.append(
                {
                    "title": title,
                    "content": content or SECTION_FALLBACK_TEXT,
                    "insights": insights,
                }
            )
        else:
            normalized.append(
                {
                    "title": title,
                    "content": content or SECTION_FALLBACK_TEXT,
                    "insights": [],
                }
            )

    body["sections"] = normalized
    return brief



def _count_numeric_values(text: str) -> int:
    """Count specific numeric values in text.
    
    Counts: integers, floats, percentages, currency amounts, numbers with units.
    Examples: "503,687", "$420K", "158.2%", "z-score 2.06", "1.8M"
    """
    if not text:
        return 0
    import re
    # Pattern matches: numbers with commas, decimals, percentages, currency, units (K, M, B)
    # Also matches scientific notation and numbers in statistical contexts
    patterns = [
        r'\$[\d,]+(?:\.\d+)?[KMB]?',  # Currency: $420K, $1.5M
        r'\d+(?:,\d{3})*(?:\.\d+)?%',  # Percentages: 158.2%, 22%
        r'\d+(?:,\d{3})*(?:\.\d+)?[KMB](?!\w)',  # With units: 503K, 1.8M, 2.3B
        r'\d+(?:,\d{3})*\.\d+',  # Decimals: 2.06, 0.33
        r'\d+(?:,\d{3})+',  # Comma-separated: 503,687
        r'(?:z-score|p-value|r=|correlation)\s*[=:]?\s*[-+]?\d+(?:\.\d+)?',  # Statistical: z-score 2.06, p-value 0.33, r=1.0
    ]
    matches = set()  # Use set to avoid counting the same value twice
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            matches.add(match.group())
    return len(matches)


def _validate_structured_brief(
    brief: dict,
    section_contract: list[dict[str, str]] | None,
    has_critical_findings: bool = False,
    critical_metrics: list[str] | None = None,
    min_insight_values: int = 3,
    is_scoped: bool = False,
) -> list[str]:
    """Return a list of validation errors for the structured brief payload.
    
    Args:
        min_insight_values: Minimum numeric values per Key Findings insight (default 3).
                           Use 2 for scoped briefs with less signal.
        is_scoped: True for entity-scoped briefs (relaxed validation).
    """

    errors: list[str] = []
    header = brief.get("header") or {}
    header_title = str(header.get("title") or "").strip()
    header_summary = str(header.get("summary") or "").strip()
    if not header_title:
        errors.append("header.title is empty")
    if not header_summary:
        errors.append("header.summary is empty")
    
    # Validate header has minimum numeric values
    header_value_count = _count_numeric_values(header_title + " " + header_summary)
    if header_value_count < 2:
        errors.append(
            f"header contains only {header_value_count} numeric values (minimum: 2)"
        )
    
    # Check for forbidden fallback when critical findings exist
    if has_critical_findings and critical_metrics:
        fallback_lower = SECTION_FALLBACK_TEXT.lower()
        if header_summary and fallback_lower in header_summary.lower():
            errors.append(
                f"CRITICAL VIOLATION: header.summary uses fallback text but critical findings exist in: {', '.join(critical_metrics)}"
            )

    body = brief.get("body") or {}
    sections = body.get("sections") or []
    if not isinstance(sections, list) or not sections:
        errors.append("body.sections missing or empty")
        return errors
    
    # Check each section for forbidden fallback when critical findings exist
    if has_critical_findings and critical_metrics:
        fallback_lower = SECTION_FALLBACK_TEXT.lower()
        for idx, section in enumerate(sections):
            if not isinstance(section, dict):
                continue
            section_title = section.get("title", f"Section {idx}")
            content = str(section.get("content") or "").strip().lower()
            if content and fallback_lower in content:
                # Allow fallback ONLY for sections that explicitly mention metrics without critical findings
                # or for Recommended Actions section
                if section_title not in ("Recommended Actions",):
                    # Check if the content mentions any of the critical metrics
                    critical_mention = any(
                        metric.lower() in content for metric in critical_metrics
                    )
                    if critical_mention or section_title in ("Executive Summary", "Key Findings", "Scope Overview"):
                        errors.append(
                            f"CRITICAL VIOLATION: Section '{section_title}' uses fallback text but critical findings exist in: {', '.join(critical_metrics)}"
                        )
            
            # Check insights for fallback
            insights = section.get("insights", [])
            if isinstance(insights, list):
                for insight in insights:
                    if not isinstance(insight, dict):
                        continue
                    details = str(insight.get("details") or "").strip().lower()
                    if details and fallback_lower in details:
                        insight_title = insight.get("title", "Unknown")
                        errors.append(
                            f"CRITICAL VIOLATION: Insight '{insight_title}' in '{section_title}' uses fallback text but critical findings exist in: {', '.join(critical_metrics)}"
                        )

    expected_titles = [spec["title"] for spec in section_contract] if section_contract else None
    actual_titles: list[str] = []
    total_numeric_values = header_value_count  # Start with header values
    for idx, section in enumerate(sections):
        if not isinstance(section, dict):
            errors.append(f"body.sections[{idx}] is not an object")
            continue
        title = str(section.get("title") or "").strip()
        actual_titles.append(title)
        content = str(section.get("content") or "").strip()
        if not title:
            errors.append(f"body.sections[{idx}] missing title")
        if not content:
            errors.append(f"{title or f'section[{idx}]'} content empty")
        elif content == SECTION_FALLBACK_TEXT:
            errors.append(
                f"{title or f'section[{idx}]'} contains only placeholder fallback text - "
                "LLM did not populate this section"
            )
        
        # Count values in section content
        total_numeric_values += _count_numeric_values(content)
        
        insights = section.get("insights")
        if insights is None:
            errors.append(f"{title or f'section[{idx}]'} missing insights array")
            continue
        if not isinstance(insights, list):
            errors.append(f"{title or f'section[{idx}]'} insights is not a list")
            continue
        if title == "Key Findings":
            min_key_findings = 2 if is_scoped else TOP_INSIGHT_MIN_COUNT
            if len(insights) < min_key_findings:
                errors.append(f"Key Findings must include at least {min_key_findings} entries")
            if len(insights) > 5:
                errors.append("Key Findings must not include more than five entries")
        for insight_idx, insight in enumerate(insights):
            if not isinstance(insight, dict):
                errors.append(f"{title or f'section[{idx}]'} insight {insight_idx} is not an object")
                continue
            details = str(insight.get("details") or "").strip()
            title_field = str(insight.get("title") or "").strip()
            if title == "Key Findings" and not details:
                errors.append(f"Key Findings entry {insight_idx} missing details")
            elif details == SECTION_FALLBACK_TEXT:
                errors.append(
                    f"Key Findings entry {insight_idx} contains only placeholder fallback text - "
                    "LLM did not populate this insight"
                )
            if not details and not title_field:
                errors.append(f"{title or f'section[{idx}]'} insight {insight_idx} missing title/detail content")
            
            # Validate numeric values in Key Findings insights
            if title == "Key Findings" and details:
                insight_text = title_field + " " + details
                insight_value_count = _count_numeric_values(insight_text)
                total_numeric_values += insight_value_count
                if insight_value_count < min_insight_values:
                    errors.append(
                        f"Key Findings insight '{title_field or f'#{insight_idx + 1}'}' contains only "
                        f"{insight_value_count} numeric values (minimum: {min_insight_values}). Include more specific amounts, "
                        "percentages, baselines, or statistical values."
                    )

    if expected_titles and actual_titles != expected_titles:
        errors.append(
            "Section titles/order mismatch: " + ", ".join(actual_titles or ["<empty>"])
        )
    
    # Validate total numeric values across entire brief
    MINIMUM_TOTAL_VALUES = 10 if is_scoped else 15
    if total_numeric_values < MINIMUM_TOTAL_VALUES:
        errors.append(
            f"Brief contains only {total_numeric_values} total numeric values (minimum: {MINIMUM_TOTAL_VALUES}). "
            "Include more specific amounts, percentages, baselines, entity breakdowns, and statistical context."
        )

    return errors



def _format_instruction(template: str, **fields: str) -> str:
    """Safely render the executive-brief prompt with literal braces intact."""
    placeholders = {key: f"<<{key.upper()}_PLACEHOLDER>>" for key in fields}
    safe = template
    for key, token in placeholders.items():
        safe = safe.replace(f"{{{key}}}", token)
    safe = safe.replace("{", "{{").replace("}", "}}")
    for key, token in placeholders.items():
        safe = safe.replace(token, f"{{{key}}}")
    return safe.format(**fields)


def _extract_response_text(response: Any) -> str:
    text = (getattr(response, "text", None) or "").strip()
    if text:
        return text
    parts: list[str] = []
    try:
        candidates = getattr(response, "candidates", []) or []
        for candidate in candidates:
            content = getattr(candidate, "content", None)
            content_parts = getattr(content, "parts", None) if content else None
            if not content_parts and hasattr(candidate, "parts"):
                content_parts = getattr(candidate, "parts", None)
            if not content_parts:
                continue
            for part in content_parts:
                part_text = getattr(part, "text", "")
                if part_text:
                    parts.append(part_text)
    except Exception:
        return ""
    return "".join(parts).strip()


async def _llm_generate_brief(
    model_name: str,
    instruction: str,
    user_message: str,
    thinking_config: Any,
    digest: str = "",
    section_contract: list[dict[str, str]] | None = None,
    reports: dict[str, str] | None = None,
    unit: str | None = None,
    has_critical_findings: bool = False,
    critical_metrics: list[str] | None = None,
    max_attempts: int | None = None,
    min_insight_values: int = 3,
    is_scoped: bool = False,
) -> tuple[dict, str, bool]:
    """Call the LLM to generate a brief JSON.

    Args:
        max_attempts: Maximum retry attempts. If None, uses BRIEF_CONFIG.max_llm_retries().
        min_insight_values: Minimum numeric values per Key Findings insight (default 3 for network, 2 for scoped).
        is_scoped: True for entity-scoped briefs (relaxed validation).

    Returns:
        Tuple of (brief_data_dict, brief_markdown, used_structured_fallback).
    """
    import asyncio

    config = types.GenerateContentConfig(
        system_instruction=instruction,
        response_modalities=["TEXT"],
        response_mime_type="application/json",
        response_schema=EXECUTIVE_BRIEF_RESPONSE_SCHEMA,
        temperature=0.05,
        thinking_config=thinking_config,
    )
    loop = asyncio.get_running_loop()
    fallback_payload: tuple[dict, str] | None = None
    last_err: Exception | None = None
    if max_attempts is None:
        max_attempts = BRIEF_CONFIG.max_llm_retries()

    def _structured_fallback(reason: str) -> tuple[dict, str]:
        recs = collect_recommendations_from_reports(reports or {}, unit=unit) if reports else []
        brief_json = build_structured_fallback_brief(digest, reason, recs, unit=unit)
        brief_markdown = _build_structured_fallback_markdown(digest, recs, unit=unit)
        return brief_json, brief_markdown

    for attempt in range(1, max_attempts + 1):
        try:
            client = genai.Client()
            response = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: client.models.generate_content(
                        model=model_name,
                        contents=user_message,
                        config=config,
                    ),
                ),
                timeout=BRIEF_CONFIG.llm_timeout_seconds(),
            )
            raw = _extract_response_text(response)
            if not raw:
                print("[BRIEF] Empty response payload from LLM — using deterministic fallback.")
                fallback_json, fallback_markdown = _structured_fallback("Empty response from LLM")
                return fallback_json, fallback_markdown, True
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
            try:
                brief_data = _parse_brief_json_payload(raw)
            except json.JSONDecodeError as json_err:
                print(f"[BRIEF] JSON parse failed: {json_err}. Falling back to structured digest.")
                fallback_json, fallback_markdown = _structured_fallback(f"JSON parse failed: {json_err}")
                return fallback_json, fallback_markdown, True
            except ValueError as val_err:
                reason = f"Invalid JSON payload: {val_err}"
                print(f"[BRIEF] {reason} Falling back to structured digest.")
                fallback_json, fallback_markdown = _structured_fallback(reason)
                return fallback_json, fallback_markdown, True
            
            # PRE-NORMALIZATION VALIDATION: Check if LLM returned the required section titles
            if section_contract:
                expected_titles = [spec["title"] for spec in section_contract]
                actual_sections = brief_data.get("body", {}).get("sections", [])
                actual_titles = [
                    str(s.get("title", "")).strip() 
                    for s in actual_sections 
                    if isinstance(s, dict)
                ]
                
                if actual_titles != expected_titles:
                    error_msg = (
                        f"LLM returned wrong section titles. "
                        f"Expected: {', '.join(expected_titles)}. "
                        f"Got: {', '.join(actual_titles or ['<empty>'])}"
                    )
                    print(f"[BRIEF] Attempt {attempt}/{max_attempts}: {error_msg}")
                    if attempt < max_attempts:
                        print(f"[BRIEF] Retrying with stronger section title enforcement...")
                        await asyncio.sleep(BRIEF_CONFIG.retry_delay_seconds())
                        continue
                    else:
                        # After exhausting retries, RAISE to trigger fallback
                        raise ValueError(
                            f"LLM persistently returned wrong section titles after {max_attempts} attempts: "
                            f"got {actual_titles}, expected {expected_titles}"
                        )
            
            if section_contract:
                brief_data = _apply_section_contract(brief_data, section_contract)
            else:
                brief_data.setdefault("header", {})
                brief_data.setdefault("body", {}).setdefault("sections", [])

            structural_errors = _validate_structured_brief(
                brief_data, 
                section_contract,
                has_critical_findings=has_critical_findings,
                critical_metrics=critical_metrics or [],
                min_insight_values=min_insight_values,
                is_scoped=is_scoped
            )
            if structural_errors:
                # Check if errors include SECTION_FALLBACK_TEXT usage (indicates normalization failure)
                fallback_errors = [e for e in structural_errors if "fallback text" in e.lower()]
                if fallback_errors:
                    print(f"[BRIEF] Fallback text detected: {'; '.join(fallback_errors)}")
                    if attempt < max_attempts:
                        print(f"[BRIEF] Retrying...")
                        continue
                raise ValueError(
                    "Structured brief failed validation: " + '; '.join(structural_errors)
                )

            brief_markdown, used_fallback = _format_brief_with_fallback(brief_data, digest)
            if used_fallback:
                fallback_payload = (brief_data, brief_markdown)
                if attempt < max_attempts:
                    print(
                        f"[BRIEF] Attempt {attempt}/{max_attempts} produced fallback output. Retrying in {BRIEF_CONFIG.retry_delay_seconds()}s..."
                    )
                    await asyncio.sleep(BRIEF_CONFIG.retry_delay_seconds())
                    continue
                print("[BRIEF] LLM returned fallback output after all retries — using structured fallback.")
                return brief_data, brief_markdown, True

            return brief_data, brief_markdown, False
        except Exception as attempt_err:
            last_err = attempt_err
            if attempt < max_attempts:
                print(f"[BRIEF] Attempt {attempt}/{max_attempts} failed: {attempt_err}. Retrying in {BRIEF_CONFIG.retry_delay_seconds()}s...")
                await asyncio.sleep(BRIEF_CONFIG.retry_delay_seconds())
            else:
                print(f"[BRIEF] Attempt {attempt}/{max_attempts} failed: {attempt_err}.")

    if fallback_payload:
        print("[BRIEF] All attempts resulted in fallback output — using structured fallback text.")
        return fallback_payload[0], fallback_payload[1], True
    if last_err:
        raise last_err
    raise RuntimeError("LLM failed to return executive brief output")



class CrossMetricExecutiveBriefAgent(BaseAgent):
    """Synthesizes all per-metric analysis reports into a single executive brief."""

    def __init__(self) -> None:
        super().__init__(name="executive_brief_agent")

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        import asyncio

        print("\n" + "=" * 80)
        print("[BRIEF] CrossMetricExecutiveBriefAgent starting")
        print("=" * 80)

        run_dir = os.getenv("DATA_ANALYST_OUTPUT_DIR")
        outputs_dir = Path(run_dir).resolve() if run_dir else Path("outputs").resolve()
        reports = _collect_metric_reports(outputs_dir)

        extracted_targets = ctx.session.state.get("extracted_targets") or []
        if extracted_targets:
            requested = {str(t).strip().replace(" ", "_").lower() for t in extracted_targets}
            reports = {k: v for k, v in reports.items() if k.replace(" ", "_").lower() in requested}
            if reports:
                print(f"[BRIEF] Filtered to {len(reports)} requested metric(s): {', '.join(reports.keys())}")

        if not reports:
            if extracted_targets:
                print("[BRIEF] No metric reports found for requested metric(s). Skipping.")
            else:
                print("[BRIEF] No metric reports found in outputs/. Skipping.")
            yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=EventActions())
            return

        print(f"[BRIEF] Found {len(reports)} metric report(s): {', '.join(reports.keys())}")

        contract = ctx.session.state.get("dataset_contract")
        presentation_unit = _contract_presentation_unit(contract)

        timeframe = ctx.session.state.get("timeframe", {})
        period_end = timeframe.get("end") or ctx.session.state.get("primary_query_end_date")
        if not period_end:
            first_content = next(iter(reports.values()), "")
            match = re.search(r"\d{4}-\d{2}-\d{2}", first_content)
            period_end = match.group(0) if match else datetime.now().strftime("%Y-%m-%d")
        analysis_period = ctx.session.state.get("analysis_period") or _format_analysis_period(
            period_end, contract
        )
        print(f"[BRIEF] Analysis period: {analysis_period}")

        json_data = _collect_metric_json_data(outputs_dir)
        if extracted_targets:
            requested = {str(t).strip().replace(" ", "_").lower() for t in extracted_targets}
            json_data = {k: v for k, v in json_data.items() if k.replace(" ", "_").lower() in requested}
        if json_data:
            json_data = _backfill_missing_titles(json_data)

        raw_focus_lines = get_focus_lines(ctx.session.state)
        focus_block = "\n".join(f"- {line}" for line in raw_focus_lines)
        focus_block_with_header = build_focus_block(ctx.session.state)

        use_json = parse_bool_env(os.environ.get("EXECUTIVE_BRIEF_USE_JSON", "true"))
        if use_json and json_data:
            digest = _build_digest_from_json(reports, json_data, presentation_unit)
            print(f"[BRIEF] Using JSON-backed digest ({len(json_data)} metrics)")
        else:
            digest = _build_digest(reports)
            print("[BRIEF] Using markdown-only digest")

        digest = _apply_unit_to_text(digest, presentation_unit)

        drill_levels = 0
        max_scope_entities = 10
        min_scope_share_of_total = 0.0
        output_format = "pdf"

        try:
            import yaml

            config_path = Path(__file__).resolve().parents[3] / "config" / "report_config.yaml"
            if config_path.exists():
                with open(config_path, "r", encoding="utf-8") as f:
                    report_cfg = yaml.safe_load(f) or {}
                    eb_cfg = report_cfg.get("executive_brief", {})
                    drill_levels = eb_cfg.get("drill_levels", 0)
                    max_scope_entities = eb_cfg.get("max_scope_entities", 10)
                    min_scope_share_of_total = float(eb_cfg.get("min_scope_share_of_total", min_scope_share_of_total))
                    output_format = eb_cfg.get("output_format", "pdf")
        except Exception as e:
            print(f"[BRIEF] Warning: Failed to load report_config.yaml: {e}")

        if contract and getattr(contract, "reporting", None):
            reporting_cfg = contract.reporting
            drill_levels = reporting_cfg.executive_brief_drill_levels
            max_scope_entities = reporting_cfg.max_scope_entities
            min_scope_share_of_total = float(getattr(reporting_cfg, "min_scope_share_of_total", min_scope_share_of_total) or 0.0)
            output_format = reporting_cfg.output_format
            print(f"[BRIEF] Using reporting settings from contract: {contract.name}")

        session_drill = ctx.session.state.get("executive_brief_drill_levels")
        if session_drill is not None:
            try:
                drill_levels = int(session_drill)
            except (ValueError, TypeError):
                pass

        env_drill = os.environ.get("EXECUTIVE_BRIEF_DRILL_LEVELS")
        if env_drill is not None:
            try:
                drill_levels = int(env_drill)
                print(f"[BRIEF] Overriding drill_levels={drill_levels} from env")
            except (ValueError, TypeError):
                pass

        env_max_scope = os.environ.get("EXECUTIVE_BRIEF_MAX_SCOPE_ENTITIES")
        if env_max_scope is not None:
            try:
                max_scope_entities = int(env_max_scope)
                print(f"[BRIEF] Overriding max_scope_entities={max_scope_entities} from env")
            except (ValueError, TypeError):
                pass

        env_min_scope_share = os.environ.get("EXECUTIVE_BRIEF_MIN_SCOPE_SHARE")
        if env_min_scope_share is not None:
            try:
                min_scope_share_of_total = float(env_min_scope_share)
                print(f"[BRIEF] Overriding min_scope_share_of_total={min_scope_share_of_total:.4f} from env")
            except (ValueError, TypeError):
                pass

        # Build contract-driven context for the prompt
        contract = ctx.session.state.get("dataset_contract")
        dataset_name = getattr(contract, "display_name", getattr(contract, "name", "the dataset")) if contract else "the dataset"
        dataset_desc = getattr(contract, "description", "") if contract else ""
        contract_context = f"\nDataset: {dataset_name}."
        if dataset_desc:
            contract_context += f" {dataset_desc.strip()}"
        contract_context_text = contract_context + format_contract_context(contract)
        contract_metadata = build_contract_metadata(contract)
        contract_metadata_block = ""
        if contract_metadata:
            contract_metadata_block = (
                "CONTRACT_METADATA_JSON (contract-derived — do not invent or omit fields):\n"
                f"{json.dumps(contract_metadata, indent=2, ensure_ascii=False)}\n\n"
            )
        contract_reference_block = format_contract_reference_block(contract)
        # Use ANALYZED metrics (from filtered reports) instead of ALL contract metrics
        # This prevents the brief from trying to synthesize insights for non-analyzed metrics
        metric_names = sorted(reports.keys())
        metric_coverage_block = ""
        if metric_names:
            metric_coverage_block = (
                "METRIC_COVERAGE (mention every metric explicitly — add a monitoring sentence when no signal survives):\n"
                f"- {', '.join(metric_names)}\n\n"
            )

        # Build mandatory section title enforcement (will be injected into system instruction)
        expected_sections = [spec["title"] for spec in NETWORK_SECTION_CONTRACT]
        section_title_enforcement = (
            "\n\n⚠️⚠️⚠️ SECTION TITLE ENFORCEMENT (CRITICAL — RESPONSE WILL BE REJECTED IF VIOLATED) ⚠️⚠️⚠️\n\n"
            "Your JSON body.sections array MUST contain EXACTLY these section titles in this EXACT order:\n\n"
            + "\n".join(f"  {i+1}. \"{title}\"" for i, title in enumerate(expected_sections))
            + "\n\n"
            "❌ ABSOLUTELY FORBIDDEN SECTION TITLES (RESPONSE REJECTED IF USED):\n"
            "   ❌ \"Opening\" → Use \"Executive Summary\" instead\n"
            "   ❌ \"Top Operational Insights\" → Use \"Key Findings\" instead\n"
            "   ❌ \"Network Snapshot\" → Merge into \"Key Findings\"\n"
            "   ❌ \"Focus For Next Week\" → Merge into \"Recommended Actions\"\n"
            "   ❌ \"Leadership Question\" → Merge into \"Recommended Actions\"\n"
            "   ❌ Any other custom titles → FORBIDDEN\n\n"
            "VALIDATION: Your response will be parsed and section titles checked BEFORE acceptance.\n"
            "If titles don't match EXACTLY, your response will be REJECTED and you will retry.\n"
        )
        
        instruction = _format_instruction(
            EXECUTIVE_BRIEF_INSTRUCTION,
            metric_count=len(reports),
            analysis_period=analysis_period,
            scope_preamble=focus_block,
            dataset_specific_append=load_dataset_specific_append() + contract_context_text,
            prompt_variant_append=load_prompt_variant(os.environ.get("EXECUTIVE_BRIEF_PROMPT_VARIANT", "default")),
        )
        # Inject section title enforcement directly into system instruction for maximum weight
        instruction = instruction + section_title_enforcement
        instruction = augment_instruction(instruction, ctx.session.state)
        weather_block = _build_weather_context_block(ctx.session.state.get("weather_context"))

        temporal_grain = ctx.session.state.get("temporal_grain", "unknown")
        canonical_grain = normalize_temporal_grain(temporal_grain)
        period_unit = temporal_grain_to_period_unit(canonical_grain)
        brief_temporal_context = {
            "reference_period_end": period_end,
            "temporal_grain": canonical_grain,
            "analysis_period": analysis_period,
            "period_unit": period_unit,
            "default_comparison_basis": _default_comparison_basis(canonical_grain),
            "comparison_priority_order": _build_comparison_priority(canonical_grain),
            "comparison_requirement": (
                "Every comparative claim must include its explicit baseline in the same sentence."
            ),
        }

        focus_preamble_text = f"{focus_block_with_header}\n\n" if focus_block_with_header else ""
        contract_summary_block = contract_context_text.strip()
        if contract_summary_block:
            contract_summary_block = contract_summary_block + "\n\n"

        # JSON enforcement block (kept in user message for immediate visibility)
        json_enforcement_block = (
            "⚠️ JSON OUTPUT REQUIREMENTS (CRITICAL):\n"
            "1. '{' must be the FIRST character of your reply and '}' the LAST.\n"
            "2. Do NOT wrap the JSON in markdown fences (```json...```).\n"
            "3. Do NOT include any prose, acknowledgements, or explanations outside the JSON object.\n"
            "4. Your response must deserialize into the exact header/body/sections structure defined in the system instruction.\n\n"
        )

        # Check for CRITICAL/HIGH severity findings and build enforcement block
        has_critical, critical_metrics = has_critical_or_high_findings(json_data)
        severity_enforcement_block = build_severity_enforcement_block(has_critical, critical_metrics)
        
        if has_critical:
            print(f"[BRIEF] CRITICAL/HIGH findings detected in: {', '.join(critical_metrics)}")
            print("[BRIEF] Injecting severity enforcement to prevent fallback boilerplate")

        # Build monthly grain enforcement block when monthly temporal grain is detected
        monthly_enforcement_block = ""
        if canonical_grain == "monthly":
            print("[BRIEF] Monthly grain detected — injecting sequential comparison enforcement")
            monthly_enforcement_block = (
                "⚠️ MONTHLY GRAIN ENFORCEMENT (MANDATORY):\n"
                "The analysis uses MONTHLY temporal grain. You MUST provide SEQUENTIAL month-over-month comparisons in your Key Findings.\n"
                "- DO NOT write: 'Cases decreased 95% from January peak' (endpoint only)\n"
                "- ALWAYS write: 'Cases decreased 35.7% from January to February, then declined another 33.7% from February to March, reaching April levels 67% below the January peak.'\n"
                "- Show the PROGRESSION across ALL months in the period\n"
                "- Use the monthly_totals data from the digest to calculate sequential changes\n"
                "- Format: 'Month1→Month2: X%, Month2→Month3: Y%'\n\n"
            )

        # Build explicit section title reminder for user message (reinforces system instruction)
        section_title_reminder = (
            f"⚠️ REQUIRED SECTION TITLES (in this exact order):\n"
            f"{', '.join(f'\"{t}\"' for t in expected_sections)}\n\n"
        )
        
        user_message = (
            f"{section_title_reminder}"  # FIRST — most visible position
            f"{json_enforcement_block}"
            f"{focus_preamble_text}"
            f"{contract_summary_block}"
            f"{contract_metadata_block}"
            f"{contract_reference_block}"
            f"{metric_coverage_block}"
            f"{severity_enforcement_block}"
            f"{monthly_enforcement_block}"
            f"BRIEF_TEMPORAL_CONTEXT (MANDATORY GROUNDING):\n"
            f"{json.dumps(brief_temporal_context, indent=2)}\n\n"
            f"Use the above 'reference_period_end' when writing header.title.\n\n"
            f"Here are the individual metric analysis summaries for {analysis_period}.\n\n"
            f"{digest}\n\n"
            f"{weather_block}"
            "Generate the executive brief JSON as instructed. Your response must be ONLY the JSON object — no markdown fences, no preamble, no explanation."
        )

        metric_names = sorted(reports.keys())
        model_name = get_agent_model("executive_brief_agent")
        thinking_config = get_agent_thinking_config("executive_brief_agent")

        _write_executive_brief_cache(
            outputs_dir=outputs_dir,
            digest=digest + weather_block,
            period_end=period_end,
            analysis_period=analysis_period,
            metric_names=metric_names,
            timeframe=timeframe if isinstance(timeframe, dict) else {},
            weather_context=ctx.session.state.get("weather_context"),
            dataset=ctx.session.state.get("dataset"),
            contract_metadata=contract_metadata,
        )

        print(f"[BRIEF] Sending digest ({len(digest)} chars) to LLM...")

        try:
            brief_json, brief_md, used_fallback = await _llm_generate_brief(
                model_name=model_name,
                instruction=instruction,
                user_message=user_message,
                thinking_config=thinking_config,
                digest=digest,
                section_contract=NETWORK_SECTION_CONTRACT,
                reports=reports,
                unit=presentation_unit,
                has_critical_findings=has_critical,
                critical_metrics=critical_metrics,
            )

            if used_fallback:
                print("[BRIEF] WARNING: Structured fallback output detected for network brief.")

            brief_filename = "brief.md" if os.getenv("DATA_ANALYST_OUTPUT_DIR") else f"executive_brief_{period_end}.md"
            brief_path = outputs_dir / brief_filename
            brief_path.write_text(brief_md, encoding="utf-8")
            print(f"[BRIEF] Saved executive brief to {brief_filename}")
            print(f"[BRIEF] File size: {brief_path.stat().st_size} bytes")

            json_filename = "brief.json" if os.getenv("DATA_ANALYST_OUTPUT_DIR") else f"executive_brief_{period_end}.json"
            brief_json_path = outputs_dir / json_filename
            brief_json_path.write_text(json.dumps(brief_json, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"[BRIEF] Saved executive brief JSON to {json_filename}")

            print("\n" + "=" * 80)
            print("EXECUTIVE BRIEF")
            print("=" * 80)
            print(brief_md)
            print("=" * 80 + "\n")

            scoped_briefs: dict[str, dict[str, Any]] = {}
            scoped_digests_map: dict[str, str] = {}
            hierarchy_hint = ctx.session.state.get("selected_hierarchy") or ctx.session.state.get("hierarchy_name")
            scope_level_labels = derive_scope_level_labels(contract, preferred_name=hierarchy_hint)
            max_scoped_briefs = _max_scoped_briefs()
            scoped_sem = asyncio.Semaphore(_scope_concurrency_limit())

            async def _generate_scoped_brief(
                entity: str,
                level_name: str,
                scoped_instruction: str,
                scoped_user_message: str,
                scoped_digest: str,
                level: int,
            ) -> tuple[str, dict[str, Any] | None]:
                async with scoped_sem:
                    print(f"[BRIEF] Generating scoped brief for {entity} ({level_name})...")
                    try:
                        scoped_json, scoped_brief_md, scoped_fallback = await _llm_generate_brief(
                            model_name=model_name,
                            instruction=scoped_instruction,
                            user_message=scoped_user_message,
                            thinking_config=thinking_config,
                            digest=scoped_digest,
                            section_contract=SCOPED_SECTION_CONTRACT,
                            reports=reports,
                            unit=presentation_unit,
                            has_critical_findings=False,  # TODO: Implement scope-specific critical check
                            critical_metrics=[],
                            max_attempts=BRIEF_CONFIG.max_scoped_retries(),
                            min_insight_values=2,  # Scoped briefs have less signal, require only 2 values
                            is_scoped=True,  # Relaxed validation for entity-scoped briefs
                        )
                        if scoped_fallback:
                            print(f"[BRIEF] WARNING: Scoped brief for {entity} used structured fallback output.")
                        safe_entity = _sanitize_entity_name(entity)
                        scoped_filename = (
                            "brief_" + safe_entity + ".md"
                            if os.getenv("DATA_ANALYST_OUTPUT_DIR")
                            else f"executive_brief_{period_end}_{safe_entity}.md"
                        )
                        scoped_path = outputs_dir / scoped_filename
                        scoped_path.write_text(scoped_brief_md, encoding="utf-8")
                        print(f"[BRIEF] Saved scoped brief for {entity} to {scoped_filename}")
                        scoped_json_filename = (
                            "brief_" + safe_entity + ".json"
                            if os.getenv("DATA_ANALYST_OUTPUT_DIR")
                            else f"executive_brief_{period_end}_{safe_entity}.json"
                        )
                        scoped_json_path = outputs_dir / scoped_json_filename
                        scoped_json_path.write_text(json.dumps(scoped_json, indent=2, ensure_ascii=False), encoding="utf-8")
                        return (
                            entity,
                            {
                                "path": str(scoped_path),
                                "json_path": str(scoped_json_path),
                                "content": scoped_brief_md,
                                "level": level,
                                "level_name": level_name,
                                "bookmark_label": f"{entity} ({level_name})",
                                "used_fallback": scoped_fallback,
                            },
                        )
                    except Exception as scope_err:
                        print(f"[BRIEF] ERROR generating scoped brief for {entity}: {scope_err}")
                        return entity, None

            if drill_levels >= 1 and json_data:
                print(f"[BRIEF] Drill levels={drill_levels}: generating scoped briefs")
                scheduled_scoped = 0
                for level in range(1, min(drill_levels, 2) + 1):
                    if max_scoped_briefs and scheduled_scoped >= max_scoped_briefs:
                        print(
                            f"[BRIEF] Reached EXECUTIVE_BRIEF_MAX_SCOPED_BRIEFS={max_scoped_briefs}; skipping remaining levels"
                        )
                        break

                    entities = _discover_level_entities(
                        json_data,
                        level,
                        min_share_of_total=min_scope_share_of_total,
                    )
                    if level == 2:
                        entities = entities[:max_scope_entities]
                    level_name = scope_level_labels.get(level, f"Level {level}")

                    if max_scoped_briefs:
                        remaining = max_scoped_briefs - scheduled_scoped
                        if remaining <= 0:
                            break
                        if len(entities) > remaining:
                            print(
                                f"[BRIEF] Level {level} truncated to {remaining} entity(ies) due to EXECUTIVE_BRIEF_MAX_SCOPED_BRIEFS={max_scoped_briefs}"
                            )
                            entities = entities[:remaining]

                    print(f"[BRIEF] Level {level} ({level_name}): {len(entities)} entities: {', '.join(entities)}")

                    hierarchy_map = _load_hierarchy_level_mapping(
                        json_data,
                        level,
                        level + 1,
                        contract=contract,
                        preferred_hierarchy=hierarchy_hint,
                    )
                    if hierarchy_map:
                        total_children = sum(len(v) for v in hierarchy_map.values())
                        print(
                            f"[BRIEF] Hierarchy mapping loaded ({total_children} children across {len(hierarchy_map)} parents)"
                        )
                    else:
                        print("[BRIEF] No hierarchy mapping found — using Strategy A fallback")

                    tasks: list[asyncio.Task[tuple[str, dict[str, Any] | None]]] = []
                    for entity in entities:
                        scope_children = set(hierarchy_map.get(entity, [])) if hierarchy_map else None
                        scoped_digest = _build_scoped_digest(
                            json_data,
                            reports,
                            entity,
                            level,
                            analysis_period,
                            scope_children=scope_children,
                            unit=presentation_unit,
                        )
                        scoped_digests_map[entity] = scoped_digest

                        scope_preamble = SCOPED_BRIEF_PREAMBLE.format(
                            scope_entity=entity,
                            scope_level_name=level_name.lower(),
                        )
                        
                        # Build section title enforcement for scoped briefs (inject into system instruction)
                        scoped_expected_sections = [spec["title"] for spec in SCOPED_SECTION_CONTRACT]
                        scoped_section_enforcement = (
                            "\n\n⚠️ SECTION TITLE ENFORCEMENT (MANDATORY — VALIDATION WILL FAIL IF VIOLATED):\n"
                            "Your JSON body.sections array MUST contain EXACTLY these section titles in this order:\n"
                            + "\n".join(f"{i+1}. \"{title}\"" for i, title in enumerate(scoped_expected_sections))
                            + "\n\n"
                            "FORBIDDEN SECTION TITLES (DO NOT USE):\n"
                            "- \"Opening\" (use \"Executive Summary\" instead)\n"
                            "- \"Top Operational Insights\" (use \"Key Findings\" instead)\n"
                            "- \"Network Snapshot\" (merge into \"Key Findings\")\n"
                            "- \"Focus For Next Week\" (merge into \"Recommended Actions\")\n"
                            "- \"Leadership Question\" (merge into \"Recommended Actions\")\n"
                            "- Any other custom titles not listed above\n\n"
                            "VALIDATION PROCESS:\n"
                            "1. Parse your JSON response\n"
                            "2. Check body.sections[i].title matches expected titles exactly\n"
                            "3. If mismatch detected → automatic retry (up to 2 attempts for scoped briefs)\n"
                            "4. After exhausting retries → structured fallback output\n"
                        )
                        
                        scoped_instruction = _format_instruction(
                            EXECUTIVE_BRIEF_INSTRUCTION,
                            metric_count=len(reports),
                            analysis_period=analysis_period,
                            scope_preamble=scope_preamble,
                            dataset_specific_append=load_dataset_specific_append() + contract_context_text,
                            prompt_variant_append=load_prompt_variant(
                                os.environ.get("EXECUTIVE_BRIEF_PROMPT_VARIANT", "default")
                            ),
                        )
                        # Inject section title enforcement into system instruction
                        scoped_instruction = scoped_instruction + scoped_section_enforcement
                        scoped_instruction = augment_instruction(scoped_instruction, ctx.session.state)
                        
                        scoped_json_enforcement = (
                            "⚠️ JSON OUTPUT REQUIREMENTS (CRITICAL):\n"
                            "1. '{' must be the FIRST character of your reply and '}' the LAST.\n"
                            "2. Do NOT wrap the JSON in markdown fences (```json...```).\n"
                            "3. Do NOT include any prose, acknowledgements, or explanations outside the JSON object.\n"
                            "4. Your response must deserialize into the exact header/body/sections structure defined in the system instruction.\n\n"
                        )
                        
                        # Build explicit section title reminder for scoped brief
                        scoped_section_reminder = (
                            f"⚠️ REQUIRED SECTION TITLES (in this exact order):\n"
                            f"{', '.join(f'\"{t}\"' for t in scoped_expected_sections)}\n\n"
                        )
                        
                        scoped_user_message = (
                            f"{scoped_section_reminder}"  # FIRST — most visible
                            f"{scoped_json_enforcement}"
                            f"{focus_preamble_text}"
                            f"{contract_summary_block}"
                            f"{contract_metadata_block}"
                            f"{contract_reference_block}"
                            f"{metric_coverage_block}"
                            f"BRIEF_TEMPORAL_CONTEXT (MANDATORY GROUNDING):\n"
                            f"{json.dumps(brief_temporal_context, indent=2)}\n\n"
                            f"Use the above 'reference_period_end' when writing header.title.\n\n"
                            f"Here are the individual metric analysis summaries for {analysis_period}, scoped to {entity}.\n\n"
                            f"{scoped_digest}\n\n"
                            "Generate the executive brief JSON as instructed. Your response must be ONLY the JSON object — no markdown fences, no preamble, no explanation. Focus exclusively on this scope."
                        )

                        task = asyncio.create_task(
                            _generate_scoped_brief(
                                entity=entity,
                                level_name=level_name,
                                scoped_instruction=scoped_instruction,
                                scoped_user_message=scoped_user_message,
                                scoped_digest=scoped_digest,
                                level=level,
                            )
                        )
                        tasks.append(task)
                        scheduled_scoped += 1

                    if tasks:
                        results = await asyncio.gather(*tasks)
                        for entity_name, scoped_info in results:
                            if scoped_info:
                                scoped_briefs[entity_name] = scoped_info

                if scoped_digests_map:
                    _write_executive_brief_cache(
                        outputs_dir=outputs_dir,
                        digest=digest + weather_block,
                        period_end=period_end,
                        analysis_period=analysis_period,
                        metric_names=metric_names,
                        timeframe=timeframe if isinstance(timeframe, dict) else {},
                        weather_context=ctx.session.state.get("weather_context"),
                        dataset=ctx.session.state.get("dataset"),
                        contract_metadata=contract_metadata,
                        drill_levels=drill_levels,
                        scoped_digests=scoped_digests_map,
                    )
            env_format = os.environ.get("EXECUTIVE_BRIEF_OUTPUT_FORMAT")
            if env_format:
                output_format = env_format.lower()

            pdf_path: Path | None = None
            html_path: Path | None = None

            from .pdf_renderer import BriefPage

            network_label = f"Network — {period_end}"
            network_placeholder = _is_placeholder_markdown(brief_md, used_fallback)
            pages: list[BriefPage] = [
                BriefPage(
                    bookmark_label=network_label,
                    markdown_content=brief_md,
                    level=0,
                    is_placeholder=network_placeholder,
                )
            ]
            for info in scoped_briefs.values():
                scoped_placeholder = _is_placeholder_markdown(
                    info.get("content", ""),
                    info.get("used_fallback", False),
                )
                pages.append(
                    BriefPage(
                        bookmark_label=info.get("bookmark_label", "Scoped"),
                        markdown_content=info.get("content", ""),
                        level=info.get("level", 1),
                        parent_label=info.get("parent_label", ""),
                        is_placeholder=scoped_placeholder,
                    )
                )

            if output_format in ("pdf", "both"):
                try:
                    from .pdf_renderer import render_briefs_to_pdf

                    pdf_candidates = [p for p in pages if not p.is_placeholder]
                    placeholder_count = len(pages) - len(pdf_candidates)
                    if not pdf_candidates:
                        print("[BRIEF] Skipping PDF render: only placeholder/fallback brief content available.")
                    else:
                        if placeholder_count:
                            print(
                                f"[BRIEF] PDF render: skipped {placeholder_count} placeholder brief(s) to avoid empty content."
                            )
                        pdf_filename = "brief.pdf" if os.getenv("DATA_ANALYST_OUTPUT_DIR") else f"executive_brief_{period_end}.pdf"
                        pdf_path = render_briefs_to_pdf(pdf_candidates, outputs_dir / pdf_filename, period_end)
                except Exception as pdf_err:
                    print(f"[BRIEF] PDF rendering error (non-fatal): {pdf_err}")

            if output_format in ("html", "both"):
                try:
                    from .html_renderer import render_briefs_to_html

                    html_filename = "brief.html" if os.getenv("DATA_ANALYST_OUTPUT_DIR") else f"executive_brief_{period_end}.html"
                    html_path = render_briefs_to_html(pages, outputs_dir / html_filename, period_end)
                except Exception as html_err:
                    print(f"[BRIEF] HTML rendering error (non-fatal): {html_err}")

            state_delta: dict[str, Any] = {
                "executive_brief": brief_md,
                "executive_brief_path": str(brief_path),
                "executive_brief_json": str(brief_json_path),
                "executive_brief_used_fallback": used_fallback,
            }
            if scoped_briefs:
                state_delta["scoped_briefs"] = scoped_briefs
            if pdf_path:
                state_delta["executive_brief_pdf"] = str(pdf_path)
            if html_path:
                state_delta["executive_brief_html"] = str(html_path)

            yield Event(
                invocation_id=ctx.invocation_id,
                author=self.name,
                actions=EventActions(state_delta=state_delta),
            )

        except asyncio.TimeoutError:
            print("[BRIEF] TIMEOUT: LLM call exceeded 300s. Executive brief not generated.")
            yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=EventActions())
        except json.JSONDecodeError as exc:
            print(f"[BRIEF] JSON parse error: {exc}.")
            yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=EventActions())
        except Exception as exc:  # noqa: BLE001
            import traceback

            print(f"[BRIEF] ERROR: {exc}")
            traceback.print_exc()
            yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=EventActions())

        print("\n[BRIEF] CrossMetricExecutiveBriefAgent complete")
