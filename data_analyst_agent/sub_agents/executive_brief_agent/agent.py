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

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncGenerator

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google import genai
from google.genai import types

from config.model_loader import get_agent_model, get_agent_thinking_config
from .prompt import EXECUTIVE_BRIEF_INSTRUCTION, SCOPED_BRIEF_PREAMBLE, load_dataset_specific_append, load_prompt_variant
from ...utils import parse_bool_env


def _format_analysis_period(period_end: str, contract: Any) -> str:
    """Format period_end into dataset-appropriate analysis_period label."""
    freq = "weekly"
    if contract and hasattr(contract, "time") and contract.time:
        t = contract.time
        freq = getattr(t, "frequency", None) or (t.get("frequency") if isinstance(t, dict) else None) or "weekly"
    labels = {
        "daily": "the day",
        "weekly": "the week ending",
        "monthly": "the month ending",
        "quarterly": "the quarter ending",
        "yearly": "the year ending",
    }
    label = labels.get(str(freq).lower(), "the period ending")
    return f"{label} {period_end}" if period_end else "the current period"


def _metric_name_to_stem(name: str) -> str:
    """Convert metric name to filename stem (e.g. 'Loaded Miles' -> 'Loaded_Miles')."""
    return name.replace("/", "-").replace(" ", "_")


def _collect_metric_reports(outputs_dir: Path) -> dict[str, str]:
    """Read all metric reports and return {metric_name: markdown_content}.
    
    Supports both legacy (metric_*.md) and standardized (report.md) patterns.
    """
    reports = {}
    
    # 1. Try legacy pattern: metric_*.md
    for md_file in sorted(outputs_dir.glob("metric_*.md")):
        # Derive a readable metric name from the filename
        name = md_file.stem.replace("metric_", "").replace("_", " ").replace("-", "/")
        content = md_file.read_text(encoding="utf-8", errors="replace")
        reports[name] = content
        
    # 2. If no legacy reports found, try standardized run-dir pattern: report.md
    # Requires analysis_results.json to identify the metric name.
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
    section_lines = []
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
    """Pull up to max_cards insight card blocks from a metric report."""
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
    """Extract insight card blocks from a rendered markdown report that mention
    the scope entity or any of its child entities.

    Used as a fallback in _build_scoped_digest when the structured JSON
    narrative_results.insight_cards is empty for a metric — which happens when
    the pipeline omits that field but still writes the full rendered report.
    """
    # Collect lines that are inside the ## Insight Cards section
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

    # Split into individual ### card blocks
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

    # Keep blocks that mention the scope entity or any child terminal
    matching: list[str] = []
    for block in blocks:
        block_lower = block.lower()
        if scope_entity_lower in block_lower or any(c in block_lower for c in children_lower):
            matching.append(block)
            if len(matching) >= max_cards:
                break

    return "\n\n".join(matching)


def _build_digest(reports: dict[str, str]) -> str:
    """Build a compact digest of all metric reports for the LLM prompt."""
    parts = []
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


def _build_weather_context_block(weather_context: Any) -> str:
    """Build WEATHER CONTEXT block from weather_context (from WeatherContextAgent)."""
    if not weather_context or not isinstance(weather_context, dict):
        return ""
    results = weather_context.get("results", [])
    explicable = [r for r in results if r.get("weather_explicable") and r.get("confidence") != "none"]
    if not explicable:
        return ""
    lines = ["WEATHER CONTEXT (from web search, grounded in Google Search):"]
    for r in explicable:
        conf = (r.get("confidence") or "low").upper()
        entity = r.get("entity", "?")
        date_range = r.get("date_range", "")
        summary = r.get("weather_summary") or "Weather may explain anomaly."
        lines.append(f"- [{conf} confidence] {entity} ({date_range}): {summary}")
    return "\n".join(lines) + "\n\n"


def _collect_metric_json_data(outputs_dir: Path) -> dict[str, dict[str, Any]]:
    """Read metric JSON data and return {metric_name: parsed_data}.
    
    Supports both legacy (metric_*.json) and standardized (analysis_results.json) patterns.
    """
    result = {}
    
    # 1. Try legacy pattern: metric_*.json
    for json_file in sorted(outputs_dir.glob("metric_*.json")):
        stem = json_file.stem.replace("metric_", "")
        name = stem.replace("_", " ").replace("-", "/")
        try:
            data = json.loads(json_file.read_text(encoding="utf-8", errors="replace"))
            result[name] = data
        except (json.JSONDecodeError, OSError):
            pass
            
    # 2. If no legacy data found, try standardized run-dir pattern: analysis_results.json
    if not result:
        results_json = outputs_dir / "analysis_results.json"
        if results_json.exists():
            try:
                data = json.loads(results_json.read_text(encoding="utf-8", errors="replace"))
                name = data.get("dimension_value") or "unknown"
                result[name] = data
            except (json.JSONDecodeError, OSError):
                pass
                
    return result


def _build_cross_entity_table(json_data: dict[str, dict[str, Any]]) -> str:
    """Build cross-entity signal table: entities appearing in 2+ metrics with notable signals.
    
    Suppresses signals from the lag window if LAG_METRIC_SUPPRESSION is true.
    """
    suppress_lag = os.environ.get("LAG_METRIC_SUPPRESSION", "true").lower() == "true"
    
    # Collect (entity, metric, signal) from anomalies, top_drivers, hierarchy
    entity_signals: dict[str, dict[str, str]] = {}
    metrics_list = sorted(json_data.keys())

    for metric_name, data in json_data.items():
        # Resolve lag window for this metric
        lag_meta = data.get("lag_metadata") or (data.get("statistical_summary") or {}).get("lag_metadata")
        lag_window = set(lag_meta.get("lag_window", [])) if (lag_meta and suppress_lag) else set()
        
        stats = data.get("statistical_summary") or {}
        if isinstance(stats, dict):
            for a in stats.get("anomalies", [])[:5]:
                period = str(a.get("period", ""))
                if period in lag_window:
                    continue # Suppress signal from incomplete period
                    
                item = a.get("item") or a.get("item_name") or ""
                if item:
                    entity_signals.setdefault(item, {})
                    val = a.get("value", "")
                    direction = "+" if (val and a.get("z_score", 0) > 0) else "-"
                    entity_signals[item][metric_name] = f"{direction} anomaly ({period})"
            for d in stats.get("top_drivers", [])[:3]:
                item = d.get("item") or d.get("item_name") or ""
                if item and entity_signals.get(item, {}).get(metric_name) is None:
                    # Top drivers are already computed for the effective latest period
                    # so no need to check lag_window here.
                    share = d.get("share_of_total")
                    entity_signals.setdefault(item, {})
                    try:
                        entity_signals[item][metric_name] = f"top driver ({share:.1%})" if share is not None else "top driver"
                    except (TypeError, ValueError):
                        entity_signals[item][metric_name] = "top driver"

        # Hierarchy level_1 insight cards (region-level)
        hier = data.get("hierarchical_analysis") or {}
        for level_key in ("level_1", "level_2"):
            lvl = hier.get(level_key)
            if isinstance(lvl, str):
                try:
                    lvl = json.loads(lvl)
                except json.JSONDecodeError:
                    lvl = {}
            if isinstance(lvl, dict):
                # Check lag window for hierarchy cards
                lvl_lag_meta = lvl.get("lag_metadata")
                lvl_lag_window = set(lvl_lag_meta.get("lag_window", [])) if (lvl_lag_meta and suppress_lag) else set()
                
                for card in lvl.get("insight_cards", [])[:2]:
                    # Hierarchy tools already use the effective latest period, 
                    # but if we ever support multi-period cards we'd check here.
                    title = card.get("title", "")
                    if "Driver:" in title or "Shift:" in title:
                        entity = _extract_entity_from_card_title(title)
                        if entity and entity not in ("Total", ""):
                            entity_signals.setdefault(entity, {})
                            if entity_signals[entity].get(metric_name) is None:
                                entity_signals[entity][metric_name] = "variance driver"

        # Independent level scan cards (spec 035) — net-new entities masked at higher levels
        ind_results = hier.get("independent_level_results") or {}
        if isinstance(ind_results, str):
            try:
                ind_results = json.loads(ind_results)
            except json.JSONDecodeError:
                ind_results = {}
        for _ind_key, ind_lvl in ind_results.items():
            if isinstance(ind_lvl, str):
                try:
                    ind_lvl = json.loads(ind_lvl)
                except json.JSONDecodeError:
                    ind_lvl = {}
            if isinstance(ind_lvl, dict):
                for card in ind_lvl.get("insight_cards", [])[:2]:
                    title = card.get("title", "")
                    if "Driver:" in title or "Shift:" in title:
                        entity = _extract_entity_from_card_title(title)
                        if entity and entity not in ("Total", ""):
                            entity_signals.setdefault(entity, {})
                            if entity_signals[entity].get(metric_name) is None:
                                entity_signals[entity][metric_name] = "variance driver (flat scan)"

    # Incorporate cross-dimension findings into entity signals
    for metric_name, data in json_data.items():
        # Cross-dimension analysis is already performed on the effective latest period.
        cross_dim = data.get("cross_dimension_analysis") or {}
        if isinstance(cross_dim, dict):
            for _cd_key, cd_result_raw in cross_dim.items():
                cd_result = cd_result_raw
                if isinstance(cd_result_raw, str):
                    try:
                        cd_result = json.loads(cd_result_raw)
                    except (json.JSONDecodeError, ValueError):
                        continue
                if not isinstance(cd_result, dict) or cd_result.get("skipped"):
                    continue
                for pattern in (cd_result.get("cross_cutting_patterns") or [])[:3]:
                    for ent in (pattern.get("affected_entities") or [])[:5]:
                        entity_signals.setdefault(ent, {})
                        if entity_signals[ent].get(metric_name) is None:
                            aux_val = pattern.get("auxiliary_value", "")
                            direction = pattern.get("effect_direction", "")
                            tag = "drag" if direction == "negative" else "boost"
                            entity_signals[ent][metric_name] = f"{aux_val} {tag}"

    # Keep only entities in 2+ metrics
    multi_metric = {e: sigs for e, sigs in entity_signals.items() if len(sigs) >= 2}
    if not multi_metric:
        return ""

    lines = ["CROSS-ENTITY SIGNALS (entities in 2+ metrics):", "| Entity | " + " | ".join(metrics_list[:6]) + " |"]
    lines.append("|" + "---|" * (len(metrics_list[:6]) + 1))
    for entity, sigs in sorted(multi_metric.items(), key=lambda x: -len(x[1]))[:12]:
        row = [entity]
        for m in metrics_list[:6]:
            row.append(sigs.get(m, "—"))
        lines.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(lines)


def _build_digest_from_json(
    json_data: dict[str, dict[str, Any]],
    reports_md: dict[str, str],
    max_cards: int = 6,
) -> str:
    """Build digest from JSON when available, with cross-entity table and temporal anchors."""
    try:
        max_cards = max(4, min(int(os.environ.get("EXECUTIVE_BRIEF_MAX_CARDS_PER_METRIC", "6")), 10))
    except (ValueError, TypeError):
        max_cards = 6

    suppress_lag = os.environ.get("LAG_METRIC_SUPPRESSION", "true").lower() == "true"
    parts = []
    lag_notes = []

    # Cross-entity table
    cross_table = _build_cross_entity_table(json_data)
    if cross_table:
        parts.append(cross_table)
        parts.append("")

    # Temporal anchors from summary_stats
    temporal_parts = []
    for metric_name, data in json_data.items():
        stats = data.get("statistical_summary") or {}
        if isinstance(stats, dict):
            ss = stats.get("summary_stats", {})
            hi = ss.get("highest_total_month") or {}
            lo = ss.get("lowest_total_month") or {}
            if hi or lo:
                # Use generic 'period' to avoid biasing LLM toward 'month' when it's weekly
                temporal_parts.append(f"{metric_name}: peak {hi.get('period','N/A')}, low {lo.get('period','N/A')}")
            
            # Collect lag notes
            lag_meta = stats.get("lag_metadata") or data.get("lag_metadata")
            if lag_meta and lag_meta.get("lag_periods", 0) > 0:
                lag_p = lag_meta["lag_periods"]
                eff_latest = lag_meta.get("effective_latest") or lag_meta.get("effective_latest_period")
                lag_window = lag_meta.get("lag_window", [])
                if lag_window:
                    lag_notes.append(
                        f"Note: {metric_name} data lags by ~{lag_p} periods. "
                        f"Analysis uses data through {eff_latest}. "
                        f"Periods {lag_window[0]}..{lag_window[-1]} excluded (incomplete)."
                    )

    if temporal_parts:
        parts.append("HISTORICAL ANCHORS (Reference Only - Do Not Use for Current Period Subject):")
        parts.extend(f"- {t}" for t in temporal_parts)
        parts.append("")

    # Key anomalies this period
    anomaly_parts = []
    for metric_name, data in json_data.items():
        # Resolve lag window for this metric
        lag_meta = data.get("lag_metadata") or (data.get("statistical_summary") or {}).get("lag_metadata")
        lag_window = set(lag_meta.get("lag_window", [])) if (lag_meta and suppress_lag) else set()
        
        stats = data.get("statistical_summary") or {}
        if isinstance(stats, dict):
            for a in stats.get("anomalies", [])[:3]:
                period = str(a.get("period", ""))
                if period in lag_window:
                    continue # Suppress
                    
                item = a.get("item") or a.get("item_name") or "?"
                direction = "up" if (a.get("z_score", 0) or 0) > 0 else "down"
                anomaly_parts.append(f"- {metric_name}: {item} ({period}) {direction}")
    if anomaly_parts:
        parts.append("KEY ANOMALIES THIS PERIOD:")
        parts.extend(anomaly_parts[:15])
        parts.append("")

    # Per-metric sections from JSON (narrative + insights)
    for metric_name in sorted(json_data.keys()):
        data = json_data.get(metric_name, {})
        
        # Resolve lag window for this metric
        lag_meta = data.get("lag_metadata") or (data.get("statistical_summary") or {}).get("lag_metadata")
        lag_window = set(lag_meta.get("lag_window", [])) if (lag_meta and suppress_lag) else set()
        
        narrative = data.get("narrative_results") or {}
        if isinstance(narrative, str):
            try:
                narrative = json.loads(narrative)
            except json.JSONDecodeError:
                narrative = {}
        summary = narrative.get("narrative_summary", "")
        
        # Filter cards by lag window
        raw_cards = narrative.get("insight_cards", [])
        cards = []
        for c in raw_cards:
            if isinstance(c, dict):
                # Most cards are for the effective latest period, but if they have 
                # a 'period' key, we check it.
                c_period = str(c.get("period", ""))
                if c_period and c_period in lag_window:
                    continue
                cards.append(c)
        
        cards = cards[:max_cards]
        cards_text = []
        for c in cards:
            if isinstance(c, dict):
                title = c.get("title", "")
                what = c.get("what_changed", "")
                cards_text.append(f"### {title}\n{what}")
        cards_str = "\n".join(cards_text) if cards_text else ""

        if not summary and metric_name in reports_md:
            summary = _extract_executive_summary(reports_md[metric_name])
        if not cards_str and metric_name in reports_md:
            cards_str = _extract_insight_cards(reports_md[metric_name], max_cards=max_cards)

        section = (
            f"=== {metric_name.upper()} ===\n"
            f"SUMMARY:\n{summary or '(no summary)'}\n\n"
            f"TOP INSIGHTS:\n{cards_str}\n"
        )
        parts.append(section)

    if lag_notes:
        parts.append("DATA MATURITY CONTEXT:")
        parts.extend(f"- {n}" for n in lag_notes)
        parts.append("")

    return "\n\n".join(parts)


def _load_hierarchy_level_mapping(
    json_data: dict[str, dict[str, Any]],
    parent_level: int,
    child_level: int,
) -> dict[str, list[str]]:
    """Build a definitive parent→[children] mapping from the raw data source.

    Generic approach — no entity names or column names are hardcoded:

    1. Reads `level_name` from hierarchical_analysis.level_{parent_level} in the
       metric JSON to discover the parent column name (e.g. "Region").
    2. Reads the contract YAML level_names[child_level] to discover the child column
       name (e.g. "Terminal").
    3. Scans every CSV in data/ for a file containing both columns and builds the
       many-to-one mapping from it.

    Returns {} if no suitable data file is found; callers fall back gracefully.
    The returned mapping guarantees no overlap — each child entity maps to exactly
    one parent.
    """
    import csv as _csv

    # --- Step 1: parent column name from JSON level_name -----------------------
    parent_col: str | None = None
    level_key = f"level_{parent_level}"
    for data in json_data.values():
        hier = data.get("hierarchical_analysis") or {}
        lvl_raw = hier.get(level_key)
        if isinstance(lvl_raw, str):
            try:
                lvl_raw = json.loads(lvl_raw)
            except json.JSONDecodeError:
                lvl_raw = {}
        if isinstance(lvl_raw, dict) and lvl_raw.get("level_name"):
            parent_col = lvl_raw["level_name"]
            break

    if not parent_col:
        return {}

    # --- Step 2: child column name from contract level_names -------------------
    child_col: str | None = None
    try:
        from config.dataset_resolver import get_dataset_path_optional
        contract_path = get_dataset_path_optional("contract.yaml")
        if contract_path and contract_path.exists():
            # Parse YAML minimally — avoid a hard yaml dependency at import time
            text = contract_path.read_text(encoding="utf-8")
            # Find level_names block and extract the child_level entry
            for line in text.splitlines():
                stripped = line.strip()
                # Match lines like "  2: Terminal" or "  2: \"Terminal\""
                if stripped.startswith(f"{child_level}:"):
                    val = stripped.split(":", 1)[-1].strip().strip("\"'")
                    if val:
                        child_col = val
                        break
    except Exception:
        pass

    # --- Step 3: scan data/ CSVs for a file with both columns -----------------
    data_dir = Path("data")
    if not data_dir.exists():
        return {}

    candidate_encs = [
        ("utf-16", "\t"),       # handles BOM automatically (LE or BE)
        ("utf-16-le", "\t"),    # explicit LE without BOM handling
        ("utf-8-sig", ","),     # UTF-8 with BOM
        ("utf-8", ","),
        ("latin-1", ","),
        ("utf-16", ","),
    ]

    for csv_path in sorted(data_dir.glob("*.csv")):
        for enc, delim in candidate_encs:
            try:
                with open(csv_path, encoding=enc, newline="") as fh:
                    reader = _csv.reader(fh, delimiter=delim)
                    headers = next(reader, None)
                    if not headers:
                        continue
                    # Strip whitespace AND Unicode BOM (U+FEFF) that may appear
                    # on the first field when reading UTF-16-LE without BOM handling
                    headers = [h.strip().lstrip("\ufeff") for h in headers]

                    parent_idx = next((i for i, h in enumerate(headers) if h == parent_col), None)
                    if parent_idx is None:
                        break  # wrong encoding or file — try next file

                    # Resolve child column index
                    child_idx: int | None = None
                    if child_col:
                        child_idx = next(
                            (i for i, h in enumerate(headers) if h == child_col), None
                        )
                    if child_idx is None:
                        # Fallback: first non-parent, non-date, non-metric column
                        for i, h in enumerate(headers):
                            if i == parent_idx:
                                continue
                            if "/" in h or h in ("Metric", "metric", "Date", "date"):
                                continue
                            child_idx = i
                            break

                    if child_idx is None:
                        break

                    mapping: dict[str, list[str]] = {}
                    seen: set[tuple[str, str]] = set()
                    for row in reader:
                        if len(row) <= max(parent_idx, child_idx):
                            continue
                        parent_val = row[parent_idx].strip()
                        child_val = row[child_idx].strip()
                        if not parent_val or not child_val:
                            continue
                        pair = (parent_val, child_val)
                        if pair not in seen:
                            seen.add(pair)
                            mapping.setdefault(parent_val, []).append(child_val)

                    if mapping:
                        return {k: sorted(v) for k, v in mapping.items()}
                    break  # found the right file/encoding but it was empty
            except Exception:
                continue

    return {}


def _sanitize_entity_name(entity: str) -> str:
    """Return a filesystem-safe version of an entity name (spaces -> underscores, strip special chars)."""
    sanitized = entity.replace(" ", "_")
    sanitized = re.sub(r"[^\w\-]", "", sanitized)
    return sanitized


def _extract_entity_from_card_title(title: str) -> str:
    """Extract entity name from a hierarchical insight card title.

    Supports two patterns:
    - "Level N Variance Driver: EntityName"  (current pipeline format)
    - "Top Driver: EntityName"               (legacy format)
    Returns empty string if no match.
    """
    for marker in ("Variance Driver:", "Driver:"):
        if marker in title:
            return title.split(marker, 1)[-1].strip()
    return ""


def _extract_entity_from_alert_id(alert_id: str) -> str:
    """Extract entity name from an alert id of the form '{period}-{EntityName}-{category}'.

    The id has exactly 3 dash-separated segments where the first is a date (YYYY-MM-DD).
    Returns empty string on parse failure.
    """
    # id format: "2026-02-14-Richmond-anomaly"
    # date occupies the first 10 chars (YYYY-MM-DD), then a dash, then "name-category"
    if len(alert_id) <= 11:
        return ""
    remainder = alert_id[11:]  # e.g. "Richmond-anomaly" or "Oklahoma City-anomaly"
    # Everything except the last dash-segment is the entity name
    parts = remainder.rsplit("-", 1)
    return parts[0].strip() if len(parts) == 2 else remainder.strip()


def _is_skip_card_simple(card: Any) -> bool:
    """Return True if card should be omitted (zero variance)."""
    if not isinstance(card, dict):
        return True
    
    # Check text patterns
    what = str(card.get("what_changed", "")).strip()
    zero_patterns = ("Variance of $0", "Variance of $0.00", "Variance of 0", 
                    "Variance of +0", "Variance of -0", "Variance of +0.00", "Variance of -0.00")
    if any(p in what for p in zero_patterns):
        return True
        
    # Check evidence values
    ev = card.get("evidence", {})
    if isinstance(ev, dict):
        for key in ("variance_dollar", "variance", "variance_amount"):
            val = ev.get(key)
            if val is not None:
                try:
                    if abs(float(val)) < 0.001:
                        return True
                except (ValueError, TypeError):
                    pass
    return False


def _normalize_share_value(raw_share: Any) -> float | None:
    """Normalize share value to 0-1 scale when possible."""
    try:
        share = float(raw_share)
    except (ValueError, TypeError):
        return None
    if share < 0:
        return None
    # Accept either fraction (0-1) or percent (0-100)
    if share > 1.0 and share <= 100.0:
        return share / 100.0
    return share


def _extract_share_from_payload(payload: dict[str, Any]) -> float | None:
    """Extract best available share metric from a card/row payload."""
    if not isinstance(payload, dict):
        return None
    evidence = payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {}
    for key in ("share_of_total", "share_current", "share"):
        if key in evidence:
            val = _normalize_share_value(evidence.get(key))
            if val is not None:
                return val
    for key in ("share_of_total", "share_current", "share"):
        if key in payload:
            val = _normalize_share_value(payload.get(key))
            if val is not None:
                return val
    return None


def _discover_level_entities(
    json_data: dict[str, dict[str, Any]],
    level: int,
    min_share_of_total: float = 0.0,
) -> list[str]:
    """Scan all metric JSON data and collect unique entity names at the given hierarchy level.

    Parses entity names from hierarchical_analysis.level_N.insight_cards[].title
    using the "Level N Variance Driver: {entity}" pattern produced by the pipeline.
    Also scans independent_level_results.level_N (flat-scan findings) for net-new entities.
    Also falls back to the legacy "level_results[].item" structure if present.
    Returns a deduplicated sorted list.
    """
    level_key = f"level_{level}"
    entities: set[str] = set()
    entity_max_share: dict[str, float] = {}
    entity_has_unknown_share: set[str] = set()
    for data in json_data.values():
        hier = data.get("hierarchical_analysis") or {}

        def _extract_cards_from_block(block: Any) -> None:
            if isinstance(block, str):
                try:
                    block = json.loads(block)
                except json.JSONDecodeError:
                    return
            if isinstance(block, dict):
                for card in block.get("insight_cards", []):
                    # Filter out zero-variance entities (Spec 039 cleanup)
                    if _is_skip_card_simple(card):
                        continue
                    entity = _extract_entity_from_card_title(card.get("title", ""))
                    if entity and entity.lower() not in ("total", ""):
                        entities.add(entity)
                        share = _extract_share_from_payload(card)
                        if share is None:
                            entity_has_unknown_share.add(entity)
                        else:
                            entity_max_share[entity] = max(entity_max_share.get(entity, 0.0), share)
                for row in block.get("level_results", []):
                    item = (row.get("item") or "").strip()
                    if item and item.lower() not in ("total", ""):
                        # Check for zero variance in row if possible
                        var = row.get("variance_dollar") or row.get("variance")
                        try:
                            if var is not None and abs(float(var)) < 0.001:
                                continue
                        except (ValueError, TypeError):
                            pass
                        entities.add(item)
                        share = _extract_share_from_payload(row)
                        if share is None:
                            entity_has_unknown_share.add(item)
                        else:
                            entity_max_share[item] = max(entity_max_share.get(item, 0.0), share)

        # Standard drill-down results
        _extract_cards_from_block(hier.get(level_key))

        # Independent flat-scan results (spec 035)
        ind_results = hier.get("independent_level_results") or {}
        if isinstance(ind_results, str):
            try:
                ind_results = json.loads(ind_results)
            except json.JSONDecodeError:
                ind_results = {}
        _extract_cards_from_block(ind_results.get(level_key))

    if min_share_of_total <= 0:
        return sorted(entities)

    filtered = []
    for entity in sorted(entities):
        if entity in entity_has_unknown_share:
            filtered.append(entity)
            continue
        if entity_max_share.get(entity, 0.0) >= min_share_of_total:
            filtered.append(entity)
    return filtered


def _alert_entity(alert: dict[str, Any]) -> str:
    """Extract the entity name from an alert record (case-preserved).

    Checks fields in order: item_name → item → id-parsed → details.description.
    """
    for field in ("item_name", "item"):
        val = (alert.get(field) or "").strip()
        if val:
            return val
    alert_id = alert.get("id") or ""
    if alert_id:
        parsed = _extract_entity_from_alert_id(alert_id)
        if parsed:
            return parsed
    desc = (alert.get("details") or {}).get("description") or ""
    # "Statistical anomaly in {entity} for {period}"
    if " in " in desc and " for " in desc:
        return desc.split(" in ", 1)[1].split(" for ")[0].strip()
    return ""


def _filter_alerts_for_scope(
    alerts: list[dict[str, Any]],
    scope_entity: str,
    sub_entity_names: set[str],
) -> list[dict[str, Any]]:
    """Filter top_alerts to those relevant to the scope entity or its sub-entities.

    Matches entity derived from item_name, item, id, or details.description (case-insensitive).
    If no filtered alerts exist, returns empty list (caller omits ALERTS block — FR-5.3).
    """
    relevant = {scope_entity.lower()} | {n.lower() for n in sub_entity_names}
    filtered = []
    for alert in alerts:
        entity = _alert_entity(alert).lower()
        region = (alert.get("region") or "").lower()
        if entity in relevant or region in relevant:
            filtered.append(alert)
    return filtered


def _build_scoped_digest(
    json_data: dict[str, dict[str, Any]],
    reports_md: dict[str, str],
    scope_entity: str,
    scope_level: int,
    analysis_period: str = "",
    scope_children: set[str] | None = None,
) -> str:
    """Build a digest focused on a single entity at the given scope level (FR-2.2).

    When scope_children is provided it is the authoritative, non-overlapping set of
    child-level entities belonging to scope_entity (e.g. all terminals in a region).
    All statistical data, anomalies, alerts and narrative cards are filtered strictly
    to that set — no entity appears in more than one scoped digest.

    When scope_children is None the function falls back to Strategy A: include all
    available child-level entities and rely on the LLM scope preamble to focus.

    Level labels are derived from the JSON data (level_name field) rather than being
    hardcoded, so the function works for any dataset hierarchy.
    """
    scope_entity_lower = scope_entity.lower()
    level_key = f"level_{scope_level}"

    # Resolve level label generically from JSON metadata
    level_label: str = f"Level {scope_level}"
    for data in json_data.values():
        hier = data.get("hierarchical_analysis") or {}
        lvl_raw = hier.get(level_key)
        if isinstance(lvl_raw, str):
            try:
                lvl_raw = json.loads(lvl_raw)
            except json.JSONDecodeError:
                lvl_raw = {}
        if isinstance(lvl_raw, dict) and lvl_raw.get("level_name"):
            level_label = lvl_raw["level_name"]
            break

    # Normalise children to lowercase for case-insensitive matching
    children_lower: set[str] = (
        {c.lower() for c in scope_children} if scope_children else set()
    )
    has_mapping = bool(children_lower)

    parts: list[str] = []
    header = f"SCOPE: {scope_entity} ({level_label})"
    if analysis_period:
        header += f"\nPERIOD: {analysis_period}"
    if scope_children:
        header += f"\nCHILD ENTITIES ({len(scope_children)}): {', '.join(sorted(scope_children))}"
    parts.append(header)
    parts.append("")

    for metric_name in sorted(json_data.keys()):
        data = json_data.get(metric_name, {})
        hier = data.get("hierarchical_analysis") or {}

        # --- Scope entity's level_N insight card (variance figures) ---
        lvl_raw = hier.get(level_key)
        if isinstance(lvl_raw, str):
            try:
                lvl_raw = json.loads(lvl_raw)
            except json.JSONDecodeError:
                lvl_raw = {}
        lvl_data: dict = lvl_raw if isinstance(lvl_raw, dict) else {}

        entity_card: dict | None = None
        for card in lvl_data.get("insight_cards", []):
            if _extract_entity_from_card_title(card.get("title", "")).lower() == scope_entity_lower:
                entity_card = card
                break

        # --- Statistical summary data for child entities ---------------------
        stats = data.get("statistical_summary") or {}
        if isinstance(stats, str):
            try:
                stats = json.loads(stats)
            except json.JSONDecodeError:
                stats = {}
        top_drivers: list[dict] = stats.get("top_drivers") or []
        anomalies: list[dict] = stats.get("anomalies") or []

        def _in_scope(item_name: str) -> bool:
            """Return True if item_name belongs to this scope's children."""
            if not item_name:
                return False
            nl = item_name.lower()
            if has_mapping:
                return nl in children_lower
            # Strategy A fallback: include everything, LLM will focus
            return True

        scoped_drivers = [
            d for d in top_drivers
            if _in_scope((d.get("item") or d.get("item_name") or "").strip())
        ]
        scoped_anomalies = [
            a for a in anomalies
            if _in_scope((a.get("item") or a.get("item_name") or "").strip())
        ]

        # --- Narrative insight cards -----------------------------------------
        # Include cards that mention the scope entity OR any of its child entities.
        narrative = data.get("narrative_results") or {}
        if isinstance(narrative, str):
            try:
                narrative = json.loads(narrative)
            except json.JSONDecodeError:
                narrative = {}
        narrative_cards: list[dict] = []
        for card in (narrative.get("insight_cards") or []):
            text_l = " ".join([
                card.get("title") or "",
                card.get("what_changed") or "",
                card.get("why") or "",
            ]).lower()
            mentions_scope = scope_entity_lower in text_l
            if not mentions_scope and has_mapping:
                mentions_scope = any(child in text_l for child in children_lower)
            if mentions_scope:
                narrative_cards.append(card)

        # --- Alerts -----------------------------------------------------------
        analysis_block = data.get("analysis") or {}
        top_alerts: list[dict] = (analysis_block.get("alert_scoring") or {}).get("top_alerts") or []
        child_names_orig: set[str] = scope_children if scope_children else set()
        scoped_alerts = _filter_alerts_for_scope(top_alerts, scope_entity, child_names_orig)

        # --- Report markdown fallback for narrative insights ------------------
        # When JSON narrative_results.insight_cards is empty (some metrics omit it),
        # fall back to filtering the rendered markdown report for scope-relevant cards.
        report_cards_fallback: str = ""
        if not narrative_cards and metric_name in reports_md:
            report_cards_fallback = _extract_scoped_cards_from_report(
                reports_md[metric_name],
                scope_entity_lower,
                children_lower,
                max_cards=4,
            )

        # --- Assemble section -------------------------------------------------
        section_parts: list[str] = [f"=== {metric_name.upper()} ==="]

        if entity_card:
            ev = entity_card.get("evidence") or {}
            variance_dollar = ev.get("variance_dollar") or 0
            variance_pct = ev.get("variance_pct") or 0
            share = ev.get("share_of_total")
            sign = "+" if variance_dollar >= 0 else ""
            summary_lines = [
                f"{level_label.upper()} SUMMARY ({scope_entity}):",
                f"- Variance: {sign}${variance_dollar:,.0f} ({sign}{variance_pct:.1f}%)",
            ]
            if share is not None:
                try:
                    summary_lines.append(f"- Share of total variance: {share:.1%}")
                except (TypeError, ValueError):
                    pass
            what_changed = entity_card.get("what_changed") or ""
            if what_changed:
                summary_lines.append(f"- {what_changed}")
            section_parts.append("\n".join(summary_lines))

        if scoped_drivers:
            driver_lines = ["CHILD ENTITY PERFORMANCE:"]
            for d in scoped_drivers[:12]:
                item = d.get("item") or d.get("item_name") or "?"
                avg = d.get("avg")
                slope = d.get("slope_3mo")
                try:
                    driver_lines.append(f"- {item}: avg={avg:.1f}, 3mo trend={slope:+.1f}")
                except (TypeError, ValueError):
                    driver_lines.append(f"- {item}: avg={avg}, 3mo trend={slope}")
            section_parts.append("\n".join(driver_lines))

        if scoped_anomalies:
            anom_lines = ["ANOMALIES (in scope):"]
            for a in scoped_anomalies[:8]:
                item = a.get("item") or a.get("item_name") or "?"
                period = a.get("period") or ""
                zscore = a.get("z_score") or ""
                try:
                    anom_lines.append(f"- {item} ({period}): z-score={zscore:.2f}")
                except (TypeError, ValueError):
                    anom_lines.append(f"- {item} ({period})")
            section_parts.append("\n".join(anom_lines))

        if narrative_cards:
            card_lines = ["INSIGHTS (scope-relevant):"]
            seen_titles: set[str] = set()
            for c in narrative_cards[:6]:
                t = c.get("title") or ""
                if t in seen_titles:
                    continue
                seen_titles.add(t)
                what = c.get("what_changed") or ""
                why = c.get("why") or ""
                card_lines.append(f"### {t}")
                if what:
                    card_lines.append(what)
                if why:
                    card_lines.append(f"Why: {why[:300]}")
            section_parts.append("\n".join(card_lines))
        elif report_cards_fallback:
            section_parts.append(f"INSIGHTS (from report):\n{report_cards_fallback}")

        if scoped_alerts:
            alert_lines = ["KEY ALERTS:"]
            for a in scoped_alerts[:6]:
                entity = _alert_entity(a)
                category = a.get("category") or ""
                score = a.get("score") or 0
                period = a.get("period") or ""
                try:
                    alert_lines.append(f"- {entity} ({period}): {category} (score {score:.2f})")
                except (TypeError, ValueError):
                    alert_lines.append(f"- {entity}: {category}")
            section_parts.append("\n".join(alert_lines))

        if len(section_parts) > 1:
            parts.append("\n\n".join(section_parts))

    return "\n\n".join(parts)


async def _llm_generate_brief(
    model_name: str,
    instruction: str,
    user_message: str,
    thinking_config: Any,
) -> tuple[dict, str]:
    """Call the LLM to generate a brief JSON. Returns (brief_data_dict, brief_markdown).

    Retries up to 3 times on transient errors with 5-second back-off.
    Raises on final failure (caller decides how to handle).
    """
    import asyncio

    config = types.GenerateContentConfig(
        system_instruction=instruction,
        response_modalities=["TEXT"],
        temperature=0.05,
        thinking_config=thinking_config,
    )
    loop = asyncio.get_running_loop()
    raw: str | None = None
    last_err: Exception | None = None
    for attempt in range(1, 4):
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
                timeout=300.0,
            )
            raw = response.text.strip()
            break
        except Exception as attempt_err:
            last_err = attempt_err
            print(f"[BRIEF] Attempt {attempt}/3 failed: {attempt_err}. Retrying in 5s...")
            if attempt < 3:
                await asyncio.sleep(5)

    if raw is None:
        raise last_err  # type: ignore[misc]

    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    brief_data = json.loads(raw)
    return brief_data, _format_brief(brief_data)


def _write_executive_brief_cache(
    outputs_dir: Path,
    digest: str,
    period_end: str,
    analysis_period: str,
    metric_names: list[str],
    timeframe: dict,
    weather_context: Any,
    dataset: str | None = None,
    drill_levels: int = 0,
    scoped_digests: dict[str, str] | None = None,
) -> None:
    """Write executive_brief_input_cache.json for Spec 031/032 regeneration workflow.

    Version 1: network-only (drill_levels == 0).
    Version 2: includes drill_levels and scoped_digests dict (drill_levels >= 1).
    """
    try:
        version = 2 if (drill_levels > 0 or scoped_digests) else 1
        cache: dict[str, Any] = {
            "version": version,
            "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "dataset": dataset or "unknown",
            "period_end": period_end,
            "analysis_period": analysis_period,
            "metrics": metric_names,
            "metric_count": len(metric_names),
            "timeframe": timeframe if isinstance(timeframe, dict) else {},
            "digest": digest,
            "weather_context": weather_context,
        }
        if version == 2:
            cache["drill_levels"] = drill_levels
            cache["scoped_digests"] = scoped_digests or {}
        cache_path = outputs_dir / "executive_brief_input_cache.json"
        cache_path.write_text(json.dumps(cache, indent=2), encoding="utf-8")
        print(f"[BRIEF] Wrote executive brief input cache to {cache_path.name} (v{version})")
    except Exception as e:
        print(f"[BRIEF] WARNING: Failed to write cache: {e}")


def _format_brief(brief: dict) -> str:
    """Render the LLM JSON response as clean markdown."""
    subject = brief.get("subject", "Weekly Performance Brief")
    opening = brief.get("opening") or brief.get("summary", "")

    # New email-style fields
    top_insights = brief.get("top_operational_insights", [])
    network_snapshot = brief.get("network_snapshot", "")
    focus_for_next_week = brief.get("focus_for_next_week", "")
    scope_summary = brief.get("scope_summary") or brief.get("regional_summary", "")
    child_entity_label = brief.get("child_entity_label", "Child Entity")
    child_entity_insights = brief.get("child_entity_insights") or brief.get("terminal_insights", [])
    structural_insights = brief.get("structural_insights") or brief.get("regional_insight", [])
    leadership_question = brief.get("leadership_question", "")
    signoff_name = brief.get("signoff_name", "Ty")

    # Legacy fallback fields
    going_well = brief.get("whats_going_well", [])
    masking = brief.get("whats_masking_the_picture", [])
    concern = brief.get("primary_concern", "")
    bottom_line = brief.get("bottom_line", "")

    is_scoped_deep_dive = bool(scope_summary or child_entity_insights or structural_insights or leadership_question)
    lines = [f"**Subject: {subject}**", "", "Team,", ""]

    if opening:
        lines += [opening, ""]

    if is_scoped_deep_dive:
        if scope_summary:
            lines += ["**Scope Summary**", "", scope_summary, ""]

        if child_entity_insights:
            lines += [f"**{child_entity_label} Insights**", ""]
            for child_data in child_entity_insights:
                if not isinstance(child_data, dict):
                    continue
                entity_name = str(child_data.get("entity") or child_data.get("terminal", "")).strip()
                entity_analysis = str(child_data.get("analysis", "")).strip()
                key_takeaway = str(child_data.get("key_takeaway", "")).strip()

                if entity_name:
                    lines += [f"**{entity_name}**", ""]
                if entity_analysis:
                    lines += [entity_analysis, ""]
                if key_takeaway:
                    lines += [f"Key takeaway: {key_takeaway}", ""]

        if structural_insights:
            lines += ["**Structural Insights**", ""]
            for item in structural_insights:
                lines.append(f"- {item}")
            lines.append("")

        if leadership_question:
            lines += ["**Leadership Question**", "", leadership_question, ""]
    else:
        # Preferred network format
        if top_insights:
            lines += ["**Top Operational Insights**", ""]
            for idx, insight in enumerate(top_insights, start=1):
                if isinstance(insight, dict):
                    title = str(insight.get("title", "")).strip()
                    detail = str(insight.get("detail", "")).strip()
                else:
                    title = ""
                    detail = str(insight).strip()

                lines += [f"{idx}. {title or f'Insight {idx}'}"]
                if detail:
                    lines += [detail, ""]
                else:
                    lines.append("")
        else:
            # Legacy fallback shape from prior prompt versions
            lines += ["**Top Operational Insights**", ""]
            combined = list(going_well) + list(masking)
            for idx, item in enumerate(combined[:4], start=1):
                lines += [f"{idx}. Insight {idx}", str(item), ""]

        if network_snapshot:
            lines += ["**Network Snapshot**", "", network_snapshot, ""]
        elif bottom_line:
            lines += ["**Network Snapshot**", "", bottom_line, ""]

        if focus_for_next_week:
            lines += ["**Focus for next week**", "", focus_for_next_week, ""]
        elif concern:
            lines += ["**Focus for next week**", "", concern, ""]

    lines += ["Best,", signoff_name, ""]

    lines += [
        "---",
        f"*Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} by the Cross-Metric Executive Brief Agent*",
    ]
    return "\n".join(lines)


class CrossMetricExecutiveBriefAgent(BaseAgent):
    """
    Synthesizes all per-metric analysis reports into a single executive brief.

    Runs after ParallelDimensionTargetAgent completes. Reads metric_*.md from
    the outputs directory, sends a compact digest to the LLM, and writes the
    brief to outputs/executive_brief_<YYYY-MM-DD>.md.
    """

    def __init__(self) -> None:
        super().__init__(name="executive_brief_agent")

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        print("\n" + "=" * 80)
        print("[BRIEF] CrossMetricExecutiveBriefAgent starting")
        print("=" * 80)

        # Use run-specific directory if available
        run_dir = os.getenv("DATA_ANALYST_OUTPUT_DIR")
        if run_dir:
            outputs_dir = Path(run_dir).resolve()
        else:
            outputs_dir = Path("outputs").resolve()
            
        reports = _collect_metric_reports(outputs_dir)

        # Filter to only requested metrics when user specified a subset (e.g. --metrics "Truck Count")
        extracted_targets = ctx.session.state.get("extracted_targets") or []
        if extracted_targets:
            requested = {str(t).strip() for t in extracted_targets}
            reports = {k: v for k, v in reports.items() if k in requested}
            if reports:
                print(f"[BRIEF] Filtered to {len(reports)} requested metric(s): {', '.join(reports.keys())}")

        if not reports:
            if extracted_targets:
                print("[BRIEF] No metric reports found for requested metric(s). Skipping.")
            else:
                print("[BRIEF] No metric reports found in outputs/. Skipping.")
            yield Event(
                invocation_id=ctx.invocation_id,
                author=self.name,
                actions=EventActions(),
            )
            return

        print(f"[BRIEF] Found {len(reports)} metric report(s): {', '.join(reports.keys())}")

        # Determine reference period from session state or reports (dataset-agnostic)
        timeframe = ctx.session.state.get("timeframe", {})
        period_end = timeframe.get("end") or ctx.session.state.get("primary_query_end_date")
        if not period_end:
            first_content = next(iter(reports.values()), "")
            match = re.search(r"\d{4}-\d{2}-\d{2}", first_content)
            period_end = match.group(0) if match else datetime.now().strftime("%Y-%m-%d")
        analysis_period = ctx.session.state.get("analysis_period") or _format_analysis_period(
            period_end, ctx.session.state.get("dataset_contract")
        )

        print(f"[BRIEF] Analysis period: {analysis_period}")

        json_data = _collect_metric_json_data(outputs_dir)
        if extracted_targets:
            requested = {str(t).strip() for t in extracted_targets}
            json_data = {k: v for k, v in json_data.items() if k in requested}
        use_json = parse_bool_env(os.environ.get("EXECUTIVE_BRIEF_USE_JSON", "true"))
        if use_json and json_data:
            digest = _build_digest_from_json(json_data, reports, max_cards=6)
            print(f"[BRIEF] Using JSON-backed digest ({len(json_data)} metrics)")
        else:
            digest = _build_digest(reports)
            print(f"[BRIEF] Using markdown-only digest")

        # Read drill level config (priority: contract > report_config.yaml > env/session > defaults)
        drill_levels = 0
        max_scope_entities = 10
        min_scope_share_of_total = 0.0
        output_format = "pdf"
        
        # 1. Load from global report_config.yaml (baseline defaults)
        try:
            import yaml
            config_path = Path(__file__).resolve().parent.parent.parent.parent / "config" / "report_config.yaml"
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

        # 2. Override with dataset-specific contract settings (preferred)
        contract = ctx.session.state.get("dataset_contract")
        if contract and hasattr(contract, "reporting") and contract.reporting:
            r = contract.reporting
            drill_levels = r.executive_brief_drill_levels
            max_scope_entities = r.max_scope_entities
            min_scope_share_of_total = float(getattr(r, "min_scope_share_of_total", min_scope_share_of_total) or 0.0)
            output_format = r.output_format
            print(f"[BRIEF] Using reporting settings from contract: {contract.name}")

        # 3. Session state overrides (from RequestAnalyzer or test-bench)
        session_drill = ctx.session.state.get("executive_brief_drill_levels")
        if session_drill is not None:
            try:
                drill_levels = int(session_drill)
            except (ValueError, TypeError):
                pass
        
        # 4. Environment variable overrides (absolute highest priority for CI/experimental overrides)
        try:
            env_drill = os.environ.get("EXECUTIVE_BRIEF_DRILL_LEVELS")
            if env_drill is not None:
                drill_levels = int(env_drill)
                print(f"[BRIEF] Overriding drill_levels={drill_levels} from env")
        except (ValueError, TypeError):
            pass

        try:
            env_max_scope = os.environ.get("EXECUTIVE_BRIEF_MAX_SCOPE_ENTITIES")
            if env_max_scope is not None:
                max_scope_entities = int(env_max_scope)
                print(f"[BRIEF] Overriding max_scope_entities={max_scope_entities} from env")
        except (ValueError, TypeError):
            pass

        try:
            env_min_scope_share = os.environ.get("EXECUTIVE_BRIEF_MIN_SCOPE_SHARE")
            if env_min_scope_share is not None:
                min_scope_share_of_total = float(env_min_scope_share)
                print(f"[BRIEF] Overriding min_scope_share_of_total={min_scope_share_of_total:.4f} from env")
        except (ValueError, TypeError):
            pass

        instruction = EXECUTIVE_BRIEF_INSTRUCTION.format(
            metric_count=len(reports),
            analysis_period=analysis_period,
            scope_preamble="",
            dataset_specific_append=load_dataset_specific_append(),
            prompt_variant_append=load_prompt_variant(os.environ.get("EXECUTIVE_BRIEF_PROMPT_VARIANT", "default")),
        )

        weather_block = _build_weather_context_block(ctx.session.state.get("weather_context"))
        
        # --- BRIEF TEMPORAL CONTEXT: Mandatory grounding for subject/opening ---
        temporal_grain = ctx.session.state.get("temporal_grain", "unknown")
        brief_temporal_context = {
            "reference_period_end": period_end,
            "temporal_grain": temporal_grain,
            "analysis_period": analysis_period,
            "period_unit": "week" if temporal_grain == "weekly" else "month",
            "default_comparison_basis": (
                "vs prior week (WoW)" if temporal_grain == "weekly" else "vs prior month (MoM)"
            ),
            "comparison_priority_order": (
                [
                    "current week vs prior week (WoW)",
                    "current week vs rolling 4-week average",
                    "other supported comparisons (lower priority)",
                ]
                if temporal_grain == "weekly"
                else [
                    "current month vs prior month (MoM)",
                    "current month vs rolling 3-month average",
                    "current month vs same month prior year (YoY)",
                    "other supported comparisons (lower priority)",
                ]
            ),
            "comparison_requirement": (
                "Every comparative claim must include its explicit baseline in the same sentence."
            ),
        }

        user_message = (
            f"BRIEF_TEMPORAL_CONTEXT (MANDATORY GROUNDING):\n"
            f"{json.dumps(brief_temporal_context, indent=2)}\n\n"
            f"Use the above 'reference_period_end' as the date in your JSON 'subject'.\n\n"
            f"Here are the individual metric analysis summaries for {analysis_period}.\n\n"
            f"{digest}\n\n"
            f"{weather_block}"
            "Generate the executive brief JSON as instructed."
        )

        metric_names = sorted(reports.keys())
        model_name = get_agent_model("executive_brief_agent")
        thinking_config = get_agent_thinking_config("executive_brief_agent")

        # Spec 031: Write cache before LLM call for iterative refinement (v1 — scoped digests added later)
        _write_executive_brief_cache(
            outputs_dir=outputs_dir,
            digest=digest + weather_block,
            period_end=period_end,
            analysis_period=analysis_period,
            metric_names=metric_names,
            timeframe=timeframe if isinstance(timeframe, dict) else {},
            weather_context=ctx.session.state.get("weather_context"),
            dataset=ctx.session.state.get("dataset"),
        )

        print(f"[BRIEF] Sending digest ({len(digest)} chars) to LLM...")

        try:
            import asyncio

            _, brief_md = await _llm_generate_brief(
                model_name=model_name,
                instruction=instruction,
                user_message=user_message,
                thinking_config=thinking_config,
            )

            # Save network brief
            if os.getenv("DATA_ANALYST_OUTPUT_DIR"):
                brief_filename = "brief.md"
            else:
                brief_filename = f"executive_brief_{period_end}.md"
            brief_path = outputs_dir / brief_filename
            brief_path.write_text(brief_md, encoding="utf-8")
            print(f"[BRIEF] Saved executive brief to {brief_filename}")
            print(f"[BRIEF] File size: {brief_path.stat().st_size} bytes")

            print("\n" + "=" * 80)
            print("EXECUTIVE BRIEF")
            print("=" * 80)
            print(brief_md)
            print("=" * 80 + "\n")

            # --- Spec 032: Scoped brief generation loop ---
            scoped_briefs: dict[str, dict[str, str]] = {}
            scoped_digests_map: dict[str, str] = {}
            _scope_level_labels = {1: "Region", 2: "Terminal"}

            if drill_levels >= 1 and json_data:
                print(f"[BRIEF] Drill levels={drill_levels}: generating scoped briefs")
                for level in range(1, min(drill_levels, 2) + 1):
                    entities = _discover_level_entities(
                        json_data,
                        level,
                        min_share_of_total=min_scope_share_of_total,
                    )
                    if level == 2:
                        entities = entities[:max_scope_entities]
                    level_name = _scope_level_labels.get(level, f"Level {level}")
                    print(f"[BRIEF] Level {level} ({level_name}): {len(entities)} entities: {', '.join(entities)}")

                    # Load definitive parent→children mapping once for this level
                    hierarchy_map = _load_hierarchy_level_mapping(json_data, level, level + 1)
                    if hierarchy_map:
                        print(f"[BRIEF] Hierarchy mapping loaded ({sum(len(v) for v in hierarchy_map.values())} children across {len(hierarchy_map)} parents)")
                    else:
                        print(f"[BRIEF] No hierarchy mapping found — using Strategy A (LLM-scoped) fallback")

                    for entity in entities:
                        scope_children = set(hierarchy_map.get(entity, [])) if hierarchy_map else None
                        scoped_digest = _build_scoped_digest(
                            json_data, reports, entity, level, analysis_period,
                            scope_children=scope_children,
                        )
                        scoped_digests_map[entity] = scoped_digest

                        scope_preamble = SCOPED_BRIEF_PREAMBLE.format(
                            scope_entity=entity,
                            scope_level_name=level_name.lower(),
                        )
                        scoped_instruction = EXECUTIVE_BRIEF_INSTRUCTION.format(
                            metric_count=len(reports),
                            analysis_period=analysis_period,
                            scope_preamble=scope_preamble,
                            dataset_specific_append=load_dataset_specific_append(),
                            prompt_variant_append=load_prompt_variant(
                                os.environ.get("EXECUTIVE_BRIEF_PROMPT_VARIANT", "default")
                            ),
                        )
                        scoped_user_message = (
                            f"BRIEF_TEMPORAL_CONTEXT (MANDATORY GROUNDING):\n"
                            f"{json.dumps(brief_temporal_context, indent=2)}\n\n"
                            f"Use the above 'reference_period_end' as the date in your JSON 'subject'.\n\n"
                            f"Here are the individual metric analysis summaries for {analysis_period}, "
                            f"scoped to the {entity} {level_name.lower()}.\n\n"
                            f"{scoped_digest}\n\n"
                            "Generate the executive brief JSON as instructed. "
                            f"Focus exclusively on the {entity} {level_name.lower()} scope."
                        )
                        print(f"[BRIEF] Generating scoped brief for {entity} ({level_name})...")
                        try:
                            _, scoped_brief_md = await _llm_generate_brief(
                                model_name=model_name,
                                instruction=scoped_instruction,
                                user_message=scoped_user_message,
                                thinking_config=thinking_config,
                            )
                            safe_entity = _sanitize_entity_name(entity)
                            if os.getenv("DATA_ANALYST_OUTPUT_DIR"):
                                scoped_filename = f"brief_{safe_entity}.md"
                            else:
                                scoped_filename = f"executive_brief_{period_end}_{safe_entity}.md"
                            scoped_path = outputs_dir / scoped_filename
                            scoped_path.write_text(scoped_brief_md, encoding="utf-8")
                            print(f"[BRIEF] Saved scoped brief for {entity} to {scoped_filename}")
                            scoped_briefs[entity] = {
                                "path": str(scoped_path),
                                "content": scoped_brief_md,
                                "level": level,
                                "level_name": level_name,
                                "bookmark_label": f"{entity} ({level_name})",
                            }
                        except Exception as scope_err:
                            print(f"[BRIEF] ERROR generating scoped brief for {entity}: {scope_err}")

                # Update cache to v2 with scoped digests (FR-3.4 / FR-4.4)
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
                        drill_levels=drill_levels,
                        scoped_digests=scoped_digests_map,
                    )

            # --- Spec 033: PDF/HTML Export ---
            env_format = os.environ.get("EXECUTIVE_BRIEF_OUTPUT_FORMAT")
            if env_format:
                output_format = env_format.lower()
            
            pdf_path: Path | None = None
            html_path: Path | None = None
            
            # Prepare pages for rendering
            network_label = f"Network \u2014 {period_end}"
            from .pdf_renderer import BriefPage
            pages: list[BriefPage] = [
                BriefPage(
                    bookmark_label=network_label,
                    markdown_content=brief_md,
                    level=0,
                )
            ]
            for entity, info in scoped_briefs.items():
                pages.append(
                    BriefPage(
                        bookmark_label=info.get("bookmark_label", entity),
                        markdown_content=info["content"],
                        level=info.get("level", 1),
                        parent_label="",
                    )
                )

            # PDF Render
            if output_format in ("pdf", "both"):
                try:
                    from .pdf_renderer import render_briefs_to_pdf
                    if os.getenv("DATA_ANALYST_OUTPUT_DIR"):
                        pdf_filename = "brief.pdf"
                    else:
                        pdf_filename = f"executive_brief_{period_end}.pdf"
                    pdf_out = outputs_dir / pdf_filename
                    pdf_path = render_briefs_to_pdf(pages, pdf_out, period_end)
                except Exception as pdf_err:
                    print(f"[BRIEF] PDF rendering error (non-fatal): {pdf_err}")

            # HTML Render
            if output_format in ("html", "both"):
                try:
                    from .html_renderer import render_briefs_to_html
                    if os.getenv("DATA_ANALYST_OUTPUT_DIR"):
                        html_filename = "brief.html"
                    else:
                        html_filename = f"executive_brief_{period_end}.html"
                    html_out = outputs_dir / html_filename
                    html_path = render_briefs_to_html(pages, html_out, period_end)
                except Exception as html_err:
                    print(f"[BRIEF] HTML rendering error (non-fatal): {html_err}")

            # Build final state delta (FR-3.4)
            state_delta: dict[str, Any] = {
                "executive_brief": brief_md,
                "executive_brief_path": str(brief_path),
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
        except json.JSONDecodeError as e:
            print(f"[BRIEF] JSON parse error: {e}.")
            yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=EventActions())
        except Exception as e:
            import traceback
            print(f"[BRIEF] ERROR: {e}")
            traceback.print_exc()
            yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=EventActions())

        print("\n[BRIEF] CrossMetricExecutiveBriefAgent complete")
