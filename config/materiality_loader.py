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
Materiality Threshold Loader

Loads materiality thresholds from config, with support for empirical thresholds.
"""

from pathlib import Path
from typing import Dict, Any, Tuple, Optional
import yaml


_THRESHOLD_CACHE: Optional[Dict[str, Any]] = None


def load_materiality_config() -> Dict[str, Any]:
    """
    Load materiality configuration with optional empirical overrides.
    
    Returns:
        Dict with materiality thresholds and per-unit thresholds
    """
    global _THRESHOLD_CACHE
    
    if _THRESHOLD_CACHE is not None:
        return _THRESHOLD_CACHE
    
    config_path = Path(__file__).parent / "materiality_config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    
    # Check if empirical thresholds are enabled
    use_empirical = config.get("use_empirical", False)
    
    if use_empirical:
        empirical_path = Path(__file__).parent / "materiality_thresholds_empirical.yaml"
        if empirical_path.exists():
            try:
                with open(empirical_path, "r", encoding="utf-8") as f:
                    empirical = yaml.safe_load(f)
                
                # Merge empirical thresholds into config
                config["empirical_overrides"] = {
                    "category_overrides": empirical.get("category_overrides", {}),
                    "gl_overrides": empirical.get("gl_overrides", {}),
                    "generation_date": empirical.get("generation_date"),
                    "data_period": empirical.get("data_period")
                }
                
                print(f"[materiality_loader] Loaded empirical thresholds from {empirical['data_period']}")
            except Exception as e:
                print(f"[materiality_loader] Warning: Could not load empirical thresholds: {e}")
                config["empirical_overrides"] = None
        else:
            print(f"[materiality_loader] Warning: use_empirical=true but {empirical_path} not found")
            config["empirical_overrides"] = None
    else:
        config["empirical_overrides"] = None
    
    _THRESHOLD_CACHE = config
    return config


def get_thresholds_for_category(category: str) -> Tuple[float, float]:
    """
    Get variance thresholds for a specific category.
    
    Args:
        category: Canonical category (e.g., "Revenue", "Fuel", "Wages")
    
    Returns:
        Tuple of (variance_pct_threshold, variance_dollar_threshold)
    """
    config = load_materiality_config()
    
    # Check for empirical category override
    empirical = config.get("empirical_overrides")
    if empirical and category in empirical.get("category_overrides", {}):
        override = empirical["category_overrides"][category]
        return (override["variance_pct"], override["variance_dollar"])
    
    # Fall back to global defaults
    thresholds = config.get("materiality_thresholds", {})
    return (thresholds.get("variance_pct", 5.0), thresholds.get("variance_dollar", 50000))


def get_thresholds_for_gl(gl_account: str, category: Optional[str] = None) -> Tuple[float, float]:
    """
    Get variance thresholds for a specific GL account.
    
    Priority order:
    1. GL-specific override
    2. Category-specific override (if category provided)
    3. Global defaults
    
    Args:
        gl_account: GL account code (e.g., "4560-06")
        category: Optional canonical category for category-level fallback
    
    Returns:
        Tuple of (variance_pct_threshold, variance_dollar_threshold)
    """
    config = load_materiality_config()
    
    # Check for GL-specific override
    empirical = config.get("empirical_overrides")
    if empirical and gl_account in empirical.get("gl_overrides", {}):
        override = empirical["gl_overrides"][gl_account]
        return (override["variance_pct"], override["variance_dollar"])
    
    # Fall back to category if provided
    if category:
        return get_thresholds_for_category(category)
    
    # Fall back to global defaults
    thresholds = config.get("materiality_thresholds", {})
    return (thresholds.get("variance_pct", 5.0), thresholds.get("variance_dollar", 50000))


def get_global_defaults() -> Dict[str, Any]:
    """Get global default thresholds."""
    config = load_materiality_config()
    return config.get("materiality_thresholds", {})


def clear_threshold_cache():
    """Clear the threshold cache. Useful for testing or reloading."""
    global _THRESHOLD_CACHE
    _THRESHOLD_CACHE = None

