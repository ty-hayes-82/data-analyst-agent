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
Materiality Config Loader

Loads variance materiality thresholds from config/materiality_config.yaml.
Follows the same pattern as model_loader.py and ratios_config_loader.py.
"""

from pathlib import Path
from typing import Dict, Any, Optional

import yaml

_CONFIG_PATH = Path(__file__).parent / "materiality_config.yaml"
_CONFIG_CACHE: Optional[Dict[str, Any]] = None


def _load_config() -> Dict[str, Any]:
    global _CONFIG_CACHE
    if _CONFIG_CACHE is not None:
        return _CONFIG_CACHE

    if _CONFIG_PATH.exists():
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            _CONFIG_CACHE = yaml.safe_load(f) or {}
    else:
        _CONFIG_CACHE = {}

    return _CONFIG_CACHE


def get_global_defaults() -> Dict[str, Any]:
    """Return the top-level materiality thresholds.

    Returns a dict with at minimum:
        variance_pct (float)   - percentage threshold (default 5.0)
        variance_dollar (float) - absolute dollar threshold (default 50000)
    """
    cfg = _load_config()
    thresholds = cfg.get("materiality_thresholds", {})
    return {
        "variance_pct": float(thresholds.get("variance_pct", 5.0)),
        "variance_dollar": float(thresholds.get("variance_dollar", 50_000)),
        "top_categories_count": int(thresholds.get("top_categories_count", 5)),
        "cumulative_variance_pct": float(thresholds.get("cumulative_variance_pct", 80.0)),
        "min_amount": float(thresholds.get("min_amount", 10_000)),
    }


def get_thresholds_for_category(category: str) -> Dict[str, Any]:
    """Return materiality thresholds for a specific analysis category.

    Args:
        category: One of 'revenue_analysis', 'expense_analysis',
                  'operational_analysis', or any key in type_thresholds.
                  Falls back to global defaults if not found.

    Returns:
        Dict with variance_pct and variance_dollar keys.
    """
    cfg = _load_config()
    type_thresholds: Dict[str, Any] = cfg.get("type_thresholds", {})
    defaults = get_global_defaults()

    if category in type_thresholds:
        entry = type_thresholds[category]
        return {
            "variance_pct": float(entry.get("variance_pct", defaults["variance_pct"])),
            "variance_dollar": float(
                entry.get("variance_dollar", defaults["variance_dollar"])
            ),
        }

    return {
        "variance_pct": defaults["variance_pct"],
        "variance_dollar": defaults["variance_dollar"],
    }
