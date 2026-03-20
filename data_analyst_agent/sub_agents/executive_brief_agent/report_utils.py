"""Helpers for collecting metric reports and building digest payloads."""

from __future__ import annotations

import json
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
