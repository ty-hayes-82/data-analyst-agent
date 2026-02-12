# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Ratios Config Loader

Loads operational metrics and P&L ratio configurations from YAML files.
Follows the same pattern as model_loader.py and materiality_loader.py.
"""

import os
from pathlib import Path
from typing import Dict, Any, Optional, List

import yaml


_OPS_CONFIG_CACHE: Optional[Dict[str, Any]] = None
_PL_CONFIG_CACHE: Optional[Dict[str, Any]] = None


def load_ops_metrics_config() -> Dict[str, Any]:
    """
    Load ops metrics ratios configuration.

    Returns:
        Dict with metric definitions, hierarchy, outlier detection settings.
    """
    global _OPS_CONFIG_CACHE

    if _OPS_CONFIG_CACHE is not None:
        return _OPS_CONFIG_CACHE

    config_path = Path(__file__).parent / "ops_metrics_ratios_config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    _OPS_CONFIG_CACHE = config
    return config


def load_pl_ratios_config() -> Dict[str, Any]:
    """
    Load P&L ratios configuration.

    Returns:
        Dict with P&L metric definitions and account classification rules.
    """
    global _PL_CONFIG_CACHE

    if _PL_CONFIG_CACHE is not None:
        return _PL_CONFIG_CACHE

    config_path = Path(__file__).parent / "pl_ratios_config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    _PL_CONFIG_CACHE = config
    return config


def get_ops_metric_def(metric_name: str) -> Optional[Dict[str, Any]]:
    """
    Get definition for a specific ops metric.

    Args:
        metric_name: Metric key (e.g., 'miles_per_truck', 'deadhead_pct')

    Returns:
        Metric definition dict or None if not found.
    """
    config = load_ops_metrics_config()
    return config.get("metrics", {}).get(metric_name)


def get_ops_metric_thresholds(metric_name: str) -> Dict[str, float]:
    """
    Get degradation thresholds for an ops metric.

    Args:
        metric_name: Metric key

    Returns:
        Dict with 'degradation_pct' and 'high_severity_pct', or defaults.
    """
    metric_def = get_ops_metric_def(metric_name)
    if metric_def and "thresholds" in metric_def:
        return metric_def["thresholds"]
    return {"degradation_pct": 5.0, "high_severity_pct": 10.0}


def get_ops_hierarchy() -> Dict[str, Optional[str]]:
    """
    Get the operational hierarchy level column mapping.

    Returns:
        Dict with level_2, level_3, level_4 column names.
    """
    config = load_ops_metrics_config()
    return config.get("hierarchy", {})


def get_outlier_config() -> Dict[str, Any]:
    """
    Get outlier detection configuration.

    Returns:
        Dict with 'method' and 'threshold'.
    """
    config = load_ops_metrics_config()
    return config.get("outlier_detection", {"method": "stdev", "threshold": 1.5})


def get_all_ops_metric_names() -> List[str]:
    """
    Get all configured ops metric names.

    Returns:
        List of metric keys.
    """
    config = load_ops_metrics_config()
    return list(config.get("metrics", {}).keys())


def get_pl_account_classification() -> Dict[str, List[str]]:
    """
    Get P&L account classification keywords.

    Returns:
        Dict with 'revenue_keywords', 'cost_keywords', 'fuel_keywords'.
    """
    config = load_pl_ratios_config()
    return config.get("account_classification", {})


def clear_ratios_config_cache():
    """Clear cached configs. Useful for testing or reloading."""
    global _OPS_CONFIG_CACHE, _PL_CONFIG_CACHE
    _OPS_CONFIG_CACHE = None
    _PL_CONFIG_CACHE = None
