"""
Executive brief agent micro-benchmark (Phase 4).

Tests the executive_brief_agent in isolation using pre-stored fixture markdown
files that represent per-metric analysis reports. No ADK pipeline needed.
Measures latency and scores output quality (JSON validity, field presence,
word count, factual grounding).

Usage:
    python scripts/benchmark_executive.py
    python scripts/benchmark_executive.py --tiers advanced pro
    python scripts/benchmark_executive.py --runs 2

Output:
    results/benchmark_executive/results.csv
    results/benchmark_executive/report.md
    results/benchmark_executive/<tier>_output.json   raw LLM output per tier
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from pathlib import Path

import yaml

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
RESULTS_DIR = PROJECT_ROOT / "results" / "benchmark_executive"
FIXTURE_DIR = PROJECT_ROOT / "config" / "experiments" / "fixtures"


def _setup_auth() -> bool:
    """Load .env and configure Vertex AI / service-account auth."""
    try:
        from dotenv import load_dotenv
        env_path = PROJECT_ROOT / ".env"
        if env_path.exists():
            load_dotenv(env_path, override=False)
    except ImportError:
        pass

    try:
        sys.path.insert(0, str(PROJECT_ROOT))
        from data_analyst_agent.config import config  # noqa: F401
    except Exception:
        pass

    use_vertex = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "false").lower() == "true"
    sa_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
    api_key = os.getenv("GOOGLE_API_KEY", "")
    location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")

    if use_vertex and sa_path:
        print(f"[auth] Vertex AI  project={os.getenv('GOOGLE_CLOUD_PROJECT', '?')}  location={location}  sa={Path(sa_path).name}")
    elif api_key:
        print("[auth] Google AI  (API key — free-tier rate limits apply)")
    else:
        print("[auth] Vertex AI  (Application Default Credentials)")

    return use_vertex


_USE_VERTEXAI = _setup_auth()

REQUIRED_JSON_FIELDS = ["subject", "summary", "whats_going_well", "whats_masking_the_picture", "primary_concern", "bottom_line"]

# Executive brief has a higher quality bar
MIN_WORD_COUNT = 80
MAX_WORD_COUNT_RATIO = 3.0   # no more than 3x the shortest acceptable brief


def load_executive_prompt() -> str:
    """Load EXECUTIVE_BRIEF_INSTRUCTION from the source file."""
    prompt_path = PROJECT_ROOT / "data_analyst_agent" / "sub_agents" / "executive_brief_agent" / "prompt.py"
    namespace = {}
    exec(prompt_path.read_text(encoding="utf-8"), namespace)
    return namespace["EXECUTIVE_BRIEF_INSTRUCTION"]


def load_fixture_reports() -> list[tuple[str, str]]:
    """Load all fixture metric report markdown files."""
    reports = []
    for md_file in sorted(FIXTURE_DIR.glob("executive_metric_*.md")):
        reports.append((md_file.stem, md_file.read_text(encoding="utf-8")))
    return reports


def build_executive_digest(reports: list[tuple[str, str]]) -> str:
    """Build the compact digest that the executive brief agent receives."""
    parts = []
    for name, content in reports:
        # Take just the executive summary + top findings from each report (compact)
        lines = content.split("\n")
        compact_lines = []
        in_top_findings = False
        for line in lines:
            if line.startswith("## Executive Summary"):
                compact_lines.append(line)
                in_top_findings = False
            elif line.startswith("## Top Findings"):
                compact_lines.append(line)
                in_top_findings = True
            elif line.startswith("##") and in_top_findings:
                break
            elif compact_lines:
                compact_lines.append(line)
        parts.append(f"### Metric: {name.replace('executive_metric_', '').replace('_', ' ').title()}\n\n" + "\n".join(compact_lines[:30]))
    return "\n\n---\n\n".join(parts)


def _parse_retry_delay(exc: Exception) -> int:
    msg = str(exc)
    m = re.search(r"retry[^\d]*(\d+)", msg, re.IGNORECASE)
    return max(int(m.group(1)) + 2, 5) if m else 65


def get_thinking_config(tier_cfg: dict):
    from google.genai import types
    model = tier_cfg.get("model", "")
    budget = tier_cfg.get("thinking_budget")
    if "gemini-2.5-flash" in model:
        if budget is not None:
            try:
                return types.ThinkingConfig(thinking_budget_tokens=budget)
            except Exception:
                return None
        return None
    if "gemini-2.5-pro" in model:
        b = tier_cfg.get("thinking_budget")
        try:
            if b:
                return types.ThinkingConfig(include_thoughts=True, thinking_budget_tokens=b)
            return types.ThinkingConfig(include_thoughts=True)
        except Exception:
            return None
    return None


def parse_json_from_text(text: str) -> dict | None:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"```\s*$", "", text, flags=re.MULTILINE)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    return None


def score_executive_output(parsed: dict | None, raw_text: str) -> dict:
    if not parsed or not isinstance(parsed, dict):
        return {
            "json_valid": False,
            "fields_present": 0,
            "total_fields": len(REQUIRED_JSON_FIELDS),
            "word_count": 0,
            "has_specifics": False,
            "overall_pass": False,
            "notes": "No parseable JSON",
        }

    fields_present = sum(1 for f in REQUIRED_JSON_FIELDS if parsed.get(f))
    word_count = len(raw_text.split())

    # Check for terminal names (evidence the model used the fixture data)
    fixture_terminals = ["albuquerque", "amarillo", "troutdale", "el paso"]
    full_text = json.dumps(parsed).lower()
    has_specifics = any(t in full_text for t in fixture_terminals)

    notes_parts = []
    if fields_present < len(REQUIRED_JSON_FIELDS):
        missing = [f for f in REQUIRED_JSON_FIELDS if not parsed.get(f)]
        notes_parts.append(f"missing fields: {missing}")
    if word_count < MIN_WORD_COUNT:
        notes_parts.append(f"too short ({word_count} words, min {MIN_WORD_COUNT})")
    if not has_specifics:
        notes_parts.append("no terminal names found — possible hallucination or generic output")

    overall_pass = (
        fields_present == len(REQUIRED_JSON_FIELDS)
        and word_count >= MIN_WORD_COUNT
        and has_specifics
    )

    return {
        "json_valid": True,
        "fields_present": fields_present,
        "total_fields": len(REQUIRED_JSON_FIELDS),
        "word_count": word_count,
        "has_specifics": has_specifics,
        "overall_pass": overall_pass,
        "notes": "; ".join(notes_parts) if notes_parts else "OK",
    }


def run_benchmark(tiers_to_test: list[str], runs: int = 1, call_delay: float = 0.0):
    from google.genai import Client, types

    config_path = PROJECT_ROOT / "config" / "agent_models.yaml"
    with open(config_path, encoding="utf-8") as f:
        models_config = yaml.safe_load(f)

    all_tiers = models_config["model_tiers"]
    reports = load_fixture_reports()

    try:
        instruction_template = load_executive_prompt()
    except Exception as exc:
        print(f"[benchmark] Could not load executive prompt: {exc}")
        instruction_template = "You are an executive analyst. Synthesize the metric reports into a JSON executive brief with fields: subject, summary, whats_going_well, whats_masking_the_picture, primary_concern, bottom_line."

    week_ending = "2026-02-15"
    instruction = instruction_template.format(
        metric_count=len(reports),
        week_ending=week_ending,
    )

    digest = build_executive_digest(reports)
    user_message = f"Here are the {len(reports)} metric analysis reports for the week ending {week_ending}:\n\n{digest}"

    location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    project = os.getenv("GOOGLE_CLOUD_PROJECT") if _USE_VERTEXAI else None
    client = Client(vertexai=_USE_VERTEXAI, project=project, location=location if _USE_VERTEXAI else None)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    csv_rows = []

    print(f"\n{'='*70}")
    print(f"  EXECUTIVE BRIEF BENCHMARK")
    print(f"  Fixture: {len(reports)} metric reports (Truck Count, Rev/Trk/Wk, LRPM)")
    print(f"  Tiers: {tiers_to_test},  Runs each: {runs}")
    print(f"{'='*70}\n")

    for tier_name in tiers_to_test:
        if tier_name not in all_tiers:
            print(f"  [skip] Unknown tier: {tier_name}")
            continue

        tier_cfg = all_tiers[tier_name]
        model = tier_cfg["model"]
        thinking_config = get_thinking_config(tier_cfg)
        budget = tier_cfg.get("thinking_budget", "default")

        print(f"\n--- Tier: {tier_name}  model={model}  budget={budget} ---")

        for run_idx in range(1, runs + 1):
            if call_delay > 0:
                time.sleep(call_delay)
            print(f"  Run {run_idx}...", end=" ")
            try:
                config_kwargs = {
                    "response_modalities": ["TEXT"],
                    "temperature": 0.3,
                }
                if thinking_config is not None:
                    config_kwargs["thinking_config"] = thinking_config

                gen_cfg = types.GenerateContentConfig(
                    system_instruction=instruction,
                    **config_kwargs,
                )
                contents = [types.Content(role="user", parts=[types.Part(text=user_message)])]

                for attempt in range(3):
                    try:
                        start = time.perf_counter()
                        response = client.models.generate_content(model=model, contents=contents, config=gen_cfg)
                        latency_ms = round((time.perf_counter() - start) * 1000)
                        text = response.text or ""
                        break
                    except Exception as _exc:
                        if "429" in str(_exc) and attempt < 2:
                            delay = _parse_retry_delay(_exc)
                            print(f"[rate-limit] waiting {delay}s...", end=" ")
                            time.sleep(delay)
                        else:
                            raise

                parsed = parse_json_from_text(text)
                score = score_executive_output(parsed, text)

                status = "PASS" if score["overall_pass"] else "FAIL"
                print(f"{latency_ms}ms [{status}] fields={score['fields_present']}/{score['total_fields']} words={score['word_count']} specifics={score['has_specifics']} {score['notes']}")

                if run_idx == 1:
                    output_path = RESULTS_DIR / f"{tier_name}_output.json"
                    output_path.write_text(json.dumps({"tier": tier_name, "latency_ms": latency_ms, "score": score, "parsed": parsed, "raw_text": text[:2000]}, indent=2), encoding="utf-8")

            except Exception as exc:
                latency_ms = 0
                score = {"json_valid": False, "fields_present": 0, "total_fields": len(REQUIRED_JSON_FIELDS), "word_count": 0, "has_specifics": False, "overall_pass": False, "notes": str(exc)}
                status = "ERROR"
                print(f"ERROR: {exc}")

            csv_rows.append({
                "tier": tier_name,
                "model": model,
                "thinking_budget": budget,
                "run": run_idx,
                "latency_ms": latency_ms,
                "fields_present": score["fields_present"],
                "word_count": score["word_count"],
                "has_specifics": score["has_specifics"],
                "pass": score["overall_pass"],
                "notes": score["notes"],
            })

    csv_path = RESULTS_DIR / "results.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["tier", "model", "thinking_budget", "run", "latency_ms", "fields_present", "word_count", "has_specifics", "pass", "notes"])
        writer.writeheader()
        writer.writerows(csv_rows)
    print(f"\n[benchmark] CSV written: {csv_path}")

    report_path = RESULTS_DIR / "report.md"
    _write_report(report_path, csv_rows, tiers_to_test)
    print(f"[benchmark] Report written: {report_path}")

    _print_summary(csv_rows, tiers_to_test)


def _print_summary(rows: list[dict], tiers: list[str]):
    from statistics import median

    print(f"\n{'='*70}")
    print(f"  EXECUTIVE BRIEF BENCHMARK SUMMARY")
    print(f"{'='*70}")
    print(f"  {'Tier':<12} {'Budget':>8} {'Median ms':>10} {'Fields':>7} {'Words':>7} {'Specific':>9} {'Verdict'}")
    print(f"  {'-'*12} {'-'*8} {'-'*10} {'-'*7} {'-'*7} {'-'*9} {'-'*8}")

    for tier in tiers:
        tier_rows = [r for r in rows if r["tier"] == tier]
        if not tier_rows:
            continue
        budget = tier_rows[0].get("thinking_budget", "default")
        latencies = [r["latency_ms"] for r in tier_rows if r["latency_ms"] > 0]
        med = int(median(latencies)) if latencies else 0
        avg_fields = sum(r["fields_present"] for r in tier_rows) / len(tier_rows)
        avg_words = int(sum(r["word_count"] for r in tier_rows) / len(tier_rows))
        pct_specific = sum(1 for r in tier_rows if r["has_specifics"]) / len(tier_rows)
        pass_rate = sum(1 for r in tier_rows if r["pass"]) / len(tier_rows)
        verdict = "PASS" if pass_rate == 1.0 else f"FAIL ({pass_rate:.0%})"
        print(f"  {tier:<12} {str(budget):>8} {med:>10,} {avg_fields:>7.1f} {avg_words:>7} {pct_specific:>9.0%} {verdict}")

    print(f"{'='*70}\n")


def _write_report(path: Path, rows: list[dict], tiers: list[str]):
    from statistics import median
    from datetime import datetime

    lines = [
        "# Executive Brief Agent Benchmark Report",
        "",
        f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**Fixture**: 3 metric reports (Truck Count, Rev/Trk/Wk, LRPM) — week ending 2026-02-15",
        f"**Required JSON fields**: `{', '.join(REQUIRED_JSON_FIELDS)}`",
        "",
        "## Summary",
        "",
        "| Tier | Budget | Median ms | Fields | Words | Specific? | Pass Rate | Verdict |",
        "|------|--------|----------:|-------:|------:|----------:|----------:|---------|",
    ]

    for tier in tiers:
        tier_rows = [r for r in rows if r["tier"] == tier]
        if not tier_rows:
            continue
        budget = tier_rows[0].get("thinking_budget", "default")
        latencies = [r["latency_ms"] for r in tier_rows if r["latency_ms"] > 0]
        med = int(median(latencies)) if latencies else 0
        avg_fields = sum(r["fields_present"] for r in tier_rows) / len(tier_rows)
        avg_words = int(sum(r["word_count"] for r in tier_rows) / len(tier_rows))
        pct_specific = sum(1 for r in tier_rows if r["has_specifics"]) / len(tier_rows)
        pass_rate = sum(1 for r in tier_rows if r["pass"]) / len(tier_rows)
        verdict = "PASS" if pass_rate == 1.0 else "**FAIL**"
        lines.append(f"| {tier} | {budget} | {med:,} | {avg_fields:.1f} | {avg_words} | {pct_specific:.0%} | {pass_rate:.0%} | {verdict} |")

    lines += [
        "",
        "## Decision",
        "",
        "Executive brief has a higher quality bar: fields must all be present, terminal names must appear (grounded in data), minimum word count.",
        "",
        "- **Winner for executive_brief_agent**: (fastest tier that passes all checks)",
        "",
        "## Manual Quality Scoring (fill in — higher threshold: >= 4.0 weighted, >= 4.5 accuracy)",
        "",
        "| Tier | Accuracy /5 | Completeness /5 | Insight Value /5 | Actionability /5 | Weighted /5 | Pass? |",
        "|------|------------|----------------|-----------------|-----------------|------------|-------|",
    ]
    for tier in tiers:
        lines.append(f"| {tier} | | | | | | |")

    path.write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Benchmark executive brief agent across model tiers.")
    parser.add_argument("--tiers", nargs="+", default=["standard", "advanced"],
                        help="Tiers to test (default: standard advanced)")
    parser.add_argument("--runs", type=int, default=1, help="Runs per tier (default: 1)")
    parser.add_argument("--call-delay", type=float, default=0.0,
                        help="Seconds between API calls. Default 0 (Vertex AI). Use 13 for free-tier API key.")
    args = parser.parse_args()
    run_benchmark(args.tiers, args.runs, args.call_delay)


if __name__ == "__main__":
    main()
