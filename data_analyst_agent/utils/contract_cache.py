"""Contract parsing cache for faster pipeline startup."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..semantic.models import DatasetContract


@lru_cache(maxsize=32)
def _get_cached_contract(contract_path: str, mtime_ns: int) -> "DatasetContract":
    """Load and cache contract by path and file modification time.
    
    This internal function is cached by (contract_path, mtime_ns).
    When the file is modified, mtime_ns changes, creating a new cache entry.
    
    Args:
        contract_path: Absolute path to contract YAML file
        mtime_ns: File modification time in nanoseconds (from os.stat().st_mtime_ns)
    
    Returns:
        Parsed DatasetContract instance
    """
    from ..semantic.models import DatasetContract
    return DatasetContract.from_yaml(contract_path)


def load_contract_cached(contract_path: str | Path) -> "DatasetContract":
    """Load contract with caching based on file modification time.
    
    Uses an LRU cache keyed by (contract_path, file_mtime). When the contract
    file is modified, the cache automatically invalidates for that file.
    
    Args:
        contract_path: Path to contract YAML file (str or Path)
    
    Returns:
        Cached or freshly loaded DatasetContract instance
        
    Example:
        >>> contract = load_contract_cached("config/datasets/trade_data/contract.yaml")
        >>> # Second call uses cached version (if file unchanged)
        >>> contract2 = load_contract_cached("config/datasets/trade_data/contract.yaml")
    """
    path_str = str(Path(contract_path).resolve())
    
    # Get file modification time to use as cache key
    stat_result = os.stat(path_str)
    mtime_ns = stat_result.st_mtime_ns
    
    return _get_cached_contract(path_str, mtime_ns)


def clear_contract_cache():
    """Clear the contract cache. Useful for testing or forced reloads."""
    _get_cached_contract.cache_clear()


def get_contract_cache_info():
    """Get cache statistics for monitoring/debugging.
    
    Returns:
        CacheInfo namedtuple with hits, misses, maxsize, currsize
    """
    return _get_cached_contract.cache_info()
