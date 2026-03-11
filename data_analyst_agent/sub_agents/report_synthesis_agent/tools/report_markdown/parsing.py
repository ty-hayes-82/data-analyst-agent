"""Parsing helpers for markdown report generation."""

from __future__ import annotations

import json
from typing import Any, Dict, List


def _default_level_name(level_num: int) -> str:
    """Fallback label when hierarchy metadata omits level names."""
    return "Total" if level_num <= 0 else f"Level {level_num}"


def parse_json_safe(raw: Any) -> Any:
    """Parse JSON if string; otherwise return dict/list or empty dict."""
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return {}
    return raw if isinstance(raw, (dict, list)) else {}


def _convert_level_list_to_dict(val: list, level_num: int) -> dict:
    items = [d for d in val if isinstance(d, dict)]
    if not items:
        return {
            "insight_cards": [],
            "total_variance_dollar": 0,
            "level_name": _default_level_name(level_num),
        }

    first = items[0]
    if first.get("what_changed") is not None and first.get("title"):
        return {
            "insight_cards": items,
            "total_variance_dollar": sum(
                (d.get("evidence") or {}).get("variance_dollar", d.get("variance", d.get("variance_dollar", 0)))
                for d in items
            ),
            "level_name": _default_level_name(level_num),
        }

    return {
        "insight_cards": [
            {
                "title": d.get("dimension", d.get("title", d.get("name", d.get("item", "Unknown")))),
                "what_changed": f"Variance of ${d.get('variance', d.get('variance_dollar', 0)):,.0f}",
                "priority": "low",
            }
            for d in items
        ],
        "total_variance_dollar": sum(d.get("variance", d.get("variance_dollar", 0)) for d in items),
        "level_name": _default_level_name(level_num),
    }


def normalize_hierarchical_results(parsed: Any) -> Dict[str, dict]:
    """Normalize hierarchical results regardless of upstream shape."""
    if isinstance(parsed, list):
        out: Dict[str, dict] = {}
        for item in parsed:
            if not isinstance(item, dict):
                continue
            level_num = item.get("level", len(out))
            out[f"level_{level_num}"] = item
        return out

    if not isinstance(parsed, dict):
        return {}

    out: Dict[str, dict] = {}
    for key, val in parsed.items():
        if key.startswith("level_"):
            try:
                lvl = int(key.split("_")[1])
            except (IndexError, ValueError):
                continue
            parsed_val = val if isinstance(val, dict) else parse_json_safe(val)
            if isinstance(parsed_val, list):
                out[key] = _convert_level_list_to_dict(parsed_val, lvl)
            elif isinstance(parsed_val, dict):
                out[key] = parsed_val
        elif key.startswith("HIERARCHICAL_LEVEL_"):
            try:
                lvl = int(key.split("_")[-1])
                out[f"level_{lvl}"] = val if isinstance(val, dict) else parse_json_safe(val)
            except (IndexError, ValueError):
                continue
        elif key.startswith("Level "):
            try:
                lvl = int(key.split()[-1])
            except (IndexError, ValueError):
                continue
            if isinstance(val, list):
                out[f"level_{lvl}"] = _convert_level_list_to_dict(val, lvl)
            elif isinstance(val, dict):
                out[f"level_{lvl}"] = val
    return out or parsed


def collect_insight_cards(level_data: dict) -> List[dict]:
    """Return insight cards from level data regardless of format."""
    cards = [c for c in level_data.get("insight_cards", []) if isinstance(c, dict)]
    if cards:
        return cards

    fallback = []
    for driver in level_data.get("top_drivers", []) or level_data.get("top_items", []):
        if not isinstance(driver, dict):
            continue
        item = driver.get("item", "Unknown")
        var_d = driver.get("variance_dollar", 0)
        var_p = driver.get("variance_pct")
        is_new = bool(driver.get("is_new_from_zero", False))
        if is_new:
            pct_str = "new from zero"
        elif var_p is not None:
            pct_str = f"{var_p:+.1f}%"
        else:
            pct_str = "N/A"
        fallback.append(
            {
                "title": f"{item}: ${var_d:+,.0f} ({pct_str})",
                "what_changed": f"Variance of ${var_d:+,.0f} ({pct_str})",
                "why": driver.get("why", ""),
                "priority": driver.get("materiality", "LOW").lower(),
                "dimension": item,
                "evidence": {
                    "variance_dollar": var_d,
                    "variance_pct": var_p,
                    "current": driver.get("current"),
                    "prior": driver.get("prior"),
                },
            }
        )
    return fallback


__all__ = [
    "parse_json_safe",
    "normalize_hierarchical_results",
    "collect_insight_cards",
]
