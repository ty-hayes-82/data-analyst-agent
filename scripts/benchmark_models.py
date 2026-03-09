"""
Benchmark harness for model selection experiments.

Runs the data_analyst_agent pipeline against a set of benchmark queries for each
experiment configuration and records per-agent timing + output artifacts.

Usage:
    python scripts/benchmark_models.py --config config/experiments/baseline.yaml
    python scripts/benchmark_models.py --config config/experiments/extractors_fast.yaml --runs 2

All runs use --validation mode (data/validation_data.csv). No A2A server required.

Output structure:
    results/<experiment_id>/
        timing.csv                  per-agent timing for all queries and runs
        stdout_q1_r1.txt            full captured stdout for each query/run
        query_1/run_1/              output artifacts copied from outputs/
        query_1/run_2/
        ...
"""

import argparse
import csv
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml

# Force line-buffered output so progress prints appear in piped/logged contexts.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(line_buffering=True)


OUTPUTS_DIR = Path("outputs")
RESULTS_ROOT = Path("results")

TIMING_PATTERN = re.compile(
    r"\[TIMER\] <<< Finished agent: (.+?) \| Duration: ([\d.]+)s"
)
TOTAL_PATTERN = re.compile(
    r"\[TIMER\] <<< Finished agent: (data_analyst_agent|target_analysis_pipeline) \| Duration: ([\d.]+)s"
)


def load_queries(queries_path: str) -> list[dict]:
    """Load benchmark queries from YAML file."""
    with open(queries_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data["queries"]


def default_queries() -> list[dict]:
    """Return hardcoded default benchmark queries if no file is provided."""
    return [
        {
            "id": "Q1",
            "label": "Single metric, single terminal",
            "text": "Analyze Truck Count trends for Albuquerque over the last 26 weeks",
        },
        {
            "id": "Q2",
            "label": "Multi-metric, single region",
            "text": "Analyze Revenue per Truck per Week and Total Miles per Truck per Week for Central region",
        },
        {
            "id": "Q3",
            "label": "Broad analysis, all terminals",
            "text": "Analyze all key operational metrics across all terminals for the last 13 weeks",
        },
    ]


def run_single(
    query_text: str,
    config_path: str,
    run_idx: int,
    query_id: str,
    output_dir: Path,
    delay_seconds: int = 10,
) -> dict:
    """Run one analysis and return timing data + stdout.

    Args:
        query_text: The analysis query string.
        config_path: Path to the agent_models YAML to use.
        run_idx: 1-based run number for logging.
        query_id: Short identifier like Q1/Q2/Q3.
        output_dir: Where to save artifacts for this run.
        delay_seconds: Seconds to wait before starting (rate-limit protection).

    Returns:
        Dict with keys: query_id, run, agent_timings (dict), total_ms, success.
    """
    if delay_seconds > 0 and run_idx > 1:
        print(f"  [benchmark] Waiting {delay_seconds}s before run {run_idx} (rate-limit protection)...")
        time.sleep(delay_seconds)

    # Clear outputs/ dir before run so we know which files belong to this run.
    if OUTPUTS_DIR.exists():
        shutil.rmtree(OUTPUTS_DIR)
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["MODEL_CONFIG_PATH"] = os.path.abspath(config_path)
    env["DATA_ANALYST_VALIDATION_CSV_MODE"] = "true"
    env["ACTIVE_DATASET"] = "validation_ops"
    # Suppress interactive prompts
    env["PYTHONUNBUFFERED"] = "1"

    cmd = [
        sys.executable, "-m", "data_analyst_agent",
        query_text,
    ]

    print(f"  [benchmark] {query_id} run {run_idx}: {query_text[:70]}...")
    wall_start = time.perf_counter()

    try:
        result = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=600,
            cwd=Path(__file__).parent.parent,
        )
        wall_end = time.perf_counter()
        wall_ms = int((wall_end - wall_start) * 1000)
        stdout = result.stdout
        stderr = result.stderr
        success = result.returncode == 0
    except subprocess.TimeoutExpired:
        wall_end = time.perf_counter()
        wall_ms = int((wall_end - wall_start) * 1000)
        stdout = ""
        stderr = "TIMEOUT after 600s"
        success = False
        print(f"  [benchmark] TIMEOUT for {query_id} run {run_idx}")

    # Save stdout/stderr
    output_dir.mkdir(parents=True, exist_ok=True)
    stdout_file = output_dir / f"stdout_{query_id}_r{run_idx}.txt"
    stdout_file.write_text(stdout + ("\n\nSTDERR:\n" + stderr if stderr.strip() else ""), encoding="utf-8")

    if not success:
        print(f"  [benchmark] FAILED {query_id} run {run_idx} (exit {result.returncode if 'result' in dir() else 'timeout'})")
        if stderr:
            print(f"    stderr tail: {stderr[-300:]}")

    # Parse per-agent timings from stdout
    agent_timings: dict[str, float] = {}
    for match in TIMING_PATTERN.finditer(stdout):
        agent_name = match.group(1).strip()
        duration_s = float(match.group(2))
        agent_timings[agent_name] = round(duration_s * 1000)

    # Copy output artifacts to results dir
    artifacts_dir = output_dir / f"{query_id}_r{run_idx}_artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    if OUTPUTS_DIR.exists():
        for f in OUTPUTS_DIR.iterdir():
            if f.is_file():
                shutil.copy2(f, artifacts_dir / f.name)

    print(f"  [benchmark] Done {query_id} run {run_idx}: {wall_ms}ms, success={success}, agents={len(agent_timings)}")

    return {
        "query_id": query_id,
        "run": run_idx,
        "agent_timings": agent_timings,
        "total_wall_ms": wall_ms,
        "success": success,
    }


def derive_experiment_id(config_path: str) -> str:
    """Derive a short experiment ID from the config filename."""
    name = Path(config_path).stem
    return name


def write_timing_csv(output_dir: Path, all_results: list[dict], queries: list[dict]) -> Path:
    """Write per-agent timing CSV."""
    csv_path = output_dir / "timing.csv"
    query_label = {q["id"]: q.get("label", q["id"]) for q in queries}

    rows = []
    for res in all_results:
        qid = res["query_id"]
        run = res["run"]
        total_ms = res["total_wall_ms"]
        for agent_name, latency_ms in res["agent_timings"].items():
            rows.append({
                "query_id": qid,
                "query_label": query_label.get(qid, qid),
                "run": run,
                "agent_name": agent_name,
                "latency_ms": latency_ms,
                "total_pipeline_ms": total_ms,
                "success": res["success"],
            })
        # Add a summary row for total
        rows.append({
            "query_id": qid,
            "query_label": query_label.get(qid, qid),
            "run": run,
            "agent_name": "_TOTAL_WALL",
            "latency_ms": total_ms,
            "total_pipeline_ms": total_ms,
            "success": res["success"],
        })

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["query_id", "query_label", "run", "agent_name", "latency_ms", "total_pipeline_ms", "success"])
        writer.writeheader()
        writer.writerows(rows)

    return csv_path


def print_summary(output_dir: Path, all_results: list[dict]) -> None:
    """Print a summary table of per-agent median timing."""
    from statistics import median

    # Group by agent
    agent_data: dict[str, list[float]] = {}
    total_data: list[float] = []

    for res in all_results:
        for agent, ms in res["agent_timings"].items():
            agent_data.setdefault(agent, []).append(ms)
        total_data.append(res["total_wall_ms"])

    print(f"\n{'='*72}")
    print(f"  BENCHMARK SUMMARY  ({output_dir.name})")
    print(f"{'='*72}")
    print(f"  {'Agent':<45} {'Median ms':>10} {'Samples':>8}")
    print(f"  {'-'*45} {'-'*10} {'-'*8}")

    sorted_agents = sorted(agent_data.items(), key=lambda x: -median(x[1]))
    for agent, values in sorted_agents:
        med = int(median(values))
        print(f"  {agent:<45} {med:>10,} {len(values):>8}")

    if total_data:
        print(f"  {'-'*45} {'-'*10} {'-'*8}")
        print(f"  {'TOTAL WALL CLOCK':<45} {int(median(total_data)):>10,} {len(total_data):>8}")

    success_count = sum(1 for r in all_results if r["success"])
    print(f"\n  Success rate: {success_count}/{len(all_results)} runs")
    print(f"{'='*72}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Benchmark data_analyst_agent model configurations."
    )
    parser.add_argument(
        "--config",
        required=True,
        help="Path to the agent_models YAML config to benchmark.",
    )
    parser.add_argument(
        "--queries",
        default=None,
        help="Path to benchmark_queries.yaml. Defaults to config/experiments/benchmark_queries.yaml.",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=3,
        help="Number of runs per query (default: 3).",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Output directory. Defaults to results/<experiment_id>/.",
    )
    parser.add_argument(
        "--delay",
        type=int,
        default=10,
        help="Seconds to wait between runs within a query (rate-limit protection, default: 10).",
    )
    args = parser.parse_args()

    # Resolve config
    config_path = os.path.abspath(args.config)
    if not os.path.exists(config_path):
        print(f"ERROR: Config not found: {config_path}")
        sys.exit(1)

    # Resolve queries
    queries_path = args.queries or os.path.join(
        os.path.dirname(__file__), "..", "config", "experiments", "benchmark_queries.yaml"
    )
    if os.path.exists(queries_path):
        queries = load_queries(queries_path)
    else:
        print(f"[benchmark] WARNING: Queries file not found at {queries_path}, using defaults.")
        queries = default_queries()

    # Resolve output dir
    experiment_id = derive_experiment_id(config_path)
    output_dir = Path(args.output_dir) if args.output_dir else RESULTS_ROOT / experiment_id
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*72}")
    print(f"  BENCHMARK START")
    print(f"  Config   : {config_path}")
    print(f"  Queries  : {len(queries)}")
    print(f"  Runs each: {args.runs}")
    print(f"  Output   : {output_dir}")
    print(f"  Started  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*72}\n")

    all_results = []

    for query in queries:
        qid = query["id"]
        query_text = query["text"]
        print(f"\n[benchmark] === Query {qid}: {query.get('label', '')} ===")

        for run_idx in range(1, args.runs + 1):
            result = run_single(
                query_text=query_text,
                config_path=config_path,
                run_idx=run_idx,
                query_id=qid,
                output_dir=output_dir,
                delay_seconds=args.delay if run_idx > 1 else 0,
            )
            all_results.append(result)

    # Write timing CSV
    csv_path = write_timing_csv(output_dir, all_results, queries)
    print(f"\n[benchmark] Timing CSV written: {csv_path}")

    # Print summary
    print_summary(output_dir, all_results)

    # Write metadata
    meta = {
        "experiment_id": experiment_id,
        "config_path": config_path,
        "runs": args.runs,
        "queries": [q["id"] for q in queries],
        "completed_at": datetime.now().isoformat(),
        "total_runs": len(all_results),
        "successful_runs": sum(1 for r in all_results if r["success"]),
    }
    meta_path = output_dir / "metadata.yaml"
    with open(meta_path, "w", encoding="utf-8") as f:
        yaml.dump(meta, f, default_flow_style=False)

    print(f"[benchmark] Metadata written: {meta_path}")
    print(f"[benchmark] All done. Results in: {output_dir}\n")


if __name__ == "__main__":
    main()
