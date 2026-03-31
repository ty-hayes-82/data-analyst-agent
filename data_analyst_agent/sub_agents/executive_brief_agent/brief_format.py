"""Render CEO-format executive brief from structured JSON to markdown."""

from __future__ import annotations

from typing import Any


def render_flat_ceo_brief_markdown(
    brief: dict[str, Any],
    *,
    heading: str = "CEO Brief",
    analysis_period: str = "",
    outlook_heading: str = "Next-week outlook",
    persona: str = "ceo",
    kpi_rows: list[dict[str, Any]] | None = None,
) -> str:
    """Render CEO JSON from pass2_brief (flat schema: what_moved, trend_status, etc.)."""
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

    # Deterministic KPI table — computed in Python, never hallucinated
    if kpi_rows:
        lines.append("## Key Performance Indicators")
        lines.append("")
        lines.append("| Metric | Current | Prior | Change |")
        lines.append("|---|---|---|---|")
        for kpi in kpi_rows:
            name = kpi.get("display_name", kpi.get("name", ""))
            val = kpi.get("value")
            prior = kpi.get("prior_value")
            change = kpi.get("change_pct")
            fmt = kpi.get("format", "float")
            if val is None:
                continue
            if fmt == "currency":
                cur_str = f"${val:,.2f}" if val < 1000 else f"${val:,.0f}"
                pri_str = f"${prior:,.2f}" if prior and prior < 1000 else (f"${prior:,.0f}" if prior else "-")
            elif fmt == "percentage":
                cur_str = f"{val:.1f}%"
                pri_str = f"{prior:.1f}%" if prior is not None else "-"
            elif val < 100:
                cur_str = f"{val:,.1f}"
                pri_str = f"{prior:,.1f}" if prior is not None else "-"
            else:
                cur_str = f"{val:,.0f}"
                pri_str = f"{prior:,.0f}" if prior is not None else "-"
            chg_str = f"{change:+.1f}%" if change is not None else "-"
            lines.append(f"| {name} | {cur_str} | {pri_str} | {chg_str} |")
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


# ---------------------------------------------------------------------------
# HTML Email Renderer
# ---------------------------------------------------------------------------

def _html_escape(text: str) -> str:
    """Escape HTML special characters."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _change_class(change_pct: float | None) -> str:
    if change_pct is None:
        return "flat"
    if abs(change_pct) < 0.5:
        return "flat"
    return "neg" if change_pct < 0 else "pos"


def _format_kpi_html(val: float | None, fmt: str) -> str:
    if val is None:
        return "-"
    if fmt == "currency":
        return f"${val:,.2f}" if val < 1000 else f"${val:,.0f}"
    if fmt == "percentage":
        return f"{val:.1f}%"
    if val < 100:
        return f"{val:,.1f}"
    return f"{val:,.0f}"


def _colorize_pct(text: str) -> str:
    """Wrap percentage patterns like +1.8% or -2.3% in colored spans."""
    import re
    def _repl(m: re.Match) -> str:
        s = m.group(0)
        val = float(s.replace("%", "").replace(",", ""))
        cls = "flat" if abs(val) < 0.5 else ("neg" if val < 0 else "pos")
        return f'<span class="{cls}">{_html_escape(s)}</span>'
    return re.sub(r'[+-]?\d+[\d,]*\.?\d*%', _repl, text)


def _trend_tag(text: str) -> tuple[str, str]:
    """Detect trend category from text and return (tag_class, tag_label, remaining_text)."""
    lower = text.lower()
    for keyword, cls, label in [
        ("persistent", "tag-persist", "Persistent"),
        ("developing", "tag-develop", "Developing"),
        ("watchable", "tag-watch", "Watch"),
        ("watch", "tag-watch", "Watch"),
    ]:
        if keyword in lower:
            # Strip the keyword prefix if it starts the text
            cleaned = text
            for prefix in [f"{keyword} — ", f"{keyword}: ", f"{keyword}, ", f"{keyword} "]:
                if lower.startswith(prefix):
                    cleaned = text[len(prefix):]
                    break
            return cls, label, cleaned
    return "tag-watch", "", text


def _where_tag(title: str) -> tuple[str, str]:
    """Return (tag_class, tag_label) for where_it_came_from entries."""
    lower = title.lower()
    if "positive" in lower or "pos" in lower:
        return "tag-pos", "Positive"
    if "drag" in lower:
        return "tag-neg", "Drag"
    return "tag-watch", "Watch"


def render_flat_ceo_brief_html(
    brief: dict[str, Any],
    *,
    heading: str = "Weekly Performance Overview",
    analysis_period: str = "",
    outlook_heading: str = "Next-Week Outlook",
    kpi_rows: list[dict[str, Any]] | None = None,
    generated_date: str = "",
) -> str:
    """Render CEO brief as a styled HTML email.

    Uses the same flat schema as render_flat_ceo_brief_markdown (from pass2_brief).
    """
    import re
    from datetime import datetime

    data = {k: v for k, v in brief.items() if not str(k).startswith("_")}
    if not generated_date:
        generated_date = datetime.utcnow().strftime("%Y-%m-%d")

    # Parse period for display
    period_display = analysis_period or ""
    # Try to make it nicer: "the week ending 2026-03-14" -> "Week ending March 14, 2026"
    m = re.search(r'(\d{4})-(\d{2})-(\d{2})', period_display)
    if m:
        from datetime import date
        d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        period_display = f"Week ending {d.strftime('%B %d, %Y').replace(' 0', ' ')}"

    parts: list[str] = []

    # Bottom line
    bottom = _html_escape(data.get("bottom_line", ""))
    bottom_html = _colorize_pct(bottom) if bottom else ""

    # KPI table rows
    kpi_html = ""
    if kpi_rows:
        rows = []
        for kpi in kpi_rows:
            name = _html_escape(kpi.get("display_name", kpi.get("name", "")))
            val = kpi.get("value")
            prior = kpi.get("prior_value")
            change = kpi.get("change_pct")
            fmt = kpi.get("format", "float")
            if val is None:
                continue
            cls = _change_class(change)
            chg_str = f"{change:+.1f}%" if change is not None else "-"
            rows.append(
                f'      <tr><td>{name}</td>'
                f'<td>{_format_kpi_html(val, fmt)}</td>'
                f'<td>{_format_kpi_html(prior, fmt)}</td>'
                f'<td class="{cls}">{chg_str}</td></tr>'
            )
        kpi_html = "\n".join(rows)

    # What moved
    movers = data.get("what_moved") or []
    movers_html = ""
    if movers:
        items = []
        for m_item in movers:
            if isinstance(m_item, dict):
                label = _html_escape(m_item.get("label", ""))
                line = _colorize_pct(_html_escape(m_item.get("line", "")))
                items.append(f'    <li><strong>{label}:</strong> {line}</li>')
            else:
                items.append(f'    <li>{_colorize_pct(_html_escape(str(m_item)))}</li>')
        movers_html = "\n".join(items)

    # Trends
    trends = data.get("trend_status") or []
    trends_html = ""
    if trends:
        items = []
        for t in trends:
            t_str = str(t)
            tag_cls, tag_label, cleaned = _trend_tag(t_str)
            tag_span = f'<span class="tag {tag_cls}">{tag_label}</span> ' if tag_label else ""
            items.append(f'    <li>{tag_span}{_colorize_pct(_html_escape(cleaned))}</li>')
        trends_html = "\n".join(items)

    # Where it came from
    where = data.get("where_it_came_from") or {}
    where_html = ""
    if where and isinstance(where, dict):
        items = []
        for key in ["positive", "drag", "watch_item"]:
            val_str = where.get(key, "")
            if not val_str:
                continue
            tag_cls, tag_label = _where_tag(key)
            items.append(
                f'    <li><span class="tag {tag_cls}">{tag_label}</span> '
                f'{_colorize_pct(_html_escape(str(val_str)))}</li>'
            )
        where_html = "\n".join(items)

    # Why it matters + Outlook
    why = _colorize_pct(_html_escape(data.get("why_it_matters", "")))
    outlook = _colorize_pct(_html_escape(data.get("next_week_outlook", "")))

    # Leadership focus
    actions = data.get("leadership_focus") or []
    actions_html = ""
    if actions:
        items = []
        for a in actions:
            items.append(f'      <li>{_colorize_pct(_html_escape(str(a)))}</li>')
        actions_html = "\n".join(items)

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_html_escape(heading)} — {_html_escape(period_display)}</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: 'IBM Plex Sans', -apple-system, sans-serif;
    background: #f0eeea;
    color: #1a2740;
    line-height: 1.5;
    padding: 32px 16px;
  }}
  .email {{
    max-width: 720px;
    margin: 0 auto;
    background: #ffffff;
    border: 1px solid #ddd8d0;
    border-radius: 2px;
    padding: 44px 48px 48px;
  }}
  .title-block {{ margin-bottom: 24px; }}
  .title-block h1 {{
    font-family: 'DM Serif Display', serif;
    font-size: 28px;
    font-weight: 400;
    color: #0b1628;
    letter-spacing: -0.3px;
    margin-bottom: 2px;
  }}
  .title-block .date {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 12px;
    color: #8a96a8;
    text-transform: uppercase;
    letter-spacing: 1.2px;
  }}
  hr.divider {{
    border: none;
    border-top: 1px solid #e4e0da;
    margin: 20px 0;
  }}
  .bottom-line {{
    background: #fdf0ee;
    border-left: 3px solid #c0392b;
    padding: 14px 18px;
    margin-bottom: 24px;
    font-size: 13.5px;
    line-height: 1.6;
    color: #3a2828;
  }}
  .bottom-line .label {{
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: #c0392b;
    margin-bottom: 4px;
  }}
  .neg {{ color: #c0392b; }}
  .pos {{ color: #1a7a4c; }}
  .flat {{ color: #8a96a8; }}
  .section-title {{
    font-size: 10.5px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 1.8px;
    color: #8a96a8;
    margin-bottom: 10px;
    margin-top: 28px;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 12.5px;
    margin-bottom: 4px;
  }}
  thead th {{
    text-align: left;
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    color: #8a96a8;
    padding: 6px 0;
    border-bottom: 2px solid #0b1628;
  }}
  thead th:nth-child(n+2) {{ text-align: right; }}
  tbody td {{
    padding: 5px 0;
    border-bottom: 1px solid #f0eeea;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 12px;
  }}
  tbody td:first-child {{
    font-family: 'IBM Plex Sans', sans-serif;
    font-weight: 500;
    color: #2d3f5a;
    font-size: 12.5px;
  }}
  tbody td:nth-child(n+2) {{ text-align: right; }}
  tbody tr:last-child td {{ border-bottom: none; }}
  .insight-list {{
    list-style: none;
    margin: 0;
    padding: 0;
  }}
  .insight-list li {{
    font-size: 13px;
    line-height: 1.55;
    padding: 7px 0 7px 16px;
    position: relative;
    border-bottom: 1px solid #f0eeea;
  }}
  .insight-list li::before {{
    content: '';
    position: absolute;
    left: 0;
    top: 14px;
    width: 5px;
    height: 5px;
    border-radius: 50%;
    background: #c8d0dc;
  }}
  .insight-list li:last-child {{ border-bottom: none; }}
  .insight-list li strong {{ font-weight: 600; color: #0b1628; }}
  .tag {{
    display: inline-block;
    font-size: 9px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.6px;
    padding: 2px 6px;
    border-radius: 3px;
    margin-right: 3px;
    vertical-align: middle;
    position: relative;
    top: -1px;
  }}
  .tag-pos {{ background: #eef7f2; color: #1a7a4c; }}
  .tag-neg {{ background: #fdf0ee; color: #c0392b; }}
  .tag-watch {{ background: #fef9ee; color: #b8860b; }}
  .tag-persist {{ background: #f0eef8; color: #5b4bb5; }}
  .tag-develop {{ background: #eef3fd; color: #2563eb; }}
  .callout-pair {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
    margin-top: 24px;
  }}
  .callout {{
    border: 1px solid #e4e0da;
    padding: 14px 16px;
    font-size: 13px;
    line-height: 1.55;
    background: #fafaf8;
  }}
  .callout .label {{
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 1px;
    margin-bottom: 5px;
  }}
  .callout.risk {{ border-top: 3px solid #c0392b; }}
  .callout.risk .label {{ color: #c0392b; }}
  .callout.outlook {{ border-top: 3px solid #2563eb; }}
  .callout.outlook .label {{ color: #2563eb; }}
  .actions {{
    margin-top: 24px;
    background: #f6f5f2;
    border: 1px solid #e4e0da;
    padding: 16px 20px;
  }}
  .actions .label {{
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 1.2px;
    color: #0b1628;
    margin-bottom: 10px;
  }}
  .actions ol {{
    list-style: none;
    counter-reset: actions;
    margin: 0;
    padding: 0;
  }}
  .actions ol li {{
    counter-increment: actions;
    padding: 5px 0 5px 28px;
    position: relative;
    font-size: 13px;
    line-height: 1.5;
    border-bottom: 1px solid #e4e0da;
  }}
  .actions ol li:last-child {{ border-bottom: none; }}
  .actions ol li::before {{
    content: counter(actions);
    position: absolute;
    left: 0;
    top: 4px;
    font-family: 'DM Serif Display', serif;
    font-size: 18px;
    color: #2563eb;
    line-height: 1;
  }}
  .footer-note {{
    margin-top: 28px;
    padding-top: 16px;
    border-top: 1px solid #e4e0da;
    font-size: 11px;
    color: #8a96a8;
    text-align: center;
    font-family: 'IBM Plex Mono', monospace;
  }}
</style>
</head>
<body>
<div class="email">

  <div class="title-block">
    <h1>{_html_escape(heading)}</h1>
    <div class="date">{_html_escape(period_display)}</div>
  </div>

  <hr class="divider">

  <div class="bottom-line">
    <div class="label">Bottom Line</div>
    {bottom_html}
  </div>

  {"" if not kpi_html else f"""<div class="section-title">Key Performance Indicators</div>
  <table>
    <thead>
      <tr><th>Metric</th><th>Current</th><th>Prior</th><th>&Delta; WoW</th></tr>
    </thead>
    <tbody>
{kpi_html}
    </tbody>
  </table>

  <hr class="divider">"""}

  {"" if not movers_html else f"""<div class="section-title">What Moved the Business</div>
  <ul class="insight-list">
{movers_html}
  </ul>"""}

  {"" if not trends_html else f"""<div class="section-title">Trend Status</div>
  <ul class="insight-list">
{trends_html}
  </ul>"""}

  {"" if not where_html else f"""<div class="section-title">Where It Came From</div>
  <ul class="insight-list">
{where_html}
  </ul>"""}

  <div class="callout-pair">
    <div class="callout risk">
      <div class="label">Why It Matters</div>
      {why}
    </div>
    <div class="callout outlook">
      <div class="label">{_html_escape(outlook_heading)}</div>
      {outlook}
    </div>
  </div>

  {"" if not actions_html else f"""<div class="actions">
    <div class="label">Leadership Focus</div>
    <ol>
{actions_html}
    </ol>
  </div>"""}

  <div class="footer-note">
    Internal distribution only &middot; Generated {_html_escape(generated_date)}
  </div>

</div>
</body>
</html>'''

    return html
