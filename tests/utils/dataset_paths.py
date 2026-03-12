"""Helpers for resolving dataset fixture files in tests."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DATASETS_ROOT = PROJECT_ROOT / "config" / "datasets"
FIXTURE_DATASETS_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "datasets"


def resolve_dataset_file(dataset: str, relative_path: str = "contract.yaml") -> Optional[Path]:
    """Return the first matching dataset file from config/ or test fixtures."""
    search_roots = [
        CONFIG_DATASETS_ROOT,
        CONFIG_DATASETS_ROOT / "csv",
        CONFIG_DATASETS_ROOT / "tableau",
        FIXTURE_DATASETS_ROOT,
    ]
    for root in search_roots:
        candidate = root / dataset / relative_path
        if candidate.exists():
            return candidate
    return None
