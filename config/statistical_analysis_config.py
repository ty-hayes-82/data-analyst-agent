from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional, Set

import yaml

_CONFIG_CACHE: Optional[Dict[str, Any]] = None

_ADVANCED_TOOL_NAMES = {
    "seasonal_decomposition",
    "change_points",
    "mad_outliers",
    "forecast_baseline",
    "derived_metrics",
    "new_lost_same_store",
    "concentration_analysis",
    "cross_metric_correlation",
    "lagged_correlation",
    "variance_decomposition",
    "outlier_impact",
    "distribution_analysis",
    "cross_dimension_analysis",
}

_LEGACY_DEFAULT_SKIP = "seasonal_decomposition,variance_decomposition,forecast_baseline"
_CONFIG_PATH = Path(__file__).resolve().parent / "statistical_analyses.yaml"


from data_analyst_agent.utils.env_utils import parse_bool_env


def _load_yaml_config() -> Optional[Dict[str, Any]]:
    if not _CONFIG_PATH.exists():
        return None
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return raw if isinstance(raw, dict) else {}


def _legacy_skip_tools() -> Set[str]:
    raw = os.environ.get("STATISTICAL_SKIP_TOOLS", _LEGACY_DEFAULT_SKIP).strip()
    if not raw or raw.lower() == "none":
        return set()
    return {t.strip().lower() for t in raw.split(",") if t.strip()}


def _collect_tier_tool_entries(cfg: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    entries: Dict[str, Dict[str, Any]] = {}
    for tier_name in ("operational", "advanced", "academic"):
        tier_data = cfg.get(tier_name, {}) or {}
        if not isinstance(tier_data, dict):
            continue
        for item_name, item_cfg in tier_data.items():
            if not isinstance(item_cfg, dict):
                continue
            tool_name = str(item_cfg.get("tool_name", item_name)).strip().lower()
            if tool_name in _ADVANCED_TOOL_NAMES:
                entries[tool_name] = {
                    "tier": tier_name,
                    "item_name": item_name,
                    "config": item_cfg,
                }
    return entries


def _build_cache() -> Dict[str, Any]:
    cfg = _load_yaml_config()
    if not cfg:
        skip_tools = _legacy_skip_tools()
        enabled_tools = sorted(_ADVANCED_TOOL_NAMES - skip_tools)
        return {
            "source": "legacy_env",
            "profile": "legacy_env",
            "skip_tools": skip_tools,
            "enabled_tools": enabled_tools,
            "disabled_tools": sorted(skip_tools),
            "tool_options": {},
            "overrides": [],
        }

    profile_name = str(
        os.environ.get("STATISTICAL_PROFILE", cfg.get("active_profile", "lean"))
    ).strip().lower() or "lean"

    profiles = cfg.get("profiles", {}) or {}
    profile_cfg = profiles.get(profile_name) or profiles.get("lean") or {}
    enabled_tiers = profile_cfg.get("enable_tiers", []) or []
    enabled_tiers = {str(t).strip().lower() for t in enabled_tiers}

    tool_entries = _collect_tier_tool_entries(cfg)
    tool_options = {
        tool: (entry["config"].get("options", {}) or {})
        for tool, entry in tool_entries.items()
    }

    enabled_tools: Set[str] = set()
    if profile_name == "custom":
        for tool, entry in tool_entries.items():
            if bool(entry["config"].get("enabled", False)):
                enabled_tools.add(tool)
    else:
        for tool, entry in tool_entries.items():
            if entry["tier"] in enabled_tiers:
                enabled_tools.add(tool)

    overrides = []

    # Backward-compatible bridge for existing env gate.
    if parse_bool_env(os.environ.get("CROSS_DIMENSION_ANALYSIS")):
        enabled_tools.add("cross_dimension_analysis")
        overrides.append("CROSS_DIMENSION_ANALYSIS=true -> enabled cross_dimension_analysis")

    # Per-tool force overrides.
    for tool in sorted(_ADVANCED_TOOL_NAMES):
        if parse_bool_env(os.environ.get(f"STAT_ENABLE_{tool}")):
            enabled_tools.add(tool)
            overrides.append(f"STAT_ENABLE_{tool}=true")
        if parse_bool_env(os.environ.get(f"STAT_DISABLE_{tool}")):
            enabled_tools.discard(tool)
            overrides.append(f"STAT_DISABLE_{tool}=true")

    skip_tools = _ADVANCED_TOOL_NAMES - enabled_tools
    return {
        "source": "yaml",
        "profile": profile_name,
        "skip_tools": skip_tools,
        "enabled_tools": sorted(enabled_tools),
        "disabled_tools": sorted(skip_tools),
        "tool_options": tool_options,
        "overrides": overrides,
    }


def _get_cache() -> Dict[str, Any]:
    global _CONFIG_CACHE
    if _CONFIG_CACHE is None:
        _CONFIG_CACHE = _build_cache()
    return _CONFIG_CACHE


def clear_statistical_analysis_config_cache() -> None:
    global _CONFIG_CACHE
    _CONFIG_CACHE = None


def get_skip_tools() -> Set[str]:
    return set(_get_cache()["skip_tools"])


def is_tool_enabled(tool_name: str) -> bool:
    tool = str(tool_name).strip().lower()
    cache = _get_cache()
    if tool in _ADVANCED_TOOL_NAMES:
        return tool in set(cache["enabled_tools"])
    # Unknown tools default to enabled to avoid accidental suppression.
    return True


def get_tool_options(tool_name: str) -> Dict[str, Any]:
    tool = str(tool_name).strip().lower()
    cache = _get_cache()
    options = cache.get("tool_options", {}).get(tool, {})
    return options if isinstance(options, dict) else {}


def get_analysis_toggle_summary() -> Dict[str, Any]:
    cache = _get_cache()
    return {
        "source": cache.get("source"),
        "profile": cache.get("profile"),
        "enabled_tools": list(cache.get("enabled_tools", [])),
        "disabled_tools": list(cache.get("disabled_tools", [])),
        "overrides": list(cache.get("overrides", [])),
    }
