"""HTML rendering for executive briefs.

Converts brief markdown into a single combined HTML file with:
- All briefs in one scrollable page
- Navigation/Table of Contents for multiple briefs
- Clean, modern, CEO-ready styling (white background, clear typography)
"""

from __future__ import annotations

import re
import logging
from pathlib import Path
from typing import Sequence
from .pdf_renderer import BriefPage, _ordered_pages

log = logging.getLogger(__name__)

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Executive Performance Brief - {period_label}</title>
    <style>
        :root {{
            --primary-color: #1a1a1a;
            --secondary-color: #505050;
            --muted-color: #999;
            --border-color: #eee;
            --rule-color: #ccc;
            --bg-color: #fff;
            --font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
        }}
        body {{
            font-family: var(--font-family);
            line-height: 1.5;
            color: var(--primary-color);
            background-color: #f8f9fa;
            margin: 0;
            padding: 20px;
        }}
        .container {{
            max-width: 800px;
            margin: 0 auto;
            background-color: var(--bg-color);
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            padding: 40px;
            border-radius: 4px;
        }}
        .nav {{
            margin-bottom: 30px;
            padding-bottom: 20px;
            border-bottom: 1px solid var(--border-color);
        }}
        .nav h2 {{
            font-size: 14px;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: var(--secondary-color);
            margin-bottom: 10px;
        }}
        .nav ul {{
            list-style: none;
            padding: 0;
            margin: 0;
        }}
        .nav li {{
            margin-bottom: 5px;
            font-size: 14px;
        }}
        .nav a {{
            color: #0066cc;
            text-decoration: none;
        }}
        .nav a:hover {{
            text-decoration: underline;
        }}
        .brief-page {{
            margin-bottom: 60px;
            page-break-after: always;
        }}
        .brief-page:last-child {{
            margin-bottom: 0;
        }}
        .subject {{
            font-size: 20px;
            font-weight: bold;
            margin: 0 0 15px 0;
            line-height: 1.2;
        }}
        .summary-block {{
            background-color: #fcfcfc;
            border-left: 4px solid var(--primary-color);
            padding: 15px 20px;
            margin-bottom: 25px;
        }}
        .summary-label {{
            font-weight: bold;
            display: block;
            margin-bottom: 5px;
            text-transform: uppercase;
            font-size: 12px;
            letter-spacing: 0.5px;
        }}
        .sh {{
            font-size: 16px;
            font-weight: bold;
            margin: 25px 0 10px 0;
            border-bottom: 1px solid var(--rule-color);
            padding-bottom: 5px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        ul {{
            margin: 10px 0;
            padding-left: 20px;
        }}
        li {{
            margin-bottom: 8px;
        }}
        p {{
            margin: 10px 0;
        }}
        .footer {{
            font-size: 12px;
            color: var(--muted-color);
            margin-top: 30px;
            padding-top: 15px;
            border-top: 1px solid var(--border-color);
            font-style: italic;
        }}
        @media print {{
            body {{ background-color: white; padding: 0; }}
            .container {{ box-shadow: none; width: 100%; max-width: none; padding: 0; }}
            .nav {{ display: none; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        {nav_html}
        {content_html}
    </div>
</body>
</html>
"""

def _parse_markdown_to_html(md: str) -> str:
    """Simple markdown to HTML converter focused on brief structure."""
    try:
        import markdown2
        html = markdown2.markdown(md, extras=["fenced-code-blocks"])
    except ImportError:
        import html as _h
        html = _h.escape(md).replace("\n", "<br>")
        html = f"<p>{html}</p>"

    # Style Subject
    html = re.sub(r"<p><strong>Subject:\s*(.*?)</strong></p>",
                  r'<h1 class="subject">\1</h1>', html, count=1, flags=re.DOTALL)
    
    # Style Summary - catch Executive Summary followed by its content
    html = re.sub(r"<p><strong>Executive Summary</strong></p>\s*(<p>.*?</p>)",
                  r'<div class="summary-block"><span class="summary-label">Executive Summary</span>\1</div>', 
                  html, count=1, flags=re.DOTALL)
    # Fallback for old Summary format
    html = re.sub(r"<p><strong>Summary:</strong>\s*(.*?)</p>",
                  r'<div class="summary-block"><span class="summary-label">Executive Summary</span><p>\1</p></div>', 
                  html, count=1, flags=re.DOTALL)

    # Style Section Headings
    for name in ("Key Findings", "Recommended Actions", "Executive Summary",
                 "Scope Overview", "What's going well", "What's masking the picture",
                 "Primary concern", "Key Risk & Implications", "Bottom Line"):
        html = re.sub(
            rf"<p><strong>({re.escape(name)})</strong></p>",
            r'<h2 class="sh">\1</h2>', html, flags=re.IGNORECASE)

    # Style Footer
    html = re.sub(r"<p>---</p>\s*<p><em>(Generated.*?)</em></p>",
                  r'<div class="footer">\1</div>', html, flags=re.DOTALL)
    
    return html

def _check_markdown2() -> bool:
    try:
        import markdown2  # noqa: F401
        return True
    except ImportError:
        return False

def render_briefs_to_html(
    briefs: Sequence[BriefPage],
    output_path: Path,
    period_label: str = "",
) -> Path | None:
    """Render all briefs into a single combined HTML file."""
    if not briefs:
        log.warning("[HTML] No BriefPage objects supplied — HTML not written.")
        return None

    if not _check_markdown2():
        print("[HTML] WARNING: markdown2 not installed. HTML output will be unstyled text.")
        print("[HTML]          Install with: pip install markdown2")

    ordered = _ordered_pages(list(briefs))
    
    # Generate Navigation
    nav_links = []
    for i, page in enumerate(ordered):
        safe_id = f"brief-{i}"
        indent = "&nbsp;&nbsp;" * page.level
        nav_links.append(f'<li>{indent}<a href="#{safe_id}">{page.bookmark_label}</a></li>')
    
    nav_html = ""
    if len(ordered) > 1:
        nav_html = f'<div class="nav"><h2>Table of Contents</h2><ul>{"".join(nav_links)}</ul></div>'

    # Generate Content
    brief_divs = []
    for i, page in enumerate(ordered):
        safe_id = f"brief-{i}"
        body_html = _parse_markdown_to_html(page.markdown_content)
        brief_divs.append(f'<div id="{safe_id}" class="brief-page">{body_html}</div>')

    full_html = _HTML_TEMPLATE.format(
        period_label=period_label,
        nav_html=nav_html,
        content_html="\n".join(brief_divs)
    )

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(full_html, encoding="utf-8")
        print(f"[HTML] Saved HTML brief: {output_path.name}")
        return output_path
    except Exception as exc:
        log.warning("[HTML] Could not write file: %s", exc)
        print(f"[HTML] ERROR: Could not write HTML file: {exc}")
        return None
