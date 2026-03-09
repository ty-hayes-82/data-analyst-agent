"""
Statistical tools CPU benchmark.

Runs compute_statistical_summary with profile and per-tool toggles to measure
per-tool CPU cost. Supports isolated (one tool at a time) and incremental
(baseline + add one heavy tool) modes.

Usage:
    python scripts/benchmark_statistical_tools.py
    python scripts/benchmark_statistical_tools.py --mode incremental
    python scripts/benchmark_statistical_tools.py --mode both
    python scripts/benchmark_statistical_tools.py --metric "Truck Count"

Output:
    results/benchmark_statistical_tools/results.csv
    results/benchmark_statistical_tools/report.md
"""

import argparse
import asyncio
import csv
import io
import os
import re
import sys
from contextlib import redirect_stdout
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
RESULTS_DIR = PROJECT_ROOT / "results" / "benchmark_statistical_tools"
DATA_DIR = PROJECT_ROOT / "data"
DATASETS_DIR = PROJECT_ROOT / "config" / "datasets"

# Heaviest tools (add back in this order for incremental mode)
HEAVY_TOOLS_ORDER = [
    "forecast_baseline",
    "distribution_analysis",
    "variance_decomposition",
    "change_points",
    "seasonal_decomposition",
]
# All 12 tools
ALL_TOOLS = [
    "seasonal_decomposition",
    "change_points",
    "mad_outliers",
    "forecast_baseline",
    "derived_metrics",
    "new_lost_same_store",
    "concentration_analysis",
    "cross_metric_correlation",
    "lagged_correlation",
    "variance_decomposition",
    "outlier_impact",
    "distribution_analysis",
]

TIMER_REGEX = re.compile(r"\[StatisticalSummary\] \[TIMER\] (.+?): ([\d.]+)s")


def _setup_path():
    """Add project root to path for imports."""
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))


def _populate_cache(metric_filter: str = "LRPM", exclude_partial: bool = False):
    """Load validation data and set cache for statistical tools."""
    _setup_path()
    from data_analyst_agent.tools.validation_data_loader import load_validation_data
    from data_analyst_agent.sub_agents.data_cache import (
        set_validated_csv,
        set_analysis_context,
        clear_all_caches,
    )
    from data_analyst_agent.semantic.models import DatasetContract, AnalysisContext

    clear_all_caches()

    df = load_validation_data(
        metric_filter=metric_filter,
        exclude_partial_week=exclude_partial,
    )
    csv_str = df.to_csv(index=False)
    set_validated_csv(csv_str)

    contract_path = DATASETS_DIR / "validation_ops" / "contract.yaml"
    if not contract_path.exists():
        raise FileNotFoundError(f"Contract not found: {contract_path}")
    contract = DatasetContract.from_yaml(str(contract_path))
    setattr(contract, "_source_path", str(contract_path))
    target_metric = contract.get_metric("value")
    primary_dim = contract.get_dimension("terminal")

    ctx = AnalysisContext(
        contract=contract,
        df=df,
        target_metric=target_metric,
        primary_dimension=primary_dim,
        run_id="benchmark-statistical-tools",
        max_drill_depth=2,
    )
    set_analysis_context(ctx)
    return df


def _teardown_cache():
    """Clear caches after run."""
    _setup_path()
    from data_analyst_agent.sub_agents.data_cache import clear_all_caches
    clear_all_caches()


def _parse_timer_output(captured: str) -> dict:
    """Parse [TIMER] lines from captured stdout. Returns {name: duration_s}."""
    result = {}
    for line in captured.splitlines():
        m = TIMER_REGEX.search(line)
        if m:
            name, dur = m.group(1), float(m.group(2))
            result[name] = dur
    return result


async def _run_with_skip(skip_tools: set, metric: str):
    """
    Run compute_statistical_summary with given skip set.
    Returns (timer_dict, raw_stdout, success).
    """
    tracked_env = ["STATISTICAL_PROFILE", "STATISTICAL_SKIP_TOOLS"] + [
        f"STAT_DISABLE_{tool}" for tool in sorted(ALL_TOOLS)
    ]
    env_before = {k: os.environ.get(k) for k in tracked_env}

    # Force profile mode and disable selected tools explicitly.
    os.environ["STATISTICAL_PROFILE"] = "full"
    os.environ.pop("STATISTICAL_SKIP_TOOLS", None)
    for tool in ALL_TOOLS:
        key = f"STAT_DISABLE_{tool}"
        if tool in skip_tools:
            os.environ[key] = "true"
        else:
            os.environ.pop(key, None)

    buf = io.StringIO()
    success = True
    try:
        _populate_cache(metric_filter=metric)
        _setup_path()
        from data_analyst_agent.sub_agents.statistical_insights_agent.tools import (
            compute_statistical_summary,
        )

        with redirect_stdout(buf):
            result_str = await compute_statistical_summary()

        if "error" in result_str.lower() and '"error":' in result_str:
            success = False
    except Exception as e:
        buf.write(f"[ERROR] {e}\n")
        success = False
    finally:
        for key, value in env_before.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        _teardown_cache()

    return _parse_timer_output(buf.getvalue()), buf.getvalue(), success


def _skip_all_except(tool: str) -> set:
    """Return set of tools to skip so only the given tool runs."""
    return {t for t in ALL_TOOLS if t != tool}


def _skip_heavy_except(include_tools: list) -> set:
    """Return set of heavy tools to skip; include_tools are NOT skipped."""
    return {t for t in HEAVY_TOOLS_ORDER if t not in include_tools}


def run_isolated(metric: str) -> list[dict]:
    """Run each heavy tool in isolation. Returns CSV rows."""
    rows = []
    for tool in HEAVY_TOOLS_ORDER:
        skip = _skip_all_except(tool)
        print(f"[isolated] {tool} ...", end=" ", flush=True)
        timers, _, success = asyncio.run(_run_with_skip(skip, metric))
        total = timers.get("Advanced analysis total", 0.0)
        tool_dur = timers.get(_env_to_display(tool), 0.0)
        status = "OK" if success else "ERROR"
        print(f"total={total:.2f}s tool={tool_dur:.2f}s [{status}]")
        rows.append({
            "tool_name": tool,
            "mode": "isolated",
            "duration_s": round(total, 2),
            "tool_duration_s": round(tool_dur, 2),
            "status": status,
        })
    return rows


def run_incremental(metric: str) -> list[dict]:
    """Run baseline, then baseline + each heavy tool. Returns CSV rows."""
    rows = []

    # Baseline (default skip = 5 heaviest)
    print("[incremental] baseline (7 tools) ...", end=" ", flush=True)
    timers, _, success = asyncio.run(_run_with_skip(set(HEAVY_TOOLS_ORDER), metric))
    total = timers.get("Advanced analysis total", 0.0)
    status = "OK" if success else "ERROR"
    print(f"total={total:.2f}s [{status}]")
    rows.append({
        "tool_name": "baseline",
        "mode": "incremental",
        "duration_s": round(total, 2),
        "tool_duration_s": 0.0,
        "status": status,
    })

    # Add each heavy tool one by one
    include = []
    for tool in HEAVY_TOOLS_ORDER:
        include.append(tool)
        skip = _skip_heavy_except(include)
        print(f"[incremental] +{tool} ...", end=" ", flush=True)
        timers, _, success = asyncio.run(_run_with_skip(skip, metric))
        total = timers.get("Advanced analysis total", 0.0)
        tool_dur = timers.get(_env_to_display(tool), 0.0)
        status = "OK" if success else "ERROR"
        print(f"total={total:.2f}s tool={tool_dur:.2f}s [{status}]")
        rows.append({
            "tool_name": tool,
            "mode": "incremental",
            "duration_s": round(total, 2),
            "tool_duration_s": round(tool_dur, 2),
            "status": status,
        })
    return rows


def _env_to_display(env_name: str) -> str:
    """Map env tool name to display name in [TIMER] output."""
    m = {
        "seasonal_decomposition": "SeasonalDecomposition",
        "change_points": "ChangePoints",
        "mad_outliers": "MADOutliers",
        "forecast_baseline": "ForecastBaseline",
        "derived_metrics": "DerivedMetrics",
        "new_lost_same_store": "NewLostSameStore",
        "concentration_analysis": "ConcentrationAnalysis",
        "cross_metric_correlation": "CrossMetricCorrelation",
        "lagged_correlation": "LaggedCorrelation",
        "variance_decomposition": "VarianceDecomposition",
        "outlier_impact": "OutlierImpact",
        "distribution_analysis": "DistributionAnalysis",
    }
    return m.get(env_name, env_name.replace("_", " ").title())


def write_results(csv_rows: list[dict]):
    """Write results.csv."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / "results.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["tool_name", "mode", "duration_s", "tool_duration_s", "status"],
        )
        writer.writeheader()
        writer.writerows(csv_rows)
    print(f"\n[benchmark] CSV written: {path}")


def write_report(csv_rows: list[dict], metric: str):
    """Write report.md with CPU cost table ordered by standalone time."""
    from datetime import datetime

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / "report.md"

    # Isolated rows (standalone cost)
    isolated = [r for r in csv_rows if r["mode"] == "isolated"]
    isolated_sorted = sorted(isolated, key=lambda r: r["tool_duration_s"], reverse=True)

    lines = [
        "# Statistical Tools CPU Benchmark Report",
        "",
        f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**Metric**: {metric}",
        "",
        "## Standalone Cost (Isolated Mode)",
        "",
        "| Tool | Duration (s) | Status |",
        "|------|-------------:|--------|",
    ]
    for r in isolated_sorted:
        lines.append(f"| {r['tool_name']} | {r['tool_duration_s']:.2f} | {r['status']} |")

    # Incremental rows if present
    incremental = [r for r in csv_rows if r["mode"] == "incremental"]
    if incremental:
        lines += [
            "",
            "## Incremental Cost (Baseline + One Tool)",
            "",
            "| Step | Tool | Total (s) | Tool (s) | Status |",
            "|------|------|----------:|---------:|--------|",
        ]
        for r in incremental:
            lines.append(f"| | {r['tool_name']} | {r['duration_s']:.2f} | {r['tool_duration_s']:.2f} | {r['status']} |")

    lines += [
        "",
        "## How to Run",
        "",
        "```",
        "python scripts/benchmark_statistical_tools.py              # isolated (default)",
        "python scripts/benchmark_statistical_tools.py --mode incremental",
        "python scripts/benchmark_statistical_tools.py --mode both",
        "python scripts/benchmark_statistical_tools.py --metric \"Truck Count\"",
        "```",
        "",
    ]

    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[benchmark] Report written: {path}")


def main():
    parser = argparse.ArgumentParser(
        description="Benchmark statistical tools CPU cost (add tools back one-by-one)."
    )
    parser.add_argument(
        "--mode",
        choices=["isolated", "incremental", "both"],
        default="isolated",
        help="isolated: each heavy tool run alone; incremental: baseline + each; both: run both",
    )
    parser.add_argument(
        "--metric",
        default="LRPM",
        help="Metric for validation data (default: LRPM)",
    )
    args = parser.parse_args()

    if not (DATA_DIR / "validation_data.csv").exists():
        print(f"[benchmark] ERROR: validation_data.csv not found at {DATA_DIR}")
        sys.exit(1)

    _setup_path()

    csv_rows = []
    if args.mode in ("isolated", "both"):
        csv_rows.extend(run_isolated(args.metric))
    if args.mode in ("incremental", "both"):
        csv_rows.extend(run_incremental(args.metric))

    if csv_rows:
        write_results(csv_rows)
        write_report(csv_rows, args.metric)


if __name__ == "__main__":
    main()
