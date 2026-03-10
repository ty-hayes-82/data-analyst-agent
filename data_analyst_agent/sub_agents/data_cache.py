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
import sys
import contextvars

# Use a registry in sys.modules to survive multiple imports of this module
_REGISTRY_KEY = "_data_analyst_cache_registry"
_REQUIRED_REGISTRY_KEYS = {
    "validated_csv",
    "analysis_context",
    "validated_data",
    "supplementary_csv",
    "session_id_var",
}

def _create_cache_registry() -> dict:
    return {
        'validated_csv': {},
        'analysis_context': {},
        'validated_data': None,
        'supplementary_csv': None,
        'session_id_var': contextvars.ContextVar("current_session_id", default=None)
    }

def _get_cache_registry() -> dict:
    registry = sys.modules.get(_REGISTRY_KEY)
    if not isinstance(registry, dict):
        registry = _create_cache_registry()
        sys.modules[_REGISTRY_KEY] = registry
    else:
        # Defensive check for required keys (tests sometimes set registry to {})
        needs_reset = False
        if not _REQUIRED_REGISTRY_KEYS.issubset(registry.keys()):
            needs_reset = True
        else:
            dict_requirements = {
                "validated_csv": dict,
                "analysis_context": dict,
            }
            for key, expected in dict_requirements.items():
                if not isinstance(registry.get(key), expected):
                    needs_reset = True
                    break
            if not isinstance(registry.get("session_id_var"), contextvars.ContextVar):
                needs_reset = True
        if needs_reset:
            registry = _create_cache_registry()
            sys.modules[_REGISTRY_KEY] = registry
    return registry

# Initialize (or rehydrate) the cache registry
sys.modules[_REGISTRY_KEY] = _get_cache_registry()
_cache_registry = sys.modules[_REGISTRY_KEY]
current_session_id = _cache_registry['session_id_var']
_validated_csv_cache = _cache_registry['validated_csv']
_analysis_context_cache = _cache_registry['analysis_context']

def _get_validated_data_cache():
    return sys.modules[_REGISTRY_KEY]['validated_data']

def _set_validated_data_cache(val):
    sys.modules[_REGISTRY_KEY]['validated_data'] = val

def _get_supplementary_csv_cache():
    return sys.modules[_REGISTRY_KEY]['supplementary_csv']

def _set_supplementary_csv_cache(val):
    sys.modules[_REGISTRY_KEY]['supplementary_csv'] = val



def _resolve_cache_dir() -> Path:
    """Determine a cache directory writable by the current user."""
    env_override = os.getenv("DATA_ANALYST_CACHE_DIR")
    if env_override:
        return Path(env_override).expanduser()

    base_tmp = Path(tempfile.gettempdir())
    suffix = "data_analyst_cache"
    try:
        uid = os.getuid()
    except AttributeError:  # Windows compatibility
        uid = None
    if uid is not None:
        suffix = f"{suffix}_{uid}"
    return base_tmp / suffix


# Use a temp path namespaced per-user to avoid permission conflicts with root-owned files
_CACHE_DIR = _resolve_cache_dir()
_CSV_CACHE_FILE = _CACHE_DIR / "primary_data_csv.csv"
_DATA_CACHE_FILE = _CACHE_DIR / "primary_data.json"
_SUPPLEMENTARY_CACHE_FILE = _CACHE_DIR / "supplementary_data_csv.csv"
_CONTEXT_CACHE_FILE = _CACHE_DIR / "analysis_context.json"

# Ensure cache directory exists
_CACHE_DIR.mkdir(parents=True, exist_ok=True)


# === Analysis Context Cache ===

def set_analysis_context(context: Any, session_id: Optional[str] = None) -> None:
    """Store AnalysisContext in memory cache and file for cross-agent access."""
    global _analysis_context_cache
    
    # If no session_id provided, try to detect from ContextVar
    if not session_id:
        session_id = current_session_id.get() or "default"
        
    _analysis_context_cache[session_id] = context
    
    # Also persist metadata to file
    try:
        if context and context.contract:
            # Use session-specific file if provided
            cache_file = _CONTEXT_CACHE_FILE
            if session_id and session_id != "default":
                cache_file = _CACHE_DIR / f"analysis_context_{session_id}.json"

            # We store the contract path and target info to reconstruct it
            metadata = {
                "contract_path": str(context.contract._source_path) if hasattr(context.contract, '_source_path') and context.contract._source_path else None,
                "target_metric_name": str(context.target_metric.name) if context.target_metric else None,
                "primary_dimension_name": str(context.primary_dimension.name) if context.primary_dimension else None,
                "max_drill_depth": getattr(context, 'max_drill_depth', 3),
                "run_id": str(getattr(context, 'run_id', "unknown")),
                "temporal_grain": getattr(context, "temporal_grain", "unknown"),
                "temporal_grain_confidence": float(getattr(context, "temporal_grain_confidence", 0.0) or 0.0),
                "detected_anchor": getattr(context, "detected_anchor", None),
                "period_end_column": getattr(context, "period_end_column", None),
            }
            cache_file.write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    except Exception as e:
        print(f"[data_cache] WARNING: Failed to persist AnalysisContext: {e}")

def get_analysis_context(session_id: Optional[str] = None) -> Any:
    """Retrieve AnalysisContext from memory cache or reconstruct from file."""
    global _analysis_context_cache
    
    # If no session_id provided, try to detect from ContextVar
    if not session_id:
        session_id = current_session_id.get() or "default"

    # 1. First try memory cache for this session
    if session_id in _analysis_context_cache:
        return _analysis_context_cache[session_id]

    # 2. Fall back to reconstructing from file
    cache_file = _CONTEXT_CACHE_FILE
    if session_id and session_id != "default":
        cache_file = _CACHE_DIR / f"analysis_context_{session_id}.json"
    
    try:
        if cache_file.exists():
            import pandas as pd
            from io import StringIO
            from ..semantic.models import DatasetContract, AnalysisContext
            
            metadata = json.loads(cache_file.read_text(encoding='utf-8'))
            
            # 1. Load Contract
            contract_path = metadata.get("contract_path")
            if not contract_path or not os.path.exists(contract_path):
                # Fallback to default if path is missing
                contract_path = os.path.join(os.getcwd(), "config", "datasets", "account_research", "contract.yaml")
            
            contract = DatasetContract.from_yaml(contract_path)
            setattr(contract, "_source_path", contract_path)
            
            # 2. Load DataFrame
            csv_data = get_validated_csv(session_id=session_id)
            if not csv_data:
                return None
            df = pd.read_csv(StringIO(csv_data))
            
            # 3. Find target metric and primary dimension
            target_metric = next((m for m in contract.metrics if m.name == metadata.get("target_metric_name")), contract.metrics[0])
            primary_dim = next((d for d in contract.dimensions if d.name == metadata.get("primary_dimension_name")), 
                              next((d for d in contract.dimensions if d.role == "primary"), contract.dimensions[0]))
            
            # 4. Reconstruct Context
            reconstructed = AnalysisContext(
                contract=contract,
                df=df,
                target_metric=target_metric,
                primary_dimension=primary_dim,
                run_id=metadata.get("run_id", "reconstructed"),
                max_drill_depth=metadata.get("max_drill_depth", 3),
                temporal_grain=metadata.get("temporal_grain", "unknown"),
                temporal_grain_confidence=metadata.get("temporal_grain_confidence", 0.0),
                detected_anchor=metadata.get("detected_anchor"),
                period_end_column=metadata.get("period_end_column"),
            )
            
            # Update memory cache for this session
            _analysis_context_cache[session_id] = reconstructed
                
            print(f"[data_cache] Reconstructed AnalysisContext from file (run_id: {reconstructed.run_id})")
            return reconstructed
    except Exception as e:
        print(f"[data_cache] ERROR: Failed to reconstruct AnalysisContext: {e}")
        return None

    return None


def resolve_data_and_columns(caller: str = "Tool") -> tuple:
    """
    Resolve DataFrame and column names from AnalysisContext.

    Returns:
        Tuple of (df, time_col, metric_col, grain_col, name_col, ctx)
        where ctx is the AnalysisContext.

    Raises:
        ValueError: If no AnalysisContext is available.
    """
    import pandas as pd
    print(f"[{caller}] Entering resolve_data_and_columns", flush=True)

    # Try to get session ID from caller if possible, but for tools it's usually via global cache
    # In parallel runs, we expect the tool to be called within a context where get_analysis_context 
    # might need a session_id. However, most tools currently don't have access to the session.
    # We fallback to the global cache which might be stomped, OR we can try to detect if we are in a parallel run.
    ctx = get_analysis_context()
    if not ctx or ctx.df is None:
        raise ValueError(f"[{caller}] AnalysisContext not found. Semantic layer is required.")

    df = ctx.df  # Pass by reference for read-only tools
    time_col = ctx.contract.time.column if ctx.contract and ctx.contract.time else "period"
    metric_col = ctx.target_metric.column if ctx.target_metric else "amount"
    grain_cols = ctx.contract.grain.columns if ctx.contract and ctx.contract.grain else []
    
    # Filter out time_col from grain_cols for tool usage
    grain_cols_filtered = [c for c in grain_cols if c != time_col]
    grain_col = grain_cols_filtered[0] if grain_cols_filtered else (grain_cols[0] if grain_cols else "item_id")
    
    # Prefer a human-readable name column if present in the data
    name_col = "item_name" if "item_name" in df.columns else grain_col
    
    print(f"[{caller}] Using AnalysisContext (metric={metric_col}, time={time_col}, grain={grain_col})")
    return df, time_col, metric_col, grain_col, name_col, ctx


# === Legacy CSV Cache (with file-based persistence) ===

def set_validated_csv(csv_data: str, session_id: Optional[str] = None) -> None:
    """Store primary data CSV in both global cache and file."""
    global _validated_csv_cache
    
    # Defensive: reinitialize if external code set this to None
    if not isinstance(_validated_csv_cache, dict):
        _validated_csv_cache = {}
    
    # If no session_id provided, try to detect from ContextVar
    if not session_id:
        session_id = current_session_id.get() or "default"
        
    _validated_csv_cache[session_id] = csv_data

    # Use session-specific file if provided
    cache_file = _CSV_CACHE_FILE
    if session_id and session_id != "default":
        cache_file = _CACHE_DIR / f"primary_data_csv_{session_id}.csv"

    # Also write to file for cross-agent access
    try:
        cache_file.write_text(csv_data, encoding='utf-8')
        print(f"[data_cache] Wrote {len(csv_data)} bytes to {cache_file}")
    except Exception as e:
        print(f"[data_cache] WARNING: Failed to write cache file: {e}")


def get_validated_csv(session_id: Optional[str] = None) -> Optional[str]:
    """Retrieve primary data CSV from global cache or file."""
    global _validated_csv_cache

    # If no session_id provided, try to detect from ContextVar
    if not session_id:
        session_id = current_session_id.get() or "default"

    # 1. First try memory cache for this session
    if session_id in _validated_csv_cache:
        return _validated_csv_cache[session_id]

    # 2. Fall back to file cache
    cache_file = _CSV_CACHE_FILE
    if session_id and session_id != "default":
        cache_file = _CACHE_DIR / f"primary_data_csv_{session_id}.csv"

    try:
        if cache_file.exists():
            csv_data = cache_file.read_text(encoding='utf-8')
            # Cache in memory too
            _validated_csv_cache[session_id] = csv_data
            print(f"[data_cache] Read {len(csv_data)} bytes from {cache_file}")
            return csv_data
    except Exception as e:
        print(f"[data_cache] WARNING: Failed to read cache file: {e}")

    return None


def clear_validated_csv() -> None:
    """Clear the primary data CSV cache."""
    global _validated_csv_cache
    _validated_csv_cache.clear()


# === Supplementary CSV Cache (with file-based persistence) ===

def set_supplementary_data_csv(csv_data: str) -> None:
    """Store supplementary CSV data in both global cache and file."""
    _set_supplementary_csv_cache(csv_data)

    # Also write to file for cross-agent access
    try:
        _SUPPLEMENTARY_CACHE_FILE.write_text(csv_data, encoding='utf-8')
        print(f"[data_cache] Wrote {len(csv_data)} bytes supplementary data to {_SUPPLEMENTARY_CACHE_FILE}")
    except Exception as e:
        print(f"[data_cache] WARNING: Failed to write supplementary cache file: {e}")


def get_supplementary_data_csv() -> Optional[str]:
    """Retrieve supplementary CSV data from global cache or file."""
    # First try memory cache
    cached = _get_supplementary_csv_cache()
    if cached is not None:
        return cached

    # Fall back to file cache
    try:
        if _SUPPLEMENTARY_CACHE_FILE.exists():
            csv_data = _SUPPLEMENTARY_CACHE_FILE.read_text(encoding='utf-8')
            _set_supplementary_csv_cache(csv_data)  # Cache in memory too
            print(f"[data_cache] Read {len(csv_data)} bytes supplementary data from {_SUPPLEMENTARY_CACHE_FILE}")
            return csv_data
    except Exception as e:
        print(f"[data_cache] WARNING: Failed to read supplementary cache file: {e}")

    return None


def clear_supplementary_data_csv() -> None:
    """Clear the supplementary CSV cache."""
    _set_supplementary_csv_cache(None)
    try:
        if _SUPPLEMENTARY_CACHE_FILE.exists():
            _SUPPLEMENTARY_CACHE_FILE.unlink()
    except Exception:
        pass


# === Structured Data Cache (new approach) ===

def set_validated_data(data: Dict[str, Any]) -> None:
    """
    Store validated data in structured format.
    
    Args:
        data: Dictionary with keys:
            - time_series: List of records
            - metadata: Optional metadata about the dataset
            - quality_flags: Optional quality flags
    """
    _set_validated_data_cache(data)


def get_validated_data() -> Optional[Dict[str, Any]]:
    """Retrieve validated data in structured format."""
    return _get_validated_data_cache()


def get_validated_records() -> List[Dict[str, Any]]:
    """Retrieve just the time series records."""
    data = _get_validated_data_cache()
    if data and "time_series" in data:
        return data["time_series"]
    return []


def get_validated_metadata() -> Dict[str, Any]:
    """Get metadata about the validated dataset."""
    data = _get_validated_data_cache()
    if not data:
        return {}
    
    time_series = data.get("time_series", [])
    
    if not time_series:
        return {
            "total_records": 0,
            "items": 0,
            "periods": [],
            "period_range": "No data"
        }
    
    periods = sorted(list(set(r.get("period") for r in time_series if r.get("period"))))
    gl_accounts = len(set(r.get("gl_account") for r in time_series if r.get("gl_account")))

    return {
        "total_records": len(time_series),
        "gl_accounts": gl_accounts,
        "periods": periods,
        "period_count": len(periods),
        "period_range": f"{periods[0]} to {periods[-1]}" if periods else "No data",
        "quality_flags": data.get("quality_flags", {})
    }


def clear_validated_data() -> None:
    """Clear the structured data cache."""
    _set_validated_data_cache(None)


def clear_all_caches() -> None:
    """Clear all caches."""
    global _analysis_context_cache, _validated_csv_cache
    # Defensive: reinitialize if external code set these to None
    if not isinstance(_validated_csv_cache, dict):
        _validated_csv_cache = {}
    else:
        _validated_csv_cache.clear()
    if not isinstance(_analysis_context_cache, dict):
        _analysis_context_cache = {}
    else:
        _analysis_context_cache.clear()
    # Re-sync the registry so future imports stay consistent
    registry = sys.modules.get(_REGISTRY_KEY)
    if isinstance(registry, dict):
        registry['validated_csv'] = _validated_csv_cache
        registry['analysis_context'] = _analysis_context_cache
    _set_validated_data_cache(None)
    _set_supplementary_csv_cache(None)
    try:
        if _CONTEXT_CACHE_FILE.exists():
            _CONTEXT_CACHE_FILE.unlink()
    except Exception:
        pass
