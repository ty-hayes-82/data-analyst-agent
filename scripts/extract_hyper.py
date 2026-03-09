#!/usr/bin/env python3
"""Pre-extract all Hyper files from TDSX archives.

Run this script before starting the A2A server to eliminate cold-start delays.
Each A2A agent contains a .tdsx file (a ZIP archive). This script extracts the
embedded .hyper file from each archive and validates the connection, so the
server starts immediately when launched.

Usage:
    python scripts/extract_hyper.py
    python scripts/extract_hyper.py --agent tableau_ops_metrics_ds_agent
    python scripts/extract_hyper.py --dry-run
"""

import os
import sys
import glob
import time
import argparse
import tempfile
from pathlib import Path
from typing import List, Dict, Optional

# Add workspace root to path
script_dir = Path(__file__).parent.resolve()
workspace_root = script_dir.parent.parent
sys.path.insert(0, str(workspace_root))

import yaml

from remote_a2a.utils.tableau_shared import tdsx

try:
    from tableauhyperapi import HyperProcess, Connection, Telemetry
    HYPER_API_AVAILABLE = True
except ImportError:
    HYPER_API_AVAILABLE = False


def _find_agents(remote_a2a_root: Path, filter_agent: Optional[str] = None) -> List[Dict]:
    """Discover all A2A agents that have a config/dataset.yaml."""
    agents = []
    for config_path in sorted(remote_a2a_root.glob("*/config/dataset.yaml")):
        agent_dir = config_path.parent.parent
        agent_name = agent_dir.name
        if filter_agent and agent_name != filter_agent:
            continue
        agents.append({
            "name": agent_name,
            "dir": agent_dir,
            "config_path": config_path,
        })
    return agents


def _load_agent_config(agent: Dict) -> Optional[Dict]:
    """Load and return the dataset.yaml config for an agent."""
    try:
        with open(agent["config_path"], "r") as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"  [ERROR] Could not read config: {e}")
        return None


def _find_existing_hyper(extract_dir: Path) -> Optional[str]:
    """Return path to existing .hyper file if found, else None."""
    matches = glob.glob(os.path.join(str(extract_dir), "**", "*.hyper"), recursive=True)
    return matches[0] if matches else None


def _validate_hyper_file(hyper_path: str, dataset_name: str) -> bool:
    """Open a test connection to verify the .hyper file is valid."""
    if not HYPER_API_AVAILABLE:
        print("  [SKIP] tableauhyperapi not available -- skipping validation")
        return True
    try:
        log_dir = Path(tempfile.gettempdir()) / f"hyper_validate_{dataset_name}_{os.getpid()}"
        log_dir.mkdir(exist_ok=True)
        with HyperProcess(
            telemetry=Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU,
            parameters={"log_dir": str(log_dir)}
        ) as hyper:
            with Connection(endpoint=hyper.endpoint, database=hyper_path) as conn:
                schemas = conn.catalog.get_schema_names()
                table_count = sum(
                    len(conn.catalog.get_table_names(schema=s)) for s in schemas
                )
        print(f"  [OK] Validated: {table_count} table(s) accessible")
        return True
    except Exception as e:
        print(f"  [ERROR] Validation failed: {e}")
        return False


def extract_agent(agent: Dict, dry_run: bool = False) -> Dict:
    """Extract and validate the .hyper file for a single agent.

    Returns a result dict with keys: name, status, hyper_path, size_mb, elapsed_s, error.
    """
    result = {
        "name": agent["name"],
        "status": "unknown",
        "hyper_path": None,
        "size_mb": 0.0,
        "elapsed_s": 0.0,
        "error": None,
    }

    config = _load_agent_config(agent)
    if config is None:
        result["status"] = "config_error"
        result["error"] = "Could not read dataset.yaml"
        return result

    dataset_cfg = config.get("dataset", {})
    defaults = config.get("defaults", {})

    tdsx_relative = dataset_cfg.get("file_path", "")
    tdsx_path = agent["dir"] / tdsx_relative
    extract_dir = agent["dir"] / defaults.get("extract_dir", "temp_extracted")

    if dry_run:
        tdsx_exists = tdsx_path.exists()
        existing_hyper = _find_existing_hyper(extract_dir)
        print(f"  TDSX : {tdsx_path} ({'found' if tdsx_exists else 'MISSING'})")
        print(f"  Hyper: {existing_hyper or 'not yet extracted'}")
        result["status"] = "dry_run"
        return result

    # Check if already extracted
    existing_hyper = _find_existing_hyper(extract_dir)
    if existing_hyper:
        size_mb = os.path.getsize(existing_hyper) / (1024 * 1024)
        print(f"  [SKIP] Hyper file already extracted ({size_mb:.1f} MB): {existing_hyper}")
        valid = _validate_hyper_file(existing_hyper, dataset_cfg.get("name", agent["name"]))
        result["status"] = "already_extracted" if valid else "validation_failed"
        result["hyper_path"] = existing_hyper
        result["size_mb"] = size_mb
        if not valid:
            result["error"] = "Validation failed on existing hyper file"
        return result

    # TDSX must exist to extract
    if not tdsx_path.exists():
        msg = f"TDSX not found: {tdsx_path}"
        print(f"  [ERROR] {msg}")
        result["status"] = "tdsx_missing"
        result["error"] = msg
        return result

    # Extract
    tdsx_size_mb = os.path.getsize(tdsx_path) / (1024 * 1024)
    print(f"  Extracting {tdsx_path.name} ({tdsx_size_mb:.1f} MB) -> {extract_dir} ...")
    extract_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    try:
        hyper_path = tdsx.extract_hyper_from_tdsx(str(tdsx_path), str(extract_dir))
        elapsed = time.time() - t0
        size_mb = os.path.getsize(hyper_path) / (1024 * 1024)
        print(f"  [OK] Extracted in {elapsed:.1f}s ({size_mb:.1f} MB): {hyper_path}")
        result["hyper_path"] = hyper_path
        result["size_mb"] = size_mb
        result["elapsed_s"] = elapsed
    except Exception as e:
        elapsed = time.time() - t0
        msg = str(e)
        print(f"  [ERROR] Extraction failed after {elapsed:.1f}s: {msg}")
        result["status"] = "extraction_failed"
        result["error"] = msg
        result["elapsed_s"] = elapsed
        return result

    # Validate
    valid = _validate_hyper_file(hyper_path, dataset_cfg.get("name", agent["name"]))
    result["status"] = "extracted" if valid else "validation_failed"
    if not valid:
        result["error"] = "Hyper file extracted but failed validation"
    return result


def run_extraction(
    remote_a2a_root: Path,
    filter_agent: Optional[str] = None,
    dry_run: bool = False,
) -> List[Dict]:
    """Run extraction for all (or filtered) agents. Returns list of result dicts."""
    agents = _find_agents(remote_a2a_root, filter_agent)
    if not agents:
        print(f"[WARN] No agents found under {remote_a2a_root}")
        return []

    results = []
    for agent in agents:
        print(f"\n[Agent] {agent['name']}")
        result = extract_agent(agent, dry_run=dry_run)
        results.append(result)

    return results


def print_summary(results: List[Dict]) -> int:
    """Print a summary table and return exit code (0=all ok, 1=any failure)."""
    print("\n" + "=" * 70)
    print(f"{'Agent':<42} {'Status':<22} {'Size MB':>8} {'Time':>6}")
    print("-" * 70)
    any_failed = False
    for r in results:
        status = r["status"]
        size = f"{r['size_mb']:.1f}" if r["size_mb"] else "-"
        elapsed = f"{r['elapsed_s']:.1f}s" if r["elapsed_s"] else "-"
        print(f"{r['name']:<42} {status:<22} {size:>8} {elapsed:>6}")
        if status in ("extraction_failed", "validation_failed", "config_error", "tdsx_missing"):
            any_failed = True
            print(f"  -> {r['error']}")
    print("=" * 70)
    if any_failed:
        print("[RESULT] One or more agents failed. Check errors above.")
        return 1
    print("[RESULT] All agents ready.")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Pre-extract Hyper files from TDSX archives")
    parser.add_argument(
        "--agent", type=str, default=None,
        help="Extract only a specific agent (by directory name)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be extracted without doing it"
    )
    args = parser.parse_args()

    remote_a2a_root = workspace_root / "remote_a2a"
    if not remote_a2a_root.exists():
        print(f"[ERROR] remote_a2a directory not found: {remote_a2a_root}")
        sys.exit(1)

    print(f"Pre-extracting Hyper files from {remote_a2a_root}")
    if args.dry_run:
        print("[DRY RUN] No files will be modified.")

    results = run_extraction(remote_a2a_root, filter_agent=args.agent, dry_run=args.dry_run)
    exit_code = print_summary(results)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
