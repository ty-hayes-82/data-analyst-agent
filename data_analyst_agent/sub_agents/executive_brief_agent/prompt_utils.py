"""Prompt assembly and output helpers for the executive brief agent."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


def _format_analysis_period(period_end: str, contract: Any) -> str:
    freq = "weekly"
    if contract and hasattr(contract, "time") and contract.time:
        time_cfg = contract.time
        freq = getattr(time_cfg, "frequency", None) or (
            time_cfg.get("frequency") if isinstance(time_cfg, dict) else None
        ) or "weekly"
    labels = {
        "daily": "the day",
        "weekly": "the week ending",
        "monthly": "the month ending",
        "quarterly": "the quarter ending",
        "yearly": "the year ending",
    }
    label = labels.get(str(freq).lower(), "the period ending")
    return f"{label} {period_end}" if period_end else "the current period"


def _build_weather_context_block(weather_context: Any) -> str:
    if not weather_context or not isinstance(weather_context, dict):
        return ""
    results = weather_context.get("results", [])
    explicable = [r for r in results if r.get("weather_explicable") and r.get("confidence") != "none"]
    if not explicable:
        return ""
    lines = ["WEATHER CONTEXT:"]
    for entry in explicable:
        markets = ", ".join(entry.get("markets", []))
        reason = entry.get("reason") or ""
        confidence = entry.get("confidence") or "unknown"
        lines.append(f"- {markets}: {reason} (confidence {confidence})")
    return "\n".join(lines)


def _write_executive_brief_cache(
    target_dir: Path | None = None,
    payload: dict[str, Any] | None = None,
    # Back-compat kwargs (older call sites passed named fields)
    outputs_dir: Path | None = None,
    **kwargs: Any,
) -> Path:
    """Write the executive brief input cache.

    Preferred call:
      _write_executive_brief_cache(target_dir=<Path>, payload={<dict>})

    Back-compat:
      _write_executive_brief_cache(outputs_dir=<Path>, digest=..., period_end=..., ...)
    """

    if target_dir is None:
        target_dir = outputs_dir
    if target_dir is None:
        raise ValueError("target_dir/outputs_dir is required")

    if payload is None:
        payload = dict(kwargs)

    target_dir.mkdir(parents=True, exist_ok=True)
    cache_path = target_dir / "executive_brief_input_cache.json"
    cache_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return cache_path


def _format_brief(brief: dict[str, Any]) -> str:
    header = brief.get("header") or {}
    body = brief.get("body") or {}
    sections = [
        f"# {header.get('title', 'Executive Brief')}",
        f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
        "",
    ]
    if header:
        summary = header.get("summary") or ""
        if summary:
            sections.append(summary)
            sections.append("")
    for block in body.get("sections", []):
        title = block.get("title") or "Untitled Section"
        sections.append(f"## {title}")
        if block.get("content"):
            sections.append(block["content"].strip())
        insights = block.get("insights") or []
        for insight in insights:
            sections.append(f"### {insight.get('title', 'Insight')}")
            if insight.get("details"):
                sections.append(insight["details"].strip())
        sections.append("")
    return "\n".join(sections).strip()


def _format_brief_with_fallback(brief_data: dict[str, Any], digest: str) -> str:
    """Format brief from LLM JSON, falling back to digest markdown if structure is wrong."""
    formatted = _format_brief(brief_data)
    # If _format_brief produced only a header (no sections), use the digest as fallback
    lines = [l for l in formatted.splitlines() if l.strip()]
    if len(lines) <= 3:
        from datetime import datetime
        return (
            "# Executive Brief\n"
            f"Generated: {datetime.utcnow().strftime(chr(37) + "Y-" + chr(37) + "m-" + chr(37) + "d " + chr(37) + "H:" + chr(37) + "M UTC")}\n\n"
            f"{digest}"
        )
    return formatted
