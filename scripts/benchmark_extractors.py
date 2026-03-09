"""
Extractor micro-benchmark (Phase 2).

Tests request_analyzer and dimension_extractor in isolation by calling the
Gemini API directly with the exact prompts used by those agents. No ADK
pipeline overhead — runs in under 2 minutes for all tiers and queries.

Usage:
    python scripts/benchmark_extractors.py
    python scripts/benchmark_extractors.py --tiers fast standard pro
    python scripts/benchmark_extractors.py --runs 3

Output:
    results/benchmark_extractors/results.csv   per-call timing and accuracy
    results/benchmark_extractors/report.md     summary with pass/fail per tier
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

# Force line-buffered output
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
RESULTS_DIR = PROJECT_ROOT / "results" / "benchmark_extractors"


def _setup_auth() -> bool:
    """Load .env and configure Vertex AI / service-account auth.

    Returns True if Vertex AI (service account) is active, False for API key.
    """
    try:
        from dotenv import load_dotenv
        env_path = PROJECT_ROOT / ".env"
        if env_path.exists():
            load_dotenv(env_path, override=False)
    except ImportError:
        pass  # python-dotenv not installed; rely on shell env

    # Import config to trigger setup_environment() which removes GOOGLE_API_KEY
    # when a service account is present and sets GOOGLE_GENAI_USE_VERTEXAI.
    try:
        sys.path.insert(0, str(PROJECT_ROOT))
        from data_analyst_agent.config import config  # noqa: F401 — side-effect import
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

# Prompts (copied from data_analyst_agent/prompt.py to avoid importing the full module)
REQUEST_ANALYZER_TEMPLATE = """
You are an intelligent Data Analyst that interprets user requests and maps them to the correct analysis type for the {dataset_display_name} dataset.

YOUR TASK:
Analyze the user's request and determine:
1. What type of analysis they need based on available capabilities
2. What data granularity is required
3. What primary dimension they are focusing on
4. What the specific value for that dimension is

AVAILABLE CAPABILITIES:
{contract_capabilities}

AVAILABLE DIMENSIONS:
{contract_dimensions}

OUTPUT FORMAT (JSON):
{{
  "analysis_type": "one of the capabilities listed above",
  "primary_dimension": "one of the dimensions listed above",
  "primary_dimension_value": "the extracted value",
  "metrics": ["metric1", "metric2"],
  "focus": "descriptive name of what they're analyzing",
  "needs_supplementary_data": true or false,
  "description": "Brief description of the analysis needed",
  "data_fetch_query_primary": "Query for the primary data agent.",
  "data_fetch_query_supplementary": null
}}

Be intelligent and flexible - understand user intent even if they don't use exact terminology.
"""

DIMENSION_EXTRACTOR_TEMPLATE = """
Extract the primary analysis targets (dimension values) from the user's request.

AVAILABLE DIMENSIONS:
{dimension_definitions}

Look for specific values matching these dimensions (e.g., specific codes, names, or identifiers).

Return a JSON array of target value strings.

Example:
{dimension_examples}

Return ONLY a JSON array like: ["Value1", "Value2"]
"""


def load_contract():
    """Load the validation_ops contract to format prompts."""
    contract_path = PROJECT_ROOT / "config" / "datasets" / "validation_ops" / "contract.yaml"
    with open(contract_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_queries():
    """Load benchmark queries."""
    queries_path = PROJECT_ROOT / "config" / "experiments" / "benchmark_queries.yaml"
    with open(queries_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data["queries"]


def build_request_analyzer_prompt(contract: dict) -> str:
    capabilities = "\n".join(f"- {c}" for c in contract.get("capabilities", []))
    dimensions = "\n".join(
        f"- {d['name']}: {d.get('description', d['column'])}"
        for d in contract.get("dimensions", [])
    )
    return REQUEST_ANALYZER_TEMPLATE.format(
        dataset_display_name=contract.get("display_name", contract["name"]),
        contract_capabilities=capabilities,
        contract_dimensions=dimensions,
    )


def build_dimension_extractor_prompt(contract: dict) -> str:
    dimensions = "\n".join(
        f"- {d['name']}: {d.get('description', d['column'])}"
        for d in contract.get("dimensions", [])
    )
    examples = f"- 'Analyze terminal Albuquerque' -> [\"Albuquerque\"]"
    return DIMENSION_EXTRACTOR_TEMPLATE.format(
        dimension_definitions=dimensions,
        dimension_examples=examples,
    )


def get_thinking_config(tier_name: str, tier_config: dict):
    """Build ThinkingConfig for a tier, matching model_loader.py logic."""
    from google.genai import types

    model = tier_config.get("model", "")
    budget = tier_config.get("thinking_budget")

    if "gemini-2.5-flash" in model:
        if budget is not None:
            try:
                return types.ThinkingConfig(thinking_budget_tokens=budget)
            except Exception:
                return None
        return None

    if "gemini-2.5-pro" in model:
        b = tier_config.get("thinking_budget")
        try:
            if b:
                return types.ThinkingConfig(include_thoughts=True, thinking_budget_tokens=b)
            return types.ThinkingConfig(include_thoughts=True)
        except Exception:
            return None

    return None


def _parse_retry_delay(exc: Exception) -> int:
    """Parse retryDelay seconds from a 429 error message."""
    msg = str(exc)
    m = re.search(r"retry[^\d]*(\d+)", msg, re.IGNORECASE)
    if m:
        return max(int(m.group(1)) + 2, 5)
    return 65  # safe default


def call_llm(client, model: str, system_instruction: str, user_message: str, thinking_config,
             temperature: float = 0.0, max_retries: int = 3) -> tuple[str, float]:
    """Make a single LLM call with retry on 429, return (response_text, latency_ms)."""
    from google.genai import types

    config_kwargs = {
        "response_modalities": ["TEXT"],
        "temperature": temperature,
    }
    if thinking_config is not None:
        config_kwargs["thinking_config"] = thinking_config

    gen_cfg = types.GenerateContentConfig(
        system_instruction=system_instruction,
        **config_kwargs,
    )
    contents = [types.Content(role="user", parts=[types.Part(text=user_message)])]

    for attempt in range(max_retries):
        try:
            start = time.perf_counter()
            response = client.models.generate_content(model=model, contents=contents, config=gen_cfg)
            latency_ms = round((time.perf_counter() - start) * 1000)
            return response.text or "", latency_ms
        except Exception as exc:
            if "429" in str(exc) and attempt < max_retries - 1:
                delay = _parse_retry_delay(exc)
                print(f"[rate-limit] 429 on attempt {attempt+1}, waiting {delay}s...", end=" ")
                time.sleep(delay)
            else:
                raise


def parse_json_from_text(text: str) -> dict | list | None:
    """Extract JSON from an LLM response."""
    text = text.strip()
    # Strip markdown fences
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"```\s*$", "", text, flags=re.MULTILINE)
    # Try entire text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Try first { ... } or [ ... ]
    for pattern in [r"\{[\s\S]*\}", r"\[[\s\S]*\]"]:
        m = re.search(pattern, text)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                pass
    return None


def normalize_list(val) -> list[str]:
    if isinstance(val, list):
        return sorted(str(v).strip().lower() for v in val)
    if isinstance(val, str):
        return [val.strip().lower()]
    return []


# Common abbreviation keywords for fuzzy metric matching
_METRIC_KEYWORDS = {
    "revenue per truck per week": ["rev", "trk", "wk", "revenue", "truck"],
    "total miles per truck per week": ["miles", "trk", "wk", "mile"],
    "truck count": ["truck", "count"],
    "lrpm": ["lrpm", "loaded revenue"],
    "turnover": ["turnover", "turn"],
}


def _metric_fuzzy_match(got_list: list[str], expected_list: list[str]) -> bool:
    """True if each expected metric has a fuzzy match in got_list.
    Handles both abbreviated (rev/trk/wk) and full-name forms."""
    if not expected_list:
        return True
    for exp in expected_list:
        exp_lower = exp.lower()
        # Exact match
        if any(exp_lower in g or g in exp_lower for g in got_list):
            continue
        # Keyword overlap (2+ keywords must match)
        exp_keywords = _METRIC_KEYWORDS.get(exp_lower, exp_lower.split())
        matched = False
        for got in got_list:
            hits = sum(1 for kw in exp_keywords if kw in got)
            if hits >= 2:
                matched = True
                break
        if not matched:
            return False
    return True


def score_extractor(parsed: dict | None, expected: dict) -> dict:
    """Score request_analysis output against expected values."""
    if not parsed or not isinstance(parsed, dict):
        return {"metrics_match": False, "dimension_match": False, "overall_pass": False, "notes": "No parseable JSON"}

    exp_metrics = normalize_list(expected.get("expected_metrics", []))
    exp_dim = expected.get("expected_dimension", "").strip().lower()

    got_metrics = normalize_list(parsed.get("metrics", []))
    got_dim = (parsed.get("primary_dimension") or "").strip().lower()

    metrics_match = _metric_fuzzy_match(got_metrics, exp_metrics)
    dimension_match = exp_dim == "" or got_dim == exp_dim

    notes = []
    if not metrics_match:
        notes.append(f"metrics: expected {exp_metrics!r} got {got_metrics!r}")
    if not dimension_match:
        notes.append(f"dimension: expected {exp_dim!r} got {got_dim!r}")

    return {
        "metrics_match": metrics_match,
        "dimension_match": dimension_match,
        "overall_pass": metrics_match and dimension_match,
        "notes": "; ".join(notes) if notes else "OK",
    }


def score_dimension_extractor(parsed: list | None, expected: dict) -> dict:
    """Score dimension_extractor output against expected metrics.

    Uses the same fuzzy matching as score_extractor so that abbreviated forms
    like 'rev/trk/wk' match 'revenue per truck per week'.
    """
    if not parsed or not isinstance(parsed, list):
        return {"targets_found": False, "overall_pass": False, "notes": "No parseable JSON array"}

    exp_metrics = normalize_list(expected.get("expected_metrics", []))
    got = normalize_list(parsed)

    if exp_metrics:
        found = _metric_fuzzy_match(got, exp_metrics)
    else:
        found = len(got) > 0

    return {
        "targets_found": found,
        "extracted": got,
        "overall_pass": found,
        "notes": f"extracted={got}" if found else f"expected {exp_metrics!r} got {got!r}",
    }


def run_benchmark(tiers_to_test: list[str], runs: int = 1, call_delay: float = 0.0):
    """Run the extractor benchmark across all tiers and queries.

    call_delay: seconds between API calls. Defaults to 0 for Vertex AI (no free-tier
    rate limit). Set to 13 if using a free-tier API key (5 req/min limit).
    """
    from google.genai import Client

    # Load config
    config_path = PROJECT_ROOT / "config" / "agent_models.yaml"
    with open(config_path, encoding="utf-8") as f:
        models_config = yaml.safe_load(f)

    all_tiers = models_config["model_tiers"]
    contract = load_contract()
    queries = load_queries()

    location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    project = os.getenv("GOOGLE_CLOUD_PROJECT") if _USE_VERTEXAI else None
    client = Client(vertexai=_USE_VERTEXAI, project=project, location=location if _USE_VERTEXAI else None)

    ra_system_prompt = build_request_analyzer_prompt(contract)
    de_system_prompt = build_dimension_extractor_prompt(contract)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    csv_rows = []

    print(f"\n{'='*70}")
    print(f"  EXTRACTOR BENCHMARK")
    print(f"  Tiers: {tiers_to_test}")
    print(f"  Queries: {len(queries)},  Runs each: {runs}")
    print(f"{'='*70}\n")

    for tier_name in tiers_to_test:
        if tier_name not in all_tiers:
            print(f"  [skip] Unknown tier: {tier_name}")
            continue

        tier_cfg = all_tiers[tier_name]
        model = tier_cfg["model"]
        thinking_config = get_thinking_config(tier_name, tier_cfg)
        budget = tier_cfg.get("thinking_budget", "default")

        print(f"\n--- Tier: {tier_name}  model={model}  budget={budget} ---")

        for query in queries:
            if query.get("extractor_test") is False:
                print(f"  [skip] {query['id']} ({query['label']}) — not an extraction test")
                continue
            qid = query["id"]
            qtext = query["text"]
            expected = query

            for run_idx in range(1, runs + 1):
                # --- request_analyzer ---
                if call_delay > 0:
                    time.sleep(call_delay)
                print(f"  {qid} r{run_idx} request_analyzer...", end=" ")
                try:
                    ra_text, ra_ms = call_llm(client, model, ra_system_prompt, qtext, thinking_config)
                    ra_parsed = parse_json_from_text(ra_text)
                    ra_score = score_extractor(ra_parsed, expected)
                    ra_status = "PASS" if ra_score["overall_pass"] else "FAIL"
                    print(f"{ra_ms}ms [{ra_status}] {ra_score['notes']}")
                except Exception as exc:
                    ra_ms = 0
                    ra_score = {"metrics_match": False, "dimension_match": False, "overall_pass": False, "notes": str(exc)}
                    ra_status = "ERROR"
                    print(f"ERROR: {exc}")

                # --- dimension_extractor ---
                if call_delay > 0:
                    time.sleep(call_delay)
                print(f"  {qid} r{run_idx} dimension_extractor...", end=" ")
                try:
                    de_text, de_ms = call_llm(client, model, de_system_prompt, qtext, thinking_config)
                    de_parsed = parse_json_from_text(de_text)
                    de_score = score_dimension_extractor(de_parsed, expected)
                    de_status = "PASS" if de_score["overall_pass"] else "FAIL"
                    print(f"{de_ms}ms [{de_status}] {de_score['notes']}")
                except Exception as exc:
                    de_ms = 0
                    de_score = {"targets_found": False, "overall_pass": False, "notes": str(exc)}
                    de_status = "ERROR"
                    print(f"ERROR: {exc}")

                csv_rows.append({
                    "tier": tier_name,
                    "model": model,
                    "thinking_budget": budget,
                    "query_id": qid,
                    "run": run_idx,
                    "agent": "request_analyzer",
                    "latency_ms": ra_ms,
                    "pass": ra_score["overall_pass"],
                    "metrics_match": ra_score.get("metrics_match", ""),
                    "dimension_match": ra_score.get("dimension_match", ""),
                    "notes": ra_score["notes"],
                })
                csv_rows.append({
                    "tier": tier_name,
                    "model": model,
                    "thinking_budget": budget,
                    "query_id": qid,
                    "run": run_idx,
                    "agent": "dimension_extractor",
                    "latency_ms": de_ms,
                    "pass": de_score["overall_pass"],
                    "metrics_match": de_score.get("targets_found", ""),
                    "dimension_match": "",
                    "notes": de_score["notes"],
                })

    # Write CSV
    csv_path = RESULTS_DIR / "results.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["tier", "model", "thinking_budget", "query_id", "run", "agent", "latency_ms", "pass", "metrics_match", "dimension_match", "notes"])
        writer.writeheader()
        writer.writerows(csv_rows)
    print(f"\n[benchmark] CSV written: {csv_path}")

    # Write report
    report_path = RESULTS_DIR / "report.md"
    _write_extractor_report(report_path, csv_rows, tiers_to_test)
    print(f"[benchmark] Report written: {report_path}")

    # Print summary table
    _print_summary(csv_rows, tiers_to_test)


def _print_summary(rows: list[dict], tiers: list[str]):
    from statistics import median

    print(f"\n{'='*70}")
    print(f"  EXTRACTOR BENCHMARK SUMMARY")
    print(f"{'='*70}")
    print(f"  {'Tier':<12} {'Agent':<22} {'Median ms':>10} {'Pass rate':>10}")
    print(f"  {'-'*12} {'-'*22} {'-'*10} {'-'*10}")

    for tier in tiers:
        for agent in ["request_analyzer", "dimension_extractor"]:
            tier_rows = [r for r in rows if r["tier"] == tier and r["agent"] == agent]
            if not tier_rows:
                continue
            latencies = [r["latency_ms"] for r in tier_rows if r["latency_ms"] > 0]
            med = int(median(latencies)) if latencies else 0
            pass_rate = sum(1 for r in tier_rows if r["pass"]) / len(tier_rows)
            status = "PASS" if pass_rate == 1.0 else f"FAIL ({pass_rate:.0%})"
            print(f"  {tier:<12} {agent:<22} {med:>10,} {status:>10}")

    print(f"{'='*70}\n")


def _write_extractor_report(path: Path, rows: list[dict], tiers: list[str]):
    from statistics import median
    from datetime import datetime

    lines = [
        "# Extractor Benchmark Report",
        "",
        f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "## Summary",
        "",
        "| Tier | Budget | Agent | Median ms | Pass Rate | Verdict |",
        "|------|--------|-------|----------:|----------:|---------|",
    ]

    for tier in tiers:
        for agent in ["request_analyzer", "dimension_extractor"]:
            tier_rows = [r for r in rows if r["tier"] == tier and r["agent"] == agent]
            if not tier_rows:
                continue
            budgets = {r["thinking_budget"] for r in tier_rows}
            budget = next(iter(budgets), "?")
            latencies = [r["latency_ms"] for r in tier_rows if r["latency_ms"] > 0]
            med = int(median(latencies)) if latencies else 0
            pass_rate = sum(1 for r in tier_rows if r["pass"]) / len(tier_rows)
            verdict = "PASS" if pass_rate == 1.0 else "**FAIL**"
            lines.append(f"| {tier} | {budget} | {agent} | {med:,} | {pass_rate:.0%} | {verdict} |")

    lines += [
        "",
        "## Decision",
        "",
        "Fill in after reviewing the table above:",
        "",
        "- **Winner for request_analyzer**: (fastest tier that passes all queries)",
        "- **Winner for dimension_extractor**: (fastest tier that passes all queries)",
        "",
        "## Raw Results",
        "",
        "| Tier | Query | Run | Agent | ms | Pass | Notes |",
        "|------|-------|-----|-------|----|------|-------|",
    ]
    for r in rows:
        lines.append(f"| {r['tier']} | {r['query_id']} | {r['run']} | {r['agent']} | {r['latency_ms']:,} | {r['pass']} | {r['notes']} |")

    path.write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Benchmark extraction agents across model tiers.")
    parser.add_argument("--tiers", nargs="+", default=["ultra", "fast", "standard"],
                        help="Tiers to test (default: ultra fast standard)")
    parser.add_argument("--runs", type=int, default=1, help="Runs per query per tier (default: 1)")
    parser.add_argument("--call-delay", type=float, default=0.0,
                        help="Seconds between API calls. Default 0 (Vertex AI). Use 13 for free-tier API key.")
    args = parser.parse_args()
    run_benchmark(args.tiers, args.runs, args.call_delay)


if __name__ == "__main__":
    main()
