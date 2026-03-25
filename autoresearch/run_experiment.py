"""
Run a single pipeline experiment and return the output directory.

Handles pipeline invocation, output directory discovery, and error recovery.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

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


def run_pipeline(dataset_name: str, metrics: str, timeout: int = 300) -> Optional[str]:
    """Run the data-analyst-agent pipeline and return the output directory path.

    Args:
        dataset_name: Dataset to analyze (e.g., "global_superstore")
        metrics: Comma-separated metric names (e.g., "Sales,Profit")
        timeout: Max seconds to wait for pipeline completion

    Returns:
        Path to the output directory, or None on failure.
    """
    env = os.environ.copy()
    env["ACTIVE_DATASET"] = dataset_name

    cmd = [
        sys.executable, "-m", "data_analyst_agent",
        "--dataset", dataset_name,
        "--metrics", metrics,
    ]

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
        print("Usage: python run_experiment.py <dataset_name> <metrics>")
        sys.exit(1)
    result = run_pipeline(sys.argv[1], sys.argv[2])
    print(f"Output: {result}")
