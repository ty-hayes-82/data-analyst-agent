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
Dataset Resolver
================

Provides deterministic dataset selection and path resolution.

The active dataset is configured in config/agent_config.yaml under the
`active_dataset` key. The ACTIVE_DATASET environment variable overrides
the YAML value, which is useful for CI/CD and multi-environment deployments.

Usage:
    from config.dataset_resolver import get_active_dataset, get_dataset_path

    dataset = get_active_dataset()          # e.g. "account_research"
    contract = get_dataset_path("contract.yaml")  # Path to contract YAML
"""

import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

_CONFIG_DIR = Path(__file__).parent
_AGENT_CONFIG_PATH = _CONFIG_DIR / "agent_config.yaml"
_DATASETS_DIR = _CONFIG_DIR / "datasets"

_active_dataset_cache: Optional[str] = None


def get_project_root() -> Path:
    """Return the absolute path to the project root directory (pl_analyst/)."""
    # Current file is in pl_analyst/config/dataset_resolver.py
    return _CONFIG_DIR.parent


def get_active_dataset(*, force_reload: bool = False) -> str:
    """
    Return the name of the currently configured dataset.

    Resolution order:
    1. ACTIVE_DATASET environment variable (highest priority)
    2. active_dataset value in config/agent_config.yaml
    3. Hard fallback: "account_research"

    Args:
        force_reload: If True, bypass the in-memory cache and re-read from disk.

    Returns:
        Dataset name string (e.g. "account_research", "ops_metrics", "order_dispatch").
    """
    global _active_dataset_cache

    if not force_reload and _active_dataset_cache is not None:
        return _active_dataset_cache

    env_override = os.environ.get("ACTIVE_DATASET", "").strip()
    if env_override:
        _active_dataset_cache = env_override
        return _active_dataset_cache

    if _AGENT_CONFIG_PATH.exists():
        with open(_AGENT_CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        dataset = cfg.get("active_dataset", "").strip()
        if dataset:
            _active_dataset_cache = dataset
            return _active_dataset_cache

    raise RuntimeError(
        "[dataset_resolver] FATAL: active_dataset not set in agent_config.yaml "
        "and ACTIVE_DATASET env var not set. A dataset selection is required."
    )


def get_dataset_path(filename: str) -> Path:
    """
    Resolve a file path within the active dataset's config folder.

    Args:
        filename: Filename relative to the active dataset's directory.
                  Examples: "contract.yaml", "chart_of_accounts.json", "ratios.yaml"

    Returns:
        Absolute Path to the file.

    Raises:
        FileNotFoundError: If the resolved path does not exist.
    """
    dataset = get_active_dataset()
    dataset_dir = get_dataset_dir()
    resolved = dataset_dir / filename

    if not resolved.exists():
        raise FileNotFoundError(
            f"[dataset_resolver] File '{filename}' not found for dataset '{dataset}'. "
            f"Expected: {resolved}"
        )

    return resolved


def get_dataset_path_optional(filename: str) -> Optional[Path]:
    """
    Like get_dataset_path() but returns None instead of raising if the file is missing.
    Useful for optional per-dataset configs.
    """
    try:
        return get_dataset_path(filename)
    except FileNotFoundError:
        return None


def get_dataset_dir(name: Optional[str] = None) -> Path:
    """Return the directory for the specified dataset or the active dataset.
    
    Searches in:
    1. config/datasets/<dataset>/
    2. config/datasets/tableau/<dataset>/
    3. config/datasets/csv/<dataset>/
    """
    dataset = name or get_active_dataset()
    
    # Check common locations
    search_paths = [
        _DATASETS_DIR / dataset,
        _DATASETS_DIR / "tableau" / dataset,
        _DATASETS_DIR / "csv" / dataset
    ]
    
    for path in search_paths:
        if path.exists() and path.is_dir():
            return path
            
    # Fallback to the primary location for error reporting
    return _DATASETS_DIR / dataset


def clear_dataset_cache() -> None:
    """Clear the in-memory cache. Useful for testing dataset switching."""
    global _active_dataset_cache
    _active_dataset_cache = None


def get_loader_config() -> Dict[str, Any]:
    """Return raw loader.yaml for the active dataset as a dict.

    Returns an empty dict if loader.yaml does not exist for this dataset.
    """
    loader_path = get_dataset_path_optional("loader.yaml")
    if loader_path is None:
        return {}
    with open(loader_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_hyper_loader_config():
    """Return a parsed HyperLoaderConfig for the active dataset, or None.

    Returns None if the dataset does not have a loader.yaml, or if the
    loader.yaml source type is not "tableau_hyper".
    """
    raw = get_loader_config()
    source_type = (raw.get("source") or {}).get("type", "")
    if source_type != "tableau_hyper":
        return None

    from data_analyst_agent.sub_agents.tableau_hyper_fetcher.loader_config import HyperLoaderConfig
    return HyperLoaderConfig(**raw)
