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
    lines.append(f"# Weekly Performance Overview")
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
