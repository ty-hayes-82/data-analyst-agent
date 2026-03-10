"""Load and parse dataset contract.yaml files."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

DATASETS_DIR = Path(__file__).resolve().parent.parent / "config" / "datasets"


def list_datasets() -> list[dict[str, Any]]:
    """Walk config/datasets/ and return metadata for every contract.yaml found."""
    results = []
    seen_names: set[str] = set()
    for root, _dirs, files in os.walk(DATASETS_DIR):
        if "contract.yaml" in files:
            rel = Path(root).relative_to(DATASETS_DIR)
            contract_path = Path(root) / "contract.yaml"
            try:
                with open(contract_path, encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                dataset_id = str(rel).replace("\\", "/")
                name = data.get("name", str(rel))
                # Deduplicate by name (handles alias/symlink layout)
                if name in seen_names:
                    continue
                seen_names.add(name)
                results.append({
                    "id": dataset_id,
                    "name": name,
                    "display_name": data.get("display_name", name),
                    "path": str(contract_path),
                })
            except Exception:
                pass
    return sorted(results, key=lambda d: d["name"])


def load_contract(dataset_id: str) -> dict[str, Any]:
    """Load a contract.yaml by dataset ID (relative path under config/datasets/)."""
    # Security: prevent path traversal
    if ".." in dataset_id or dataset_id.startswith("/") or dataset_id.startswith("\\"):
        raise FileNotFoundError(f"Invalid dataset ID: {dataset_id}")
    contract_path = (DATASETS_DIR / dataset_id / "contract.yaml").resolve()
    # Ensure resolved path is still under DATASETS_DIR
    if not str(contract_path).startswith(str(DATASETS_DIR.resolve())):
        raise FileNotFoundError(f"Invalid dataset ID: {dataset_id}")
    if not contract_path.exists():
        raise FileNotFoundError(f"No contract at {contract_path}")
    with open(contract_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    # Ensure metrics have descriptions
    for m in data.get("metrics", []):
        m.setdefault("description", m.get("name", ""))
    # Ensure hierarchies have descriptions
    for h in data.get("hierarchies", []):
        h.setdefault("description", h.get("name", ""))
    return data
