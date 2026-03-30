"""
Run a single pipeline experiment and return the output directory.

Handles pipeline invocation, output directory discovery, and error recovery.
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

PROJECT_ROOT = Path(__file__).parent.parent


def find_latest_output(dataset_name: str) -> Optional[str]:
    """Find the most recent output directory for a dataset."""
    outputs_dir = PROJECT_ROOT / "outputs" / dataset_name / "global" / "all"
    if not outputs_dir.exists():
        return None
    dirs = sorted(outputs_dir.iterdir(), key=lambda p: p.name, reverse=True)
    if dirs:
        return str(dirs[0])
    return None


def _kill_orphan_hyper_processes() -> None:
    """Kill any orphaned hyperd.exe processes that could lock .hyper files."""
    try:
        if platform.system() == "Windows":
            subprocess.run(
                ["taskkill", "/F", "/IM", "hyperd.exe"],
                capture_output=True, timeout=5,
            )
        else:
            subprocess.run(["pkill", "-f", "hyperd"], capture_output=True, timeout=5)
    except Exception:
        pass


def run_pipeline(dataset_name: str, metrics: str, timeout: int = 420,
                 extra_args: Optional[List[str]] = None) -> Optional[str]:
    """Run the data-analyst-agent pipeline and return the output directory path.

    Args:
        dataset_name: Dataset to analyze (e.g., "global_superstore")
        metrics: Comma-separated metric names (e.g., "Sales,Profit")
        timeout: Max seconds to wait for pipeline completion (default 600s / 10 min)
        extra_args: Additional CLI arguments (e.g., ["--lob", "Line Haul", "--end-date", "2026-03-14"])

    Returns:
        Path to the output directory, or None on failure.
    """
    _kill_orphan_hyper_processes()

    env = os.environ.copy()
    env["ACTIVE_DATASET"] = dataset_name
    # Skip per-metric LLM agents (narrative + report synthesis) — the hybrid
    # brief pipeline reads from metric JSON directly, not from their output.
    env.setdefault("NARRATIVE_AGENT_SKIP", "true")
    env.setdefault("REPORT_SYNTHESIS_SKIP", "true")
    # Reduce brief retries and timeout
    env.setdefault("EXECUTIVE_BRIEF_MAX_RETRIES", "1")
    env.setdefault("EXECUTIVE_BRIEF_TIMEOUT", "120")

    cmd = [
        sys.executable, "-m", "data_analyst_agent",
        "--dataset", dataset_name,
        "--metrics", metrics,
    ]
    if extra_args:
        cmd.extend(extra_args)

    print(f"[run] Executing: {' '.join(cmd)}")
    print(f"[run] ACTIVE_DATASET={dataset_name}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(PROJECT_ROOT),
            env=env,
            stdin=subprocess.DEVNULL,
        )

        if result.returncode != 0:
            # Print last 20 lines of stderr for debugging
            stderr_lines = result.stderr.strip().split("\n")
            print(f"[run] Pipeline failed (exit code {result.returncode})")
            for line in stderr_lines[-20:]:
                print(f"  {line}")
            # Still try to find output -- partial runs may produce usable results
        else:
            print("[run] Pipeline completed successfully")

    except subprocess.TimeoutExpired:
        print(f"[run] Pipeline timed out after {timeout}s")
        return None
    except Exception as exc:
        print(f"[run] Pipeline error: {exc}")
        return None

    output_dir = find_latest_output(dataset_name)
    if output_dir:
        print(f"[run] Output: {output_dir}")
    else:
        print("[run] WARNING: No output directory found")
    return output_dir


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python run_experiment.py <dataset_name> <metrics> [extra_args...]")
        sys.exit(1)
    result = run_pipeline(sys.argv[1], sys.argv[2], extra_args=sys.argv[3:] or None)
    print(f"Output: {result}")
