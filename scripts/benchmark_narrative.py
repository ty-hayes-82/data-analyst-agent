"""
Narrative agent micro-benchmark (Phase 3).

Tests the narrative_agent in isolation using pre-stored fixture data, so there
is no need to run the full analysis pipeline. Measures latency and scores output
quality (insight card count, field completeness, JSON validity).

Usage:
    python scripts/benchmark_narrative.py
    python scripts/benchmark_narrative.py --tiers fast standard advanced pro
    python scripts/benchmark_narrative.py --runs 2

Output:
    results/benchmark_narrative/results.csv
    results/benchmark_narrative/report.md
    results/benchmark_narrative/<tier>_output.json   raw LLM output per tier
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
RESULTS_DIR = PROJECT_ROOT / "results" / "benchmark_narrative"
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

# Required fields in each insight card
REQUIRED_CARD_FIELDS = ["title", "what_changed", "why", "priority", "root_cause"]
# Minimum acceptable insight card count (relative to best-performing tier)
MIN_CARD_RATIO = 0.8


def load_narrative_prompt() -> str:
    """Load NARRATIVE_AGENT_INSTRUCTION from the source file."""
    prompt_path = PROJECT_ROOT / "data_analyst_agent" / "sub_agents" / "narrative_agent" / "prompt.py"
    namespace = {}
    exec(prompt_path.read_text(encoding="utf-8"), namespace)
    return namespace["NARRATIVE_AGENT_INSTRUCTION"]


def load_fixture() -> dict:
    fixture_path = FIXTURE_DIR / "narrative_input.json"
    with open(fixture_path, encoding="utf-8") as f:
        return json.load(f)


def format_narrative_instruction(instruction_template: str, fixture: dict) -> str:
    return instruction_template.format(
        dataset_display_name=fixture.get("dataset_display_name", "Validation Operations Metrics")
    )


def build_user_message(fixture: dict) -> str:
    return json.dumps({
        "data_analyst_result": fixture["data_analyst_result"],
        "statistical_summary": fixture["statistical_summary"],
        "seasonal_baseline_result": fixture["seasonal_baseline_result"],
        "analysis_target": fixture["analysis_target"],
        "metric_name": fixture["metric_name"],
    }, indent=2)


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


def score_narrative_output(parsed: dict | None) -> dict:
    if not parsed or not isinstance(parsed, dict):
        return {
            "card_count": 0,
            "has_summary": False,
            "avg_field_completeness": 0.0,
            "json_valid": False,
            "overall_pass": False,
            "notes": "No parseable JSON",
        }

    cards = parsed.get("insight_cards", [])
    card_count = len(cards)
    has_summary = bool(parsed.get("narrative_summary", "").strip())

    completeness_scores = []
    for card in cards:
        present = sum(1 for f in REQUIRED_CARD_FIELDS if card.get(f))
        completeness_scores.append(present / len(REQUIRED_CARD_FIELDS))
    avg_completeness = sum(completeness_scores) / len(completeness_scores) if completeness_scores else 0.0

    notes_parts = []
    if card_count < 2:
        notes_parts.append(f"only {card_count} cards (expected >= 2)")
    if not has_summary:
        notes_parts.append("missing narrative_summary")

    return {
        "card_count": card_count,
        "has_summary": has_summary,
        "avg_field_completeness": round(avg_completeness, 2),
        "json_valid": True,
        "overall_pass": card_count >= 2 and has_summary,
        "notes": "; ".join(notes_parts) if notes_parts else "OK",
    }


def run_benchmark(tiers_to_test: list[str], runs: int = 1, call_delay: float = 0.0):
    from google.genai import Client, types

    config_path = PROJECT_ROOT / "config" / "agent_models.yaml"
    with open(config_path, encoding="utf-8") as f:
        models_config = yaml.safe_load(f)

    all_tiers = models_config["model_tiers"]
    fixture = load_fixture()

    try:
        narrative_instruction_template = load_narrative_prompt()
    except Exception as exc:
        print(f"[benchmark] Could not load narrative prompt: {exc}. Using placeholder.")
        narrative_instruction_template = "You are a narrative analysis agent. Analyze the provided data and return a JSON with insight_cards and narrative_summary. Dataset: {dataset_display_name}"

    narrative_instruction = format_narrative_instruction(narrative_instruction_template, fixture)
    user_message = build_user_message(fixture)

    location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    project = os.getenv("GOOGLE_CLOUD_PROJECT") if _USE_VERTEXAI else None
    client = Client(vertexai=_USE_VERTEXAI, project=project, location=location if _USE_VERTEXAI else None)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    csv_rows = []
    best_card_count = 0

    print(f"\n{'='*70}")
    print(f"  NARRATIVE AGENT BENCHMARK")
    print(f"  Fixture: Albuquerque Truck Count (26 weeks)")
    print(f"  Tiers: {tiers_to_test},  Runs each: {runs}")
    print(f"{'='*70}\n")

    tier_outputs = {}

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
                    "temperature": 0.0,
                }
                if thinking_config is not None:
                    config_kwargs["thinking_config"] = thinking_config

                gen_cfg = types.GenerateContentConfig(
                    system_instruction=narrative_instruction,
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
                score = score_narrative_output(parsed)
                best_card_count = max(best_card_count, score["card_count"])

                status = "PASS" if score["overall_pass"] else "FAIL"
                print(f"{latency_ms}ms [{status}] cards={score['card_count']} completeness={score['avg_field_completeness']:.0%} {score['notes']}")

                # Save raw output for first run of each tier
                if run_idx == 1:
                    tier_outputs[tier_name] = {"raw_text": text, "parsed": parsed, "score": score}
                    output_path = RESULTS_DIR / f"{tier_name}_output.json"
                    output_path.write_text(json.dumps({"tier": tier_name, "latency_ms": latency_ms, "score": score, "parsed": parsed}, indent=2), encoding="utf-8")

            except Exception as exc:
                latency_ms = 0
                score = {"card_count": 0, "has_summary": False, "avg_field_completeness": 0.0, "json_valid": False, "overall_pass": False, "notes": str(exc)}
                status = "ERROR"
                print(f"ERROR: {exc}")

            csv_rows.append({
                "tier": tier_name,
                "model": model,
                "thinking_budget": budget,
                "run": run_idx,
                "latency_ms": latency_ms,
                "card_count": score["card_count"],
                "has_summary": score["has_summary"],
                "avg_field_completeness": score["avg_field_completeness"],
                "json_valid": score["json_valid"],
                "pass": score["overall_pass"],
                "notes": score["notes"],
            })

    # Apply relative card count check (experiment must have >= 80% of best count)
    if best_card_count > 0:
        for row in csv_rows:
            if row["card_count"] < MIN_CARD_RATIO * best_card_count:
                row["pass"] = False
                row["notes"] = f"{row['notes']}; card_count {row['card_count']} < {MIN_CARD_RATIO:.0%} of best ({best_card_count})"

    # Write CSV
    csv_path = RESULTS_DIR / "results.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["tier", "model", "thinking_budget", "run", "latency_ms", "card_count", "has_summary", "avg_field_completeness", "json_valid", "pass", "notes"])
        writer.writeheader()
        writer.writerows(csv_rows)
    print(f"\n[benchmark] CSV written: {csv_path}")

    report_path = RESULTS_DIR / "report.md"
    _write_report(report_path, csv_rows, tiers_to_test, best_card_count)
    print(f"[benchmark] Report written: {report_path}")

    _print_summary(csv_rows, tiers_to_test)


def _print_summary(rows: list[dict], tiers: list[str]):
    from statistics import median

    print(f"\n{'='*70}")
    print(f"  NARRATIVE BENCHMARK SUMMARY")
    print(f"{'='*70}")
    print(f"  {'Tier':<12} {'Budget':>8} {'Median ms':>10} {'Cards':>6} {'Complete':>9} {'Verdict'}")
    print(f"  {'-'*12} {'-'*8} {'-'*10} {'-'*6} {'-'*9} {'-'*8}")

    for tier in tiers:
        tier_rows = [r for r in rows if r["tier"] == tier]
        if not tier_rows:
            continue
        budget = tier_rows[0].get("thinking_budget", "default")
        latencies = [r["latency_ms"] for r in tier_rows if r["latency_ms"] > 0]
        med = int(median(latencies)) if latencies else 0
        avg_cards = sum(r["card_count"] for r in tier_rows) / len(tier_rows)
        avg_complete = sum(r["avg_field_completeness"] for r in tier_rows) / len(tier_rows)
        pass_rate = sum(1 for r in tier_rows if r["pass"]) / len(tier_rows)
        verdict = "PASS" if pass_rate == 1.0 else f"FAIL ({pass_rate:.0%})"
        print(f"  {tier:<12} {str(budget):>8} {med:>10,} {avg_cards:>6.1f} {avg_complete:>9.0%} {verdict}")

    print(f"{'='*70}\n")


def _write_report(path: Path, rows: list[dict], tiers: list[str], best_count: int):
    from statistics import median
    from datetime import datetime

    lines = [
        "# Narrative Agent Benchmark Report",
        "",
        f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**Fixture**: Albuquerque Truck Count, 26-week analysis",
        f"**Best card count observed**: {best_count}",
        f"**Minimum acceptable**: {int(MIN_CARD_RATIO * best_count)} ({MIN_CARD_RATIO:.0%} of best)",
        "",
        "## Summary",
        "",
        "| Tier | Budget | Median ms | Avg Cards | Completeness | Pass Rate | Verdict |",
        "|------|--------|----------:|----------:|-------------:|----------:|---------|",
    ]

    for tier in tiers:
        tier_rows = [r for r in rows if r["tier"] == tier]
        if not tier_rows:
            continue
        budget = tier_rows[0].get("thinking_budget", "default")
        latencies = [r["latency_ms"] for r in tier_rows if r["latency_ms"] > 0]
        med = int(median(latencies)) if latencies else 0
        avg_cards = sum(r["card_count"] for r in tier_rows) / len(tier_rows)
        avg_complete = sum(r["avg_field_completeness"] for r in tier_rows) / len(tier_rows)
        pass_rate = sum(1 for r in tier_rows if r["pass"]) / len(tier_rows)
        verdict = "PASS" if pass_rate == 1.0 else "**FAIL**"
        lines.append(f"| {tier} | {budget} | {med:,} | {avg_cards:.1f} | {avg_complete:.0%} | {pass_rate:.0%} | {verdict} |")

    lines += [
        "",
        "## Decision",
        "",
        "- **Winner for narrative_agent**: (fastest tier that passes)",
        "",
        "## Manual Quality Scoring (fill in)",
        "",
        "| Tier | Accuracy /5 | Completeness /5 | Insight Value /5 | Actionability /5 | Weighted /5 | Pass? |",
        "|------|------------|----------------|-----------------|-----------------|------------|-------|",
    ]
    for tier in tiers:
        lines.append(f"| {tier} | | | | | | |")

    path.write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Benchmark narrative agent across model tiers.")
    parser.add_argument("--tiers", nargs="+", default=["fast", "standard", "advanced"],
                        help="Tiers to test (default: fast standard advanced)")
    parser.add_argument("--runs", type=int, default=1, help="Runs per tier (default: 1)")
    parser.add_argument("--call-delay", type=float, default=0.0,
                        help="Seconds between API calls. Default 0 (Vertex AI). Use 13 for free-tier API key.")
    args = parser.parse_args()
    run_benchmark(args.tiers, args.runs, args.call_delay)


if __name__ == "__main__":
    main()
