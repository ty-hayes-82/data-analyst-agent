"""
Pre-summarization benchmark for Report Synthesis Agent (Spec 027).

Compares report synthesis latency with vs without pre-summarization.
Pre-summarization sends each of 5 prompt components through a fast LLM before
the main synthesis, reducing injection size (~22K -> ~2.5K chars) at the cost
of 5 extra LLM calls.

Usage:
    # First run the pipeline once to generate outputs/debug/report_synthesis_cache.json
    python -m data_analyst_agent --dataset validation_ops --metrics "Truck Count"

    python scripts/benchmark_presummarize.py
    python scripts/benchmark_presummarize.py --cache outputs/debug/report_synthesis_cache.json
    python scripts/benchmark_presummarize.py --runs 2 --summarizer-model gemini-3-flash-preview

Output:
    results/benchmark_presummarize/results.csv
    results/benchmark_presummarize/report.md
"""

import argparse
import asyncio
import csv
import json
import os
import sys
import tempfile
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
RESULTS_DIR = PROJECT_ROOT / "results" / "benchmark_presummarize"
DEFAULT_CACHE = PROJECT_ROOT / "outputs" / "debug" / "report_synthesis_cache.json"

_INJECTION_TEMPLATE = (
    "Here are the results from the specialized analysis agents:\n\n"
    "NARRATIVE_RESULTS:\n{narrative_results}\n\n"
    "DATA_ANALYST_RESULT (Statistical Insight Cards):\n{data_analyst_result}\n\n"
    "HIERARCHICAL_ANALYSIS:\n{hierarchical_text}\n\n"
    "ALERT_SCORING_RESULT:\n{alert_scoring_result}\n\n"
    "STATISTICAL_SUMMARY (Full Data Context):\n{statistical_summary}\n\n"
    "Please synthesize these into the final executive report. You MUST use the generate_markdown_report tool "
    "to produce the final report. Pass hierarchical_results as a JSON object with level_0, level_1 keys "
    "(from HIERARCHICAL_ANALYSIS). Do NOT output the report text directly."
)


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


async def run_baseline(
    cache: dict,
    cache_path: Path,
    runs: int,
) -> list[dict]:
    """Run report synthesis with full injection (no pre-summarization)."""
    _setup_path()
    _setup_auth()

    from google.adk.agents.invocation_context import InvocationContext
    from google.adk.agents.run_config import RunConfig
    from google.adk.sessions.in_memory_session_service import InMemorySessionService

    from data_analyst_agent.sub_agents.report_synthesis_agent.agent import create_report_synthesis_agent

    try:
        cache_env = str(cache_path.relative_to(PROJECT_ROOT))
    except ValueError:
        cache_env = str(cache_path)

    session_service = InMemorySessionService()
    agent = create_report_synthesis_agent()
    rows = []

    for run_idx in range(1, runs + 1):
        print(f"  Baseline run {run_idx}...", end=" ", flush=True)
        os.environ["REPORT_SYNTHESIS_USE_PROMPT_CACHE"] = cache_env

        try:
            session = await session_service.create_session(app_name="pl_analyst", user_id="benchmark")
            ctx = InvocationContext(
                agent=agent,
                session=session,
                session_service=session_service,
                invocation_id=f"bench_baseline_{run_idx}",
                run_config=RunConfig(),
            )

            start = time.perf_counter()
            status = "ok"
            report_chars = 0
            try:
                async for event in agent.run_async(ctx):
                    if event.content and event.content.parts:
                        for part in event.content.parts:
                            if getattr(part, "function_response", None):
                                resp = getattr(part.function_response, "response", None)
                                if resp is not None:
                                    if isinstance(resp, dict):
                                        md = str(resp.get("result", resp.get("text", str(resp))))
                                    else:
                                        md = str(resp)
                                    report_chars = len(md) if md.strip() else 0
            except asyncio.TimeoutError:
                status = "timeout"
            except Exception as e:
                status = f"error:{type(e).__name__}"

            latency_ms = round((time.perf_counter() - start) * 1000)
            print(f"{latency_ms}ms [{status}] {report_chars} chars")
            rows.append({
                "mode": "baseline",
                "run": run_idx,
                "latency_ms": latency_ms,
                "presummarize_ms": 0,
                "synthesis_ms": latency_ms,
                "injection_chars": len(cache.get("injection", "")),
                "report_chars": report_chars,
                "status": status,
            })
        finally:
            os.environ.pop("REPORT_SYNTHESIS_USE_PROMPT_CACHE", None)

    return rows


async def run_presummarize(
    cache: dict,
    runs: int,
    summarizer_model: str,
) -> list[dict]:
    """Run pre-summarization + report synthesis."""
    _setup_path()
    _setup_auth()

    from google.adk.agents.invocation_context import InvocationContext
    from google.adk.agents.run_config import RunConfig
    from google.adk.sessions.in_memory_session_service import InMemorySessionService

    from data_analyst_agent.sub_agents.report_synthesis_agent.agent import create_report_synthesis_agent
    from data_analyst_agent.sub_agents.report_synthesis_agent.pre_summarize import summarize_components

    components = cache.get("components", {})
    if not components:
        print("[benchmark] ERROR: Cache has no 'components' key. Run full pipeline to generate cache.")
        return []

    session_service = InMemorySessionService()
    agent = create_report_synthesis_agent()
    rows = []

    for run_idx in range(1, runs + 1):
        print(f"  Pre-summarize run {run_idx}...", end=" ", flush=True)

        t0 = time.perf_counter()
        summarized = await summarize_components(components, model=summarizer_model)
        presummarize_ms = round((time.perf_counter() - t0) * 1000)

        injection_message = _INJECTION_TEMPLATE.format(**summarized)
        injection_len = len(injection_message)

        temp_cache = {
            "instruction": cache["instruction"],
            "injection": injection_message,
        }

        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            delete=False,
        ) as f:
            json.dump(temp_cache, f, indent=2)
            temp_path = f.name

        try:
            os.environ["REPORT_SYNTHESIS_USE_PROMPT_CACHE"] = temp_path

            session = await session_service.create_session(app_name="pl_analyst", user_id="benchmark")
            ctx = InvocationContext(
                agent=agent,
                session=session,
                session_service=session_service,
                invocation_id=f"bench_presummarize_{run_idx}",
                run_config=RunConfig(),
            )

            t1 = time.perf_counter()
            status = "ok"
            report_chars = 0
            try:
                async for event in agent.run_async(ctx):
                    if event.content and event.content.parts:
                        for part in event.content.parts:
                            if getattr(part, "function_response", None):
                                resp = getattr(part.function_response, "response", None)
                                if resp is not None:
                                    if isinstance(resp, dict):
                                        md = str(resp.get("result", resp.get("text", str(resp))))
                                    else:
                                        md = str(resp)
                                    report_chars = len(md) if md.strip() else 0
            except asyncio.TimeoutError:
                status = "timeout"
            except Exception as e:
                status = f"error:{type(e).__name__}"

            synthesis_ms = round((time.perf_counter() - t1) * 1000)
            total_ms = presummarize_ms + synthesis_ms
            print(f"{total_ms}ms (pre={presummarize_ms}, syn={synthesis_ms}) [{status}] {report_chars} chars")
            rows.append({
                "mode": "presummarize",
                "run": run_idx,
                "latency_ms": total_ms,
                "presummarize_ms": presummarize_ms,
                "synthesis_ms": synthesis_ms,
                "injection_chars": injection_len,
                "report_chars": report_chars,
                "status": status,
            })
        finally:
            os.environ.pop("REPORT_SYNTHESIS_USE_PROMPT_CACHE", None)
            Path(temp_path).unlink(missing_ok=True)

    return rows


def _write_csv(rows: list[dict]):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = RESULTS_DIR / "results.csv"
    fieldnames = ["mode", "run", "latency_ms", "presummarize_ms", "synthesis_ms", "injection_chars", "report_chars", "status"]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"\n[benchmark] CSV written: {csv_path}")


def _write_report(rows: list[dict], baseline_chars: int, presummarize_chars: int):
    from statistics import median
    from datetime import datetime

    baseline_rows = [r for r in rows if r["mode"] == "baseline" and r["status"] == "ok"]
    presummarize_rows = [r for r in rows if r["mode"] == "presummarize" and r["status"] == "ok"]

    baseline_med = int(median([r["latency_ms"] for r in baseline_rows])) if baseline_rows else 0
    presummarize_med = int(median([r["latency_ms"] for r in presummarize_rows])) if presummarize_rows else 0

    diff_pct = ((presummarize_med - baseline_med) / baseline_med * 100) if baseline_med else 0
    faster = "faster" if presummarize_med < baseline_med else "slower"

    lines = [
        "# Pre-Summarization Benchmark Report",
        "",
        f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**Cache**: outputs/debug/report_synthesis_cache.json",
        "",
        "## Summary",
        "",
        "| Mode | Median latency | Injection chars |",
        "|------|----------------|----------------|",
        f"| Baseline (full) | {baseline_med:,} ms | {baseline_chars:,} |",
        f"| Pre-summarize | {presummarize_med:,} ms | {presummarize_chars:,} |",
        "",
        f"**Result**: Pre-summarize is {abs(diff_pct):.1f}% {faster} than baseline.",
        "",
        "## Recommendation",
        "",
    ]
    if presummarize_med < baseline_med:
        lines.append("Enable pre-summarization: `REPORT_SYNTHESIS_PRE_SUMMARIZE=1`")
    else:
        lines.append("Keep baseline (no pre-summarization) — pre-summarize adds latency.")

    lines.append("")
    path = RESULTS_DIR / "report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[benchmark] Report written: {path}")


async def main_async(cache_path: Path, runs: int, summarizer_model: str):
    if not cache_path.exists():
        print(f"[benchmark] ERROR: Cache not found: {cache_path}")
        print("Run the full pipeline once to generate the cache:")
        print("  python -m data_analyst_agent --dataset validation_ops --metrics \"Truck Count\"")
        sys.exit(1)

    cache = load_cache(cache_path)
    components = cache.get("components", {})
    if not components:
        print("[benchmark] ERROR: Cache has no 'components'. Re-run pipeline to get fresh cache.")
        sys.exit(1)

    injection_len = len(cache.get("injection", ""))
    components_len = sum(len(str(v)) for v in components.values())

    print(f"\n{'='*70}")
    print(f"  PRE-SUMMARIZATION BENCHMARK")
    print(f"  Cache: {cache_path}")
    print(f"  Injection: {injection_len:,} chars | Components total: {components_len:,}")
    print(f"  Runs: {runs} | Summarizer: {summarizer_model}")
    print(f"{'='*70}\n")

    all_rows = []

    print("--- Baseline (no pre-summarization) ---")
    baseline_rows = await run_baseline(cache, cache_path, runs)
    all_rows.extend(baseline_rows)

    print("\n--- Pre-summarization ---")
    presummarize_rows = await run_presummarize(cache, runs, summarizer_model)
    all_rows.extend(presummarize_rows)

    if presummarize_rows:
        avg_inj = sum(r["injection_chars"] for r in presummarize_rows) / len(presummarize_rows)
    else:
        avg_inj = injection_len

    _write_csv(all_rows)
    _write_report(all_rows, injection_len, int(avg_inj) if presummarize_rows else 0)

    baseline_ok = [r for r in baseline_rows if r["status"] == "ok"]
    presummarize_ok = [r for r in presummarize_rows if r["status"] == "ok"]
    from statistics import median
    b_med = int(median([r["latency_ms"] for r in baseline_ok])) if baseline_ok else 0
    p_med = int(median([r["latency_ms"] for r in presummarize_ok])) if presummarize_ok else 0
    diff = ((p_med - b_med) / b_med * 100) if b_med else 0

    print(f"\n{'='*70}")
    print(f"  SUMMARY")
    print(f"  Baseline median:     {b_med:,} ms")
    print(f"  Pre-summarize median: {p_med:,} ms ({diff:+.1f}%)")
    print(f"{'='*70}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Benchmark report synthesis with vs without pre-summarization."
    )
    parser.add_argument(
        "--cache",
        type=Path,
        default=None,
        help="Path to report_synthesis_cache.json",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=1,
        help="Runs per mode (default: 1)",
    )
    parser.add_argument(
        "--summarizer-model",
        type=str,
        default=None,
        help="Model for pre-summarization (default: REPORT_SYNTHESIS_SUMMARIZER_MODEL or gemini-2.5-flash-lite)",
    )
    args = parser.parse_args()

    cache_path = args.cache or DEFAULT_CACHE
    if not cache_path.is_absolute():
        cache_path = PROJECT_ROOT / cache_path

    summarizer = args.summarizer_model or os.environ.get(
        "REPORT_SYNTHESIS_SUMMARIZER_MODEL", "gemini-2.5-flash-lite"
    )

    asyncio.run(main_async(cache_path, args.runs, summarizer))


if __name__ == "__main__":
    main()
