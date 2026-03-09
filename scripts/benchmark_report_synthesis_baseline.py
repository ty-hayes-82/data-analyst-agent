"""
Minimal baseline: send tiny prompt to each model via genai Client (no ADK, no tools).
Establishes raw model speeds and verifies model routing.
Tests with/without thinking budget when the model supports it.

Usage:
    python scripts/benchmark_report_synthesis_baseline.py
    python scripts/benchmark_report_synthesis_baseline.py --tiers ultra flash_2_5 flash_2_5_thinking standard pro
"""

import argparse
import os
import sys
import time
from pathlib import Path

import yaml

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
GITLAB_ROOT = PROJECT_ROOT.parent
RESULTS_DIR = PROJECT_ROOT / "results" / "benchmark_report_synthesis"

# Default prompt file: real narrative prompt for realistic latency
DEFAULT_PROMPT_FILE = GITLAB_ROOT / "outputs" / "debug" / "narrative_prompt_LRPM.txt"

# Fallback minimal prompt when no file (used if --prompt-file is not set and default file missing)
MINIMAL_PROMPT = """You are a report synthesis agent. Summarize in 2 sentences:

NARRATIVE: Total LRPM stable at 2.69 (0.0% var).
DATA_ANALYST: LRPM Level 0-1 Drill-Down.
HIERARCHICAL: Total Variance +0.00. Central +1.2%, East -0.8%.
ALERTS: 1 low-severity alert.
STATS: 37 items, 59 periods.

Write the executive summary."""


def _setup():
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    try:
        from dotenv import load_dotenv
        if (PROJECT_ROOT / ".env").exists():
            load_dotenv(PROJECT_ROOT / ".env", override=False)
    except ImportError:
        pass


def _thinking_supported(tier_cfg: dict) -> bool:
    """True if model supports thinking and we can test with/without."""
    model = tier_cfg.get("model", "")
    if "flash-lite" in model or "gemini-2.0-flash" in model:
        return False
    if "gemini-2.5-flash" in model or ("gemini-3" in model and "flash" in model):
        return True
    if "gemini-2.5-pro" in model or ("gemini-3" in model and "pro" in model):
        return True
    return False


def run_baseline(tiers: list[str], variants: str = "all", prompt: str | None = None):
    from google.genai import Client
    from google.genai import types

    _setup()
    config_path = PROJECT_ROOT / "config" / "agent_models.yaml"
    with open(config_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    all_tiers = cfg["model_tiers"]

    contents = prompt or MINIMAL_PROMPT

    location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    use_vertex = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "false").lower() == "true"
    project = os.getenv("GOOGLE_CLOUD_PROJECT") if use_vertex else None

    client = Client(vertexai=use_vertex, project=project, location=location if use_vertex else None)
    base_config = types.GenerateContentConfig(temperature=0.2, max_output_tokens=512)

    print(f"\n{'='*70}")
    print("  REPORT SYNTHESIS BASELINE (no tools)")
    print(f"  Prompt: {len(contents):,} chars")
    print(f"  Tiers: {tiers}  Variants: {variants}")
    print(f"{'='*70}\n")

    results = []
    for tier_name in tiers:
        if tier_name not in all_tiers:
            print(f"  [skip] Unknown: {tier_name}")
            continue
        tier_cfg = all_tiers[tier_name]
        model = tier_cfg["model"]
        budget = tier_cfg.get("thinking_budget")
        support_thinking = _thinking_supported(tier_cfg)

        variants_to_run = []
        if variants == "all" and support_thinking:
            variants_to_run.append(("no_thinking", None))
            thinking_cfg = None
            if "gemini-2.5-flash" in model or ("gemini-3" in model and "flash" in model):
                try:
                    thinking_cfg = types.ThinkingConfig(thinking_budget=budget or 8192)
                except Exception:
                    pass
            elif "pro" in model:
                try:
                    thinking_cfg = types.ThinkingConfig(include_thoughts=True, thinking_budget=budget)
                except Exception:
                    try:
                        thinking_cfg = types.ThinkingConfig(include_thoughts=True)
                    except Exception:
                        thinking_cfg = None
            if thinking_cfg:
                variants_to_run.append(("thinking", thinking_cfg))
        if not variants_to_run:
            variants_to_run.append((tier_name if not support_thinking else "no_thinking", None))

        for variant_name, thinking_config in variants_to_run:
            label = f"{tier_name}" if variant_name == tier_name else f"{tier_name} ({variant_name})"
            max_tokens = 2048 if len(contents) > 1000 else 512
            config_kwargs = {"temperature": 0.2, "max_output_tokens": max_tokens}
            if thinking_config:
                config_kwargs["thinking_config"] = thinking_config
            gen_config = types.GenerateContentConfig(**config_kwargs)

            print(f"  {label} model={model}...", end=" ", flush=True)
            try:
                t0 = time.perf_counter()
                resp = client.models.generate_content(model=model, contents=contents, config=gen_config)
                ms = round((time.perf_counter() - t0) * 1000)
                print(f"{ms:,}ms  output={len(resp.text or '')} chars")
                results.append({
                    "tier": label,
                    "model": model,
                    "variant": variant_name,
                    "latency_ms": ms,
                    "output_chars": len(resp.text or ""),
                })
            except Exception as e:
                print(f"ERROR: {e}")
                results.append({"tier": label, "model": model, "variant": variant_name, "latency_ms": 0, "error": str(e)})

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / "baseline_speeds.txt"
    lines = ["Tier\tVariant\tModel\tLatency_ms", "-" * 60]
    for r in results:
        lines.append(f"{r['tier']}\t{r.get('variant', '')}\t{r['model']}\t{r.get('latency_ms', 0)}")
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n[benchmark] Results: {out}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--compare-3",
        action="store_true",
        help="Quick 3-way: flash_2_5, standard, pro (each with/without thinking when supported)",
    )
    parser.add_argument(
        "--tiers",
        nargs="+",
        default=["ultra", "flash_2_5", "flash_2_5_thinking", "standard", "fast", "advanced", "pro"],
        help="Tiers to test. For thinking-capable models, run both no_thinking and thinking when --variants=all",
    )
    parser.add_argument(
        "--variants",
        choices=["all", "default"],
        default="all",
        help="all=test with/without thinking when supported; default=use tier config only",
    )
    parser.add_argument(
        "--prompt-file",
        type=Path,
        default=DEFAULT_PROMPT_FILE,
        help=f"Prompt file for baseline (default: outputs/debug/narrative_prompt_LRPM.txt)",
    )
    parser.add_argument(
        "--minimal",
        action="store_true",
        help="Use minimal 302-char prompt instead of narrative_prompt_LRPM.txt",
    )
    args = parser.parse_args()
    tiers = ["flash_2_5", "standard", "pro"] if args.compare_3 else args.tiers
    if args.minimal:
        prompt = MINIMAL_PROMPT
    elif args.prompt_file.exists():
        prompt = args.prompt_file.read_text(encoding="utf-8")
    else:
        print(f"[warn] Prompt file not found: {args.prompt_file}, using minimal prompt")
        prompt = MINIMAL_PROMPT
    run_baseline(tiers, args.variants, prompt=prompt)


if __name__ == "__main__":
    main()
