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
Shared data cache for passing large CSV data between agents without bloating conversation history.

This module provides both CSV caching (legacy) and structured data caching (new).
Structured data is stored to avoid sending large datasets to LLMs.

FILE-BASED CACHE: To avoid module isolation issues in ADK (where global variables
aren't shared between agent invocations), we use file-based caching. This ensures
data persists across all agent boundaries.
"""

import os
import json
import tempfile
from pathlib import Path
from typing import Optional, Dict, Any, List

# Use a fixed temp file path for the session
_CACHE_DIR = Path(tempfile.gettempdir()) / "pl_analyst_cache"
_CSV_CACHE_FILE = _CACHE_DIR / "validated_csv.csv"
_DATA_CACHE_FILE = _CACHE_DIR / "validated_data.json"
_OPS_CACHE_FILE = _CACHE_DIR / "ops_metrics_csv.csv"

# Ensure cache directory exists
_CACHE_DIR.mkdir(exist_ok=True)

# Global cache (kept for in-memory fast access as fallback)
_validated_csv_cache: Optional[str] = None
_validated_data_cache: Optional[Dict[str, Any]] = None
_ops_metrics_csv_cache: Optional[str] = None
_analysis_context_cache: Any = None


# === Analysis Context Cache ===

def set_analysis_context(context: Any) -> None:
    """Store AnalysisContext in memory cache."""
    global _analysis_context_cache
    _analysis_context_cache = context

def get_analysis_context() -> Any:
    """Retrieve AnalysisContext from memory cache."""
    global _analysis_context_cache
    return _analysis_context_cache


# === Legacy CSV Cache (with file-based persistence) ===

def set_validated_csv(csv_data: str) -> None:
    """Store validated CSV data in both global cache and file."""
    global _validated_csv_cache
    _validated_csv_cache = csv_data

    # Also write to file for cross-agent access
    try:
        _CSV_CACHE_FILE.write_text(csv_data, encoding='utf-8')
        print(f"[data_cache] Wrote {len(csv_data)} bytes to {_CSV_CACHE_FILE}")
    except Exception as e:
        print(f"[data_cache] WARNING: Failed to write cache file: {e}")


def get_validated_csv() -> Optional[str]:
    """Retrieve validated CSV data from global cache or file."""
    global _validated_csv_cache

    # First try memory cache
    if _validated_csv_cache is not None:
        return _validated_csv_cache

    # Fall back to file cache
    try:
        if _CSV_CACHE_FILE.exists():
            csv_data = _CSV_CACHE_FILE.read_text(encoding='utf-8')
            _validated_csv_cache = csv_data  # Cache in memory too
            print(f"[data_cache] Read {len(csv_data)} bytes from {_CSV_CACHE_FILE}")
            return csv_data
    except Exception as e:
        print(f"[data_cache] WARNING: Failed to read cache file: {e}")

    return None


def clear_validated_csv() -> None:
    """Clear the validated CSV cache."""
    global _validated_csv_cache
    _validated_csv_cache = None


# === Ops Metrics CSV Cache (with file-based persistence) ===

def set_ops_metrics_csv(csv_data: str) -> None:
    """Store ops metrics CSV data in both global cache and file."""
    global _ops_metrics_csv_cache
    _ops_metrics_csv_cache = csv_data

    # Also write to file for cross-agent access
    try:
        _OPS_CACHE_FILE.write_text(csv_data, encoding='utf-8')
        print(f"[data_cache] Wrote {len(csv_data)} bytes ops metrics to {_OPS_CACHE_FILE}")
    except Exception as e:
        print(f"[data_cache] WARNING: Failed to write ops cache file: {e}")


def get_ops_metrics_csv() -> Optional[str]:
    """Retrieve ops metrics CSV data from global cache or file."""
    global _ops_metrics_csv_cache

    # First try memory cache
    if _ops_metrics_csv_cache is not None:
        return _ops_metrics_csv_cache

    # Fall back to file cache
    try:
        if _OPS_CACHE_FILE.exists():
            csv_data = _OPS_CACHE_FILE.read_text(encoding='utf-8')
            _ops_metrics_csv_cache = csv_data  # Cache in memory too
            print(f"[data_cache] Read {len(csv_data)} bytes ops metrics from {_OPS_CACHE_FILE}")
            return csv_data
    except Exception as e:
        print(f"[data_cache] WARNING: Failed to read ops cache file: {e}")

    return None


def clear_ops_metrics_csv() -> None:
    """Clear the ops metrics CSV cache."""
    global _ops_metrics_csv_cache
    _ops_metrics_csv_cache = None
    try:
        if _OPS_CACHE_FILE.exists():
            _OPS_CACHE_FILE.unlink()
    except Exception:
        pass


# === Structured Data Cache (new approach) ===

def set_validated_data(data: Dict[str, Any]) -> None:
    """
    Store validated P&L data in structured format.
    
    Args:
        data: Dictionary with keys:
            - time_series: List of records (dicts with period, gl_account, amount, etc.)
            - metadata: Optional metadata about the dataset
            - quality_flags: Optional quality flags
    
    This allows tools to access raw data without sending it to LLMs.
    """
    global _validated_data_cache
    _validated_data_cache = data


def get_validated_data() -> Optional[Dict[str, Any]]:
    """
    Retrieve validated P&L data in structured format.
    
    Returns:
        Dictionary with time_series and metadata, or None if not set
    """
    return _validated_data_cache


def get_validated_records() -> List[Dict[str, Any]]:
    """
    Retrieve just the time series records.
    
    Returns:
        List of records, or empty list if no data
    """
    if _validated_data_cache and "time_series" in _validated_data_cache:
        return _validated_data_cache["time_series"]
    return []


def get_validated_metadata() -> Dict[str, Any]:
    """
    Get metadata about the validated dataset.
    
    Returns:
        Dictionary with record counts, periods, GL accounts, etc.
    """
    if not _validated_data_cache:
        return {}
    
    time_series = _validated_data_cache.get("time_series", [])
    
    if not time_series:
        return {
            "total_records": 0,
            "gl_accounts": 0,
            "periods": [],
            "period_range": "No data"
        }
    
    periods = sorted(list(set(r.get("period") for r in time_series if r.get("period"))))
    gl_accounts = list(set(r.get("gl_account") for r in time_series if r.get("gl_account")))
    
    return {
        "total_records": len(time_series),
        "gl_accounts": len(gl_accounts),
        "gl_account_list": sorted(gl_accounts)[:10],  # First 10 for preview
        "periods": periods,
        "period_count": len(periods),
        "period_range": f"{periods[0]} to {periods[-1]}" if periods else "No data",
        "quality_flags": _validated_data_cache.get("quality_flags", {})
    }


def clear_validated_data() -> None:
    """Clear the structured validated data cache."""
    global _validated_data_cache
    _validated_data_cache = None


def clear_all_caches() -> None:
    """Clear CSV, structured data, and ops metrics caches."""
    clear_validated_csv()
    clear_validated_data()
    clear_ops_metrics_csv()

