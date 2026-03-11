"""PDF rendering for executive briefs (Spec 033).

Converts brief markdown into a single combined PDF with:
- One page per brief (network first, then drill-down levels in order)
- Fixed A4 one-page layout per brief
- PDF bookmarks/outline for navigation

Primary renderer: fpdf2 (pure Python, no system libraries required).
Optional renderer: weasyprint (richer CSS support, requires GTK3 on Windows).

Falls back to no-op if neither library is available, so the pipeline never
blocks on a missing rendering dependency.
"""

from __future__ import annotations

import dataclasses
import logging
import re
from pathlib import Path
from typing import Sequence

log = logging.getLogger(__name__)


def _safe_print(msg: str) -> None:
    """Print to stdout, replacing non-ASCII chars to avoid Windows cp1252 errors."""
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("ascii", errors="replace").decode("ascii"))


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class BriefPage:
    """One executive brief to render as a single page in the combined PDF."""

    bookmark_label: str    # e.g. "Network — Week Ending Feb 14" or "East (Region)"
    markdown_content: str  # brief markdown text as written to the .md file
    level: int             # 0 = network brief, 1 = Level 1 entity, 2 = Level 2 entity
    parent_label: str = "" # parent entity bookmark label; empty for level 0 and 1
    is_placeholder: bool = False


# ---------------------------------------------------------------------------
# Availability checks
# ---------------------------------------------------------------------------

def _check_fpdf2() -> bool:
    try:
        import fpdf  # noqa: F401
        return True
    except ImportError:
        return False


def _check_weasyprint() -> bool:
    try:
        import weasyprint  # noqa: F401
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Markdown parser — extracts the brief's structured sections
# ---------------------------------------------------------------------------

def _parse_brief(md: str) -> dict:
    """Parse brief markdown into a dict of labelled sections."""
    result: dict = {"subject": "", "summary": "", "sections": [], "footer": ""}

    # Subject: **Subject: ...**
    m = re.search(r"\*\*Subject:\s*(.*?)\*\*", md, re.DOTALL)
    if m:
        result["subject"] = m.group(1).strip()

    # Executive Summary: catch both **Executive Summary** and old **Summary:** formats
    # Note: New format has **Executive Summary** then a newline then the content.
    # Old format had **Summary:** content.
    m = re.search(r"\*\*Executive Summary\*\*\s*\n(.*?)(?=\n\n|\*\*)", md, re.DOTALL)
    if not m:
        m = re.search(r"\*\*Summary:\*\*\s*(.*?)(?=\n\n|\*\*)", md, re.DOTALL)
    if m:
        result["summary"] = m.group(1).strip()

    # Extract known sections
    _section_names = [
        "Top Operational Insights",
        "Network Snapshot",
        "Focus for next week",
        "Scope Summary",
        "Structural Insights",
        "Leadership Question",
        "What's going well",
        "What's masking the picture",
        "Primary concern",
        "Key Risk & Implications",
        "Bottom line",
    ]
    for name in _section_names:
        pattern = rf"\*\*{re.escape(name)}\*\*\s*\n(.*?)(?=\n\*\*|\n---|\Z)"
        m = re.search(pattern, md, re.DOTALL | re.IGNORECASE)
        if m:
            raw = m.group(1).strip()
            bullets: list[str] = []
            body_lines: list[str] = []
            for line in raw.splitlines():
                stripped = line.strip()
                if stripped.startswith("- "):
                    bullets.append(stripped[2:].strip())
                elif stripped:
                    body_lines.append(stripped)
            result["sections"].append({
                "heading": name,
                "bullets": bullets,
                "body": " ".join(body_lines),
            })

    # Footer: *Generated ...*
    m = re.search(r"\*Generated(.*?)\*", md)
    if m:
        result["footer"] = f"Generated{m.group(1)}"

    return result


# ---------------------------------------------------------------------------
# fpdf2 renderer
# ---------------------------------------------------------------------------

# A4 dimensions in mm
_PAGE_W = 210.0
_PAGE_H = 297.0
_MARGIN_TOP = 15.0
_MARGIN_BOTTOM = 15.0
_MARGIN_LR = 18.0
_TEXT_W = _PAGE_W - 2 * _MARGIN_LR   # 174mm usable width

# Colours (R, G, B)
_C_BLACK = (26, 26, 26)
_C_DARK  = (50, 50, 50)
_C_GREY  = (120, 120, 120)
_C_RULE  = (200, 200, 200)


def _to_latin1(text: str) -> str:
    """Normalize text to Latin-1 for fpdf2's built-in Helvetica font.

    Replaces common typographic Unicode characters with ASCII equivalents,
    then encodes/decodes to replace any remaining non-Latin-1 chars with '?'.
    """
    _REPLACEMENTS = {
        "\u2013": "-",    # en dash
        "\u2014": "--",   # em dash
        "\u2015": "--",   # horizontal bar
        "\u2018": "'",    # left single quote
        "\u2019": "'",    # right single quote
        "\u201a": ",",    # single low-9 quote
        "\u201c": '"',    # left double quote
        "\u201d": '"',    # right double quote
        "\u2022": "-",    # bullet
        "\u2026": "...",  # ellipsis
        "\u00a0": " ",    # non-breaking space
        "\u2012": "-",    # figure dash
        "\u2010": "-",    # hyphen
        "\u2011": "-",    # non-breaking hyphen
    }
    for ch, replacement in _REPLACEMENTS.items():
        text = text.replace(ch, replacement)
    return text.encode("latin-1", errors="replace").decode("latin-1")


def _render_fpdf2(pages: list[BriefPage]) -> bytes:
    """Render pages to PDF bytes using fpdf2."""
    from fpdf import FPDF

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=False)
    pdf.set_margins(_MARGIN_LR, _MARGIN_TOP, _MARGIN_LR)

    # Use built-in helvetica (no external font files needed)
    for i, page in enumerate(pages):
        pdf.add_page()

        # PDF bookmark / outline entry
        outline_level = max(0, page.level)  # 0=top-level, 1=nested
        pdf.start_section(_to_latin1(page.bookmark_label), level=outline_level)

        parsed = _parse_brief(page.markdown_content)
        y = _MARGIN_TOP  # current y cursor

        def set_y(new_y: float) -> None:
            nonlocal y
            y = new_y
            pdf.set_y(y)

        # ---- Subject -------------------------------------------------------
        if parsed["subject"]:
            pdf.set_font("Helvetica", style="B", size=11)
            pdf.set_text_color(*_C_BLACK)
            pdf.set_xy(_MARGIN_LR, y)
            pdf.multi_cell(_TEXT_W, 5.5, _to_latin1(parsed["subject"]), align="L")
            y = pdf.get_y() + 3.0

        # ---- Summary -------------------------------------------------------
        if parsed["summary"]:
            pdf.set_font("Helvetica", size=9)
            pdf.set_text_color(*_C_DARK)
            pdf.set_xy(_MARGIN_LR, y)
            pdf.multi_cell(_TEXT_W, 4.5, _to_latin1(f"Summary: {parsed['summary']}"), align="L")
            y = pdf.get_y() + 3.5

        # ---- Sections ------------------------------------------------------
        for section in parsed["sections"]:
            if y > _PAGE_H - _MARGIN_BOTTOM - 12:
                break  # enforce one-page: stop if near bottom

            # Section heading with rule
            pdf.set_draw_color(*_C_RULE)
            pdf.set_line_width(0.2)
            pdf.line(_MARGIN_LR, y + 4.0, _PAGE_W - _MARGIN_LR, y + 4.0)

            pdf.set_font("Helvetica", style="B", size=9)
            pdf.set_text_color(*_C_BLACK)
            pdf.set_xy(_MARGIN_LR, y)
            pdf.cell(_TEXT_W, 5.0, _to_latin1(section["heading"]), align="L")
            y += 6.5

            # Bullets
            pdf.set_font("Helvetica", size=8.5)
            pdf.set_text_color(*_C_DARK)
            for bullet in section["bullets"]:
                if y > _PAGE_H - _MARGIN_BOTTOM - 6:
                    break
                pdf.set_xy(_MARGIN_LR + 2, y)
                pdf.multi_cell(_TEXT_W - 2, 4.2, _to_latin1(f"-  {bullet}"), align="L")
                y = pdf.get_y() + 0.5

            # Body paragraph (for non-bullet sections like Primary Concern)
            if section["body"] and not section["bullets"]:
                if y <= _PAGE_H - _MARGIN_BOTTOM - 8:
                    pdf.set_xy(_MARGIN_LR, y)
                    pdf.multi_cell(_TEXT_W, 4.2, _to_latin1(section["body"]), align="L")
                    y = pdf.get_y()

            y += 2.0

        # ---- Footer --------------------------------------------------------
        if parsed["footer"]:
            footer_y = _PAGE_H - _MARGIN_BOTTOM - 6
            pdf.set_draw_color(*_C_RULE)
            pdf.set_line_width(0.2)
            pdf.line(_MARGIN_LR, footer_y, _PAGE_W - _MARGIN_LR, footer_y)
            pdf.set_xy(_MARGIN_LR, footer_y + 1)
            pdf.set_font("Helvetica", style="I", size=7.5)
            pdf.set_text_color(*_C_GREY)
            pdf.cell(_TEXT_W, 4.0, _to_latin1(parsed["footer"]), align="L")

    return pdf.output()


# ---------------------------------------------------------------------------
# weasyprint renderer (optional, better CSS fidelity)
# ---------------------------------------------------------------------------

_CSS_WP = """
@page { size: A4; margin: 15mm 18mm; }
body { font-family: Helvetica, Arial, sans-serif; font-size: 9.5pt;
       line-height: 1.35; color: #1a1a1a; margin: 0; padding: 0; }
.brief-page { height: 267mm; overflow: hidden; page-break-before: always;
              box-sizing: border-box; }
.brief-page.first-page { page-break-before: avoid; }
.bm { display: block; height: 0; overflow: hidden; font-size: 0;
      bookmark-level: 1; bookmark-label: content(); }
.level-2 .bm { bookmark-level: 2; }
.subject { font-size: 10.5pt; font-weight: bold; margin: 0 0 5pt 0; }
.summary { font-size: 9pt; margin: 0 0 6pt 0; }
.sh { font-size: 9.5pt; font-weight: bold; margin: 7pt 0 2pt 0;
      border-bottom: 0.4pt solid #ccc; padding-bottom: 1pt; }
ul { margin: 1pt 0 3pt 0; padding-left: 13pt; }
li { margin-bottom: 1.5pt; }
p { margin: 0 0 3pt 0; }
.footer { font-size: 7.5pt; color: #999; margin-top: 5pt;
          border-top: 0.4pt solid #eee; padding-top: 2pt; }
"""

def _render_weasyprint(pages: list[BriefPage]) -> bytes:
    """Render pages to PDF bytes using weasyprint (CSS GCPM bookmarks)."""
    import weasyprint
    try:
        import markdown2
        _md = lambda t: markdown2.markdown(t, extras=["fenced-code-blocks"])
    except ImportError:
        import html as _h
        _md = lambda t: "<p>" + _h.escape(t).replace("\n", "<br>") + "</p>"

    divs: list[str] = []
    for i, page in enumerate(pages):
        fc = " first-page" if i == 0 else ""
        lc = f"level-{page.level}"
        lbl = page.bookmark_label.replace("<", "&lt;").replace(">", "&gt;")
        body = _md(page.markdown_content)
        # Promote bold headings to section-heading class
        for name in ("What's going well", "What's masking the picture",
                     "Primary concern", "Bottom line"):
            body = re.sub(
                rf"<p><strong>({re.escape(name)})</strong></p>",
                r'<p class="sh">\1</p>', body, flags=re.IGNORECASE)
        body = re.sub(r"<p><strong>Subject:\s*(.*?)</strong></p>",
                      r'<p class="subject">\1</p>', body, count=1, flags=re.DOTALL)
        body = re.sub(r"<p><strong>Summary:</strong>\s*(.*?)</p>",
                      r'<p class="summary"><strong>Summary:</strong> \1</p>',
                      body, count=1, flags=re.DOTALL)
        body = re.sub(r"<p><em>(Generated.*?)</em></p>",
                      r'<p class="footer"><em>\1</em></p>', body)
        divs.append(
            f'<div class="brief-page {lc}{fc}">'
            f'<span class="bm">{lbl}</span>{body}</div>'
        )

    html = (
        f"<!DOCTYPE html><html><head><meta charset='UTF-8'>"
        f"<style>{_CSS_WP}</style></head><body>"
        + "\n".join(divs) + "</body></html>"
    )
    return weasyprint.HTML(string=html).write_pdf()


# ---------------------------------------------------------------------------
# Page ordering
# ---------------------------------------------------------------------------

def _ordered_pages(pages: Sequence[BriefPage]) -> list[BriefPage]:
    """Level 0 first, then Level 1 sorted, then Level 2 nested under parents."""
    l0 = [p for p in pages if p.level == 0]
    l1 = sorted((p for p in pages if p.level == 1), key=lambda p: p.bookmark_label)
    l2 = sorted((p for p in pages if p.level == 2),
                key=lambda p: (p.parent_label, p.bookmark_label))

    result: list[BriefPage] = list(l0)
    matched: set[int] = set()
    for p1 in l1:
        result.append(p1)
        children = [c for c in l2 if c.parent_label == p1.bookmark_label]
        result.extend(children)
        matched.update(id(c) for c in children)
    result.extend(p for p in l2 if id(p) not in matched)
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def render_briefs_to_pdf(
    briefs: Sequence[BriefPage],
    output_path: Path,
    period_label: str = "",
) -> Path | None:
    """Render all briefs into a single combined PDF.

    Tries fpdf2 first (pure Python, always available after pip install fpdf2).
    Falls back to weasyprint if fpdf2 is not installed (requires GTK3 on Windows).
    Returns None with a warning log if neither library is available.

    Page order: network (level 0) → Level 1 entities (sorted alphabetically) →
    Level 2 entities nested under their Level 1 parents.

    Each page is a fixed A4 one-pager. Content that would overflow is clipped.
    PDF outline/bookmarks are added for each brief.
    """
    if not briefs:
        log.warning("[PDF] No BriefPage objects supplied — PDF not written.")
        return None

    ordered = _ordered_pages(list(briefs))

    pdf_bytes: bytes | None = None
    used_lib: str = ""

    if _check_fpdf2():
        try:
            pdf_bytes = _render_fpdf2(ordered)
            used_lib = "fpdf2"
        except Exception as exc:
            log.warning("[PDF] fpdf2 render failed: %s", exc, exc_info=True)
            _safe_print(f"[PDF] fpdf2 failed: {exc}")

    if pdf_bytes is None and _check_weasyprint():
        try:
            pdf_bytes = _render_weasyprint(ordered)
            used_lib = "weasyprint"
        except Exception as exc:
            log.warning("[PDF] weasyprint render failed: %s", exc, exc_info=True)
            _safe_print(f"[PDF] weasyprint failed: {exc}")

    if pdf_bytes is None:
        log.warning(
            "[PDF] No PDF renderer available. Install fpdf2: pip install fpdf2"
        )
        print("[PDF] WARNING: No PDF renderer available - PDF output skipped.")
        print("[PDF]          Install with: pip install fpdf2")
        return None

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(pdf_bytes)
        size_bytes = len(pdf_bytes)
        page_count = len(ordered)
        if size_bytes >= 1024:
            size_label = f"{size_bytes / 1024:.1f} KB"
        else:
            size_label = f"{size_bytes} bytes"
        _safe_print(
            f"[PDF] Saved {page_count}-page PDF ({used_lib}): "
            f"{output_path} ({size_label})"
        )
        log.info(
            "[PDF] Written %s via %s (%d pages, %d bytes)",
            output_path.name, used_lib, page_count, size_bytes,
        )
        return output_path
    except Exception as exc:
        log.warning("[PDF] Could not write file: %s", exc)
        print(f"[PDF] WARNING: Could not write PDF file - {type(exc).__name__}: {str(exc).encode('ascii', errors='replace').decode('ascii')}")
        return None
