"""Interactive terminal menus for dataset / metric / dimension selection.

Called when the user passes ``--interactive`` on the CLI.  All output goes
to stderr so that stdout remains clean for pipeline output.
"""

import sys
from typing import Optional

from config.dataset_resolver import get_dataset_dir
from data_analyst_agent.semantic.models import DatasetContract

from .cli_validator import (
    list_datasets,
    list_dimension_values,
    list_metrics,
)


def _prompt(msg: str) -> str:
    """Print *msg* to stderr, read from stdin."""
    sys.stderr.write(msg)
    sys.stderr.flush()
    return input()


def _check_tty() -> None:
    if not sys.stdin.isatty():
        sys.stderr.write(
            "ERROR: --interactive requires a terminal (stdin is not a TTY).\n"
        )
        sys.exit(1)


def _dimension_choices_for_dataset(dataset: str) -> list[str]:
    try:
        contract_path = get_dataset_dir(dataset) / "contract.yaml"
        if not contract_path.is_file():
            return []
        contract = DatasetContract.from_yaml(str(contract_path))
    except Exception:
        return []

    return [d.name for d in contract.dimensions if d.role in ("primary", "secondary")]


def select_dataset() -> str:
    datasets = list_datasets()
    if not datasets:
        sys.stderr.write("ERROR: No datasets found in config/datasets/.\n")
        sys.exit(1)

    sys.stderr.write("\nAvailable datasets:\n")
    for i, ds in enumerate(datasets, 1):
        tag = f"[{ds['data_source']}]" if ds["data_source"] else ""
        sys.stderr.write(f"  {i}. {ds['name']:<20} {ds['display_name']} ({ds['frequency']}) {tag}\n")

    while True:
        choice = _prompt(f"Select dataset [1-{len(datasets)}]: ").strip()
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(datasets):
                return datasets[idx]["name"]
        except ValueError:
            for ds in datasets:
                if choice.lower() == ds["name"].lower():
                    return ds["name"]
        sys.stderr.write("  Invalid choice. Try again.\n")


def select_metrics(dataset: str) -> list[str]:
    metrics = list_metrics(dataset)
    if not metrics:
        sys.stderr.write(f"WARNING: No metrics found for {dataset}. Proceeding without filter.\n")
        return []

    sys.stderr.write(f"\nAvailable metrics ({len(metrics)}):\n")
    for i, m in enumerate(metrics, 1):
        sys.stderr.write(f"  {i:>3}. {m}\n")
    sys.stderr.write(f"  {'all':>3}. (All metrics)\n")

    while True:
        choice = _prompt("Select metrics (comma-separated numbers, or 'all'): ").strip()
        if choice.lower() == "all":
            return []

        try:
            indices = [int(x.strip()) - 1 for x in choice.split(",")]
            selected = [metrics[i] for i in indices if 0 <= i < len(metrics)]
            if selected:
                return selected
        except (ValueError, IndexError):
            pass
        sys.stderr.write("  Invalid selection. Enter numbers separated by commas.\n")


def select_dimension(dataset: str) -> tuple[Optional[str], Optional[str]]:
    """Return (dimension_name, dimension_value) or (None, None)."""
    dim_options = _dimension_choices_for_dataset(dataset)
    if not dim_options:
        sys.stderr.write("\nNo contract-defined dimensions available. Analyzing full dataset.\n")
        return None, None

    sys.stderr.write("\nDimension filter:\n")
    for i, d in enumerate(dim_options, 1):
        sys.stderr.write(f"  {i}. {d}\n")
    sys.stderr.write(f"  {len(dim_options)+1}. (none - analyze all)\n")

    choice = _prompt(f"Select [1-{len(dim_options)+1}]: " ).strip()
    try:
        idx = int(choice) - 1
    except ValueError:
        return None, None

    if idx == len(dim_options):
        return None, None
    if 0 <= idx < len(dim_options):
        dim = dim_options[idx]
    else:
        return None, None

    values = list_dimension_values(dataset, dim)
    if values:
        sys.stderr.write(f"\n{dim.title()} values: {', '.join(values)}\n")

    val = _prompt(f"Enter {dim} value (or Enter for all): " ).strip()
    if not val:
        return dim, None
    return dim, val



def select_date_range() -> tuple[Optional[str], Optional[str]]:
    sys.stderr.write("\nDate range (YYYY-MM-DD format):\n")
    start = _prompt("  Start date (Enter for default): ").strip() or None
    end = _prompt("  End date (Enter for default): ").strip() or None
    return start, end


def run_interactive() -> dict:
    """Run the full interactive selection flow. Returns a dict of parameters."""
    _check_tty()

    sys.stderr.write("\n" + "=" * 60 + "\n")
    sys.stderr.write("  Data Analyst Agent - Interactive Mode\n")
    sys.stderr.write("=" * 60 + "\n")

    dataset = select_dataset()
    metrics = select_metrics(dataset)
    dim, dim_val = select_dimension(dataset)
    start_date, end_date = select_date_range()

    result = {"dataset": dataset}
    if metrics:
        result["metrics"] = metrics
    if dim:
        result["dimension"] = dim
    if dim_val:
        result["dimension_value"] = dim_val
    if start_date:
        result["start_date"] = start_date
    if end_date:
        result["end_date"] = end_date

    sys.stderr.write(f"\n{'='*60}\n")
    sys.stderr.write(f"  Dataset   : {dataset}\n")
    sys.stderr.write(f"  Metrics   : {', '.join(metrics) if metrics else '(all)'}\n")
    sys.stderr.write(f"  Dimension : {dim or '(none)'}{'=' + dim_val if dim_val else ''}\n")
    sys.stderr.write(f"  Dates     : {start_date or '(default)'} to {end_date or '(default)'}\n")
    sys.stderr.write(f"{'='*60}\n\n")

    confirm = _prompt("Start analysis? [Y/n]: ").strip().lower()
    if confirm and confirm != "y":
        sys.stderr.write("Cancelled.\n")
        sys.exit(0)

    return result
