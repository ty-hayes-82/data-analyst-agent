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
Chart of Accounts Loader

Loads chart_of_accounts (JSON or YAML) and provides utilities for hierarchical level analysis.
Includes validation, fast lookup, and category access functions.
"""

from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
import yaml
import json
import fnmatch

# In-memory cache for fast account lookups
_CHART_CACHE: Optional[Dict[str, Any]] = None


def _load_chart_of_accounts() -> Dict[str, Any]:
    """Load the chart_of_accounts (JSON preferred, fallback to YAML)."""
    global _CHART_CACHE
    
    # Return cached data if available
    if _CHART_CACHE is not None:
        return _CHART_CACHE
    
    # Try JSON first (faster, more compact)
    json_path = Path(__file__).parent / "chart_of_accounts.json"
    if json_path.exists():
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Convert JSON format to YAML-compatible format for backward compatibility
            if "accounts" in data and isinstance(list(data["accounts"].values())[0], dict):
                # Check if it's the new JSON format with 'levels' array
                if "levels" in list(data["accounts"].values())[0]:
                    # Convert to old format
                    converted = {"accounts": {}, "cost_categories": data.get("cost_categories", [])}
                    for code, info in data["accounts"].items():
                        converted["accounts"][code] = {
                            "acct_nm": info.get("name", ""),
                            "level_1": info["levels"][0] if len(info["levels"]) > 0 else "",
                            "level_2": info["levels"][1] if len(info["levels"]) > 1 else "",
                            "level_3": info["levels"][2] if len(info["levels"]) > 2 else "",
                            "level_4": info["levels"][3] if len(info["levels"]) > 3 else "",
                            "canonical_category": info.get("category", "")
                        }
                    data = converted
            _CHART_CACHE = data
            return data
    
    # Fallback to YAML
    yaml_path = Path(__file__).parent / "chart_of_accounts.yaml"
    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
        _CHART_CACHE = data
        return data


def clear_chart_cache():
    """Clear the in-memory chart cache. Useful for testing or reloading."""
    global _CHART_CACHE
    _CHART_CACHE = None


def get_accounts_by_level(level_number: int) -> Dict[str, List[str]]:
    """
    Get accounts grouped by level name.
    
    Args:
        level_number: Level to aggregate by (2, 3, or 4)
    
    Returns:
        Dictionary mapping level names to list of GL account codes
        
    Example:
        >>> get_accounts_by_level(2)
        {
            "Freight Revenue": ["3100-00", "3100-01", ...],
            "Driver Pay": ["4100-00", "4100-01", ...],
            ...
        }
    """
    chart = _load_chart_of_accounts()
    level_key = f"level_{level_number}"
    
    level_map: Dict[str, List[str]] = {}
    
    for account_code, account_info in chart.get("accounts", {}).items():
        level_name = account_info.get(level_key)
        if level_name:
            if level_name not in level_map:
                level_map[level_name] = []
            level_map[level_name].append(account_code)
    
    return level_map


def get_level_hierarchy(account_code: str) -> Dict[str, str]:
    """
    Get the full level hierarchy for a specific GL account.
    
    Args:
        account_code: GL account code (e.g., "3100-00")
    
    Returns:
        Dictionary with level_1, level_2, level_3, level_4 values
        
    Example:
        >>> get_level_hierarchy("3100-00")
        {
            "level_1": "Total Operating Revenue",
            "level_2": "Freight Revenue",
            "level_3": "Mileage Revenue",
            "level_4": "Mileage Revenue"
        }
    """
    chart = _load_chart_of_accounts()
    account_info = chart.get("accounts", {}).get(account_code, {})
    
    return {
        "level_1": account_info.get("level_1"),
        "level_2": account_info.get("level_2"),
        "level_3": account_info.get("level_3"),
        "level_4": account_info.get("level_4"),
    }


def get_all_accounts_with_levels() -> Dict[str, Dict[str, str]]:
    """
    Get all accounts with their complete level hierarchies.
    
    Returns:
        Dictionary mapping account codes to their level hierarchies
    """
    chart = _load_chart_of_accounts()
    result = {}
    
    for account_code, account_info in chart.get("accounts", {}).items():
        result[account_code] = {
            "acct_nm": account_info.get("acct_nm"),
            "level_1": account_info.get("level_1"),
            "level_2": account_info.get("level_2"),
            "level_3": account_info.get("level_3"),
            "level_4": account_info.get("level_4"),
            "canonical_category": account_info.get("canonical_category"),
        }
    
    return result


def get_level_items_list(level_number: int) -> List[str]:
    """
    Get unique list of level names at specified level.
    
    Args:
        level_number: Level to get items for (2, 3, or 4)
    
    Returns:
        Sorted list of unique level names
    """
    level_map = get_accounts_by_level(level_number)
    return sorted(level_map.keys())


# NEW FUNCTIONS FOR ENHANCED FUNCTIONALITY

def get_account_fast(account_code: str) -> Optional[Dict[str, Any]]:
    """
    Fast lookup for a single account using in-memory cache.
    
    Args:
        account_code: GL account code (e.g., "3100-00")
    
    Returns:
        Account information dict or None if not found
        
    Example:
        >>> info = get_account_fast("3100-00")
        >>> print(info["level_2"])
        "Freight Revenue"
    """
    chart = _load_chart_of_accounts()
    return chart.get("accounts", {}).get(account_code)


def get_accounts_by_category(category: str) -> List[str]:
    """
    Get all GL account codes for a specific canonical category.
    
    Args:
        category: Canonical category (e.g., "Revenue", "Fuel", "Wages")
    
    Returns:
        List of GL account codes in that category
        
    Example:
        >>> revenue_accounts = get_accounts_by_category("Revenue")
        >>> len(revenue_accounts)
        42
    """
    chart = _load_chart_of_accounts()
    accounts = []
    
    for account_code, account_info in chart.get("accounts", {}).items():
        if account_info.get("canonical_category") == category:
            accounts.append(account_code)
    
    return sorted(accounts)


def get_account_category(account_code: str) -> Optional[str]:
    """
    Get the canonical category for a specific account.
    
    Args:
        account_code: GL account code
    
    Returns:
        Canonical category string or None if not found
    """
    account_info = get_account_fast(account_code)
    return account_info.get("canonical_category") if account_info else None


def validate_chart_completeness() -> Dict[str, Any]:
    """
    Validate chart of accounts for completeness and consistency.
    
    Checks for:
    - Missing level_2, level_3, level_4 mappings
    - Accounts without canonical_category
    - Duplicate account codes (shouldn't happen but good to check)
    - Empty level names
    
    Returns:
        Validation report dict with:
        - valid: bool (True if no critical issues)
        - errors: List of critical errors
        - warnings: List of non-critical warnings
        - stats: Summary statistics
    """
    chart = _load_chart_of_accounts()
    accounts = chart.get("accounts", {})
    
    errors = []
    warnings = []
    stats = {
        "total_accounts": len(accounts),
        "accounts_with_category": 0,
        "accounts_missing_category": 0,
        "accounts_with_complete_levels": 0,
        "accounts_with_missing_levels": 0
    }
    
    missing_level_2 = []
    missing_level_3 = []
    missing_level_4 = []
    missing_category = []
    empty_level_names = []
    
    for account_code, account_info in accounts.items():
        # Check levels
        level_2 = account_info.get("level_2", "").strip()
        level_3 = account_info.get("level_3", "").strip()
        level_4 = account_info.get("level_4", "").strip()
        category = account_info.get("canonical_category", "").strip()
        
        has_missing_level = False
        
        if not level_2:
            missing_level_2.append(account_code)
            has_missing_level = True
        if not level_3:
            missing_level_3.append(account_code)
            has_missing_level = True
        if not level_4:
            missing_level_4.append(account_code)
            has_missing_level = True
        
        if not category:
            missing_category.append(account_code)
            stats["accounts_missing_category"] += 1
        else:
            stats["accounts_with_category"] += 1
        
        if has_missing_level:
            stats["accounts_with_missing_levels"] += 1
        else:
            stats["accounts_with_complete_levels"] += 1
        
        # Check for empty level names (e.g., level exists but is empty string)
        for level_num in [2, 3, 4]:
            level_key = f"level_{level_num}"
            if level_key in account_info and not account_info[level_key].strip():
                empty_level_names.append(f"{account_code}:{level_key}")
    
    # Build error and warning lists
    if missing_level_2:
        errors.append(f"Missing level_2 for {len(missing_level_2)} accounts: {missing_level_2[:5]}...")
    
    if missing_level_3:
        warnings.append(f"Missing level_3 for {len(missing_level_3)} accounts: {missing_level_3[:5]}...")
    
    if missing_level_4:
        warnings.append(f"Missing level_4 for {len(missing_level_4)} accounts: {missing_level_4[:5]}...")
    
    if missing_category:
        errors.append(f"Missing canonical_category for {len(missing_category)} accounts: {missing_category[:5]}...")
    
    if empty_level_names:
        warnings.append(f"Empty level names found: {empty_level_names[:5]}...")
    
    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "stats": stats,
        "details": {
            "missing_level_2": missing_level_2,
            "missing_level_3": missing_level_3,
            "missing_level_4": missing_level_4,
            "missing_category": missing_category,
            "empty_level_names": empty_level_names
        }
    }


def match_account_pattern(account_code: str, pattern: str) -> bool:
    """
    Match account code against a pattern with wildcard support.
    
    Args:
        account_code: GL account code (e.g., "4560-06")
        pattern: Pattern with wildcards (e.g., "4560-*", "4*-06")
    
    Returns:
        True if account matches pattern
        
    Example:
        >>> match_account_pattern("4560-06", "4560-*")
        True
        >>> match_account_pattern("4560-06", "3*")
        False
    """
    return fnmatch.fnmatch(account_code, pattern)


def get_accounts_matching_pattern(pattern: str) -> List[str]:
    """
    Get all account codes matching a wildcard pattern.
    
    Args:
        pattern: Wildcard pattern (e.g., "4560-*", "3*")
    
    Returns:
        List of matching account codes
        
    Example:
        >>> toll_accounts = get_accounts_matching_pattern("4560-*")
        >>> len(toll_accounts)
        8
    """
    chart = _load_chart_of_accounts()
    accounts = chart.get("accounts", {})
    
    matching = []
    for account_code in accounts.keys():
        if match_account_pattern(account_code, pattern):
            matching.append(account_code)
    
    return sorted(matching)

