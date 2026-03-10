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
    for root, _dirs, files in os.walk(DATASETS_DIR):
        if "contract.yaml" in files:
            rel = Path(root).relative_to(DATASETS_DIR)
            contract_path = Path(root) / "contract.yaml"
            try:
                with open(contract_path, encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                results.append({
                    "id": str(rel).replace("\\", "/"),
                    "name": data.get("name", str(rel)),
                    "display_name": data.get("display_name", data.get("name", str(rel))),
                    "path": str(contract_path),
                })
            except Exception:
                pass
    return sorted(results, key=lambda d: d["name"])


def load_contract(dataset_id: str) -> dict[str, Any]:
    """Load a contract.yaml by dataset ID (relative path under config/datasets/)."""
    contract_path = DATASETS_DIR / dataset_id / "contract.yaml"
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
