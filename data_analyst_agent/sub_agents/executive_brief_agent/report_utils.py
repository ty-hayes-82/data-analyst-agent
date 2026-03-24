"""Helpers for collecting metric reports and building digest payloads."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict

from data_analyst_agent.sub_agents.report_synthesis_agent.tools.report_markdown.formatting import (
    is_currency_unit,
    normalize_unit,
)

def _metric_name_to_stem(name: str) -> str:
    """Convert metric name to filename stem (e.g. 'Loaded Miles' -> 'Loaded_Miles')."""
    return name.replace("/", "-").replace(" ", "_")


def _collect_metric_reports(outputs_dir: Path) -> dict[str, str]:
    """Read all metric reports and return {metric_name: markdown_content}."""
    reports: dict[str, str] = {}
    for md_file in sorted(outputs_dir.glob("metric_*.md")):
        name = md_file.stem.replace("metric_", "").replace("_", " ").replace("-", "/")
        content = md_file.read_text(encoding="utf-8", errors="replace")
        reports[name] = content
    if not reports:
        report_md = outputs_dir / "report.md"
        results_json = outputs_dir / "analysis_results.json"
        if report_md.exists() and results_json.exists():
            try:
                data = json.loads(results_json.read_text(encoding="utf-8", errors="replace"))
                name = data.get("dimension_value") or "unknown"
                content = report_md.read_text(encoding="utf-8", errors="replace")
                reports[name] = content
            except (json.JSONDecodeError, OSError):
                pass
    return reports


def _extract_executive_summary(markdown: str) -> str:
    """Pull just the Executive Summary section from a metric report."""
    lines = markdown.splitlines()
    in_section = False
    section_lines: list[str] = []
    for line in lines:
        if line.startswith("## Executive Summary"):
            in_section = True
            continue
        if in_section:
            if line.startswith("## ") and line != "## Executive Summary":
                break
            section_lines.append(line)
    return "\n".join(section_lines).strip()


def _extract_insight_cards(markdown: str, max_cards: int = 5) -> str:
    """Pull up to ``max_cards`` insight card blocks from a metric report."""
    lines = markdown.splitlines()
    in_section = False
    card_lines: list[str] = []
    card_count = 0
    for line in lines:
        if line.startswith("## Insight Cards"):
            in_section = True
            continue
        if in_section:
            if line.startswith("## ") and "Insight Cards" not in line:
                break
            if line.startswith("### "):
                card_count += 1
                if card_count > max_cards:
                    break
            card_lines.append(line)
    return "\n".join(card_lines).strip()


def _extract_scoped_cards_from_report(
    report_md: str,
    scope_entity_lower: str,
    children_lower: set[str],
    max_cards: int = 4,
) -> str:
    """Extract card blocks from rendered markdown that reference scoped entities."""
    in_section = False
    section_lines: list[str] = []
    for line in report_md.splitlines():
        if line.startswith("## Insight Cards"):
            in_section = True
            continue
        if in_section:
            if line.startswith("## ") and "Insight Cards" not in line:
                break
            section_lines.append(line)
    if not section_lines:
        return ""
    blocks: list[str] = []
    current: list[str] = []
    for line in section_lines:
        if line.startswith("### ") and current:
            blocks.append("\n".join(current).strip())
            current = [line]
        else:
            current.append(line)
    if current:
        blocks.append("\n".join(current).strip())
    matching: list[str] = []
    for block in blocks:
        block_lower = block.lower()
        if scope_entity_lower in block_lower or any(c in block_lower for c in children_lower):
            matching.append(block)
            if len(matching) >= max_cards:
                break
    return "\n\n".join(matching)


def _build_digest(reports: dict[str, str]) -> str:
    """Build a compact digest of metric reports for the LLM prompt."""
    parts: list[str] = []
    for metric_name, content in reports.items():
        summary = _extract_executive_summary(content)
        cards = _extract_insight_cards(content, max_cards=4)
        section = (
            f"=== {metric_name.upper()} ===\n"
            f"SUMMARY:\n{summary}\n\n"
            f"TOP INSIGHTS:\n{cards}\n"
        )
        parts.append(section)
    return "\n\n".join(parts)


def _compress_metadata_bullets(summary: str) -> str:
    """Collapse multi-line metadata bullets into a single pipe-delimited line."""
    variance = depth = grain = ""
    other_lines: list[str] = []
    for line in summary.splitlines():
        stripped = line.strip()
        if stripped.startswith("- **Total Variance:**"):
            variance = stripped.split(":**", 1)[1].strip()
        elif stripped.startswith("- **Analysis Depth:**"):
            depth = stripped.split(":**", 1)[1].strip()
        elif stripped.startswith("- **Detected Temporal Grain:**"):
            grain = stripped.split(":**", 1)[1].strip()
        else:
            other_lines.append(line)
    compressed_parts = []
    if variance:
        compressed_parts.append(f"Variance: {variance}")
    if depth:
        compressed_parts.append(f"Depth: {depth}")
    if grain:
        compressed_parts.append(f"Grain: {grain}")
    if compressed_parts:
        other_lines.append(" | ".join(compressed_parts))
    return "\n".join(other_lines).strip()


def _strip_card_noise(card_text: str) -> str:
    """Remove **Tags:** and **Evidence:** lines from a card block."""
    lines = []
    for line in card_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("**Tags:**") or stripped.startswith("**Evidence:**"):
            continue
        lines.append(line)
    return "\n".join(lines)


_SEVERITY_RE = re.compile(r"###\s*\[(CRITICAL|HIGH|MEDIUM|LOW)\]")


def _extract_slim_insight_cards(markdown: str, max_cards: int = 2) -> str:
    """Extract only CRITICAL/HIGH insight cards, stripped of noise, capped at max_cards."""
    lines = markdown.splitlines()
    in_section = False
    card_lines: list[str] = []
    cards: list[str] = []
    current_severity: str | None = None

    def _flush() -> None:
        nonlocal current_severity
        if card_lines and current_severity in ("CRITICAL", "HIGH"):
            cards.append(_strip_card_noise("\n".join(card_lines).strip()))
        card_lines.clear()
        current_severity = None

    for line in lines:
        if line.startswith("## Insight Cards"):
            in_section = True
            continue
        if in_section:
            if line.startswith("## ") and "Insight Cards" not in line:
                break
            if line.startswith("### "):
                _flush()
                m = _SEVERITY_RE.match(line)
                current_severity = m.group(1) if m else None
            card_lines.append(line)

    _flush()
    return "\n\n".join(cards[:max_cards])


def _build_slim_digest(
    reports: dict[str, str],
    max_cards: int = 2,
) -> str:
    """Build a compact digest for flash-lite models.

    Compared to _build_digest this:
    - Keeps only CRITICAL and HIGH insight cards (max ``max_cards`` per metric)
    - Strips **Tags:** and **Evidence:** lines from cards
    - Compresses the 3 metadata bullets into a single pipe-delimited line
    - Omits metrics that have zero qualifying cards AND no narrative summary text
    """
    parts: list[str] = []
    for metric_name, content in reports.items():
        summary = _extract_executive_summary(content)
        summary = _compress_metadata_bullets(summary)
        cards = _extract_slim_insight_cards(content, max_cards=max_cards)
        if not cards and not summary:
            continue
        section = (
            f"=== {metric_name.upper()} ===\n"
            f"SUMMARY:\n{summary}\n\n"
            f"TOP INSIGHTS:\n{cards}\n"
        ) if cards else (
            f"=== {metric_name.upper()} ===\n"
            f"SUMMARY:\n{summary}\n"
        )
        parts.append(section)
    return "\n\n".join(parts)


def _build_slim_digest_from_json(
    reports: dict[str, str],
    json_data: dict[str, dict[str, Any]],
    unit: str | None = None,
    max_cards: int = 2,
) -> str:
    """Slim digest variant augmented with cross-entity snapshot."""
    digest = _build_slim_digest(reports, max_cards=max_cards)
    cross_table = _build_cross_entity_table(json_data, unit)
    if cross_table:
        digest = f"{digest}\n\n=== CROSS-ENTITY SNAPSHOT ===\n{cross_table}"
    return digest


def _collect_metric_json_data(outputs_dir: Path) -> dict[str, dict[str, Any]]:
    """Load structured metric JSON payloads when they exist."""
    data: dict[str, dict[str, Any]] = {}
    for json_file in sorted(outputs_dir.glob("metric_*.json")):
        try:
            payload = json.loads(json_file.read_text(encoding="utf-8", errors="replace"))
        except json.JSONDecodeError:
            continue
        metric_name = (
            payload.get("metric")
            or payload.get("dimension_value")
            or payload.get("analysis_target")
            or payload.get("target_label")
        )
        if metric_name:
            data[str(metric_name)] = payload
    return data


def _coerce_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def format_variance_amount(value: Any, unit: str | None) -> str:
    """Return a human-friendly variance string that respects the contract unit."""

    amount = _coerce_float(value)
    if amount is None:
        return ""

    normalized_unit = normalize_unit(unit)
    sign = "+" if amount >= 0 else "-"
    abs_val = abs(amount)

    if is_currency_unit(normalized_unit):
        if abs_val >= 1_000_000_000:
            scaled = abs_val / 1_000_000_000
            suffix = "B"
        elif abs_val >= 1_000_000:
            scaled = abs_val / 1_000_000
            suffix = "M"
        elif abs_val >= 1_000:
            scaled = abs_val / 1_000
            suffix = "K"
        else:
            scaled = abs_val
            suffix = ""
        precision = 0 if scaled >= 100 or suffix == "" else 1
        return f"{sign}${scaled:,.{precision}f}{suffix}"

    formatted = f"{abs_val:,.0f}"
    suffix = ""
    unit_label = normalized_unit.strip()
    if unit_label and unit_label.lower() not in {"count", "units", "unit"}:
        suffix = f" {unit_label}"
    return f"{sign}{formatted}{suffix}".strip()


def _build_cross_entity_table(
    json_data: dict[str, dict[str, Any]],
    unit: str | None = None,
) -> str:
    """Render a cross-entity table when structured JSON is available."""
    rows: list[str] = []
    for metric, payload in json_data.items():
        leaders = payload.get("top_entities") or []
        if not leaders:
            continue
        parts = [f"{metric}:"]
        for entity in leaders[:5]:
            name = entity.get("name") or entity.get("entity") or "unknown"
            delta = format_variance_amount(entity.get("variance_dollar"), unit)
            pct_val = _coerce_float(entity.get("variance_pct"))
            pct = f"{pct_val:+.1f}%" if pct_val is not None else ""
            if delta and pct:
                formatted = f"{name} ({delta} / {pct})"
            elif delta:
                formatted = f"{name} ({delta})"
            elif pct:
                formatted = f"{name} ({pct})"
            else:
                formatted = name
            parts.append(formatted)
        rows.append(" - ".join(parts))
    return "\n".join(rows)


def build_minimal_metric_markdown_from_json(payload: dict[str, Any]) -> str:
    """Synthesize a tiny metric_*.md-shaped document when per-metric markdown was not written.

    Used when per-metric .md files are not written (default) so the executive brief can still assemble a digest
    (EXECUTIVE_BRIEF_USE_JSON=true) from analysis.summary plus optional card titles.
    """
    summary = (payload.get("analysis") or {}).get("summary") or "Analysis summary unavailable."
    lines: list[str] = [
        "## Executive Summary",
        "",
        str(summary).strip(),
        "",
        "## Insight Cards",
        "",
    ]
    hier = payload.get("hierarchical_analysis") or {}
    for level_key in ("level_0", "level_1", "level_2"):
        block = hier.get(level_key)
        if isinstance(block, str):
            try:
                block = json.loads(block)
            except json.JSONDecodeError:
                block = {}
        if not isinstance(block, dict):
            continue
        for card in (block.get("insight_cards") or [])[:4]:
            title = (card.get("title") or "").strip()
            what = (card.get("what_changed") or "").strip()
            if title:
                lines.append(f"### {title}")
                if what:
                    lines.append(what)
                lines.append("")
    narrative = payload.get("narrative_results") or {}
    if isinstance(narrative, str):
        try:
            narrative = json.loads(narrative)
        except json.JSONDecodeError:
            narrative = {}
    for card in (narrative.get("insight_cards") or [])[:3]:
        title = (card.get("title") or "").strip()
        what = (card.get("what_changed") or "").strip()
        if title:
            lines.append(f"### {title}")
            if what:
                lines.append(what)
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _build_digest_from_json(
    reports: dict[str, str],
    json_data: dict[str, dict[str, Any]],
    unit: str | None = None,
) -> str:
    """Return a markdown digest augmented with a cross-entity snapshot."""
    digest = _build_digest(reports)
    cross_table = _build_cross_entity_table(json_data, unit)
    if cross_table:
        digest = f"{digest}\n\n=== CROSS-ENTITY SNAPSHOT ===\n{cross_table}"
    return digest
