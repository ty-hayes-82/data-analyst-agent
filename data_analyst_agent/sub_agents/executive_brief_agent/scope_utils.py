"""Helpers for scoped executive brief digests (hierarchy lookups, filtering, alerts)."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_PARENT_CHILD_CACHE: dict[tuple[str, str, str], dict[str, list[str]]] = {}


def _resolve_scope_hierarchy(contract: Any | None, preferred_name: str | None = None):
    if not contract or not getattr(contract, "hierarchies", None):
        return None
    hierarchies = getattr(contract, "hierarchies", []) or []
    normalized_targets: list[str] = []
    for candidate in (preferred_name, os.environ.get("EXECUTIVE_BRIEF_SCOPE_HIERARCHY")):
        if candidate:
            normalized_targets.append(str(candidate).strip().lower())
    for target in normalized_targets:
        match = next(
            (h for h in hierarchies if str(getattr(h, "name", "")).lower() == target),
            None,
        )
        if match:
            return match
    reporting_cfg = getattr(contract, "reporting", None)
    if reporting_cfg:
        cfg_name = getattr(reporting_cfg, "executive_brief_scope_hierarchy", None)
        if cfg_name:
            target = str(cfg_name).strip().lower()
            match = next(
                (h for h in hierarchies if str(getattr(h, "name", "")).lower() == target),
                None,
            )
            if match:
                return match
    if not hierarchies:
        return None
    return max(hierarchies, key=lambda h: len(getattr(h, "children", []) or []))


def derive_scope_level_labels(contract: Any | None, preferred_name: str | None = None) -> dict[int, str]:
    hierarchy = _resolve_scope_hierarchy(contract, preferred_name)
    if not hierarchy:
        return {}
    labels: dict[int, str] = {}
    raw_map = getattr(hierarchy, "level_names", {}) or {}
    for raw_idx, label in raw_map.items():
        try:
            idx = int(raw_idx)
        except (TypeError, ValueError):
            continue
        if idx == 0:
            continue
        labels[idx] = str(label)
    return labels


def _resolve_contract_data_path(contract: Any | None) -> Path | None:
    if not contract:
        return None
    data_source = getattr(contract, "data_source", None)
    source_type = (getattr(data_source, "type", None) or "").lower()
    if source_type != "csv":
        return None
    file_field = getattr(data_source, "file", None)
    if not file_field and isinstance(data_source, dict):
        file_field = data_source.get("file")
    if not file_field:
        return None
    candidate = Path(file_field)
    if candidate.is_absolute() and candidate.exists():
        return candidate
    source_path = getattr(contract, "_source_path", None)
    if source_path:
        dataset_dir = Path(source_path).parent
        alt = dataset_dir / file_field
        if alt.exists():
            return alt
    alt = _PROJECT_ROOT / file_field
    if alt.exists():
        return alt
    return None


def _load_hierarchy_level_mapping(
    json_data: dict[str, dict[str, Any]],
    parent_level: int,
    child_level: int,
    *,
    contract: Any | None = None,
    preferred_hierarchy: str | None = None,
) -> dict[str, list[str]]:
    del json_data  # contract-driven implementation; JSON digest no longer needed here.
    hierarchy = _resolve_scope_hierarchy(contract, preferred_hierarchy)
    if not hierarchy:
        return {}
    children = getattr(hierarchy, "children", []) or []
    parent_idx = parent_level - 1
    child_idx = child_level - 1
    if parent_idx < 0 or child_idx < 0 or child_idx >= len(children) or parent_idx >= len(children):
        return {}
    if not contract or not hasattr(contract, "get_dimension"):
        return {}
    try:
        parent_dim = contract.get_dimension(children[parent_idx])
        child_dim = contract.get_dimension(children[child_idx])
    except Exception:
        return {}
    dataset_path = _resolve_contract_data_path(contract)
    if not dataset_path:
        return {}
    cache_key = (str(dataset_path), parent_dim.column, child_dim.column)
    if cache_key not in _PARENT_CHILD_CACHE:
        try:
            df = pd.read_csv(
                dataset_path,
                usecols=[parent_dim.column, child_dim.column],
            )
        except Exception:
            return {}
        df = df.dropna(subset=[parent_dim.column, child_dim.column])
        df[parent_dim.column] = df[parent_dim.column].astype(str).str.strip()
        df[child_dim.column] = df[child_dim.column].astype(str).str.strip()
        df = df[(df[parent_dim.column] != "") & (df[child_dim.column] != "")]
        pairs = df[[parent_dim.column, child_dim.column]].drop_duplicates()
        mapping: dict[str, list[str]] = {}
        for parent_val, child_val in pairs.values:
            mapping.setdefault(parent_val, []).append(child_val)
        mapping = {k: sorted(set(v)) for k, v in mapping.items()}
        _PARENT_CHILD_CACHE[cache_key] = mapping
    return _PARENT_CHILD_CACHE.get(cache_key, {})


def _sanitize_entity_name(entity: str) -> str:
    sanitized = entity.replace(" ", "_")
    sanitized = re.sub(r"[^\w-]", "", sanitized)
    return sanitized


def _extract_entity_from_card_title(title: str) -> str:
    for marker in ("Variance Driver:", "Driver:"):
        if marker in title:
            return title.split(marker, 1)[-1].strip()
    return ""


def _extract_entity_from_alert_id(alert_id: str) -> str:
    if len(alert_id) <= 11:
        return ""
    remainder = alert_id[11:]
    parts = remainder.rsplit("-", 1)
    return parts[0].strip() if len(parts) == 2 else remainder.strip()


def _is_skip_card_simple(card: Any) -> bool:
    if not isinstance(card, dict):
        return True
    what = str(card.get("what_changed", "")).strip()
    zero_patterns = (
        "Variance of $0",
        "Variance of $0.00",
        "Variance of 0",
        "Variance of +0",
        "Variance of -0",
        "Variance of +0.00",
        "Variance of -0.00",
    )
    if any(p in what for p in zero_patterns):
        return True
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
    try:
        share = float(raw_share)
    except (ValueError, TypeError):
        return None
    if share < 0:
        return None
    if share > 1.0 and share <= 100.0:
        return share / 100.0
    return share


def _extract_share_from_payload(payload: dict[str, Any]) -> float | None:
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
    level_key = f"level_{level}"
    entities: set[str] = set()
    entity_max_share: dict[str, float] = {}
    entity_has_unknown_share: set[str] = set()

    def _extract_cards_from_block(block: Any) -> None:
        if isinstance(block, str):
            try:
                block = json.loads(block)
            except json.JSONDecodeError:
                return
        if isinstance(block, dict):
            for card in block.get("insight_cards", []):
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

    for data in json_data.values():
        hier = data.get("hierarchical_analysis") or {}
        _extract_cards_from_block(hier.get(level_key))
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
    if " in " in desc and " for " in desc:
        return desc.split(" in ", 1)[1].split(" for ")[0].strip()
    return ""


def _filter_alerts_for_scope(
    alerts: list[dict[str, Any]],
    scope_entity: str,
    sub_entity_names: set[str],
) -> list[dict[str, Any]]:
    """Return alerts that clearly reference the scope entity or its children.

    Alerts originate from datasets with different dimension labels. Instead of
    reading trade-only fields (e.g., ``region``), normalize a broader set of
    descriptive fields so this filter remains contract-agnostic.
    """

    relevant = {scope_entity.lower()} | {n.lower() for n in sub_entity_names}

    def _matches_scope(value: Any) -> bool:
        text = str(value or "").strip().lower()
        if not text:
            return False
        if text in relevant:
            return True
        return any(term and term in text for term in relevant)

    filtered = []
    for alert in alerts:
        candidates = [
            _alert_entity(alert),
            alert.get("dimension_value"),
            alert.get("item_name"),
            alert.get("item"),
            alert.get("item_id"),
            alert.get("entity"),
            alert.get("entity_name"),
        ]
        details = alert.get("details")
        if isinstance(details, dict):
            candidates.extend(
                [
                    details.get("entity"),
                    details.get("dimension_value"),
                    details.get("description"),
                ]
            )
        if any(_matches_scope(value) for value in candidates):
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
    scope_entity_lower = scope_entity.lower()
    level_key = f"level_{scope_level}"
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
        lvl_raw = hier.get(level_key)
        if isinstance(lvl_raw, str):
            try:
                lvl_raw = json.loads(lvl_raw)
            except json.JSONDecodeError:
                lvl_raw = {}
        lvl_data: dict[str, Any] = lvl_raw if isinstance(lvl_raw, dict) else {}

        entity_card: dict[str, Any] | None = None
        for card in lvl_data.get("insight_cards", []):
            if _extract_entity_from_card_title(card.get("title", "")).lower() == scope_entity_lower:
                entity_card = card
                break

        stats = data.get("statistical_summary") or {}
        if isinstance(stats, str):
            try:
                stats = json.loads(stats)
            except json.JSONDecodeError:
                stats = {}
        top_drivers: list[dict[str, Any]] = stats.get("top_drivers") or []
        anomalies: list[dict[str, Any]] = stats.get("anomalies") or []

        def _in_scope(item_name: str) -> bool:
            if not item_name:
                return False
            nl = item_name.lower()
            if has_mapping:
                return nl in children_lower
            return True

        scoped_drivers = [
            d for d in top_drivers
            if _in_scope((d.get("item") or d.get("item_name") or "").strip())
        ]
        scoped_anomalies = [
            a for a in anomalies
            if _in_scope((a.get("item") or a.get("item_name") or "").strip())
        ]

        narrative = data.get("narrative_results") or {}
        if isinstance(narrative, str):
            try:
                narrative = json.loads(narrative)
            except json.JSONDecodeError:
                narrative = {}
        narrative_cards: list[dict[str, Any]] = []
        for card in (narrative.get("insight_cards") or []):
            text_l = " ".join(
                [card.get("title") or "", card.get("what_changed") or "", card.get("why") or ""]
            ).lower()
            mentions_scope = scope_entity_lower in text_l
            if not mentions_scope and has_mapping:
                mentions_scope = any(child in text_l for child in children_lower)
            if mentions_scope:
                narrative_cards.append(card)

        analysis_block = data.get("analysis") or {}
        top_alerts: list[dict[str, Any]] = (
            (analysis_block.get("alert_scoring") or {}).get("top_alerts") or []
        )
        child_names_orig: set[str] = scope_children if scope_children else set()
        scoped_alerts = _filter_alerts_for_scope(top_alerts, scope_entity, child_names_orig)

        report_cards_fallback = ""
        if not narrative_cards and metric_name in reports_md:
            report_cards_fallback = _extract_scoped_cards_from_report(
                reports_md[metric_name], scope_entity_lower, children_lower, max_cards=4
            )

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
