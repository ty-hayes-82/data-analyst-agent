"""Render CEO-format executive brief from structured JSON to markdown."""

from __future__ import annotations

from typing import Any


def render_ceo_brief_markdown(brief: dict[str, Any]) -> str:
    """Render a CEO-format brief dict to markdown.

    Args:
        brief: Structured brief dict with keys: week_ending, bottom_line,
               what_moved_the_business, trend_status, where_it_came_from,
               why_it_matters, next_week_outlook, leadership_focus.

    Returns:
        Formatted markdown string.
    """
    lines: list[str] = []

    week = brief.get("week_ending", "")
    grain = brief.get("temporal_grain", "weekly")
    grain_label = {"monthly": "Monthly", "weekly": "Weekly", "yearly": "Annual"}.get(grain, "Weekly")
    lines.append(f"# {grain_label} Performance Overview")
    if week:
        lines.append(f"## Week Ending {week}")
    lines.append("")

    # Bottom Line
    bottom = brief.get("bottom_line", "")
    if bottom:
        lines.append(f"**Bottom line:** {bottom}")
        lines.append("")

    # What Moved the Business
    movers = brief.get("what_moved_the_business", [])
    if movers:
        lines.append("## What moved the business")
        lines.append("")
        for m in movers:
            metric = m.get("metric", "")
            value = m.get("value", "")
            change = m.get("change", "")
            context = m.get("context", "")
            parts = [p for p in [metric, value, change] if p]
            line = ": ".join(parts[:2]) if len(parts) >= 2 else ", ".join(parts)
            if change and len(parts) >= 3:
                line = f"{parts[0]}: {parts[1]}, {parts[2]}"
            if context:
                line += f", {context}"
            lines.append(f"- **{line}**")
        lines.append("")

    # Trend Status
    trends = brief.get("trend_status", [])
    if trends:
        lines.append("## Trend status")
        lines.append("")
        for t in trends:
            trend = t.get("trend", "")
            status = t.get("status", "")
            detail = t.get("detail", "")
            status_label = f"**{status}**" if status else ""
            parts = [p for p in [trend, status_label, detail] if p]
            lines.append(f"- {' — '.join(parts)}")
        lines.append("")

    # Where It Came From
    where = brief.get("where_it_came_from", {})
    if where:
        lines.append("## Where it came from")
        lines.append("")
        for label, items in [
            ("Positive", where.get("positive", [])),
            ("Drag", where.get("drag", [])),
            ("Watch item", where.get("watch_items", [])),
        ]:
            for item in items:
                lines.append(f"- **{label}:** {item}")
        lines.append("")

    # Why It Matters
    why = brief.get("why_it_matters", "")
    if why:
        lines.append(f"**Why it matters:** {why}")
        lines.append("")

    # Next-Week Outlook
    outlook = brief.get("next_week_outlook", "")
    if outlook:
        lines.append(f"**Next-week outlook:** {outlook}")
        lines.append("")

    # Leadership Focus
    actions = brief.get("leadership_focus", [])
    if actions:
        lines.append("## Leadership focus")
        lines.append("")
        for action in actions:
            lines.append(f"- {action}")
        lines.append("")

    return "\n".join(lines)


def render_flat_ceo_brief_markdown(
    brief: dict[str, Any],
    *,
    heading: str = "CEO Brief",
    analysis_period: str = "",
    outlook_heading: str = "Next-week outlook",
    persona: str = "ceo",
) -> str:
    """Render CEO JSON from hybrid pass2_brief (flat schema: what_moved, trend_status, etc.)."""
    _aud = (persona or "ceo").lower() == "billing_auditor"
    _bl = "Audit summary:" if _aud else "Bottom line:"
    _moved = "Accounts and lanes to review" if _aud else "What moved the business"
    _trend = "Patterns suggesting billing drift" if _aud else "Trend status"
    _where = "Customer / lane drivers" if _aud else "Where it came from"
    _why = "Billing risk:" if _aud else "Why it matters:"
    _lead = "Review queue (billing)" if _aud else "Leadership focus"
    _pos = "Favorable reconciliation" if _aud else "Positive"
    _drag = "Mismatch / risk" if _aud else "Drag"
    _watch = "Sample next" if _aud else "Watch item"

    lines: list[str] = []
    lines.append(f"# {heading}")
    if analysis_period:
        lines.append(f"*{analysis_period}*")
    lines.append("")

    data = {k: v for k, v in brief.items() if not str(k).startswith("_")}

    bottom = data.get("bottom_line", "")
    if bottom:
        lines.append(f"**{_bl}** {bottom}")
        lines.append("")

    movers = data.get("what_moved") or []
    if movers:
        lines.append(f"## {_moved}")
        lines.append("")
        for m in movers:
            if isinstance(m, dict):
                label = m.get("label", "")
                line = m.get("line", "")
                lines.append(f"- **{label}:** {line}")
            else:
                lines.append(f"- {m}")
        lines.append("")

    trends = data.get("trend_status") or []
    if trends:
        lines.append(f"## {_trend}")
        lines.append("")
        for t in trends:
            lines.append(f"- {t}")
        lines.append("")

    where = data.get("where_it_came_from") or {}
    if where and isinstance(where, dict):
        lines.append(f"## {_where}")
        lines.append("")
        pos = where.get("positive", "")
        drag = where.get("drag", "")
        watch = where.get("watch_item", "")
        if pos:
            lines.append(f"- **{_pos}:** {pos}")
        if drag:
            lines.append(f"- **{_drag}:** {drag}")
        if watch:
            lines.append(f"- **{_watch}:** {watch}")
        lines.append("")

    why = data.get("why_it_matters", "")
    if why:
        lines.append(f"**{_why}** {why}")
        lines.append("")

    outlook = data.get("next_week_outlook", "")
    if outlook:
        lines.append(f"**{outlook_heading}:** {outlook}")
        lines.append("")

    actions = data.get("leadership_focus") or []
    if actions:
        lines.append(f"## {_lead}")
        lines.append("")
        for a in actions:
            lines.append(f"- {a}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
