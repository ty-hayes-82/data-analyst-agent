"""Dataset and metric validation for CLI parameter mode.

Validates user-supplied --dataset and --metrics flags against the actual
data available in config/datasets/ and (for validation_ops) the CSV file.
"""

import os
from pathlib import Path
from typing import Optional

import yaml

_PROJECT_ROOT = Path(__file__).parent.parent
_DATASETS_DIR = _PROJECT_ROOT / "config" / "datasets"


def list_datasets() -> list[dict]:
    """Return metadata for every dataset that has a contract.yaml."""
    results = []
    # Recursively find all folders with a contract.yaml
    for root, dirs, files in os.walk(_DATASETS_DIR):
        if "contract.yaml" in files:
            folder = Path(root)
            contract_path = folder / "contract.yaml"
            try:
                with open(contract_path, encoding="utf-8") as f:
                    contract = yaml.safe_load(f)
                results.append({
                    "name": folder.name,
                    "display_name": contract.get("display_name", folder.name),
                    "description": (contract.get("description") or "").strip().split("\n")[0],
                    "frequency": contract.get("time", {}).get("frequency", "unknown"),
                    "data_source": contract.get("data_source", {}).get("type", "unknown"),
                })
            except Exception:
                continue
    return sorted(results, key=lambda x: x["name"])


def validate_dataset(name: str) -> bool:
    """Return True if *name* corresponds to a dataset folder with a contract."""
    from config.dataset_resolver import get_dataset_dir
    try:
        dataset_dir = get_dataset_dir(name)
        return (dataset_dir / "contract.yaml").is_file()
    except Exception:
        return False


def list_metrics(dataset: str) -> list[str]:
    """Return the sorted list of available metric names for *dataset*.

    For validation_ops the metric column is read from the CSV.
    For other datasets the metric names come from the contract YAML.
    """
    if dataset == "validation_ops":
        return _list_metrics_from_csv()
    return _list_metrics_from_contract(dataset)


def validate_metrics(
    dataset: str, metrics: list[str]
) -> tuple[list[str], list[str]]:
    """Partition *metrics* into (valid, invalid) based on the dataset."""
    available = {m.strip().lower(): m for m in list_metrics(dataset)}
    valid, invalid = [], []
    for m in metrics:
        key = m.strip().lower()
        if key in available:
            valid.append(available[key])
        else:
            invalid.append(m)
    return valid, invalid


def list_dimension_values(dataset: str, dimension: str) -> list[str]:
    """Return the distinct values for *dimension* in the given dataset.

    Only implemented for validation_ops (reads the CSV). Returns an empty
    list for other datasets (values come from A2A at runtime).
    """
    if dataset != "validation_ops":
        return []
    try:
        from .tools.validation_data_loader import load_validation_data
        df = load_validation_data(exclude_partial_week=False)
        if dimension in df.columns:
            return sorted(df[dimension].dropna().unique().tolist())
    except Exception:
        pass
    return []


def validate_date(date_str: str) -> bool:
    """Return True if *date_str* is a valid YYYY-MM-DD date."""
    from datetime import datetime
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def validate_date_range(start: str, end: str) -> bool:
    """Return True if both dates are valid and start <= end."""
    if not (validate_date(start) and validate_date(end)):
        return False
    return start <= end


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _list_metrics_from_csv() -> list[str]:
    """Read metric names from the validation_data.csv file."""
    try:
        from .tools.validation_data_loader import load_validation_data
        df = load_validation_data(exclude_partial_week=False)
        if "metric" in df.columns:
            return sorted(df["metric"].dropna().unique().tolist())
    except Exception:
        pass
    return []


def _list_metrics_from_contract(dataset: str) -> list[str]:
    """Read metric names from the contract YAML."""
    from config.dataset_resolver import get_dataset_dir
    try:
        dataset_dir = get_dataset_dir(dataset)
        contract_path = dataset_dir / "contract.yaml"
        if not contract_path.is_file():
            return []
        with open(contract_path, encoding="utf-8") as f:
            contract = yaml.safe_load(f)
        return [m.get("name", "") for m in contract.get("metrics", [])]
    except Exception:
        return []
