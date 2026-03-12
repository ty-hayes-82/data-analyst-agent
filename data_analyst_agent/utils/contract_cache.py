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
    """Load DatasetContract from YAML with automatic file-mtime-based caching.
    
    This function dramatically speeds up pipeline startup (especially for multi-target
    analyses) by caching parsed contracts. The cache automatically invalidates when
    the contract file is modified, ensuring freshness without manual cache clearing.
    
    How It Works:
        1. Resolves contract_path to absolute path
        2. Gets file modification time (mtime_ns) via os.stat()
        3. Looks up (path, mtime) in LRU cache
        4. If cache hit and mtime matches: returns cached contract (fast)
        5. If cache miss or mtime changed: parses YAML and caches (slower, first time)
    
    Performance Impact:
        - First load: ~100-200ms (YAML parsing + validation)
        - Cached loads: ~1-5ms (99% speedup)
        - Multi-target runs: 10 targets × 200ms = 2s → 10 × 5ms = 50ms
    
    Args:
        contract_path: Path to contract YAML file (str or Path).
            Accepts absolute or relative paths. Resolved to absolute internally.
    
    Returns:
        DatasetContract: Parsed and validated contract instance.
            Either from cache or freshly loaded.
    
    Raises:
        FileNotFoundError: If contract file doesn't exist
        yaml.YAMLError: If contract YAML is invalid
        ValidationError: If contract fails Pydantic validation
    
    Example:
        >>> # First call: parses YAML (~150ms)
        >>> contract = load_contract_cached("config/datasets/trade_data/contract.yaml")
        >>> print(contract.metrics[0].name)
        'revenue'
        
        >>> # Second call: from cache (~2ms)
        >>> contract2 = load_contract_cached("config/datasets/trade_data/contract.yaml")
        >>> assert contract is contract2  # Same object instance
        
        >>> # Edit contract.yaml, save
        >>> # Third call: cache invalidated, re-parses (~150ms)
        >>> contract3 = load_contract_cached("config/datasets/trade_data/contract.yaml")
        >>> assert contract3 is not contract2  # New instance
    
    Cache Details:
        - Implementation: functools.lru_cache(maxsize=32)
        - Key: (absolute_path, mtime_ns)
        - Eviction: LRU when maxsize exceeded
        - Thread-safe: Yes (via functools.lru_cache)
    
    Note:
        - Cache is in-memory (not persistent across process restarts)
        - mtime_ns precision: nanoseconds (handles sub-second edits)
        - For testing/debugging, use clear_contract_cache() to force reload
        - Use get_contract_cache_info() to inspect cache performance
    """
    path_str = str(Path(contract_path).resolve())
    
    # Get file modification time to use as cache key
    stat_result = os.stat(path_str)
    mtime_ns = stat_result.st_mtime_ns
    
    return _get_cached_contract(path_str, mtime_ns)


def clear_contract_cache():
    """Clear the contract cache, forcing next load to re-parse YAML.
    
    Use this for:
        - Testing: Ensure tests start with fresh contract state
        - Development: Force reload after contract schema changes
        - Debugging: Eliminate caching as a variable
    
    Example:
        >>> contract = load_contract_cached("contract.yaml")
        >>> # Edit contract.yaml BUT keep same mtime (unlikely but possible)
        >>> clear_contract_cache()  # Force reload
        >>> contract2 = load_contract_cached("contract.yaml")  # Re-parses
    
    Note:
        - Normally not needed (mtime-based invalidation is automatic)
        - Clears all cached contracts (affects all dataset contracts)
    """
    _get_cached_contract.cache_clear()


def get_contract_cache_info():
    """Get cache statistics for performance monitoring and debugging.
    
    Returns:
        functools._CacheInfo: Named tuple with:
            - hits: Number of cache hits (fast path)
            - misses: Number of cache misses (slow path, YAML parsing)
            - maxsize: Maximum cache size (32)
            - currsize: Current number of cached entries
    
    Example:
        >>> info = get_contract_cache_info()
        >>> print(f"Hit rate: {info.hits / (info.hits + info.misses):.1%}")
        'Hit rate: 95.2%'
        >>> print(f"Cached contracts: {info.currsize}/{info.maxsize}")
        'Cached contracts: 3/32'
    
    Note:
        - Hit rate should be >90% in normal operation
        - Low hit rate suggests frequent contract modifications or many unique contracts
        - currsize = number of unique (path, mtime) combinations cached
    """
    return _get_cached_contract.cache_info()
