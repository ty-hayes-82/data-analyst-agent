"""
Report Synthesis Agent benchmark (Spec 027).

Runs the report synthesis agent with a cached prompt across different model tiers
to measure latency. Requires a pre-generated cache from a full pipeline run.

Usage:
    # First run the pipeline once to generate outputs/debug/report_synthesis_cache.json
    python scripts/benchmark_report_synthesis.py

    python scripts/benchmark_report_synthesis.py --tiers fast standard advanced pro
    python scripts/benchmark_report_synthesis.py --cache outputs/debug/report_synthesis_cache.json
    python scripts/benchmark_report_synthesis.py --runs 2

Output:
    results/benchmark_report_synthesis/results.csv
    results/benchmark_report_synthesis/report.md
"""

import argparse
import asyncio
import csv
import json
import os
import sys
import time
from pathlib import Path

import yaml

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
RESULTS_DIR = PROJECT_ROOT / "results" / "benchmark_report_synthesis"
DEFAULT_CACHE = PROJECT_ROOT / "outputs" / "debug" / "report_synthesis_cache.json"
MINIMAL_CACHE = PROJECT_ROOT / "config" / "experiments" / "fixtures" / "report_synthesis_minimal_cache.json"


def _setup_path():
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))


def _setup_auth():
    try:
        from dotenv import load_dotenv
        env_path = PROJECT_ROOT / ".env"
        if env_path.exists():
            load_dotenv(env_path, override=False)
    except ImportError:
        pass
    try:
        from data_analyst_agent.config import config  # noqa: F401
    except Exception:
        pass


def load_cache(cache_path: Path) -> dict:
    with open(cache_path, encoding="utf-8") as f:
        return json.load(f)


def load_models_config() -> dict:
    config_path = PROJECT_ROOT / "config" / "agent_models.yaml"
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


async def run_benchmark(
    cache_path: Path,
    tiers_to_test: list[str],
    runs: int = 1,
    call_delay: float = 0.0,
):
    _setup_path()
    _setup_auth()

    from google.adk.agents.invocation_context import InvocationContext
    from google.adk.agents.run_config import RunConfig
    from google.adk.sessions.in_memory_session_service import InMemorySessionService

    from data_analyst_agent.sub_agents.report_synthesis_agent.agent import create_report_synthesis_agent

    if not cache_path.exists():
        print(f"[benchmark] ERROR: Cache not found: {cache_path}")
        print("Run the full pipeline once to generate the cache, or specify --cache <path>")
        sys.exit(1)

    cache = load_cache(cache_path)
    models_config = load_models_config()
    all_tiers = models_config["model_tiers"]
    try:
        cache_env = str(cache_path.relative_to(PROJECT_ROOT))
    except ValueError:
        cache_env = str(cache_path)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    csv_rows = []

    injection_len = len(cache.get("injection", ""))
    instruction_len = len(cache.get("instruction", ""))

    print(f"\n{'='*70}")
    print(f"  REPORT SYNTHESIS BENCHMARK")
    print(f"  Cache: {cache_path} ({instruction_len:,} instr + {injection_len:,} inj chars)")
    print(f"  Tiers: {tiers_to_test},  Runs each: {runs}")
    print(f"{'='*70}\n")

    session_service = InMemorySessionService()

    for tier_name in tiers_to_test:
        if tier_name not in all_tiers:
            print(f"  [skip] Unknown tier: {tier_name}")
            continue

        tier_cfg = all_tiers[tier_name]
        model = tier_cfg["model"]
        budget = tier_cfg.get("thinking_budget")
        budget_str = str(budget) if budget is not None else "default"

        print(f"\n--- Tier: {tier_name}  model={model}  budget={budget_str} ---")

        for run_idx in range(1, runs + 1):
            if call_delay > 0:
                await asyncio.sleep(call_delay)

            print(f"  Run {run_idx}...", end=" ", flush=True)

            os.environ["REPORT_SYNTHESIS_USE_PROMPT_CACHE"] = cache_env
            try:
                agent = create_report_synthesis_agent(model=model, thinking_budget=budget)
                # Verify model routing
                inner = getattr(agent, "wrapped_agent", agent)
                actual_model = getattr(inner, "model", "?")
                if run_idx == 1 and actual_model != model:
                    print(f" WARNING: expected model={model} but got {actual_model}", flush=True)
                session = await session_service.create_session(app_name="pl_analyst", user_id="benchmark")
                ctx = InvocationContext(
                    agent=agent,
                    session=session,
                    session_service=session_service,
                    invocation_id=f"bench_{tier_name}_{run_idx}",
                    run_config=RunConfig(),
                )

                start = time.perf_counter()
                event_count = 0
                has_report = False
                report_md = ""
                status = "ok"
                try:
                    async for event in agent.run_async(ctx):
                        event_count += 1
                        if event.content and event.content.parts:
                            for part in event.content.parts:
                                if getattr(part, "function_response", None):
                                    resp = getattr(part.function_response, "response", None)
                                    if resp is not None:
                                        if isinstance(resp, dict):
                                            report_md = str(resp.get("result", resp.get("text", str(resp))))
                                        else:
                                            report_md = str(resp)
                                        has_report = bool(report_md.strip())
                except asyncio.TimeoutError:
                    status = "timeout"
                except Exception as e:
                    status = f"error:{type(e).__name__}"

                latency_ms = round((time.perf_counter() - start) * 1000)

                # Save report for quality comparison (first run per tier)
                report_chars = len(report_md)
                if run_idx == 1 and report_md:
                    out_path = RESULTS_DIR / f"{tier_name}_report.md"
                    out_path.write_text(report_md, encoding="utf-8")
                    print(f"{latency_ms}ms [{status}] events={event_count} report={report_chars} chars -> {out_path.name}")
                elif status == "ok":
                    print(f"{latency_ms}ms [{status}] events={event_count} report={report_chars} chars")
                else:
                    print(f"{latency_ms}ms [{status}]")

                csv_rows.append({
                    "tier": tier_name,
                    "model": model,
                    "thinking_budget": budget_str,
                    "run": run_idx,
                    "latency_ms": latency_ms,
                    "event_count": event_count,
                    "has_report": has_report,
                    "report_chars": report_chars,
                    "status": status,
                })
            finally:
                os.environ.pop("REPORT_SYNTHESIS_USE_PROMPT_CACHE", None)

    _write_csv(csv_rows)
    _write_report(csv_rows, tiers_to_test)
    _print_summary(csv_rows, tiers_to_test)


def _write_csv(rows: list[dict]):
    csv_path = RESULTS_DIR / "results.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["tier", "model", "thinking_budget", "run", "latency_ms", "event_count", "has_report", "report_chars", "status"],
        )
        writer.writeheader()
        writer.writerows(rows)
    print(f"\n[benchmark] CSV written: {csv_path}")


def _write_report(rows: list[dict], tiers: list[str]):
    from statistics import median
    from datetime import datetime

    lines = [
        "# Report Synthesis Benchmark Report",
        "",
        f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**Cache**: outputs/debug/report_synthesis_cache.json",
        "",
        "## Summary",
        "",
        "| Tier | Budget | Median ms | Report chars | Pass |",
        "|------|--------|----------:|-------------:|------|",
    ]

    for tier in tiers:
        tier_rows = [r for r in rows if r["tier"] == tier]
        if not tier_rows:
            continue
        budget = tier_rows[0].get("thinking_budget", "default")
        latencies = [r["latency_ms"] for r in tier_rows if r["status"] == "ok"]
        med = int(median(latencies)) if latencies else 0
        avg_chars = sum(r.get("report_chars", 0) for r in tier_rows) / len(tier_rows)
        pass_rate = sum(1 for r in tier_rows if r["status"] == "ok") / len(tier_rows)
        lines.append(f"| {tier} | {budget} | {med:,} | {int(avg_chars):,} | {pass_rate:.0%} |")

    lines += [
        "",
        "## Output files",
        "",
        "Each tier's first-run report is saved as `{tier}_report.md` for quality comparison.",
    ]
    path = RESULTS_DIR / "report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[benchmark] Report written: {path}")


def _print_summary(rows: list[dict], tiers: list[str]):
    from statistics import median

    print(f"\n{'='*70}")
    print(f"  REPORT SYNTHESIS BENCHMARK SUMMARY")
    print(f"{'='*70}")
    print(f"  {'Tier':<12} {'Budget':>8} {'Median ms':>10} {'Report chars':>12} {'Pass'}")
    print(f"  {'-'*12} {'-'*8} {'-'*10} {'-'*12} {'-'*6}")

    for tier in tiers:
        tier_rows = [r for r in rows if r["tier"] == tier]
        if not tier_rows:
            continue
        budget = tier_rows[0].get("thinking_budget", "default")
        ok_rows = [r for r in tier_rows if r["status"] == "ok"]
        latencies = [r["latency_ms"] for r in ok_rows]
        med = int(median(latencies)) if latencies else 0
        avg_chars = sum(r.get("report_chars", 0) for r in tier_rows) / len(tier_rows)
        pass_rate = sum(1 for r in tier_rows if r["status"] == "ok") / len(tier_rows)
        print(f"  {tier:<12} {str(budget):>8} {med:>10,} {int(avg_chars):>12,} {pass_rate:.0%}")

    print(f"{'='*70}\n")


def main():
    parser = argparse.ArgumentParser(description="Benchmark report synthesis agent across model tiers.")
    parser.add_argument(
        "--cache",
        type=Path,
        default=None,
        help="Path to cache JSON (default: outputs/debug/report_synthesis_cache.json)",
    )
    parser.add_argument(
        "--minimal",
        action="store_true",
        help="Use minimal cache for baseline speed test (~500 chars vs ~4K)",
    )
    parser.add_argument(
        "--compare-3",
        action="store_true",
        help="Quick 3-way comparison: flash_2_5, standard, pro (2.5-flash vs 3-flash vs 3.1-pro)",
    )
    parser.add_argument(
        "--tiers",
        nargs="+",
        default=["lite", "ultra", "flash_2_5", "flash_2_5_thinking", "standard", "fast", "advanced", "pro"],
        help="Tiers to test (default includes flash_2_5 with/without thinking)",
    )
    parser.add_argument("--runs", type=int, default=1, help="Runs per tier (default: 1)")
    parser.add_argument(
        "--call-delay",
        type=float,
        default=0.0,
        help="Seconds between API calls. Default 0 (Vertex AI). Use 13 for free-tier API key.",
    )
    args = parser.parse_args()

    tiers_to_test = ["flash_2_5", "standard", "pro"] if args.compare_3 else args.tiers

    if args.minimal:
        cache_path = MINIMAL_CACHE
    elif args.cache:
        cache_path = args.cache
        if not cache_path.is_absolute():
            cache_path = PROJECT_ROOT / cache_path
    else:
        cache_path = DEFAULT_CACHE

    asyncio.run(run_benchmark(cache_path, tiers_to_test, args.runs, args.call_delay))


if __name__ == "__main__":
    main()
