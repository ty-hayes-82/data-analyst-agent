"""Helpers for scoped executive brief digests (hierarchy lookups, filtering, alerts)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def _load_hierarchy_level_mapping(
    json_data: dict[str, dict[str, Any]],
    parent_level: int,
    child_level: int,
) -> dict[str, list[str]]:
    import csv as _csv

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

    child_col: str | None = None
    try:
        from config.dataset_resolver import get_dataset_path_optional

        contract_path = get_dataset_path_optional("contract.yaml")
        if contract_path and contract_path.exists():
            text = contract_path.read_text(encoding="utf-8")
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith(f"{child_level}:"):
                    val = stripped.split(":", 1)[-1].strip().strip("\"'")
                    if val:
                        child_col = val
                        break
    except Exception:
        pass

    data_dir = Path("data")
    if not data_dir.exists():
        return {}

    candidate_encs = [
        ("utf-16", "\t"),
        ("utf-16-le", "\t"),
        ("utf-8-sig", ","),
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
                    headers = [h.strip().lstrip("\ufeff") for h in headers]
                    parent_idx = next((i for i, h in enumerate(headers) if h == parent_col), None)
                    if parent_idx is None:
                        break
                    child_idx: int | None = None
                    if child_col:
                        child_idx = next((i for i, h in enumerate(headers) if h == child_col), None)
                    if child_idx is None:
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
                    break
            except Exception:
                continue
    return {}


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
