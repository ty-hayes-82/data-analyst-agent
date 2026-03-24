import json
import os
import sys
import time
import argparse
from pathlib import Path
from typing import Dict, Any, List, Optional
from google import genai
from google.genai import types
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from data_analyst_agent.brief_utils import (
    BriefUtils,
    SignalRanker,
    merge_pass1_kept_into_signals,
    pass1_curate,
    pass2_brief,
)
from data_analyst_agent.sub_agents.executive_brief_agent.report_utils import (
    _collect_metric_reports,
    _collect_metric_json_data,
    _build_slim_digest_from_json,
)

load_dotenv(PROJECT_ROOT / ".env")

FLASH_LITE = "gemini-3.1-flash-lite-preview"
PRO = "gemini-3.1-pro-preview"

# Baseline Step 1 System Instruction (from benchmark_two_step.py)
BASELINE_STEP1_SYSTEM = (
    "You are a senior operational analyst. You are given a 'slim digest' of multiple metric reports.\n"
    "Your job is to CONDENSE this into a single structured JSON summary that captures only the MOST CRITICAL moves.\n"
    "IGNORE low-materiality cards. FOCUS on contradictions (e.g. yield up but volume down) and severe variances (>20%).\n"
)

def run_baseline_pipeline(client, cache_dir: Path, pro_model: str, lite_model: str):
    """Existing benchmark_two_step.py logic (Step 1: Lite Condense, Step 2: Pro Synthesis)."""
    reports = _collect_metric_reports(cache_dir)
    json_data = _collect_metric_json_data(cache_dir)
    slim_digest = _build_slim_digest_from_json(reports, json_data)
    
    # Step 1: Condense
    t0 = time.time()
    r1 = client.models.generate_content(
        model=lite_model,
        contents=f"SLIM DIGEST:\n{slim_digest}",
        config=types.GenerateContentConfig(
            system_instruction=BASELINE_STEP1_SYSTEM,
            response_mime_type="application/json",
            temperature=0.1
        )
    )
    e1 = time.time() - t0
    condensed = r1.text
    
    totals = BriefUtils.get_network_totals(BriefUtils.load_metrics(cache_dir))
    
    # Pass 2
    t0 = time.time()
    brief = pass2_brief(client, pro_model, totals, [{"category": "Baseline", "detail": condensed}], "Baseline condensed summary.", "the analysis week")
    e2 = time.time() - t0
    
    return {
        "pipeline": "baseline",
        "step1_time": e1,
        "step2_time": e2,
        "total_time": e1 + e2,
        "brief": brief
    }

def run_hybrid_pro_pipeline(client, cache_dir: Path, pro_model: str):
    """Pass 0 (Code) -> Pass 2 (Pro)."""
    metrics = BriefUtils.load_metrics(cache_dir)
    totals = BriefUtils.get_network_totals(metrics)
    ranker = SignalRanker(metrics)
    signals = ranker.extract_all()
    
    t0 = time.time()
    brief = pass2_brief(client, pro_model, totals, signals[:12], "Deterministic ranking.", "the analysis week")
    el = time.time() - t0
    
    return {
        "pipeline": "hybrid_pro",
        "pass0_signals": len(signals),
        "pass2_time": el,
        "total_time": el,
        "brief": brief
    }

def run_hybrid_lite_pro_pipeline(client, cache_dir: Path, pro_model: str, lite_model: str):
    """Pass 0 (Code) -> Pass 1 (Lite Curate) -> Pass 2 (Pro Synthesis)."""
    metrics = BriefUtils.load_metrics(cache_dir)
    totals = BriefUtils.get_network_totals(metrics)
    ranker = SignalRanker(metrics)
    signals = ranker.extract_all()
    
    curation = pass1_curate(client, lite_model, totals, signals[:30], 12)
    curated_signals = merge_pass1_kept_into_signals(signals, curation["kept"])
    
    brief = pass2_brief(client, pro_model, totals, curated_signals, curation["narrative_thesis"], "the analysis week")
    
    return {
        "pipeline": "hybrid_lite_pro",
        "pass0_signals": len(signals),
        "pass1_time": curation["_elapsed"],
        "pass2_time": brief["_elapsed"],
        "total_time": curation["_elapsed"] + brief["_elapsed"],
        "brief": brief,
        "curation": curation
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-dir", type=str)
    parser.add_argument("--iterations", type=int, default=1)
    args = parser.parse_args()
    
    cache_dir = Path(args.cache_dir) if args.cache_dir else BriefUtils.get_latest_cache_dir()
    if not cache_dir:
        print("No cache directory found.")
        sys.exit(1)
        
    client = genai.Client()
    results = []
    
    for i in range(args.iterations):
        print(f"\nIteration {i+1}/{args.iterations}", flush=True)
        
        print("Running Baseline...", flush=True)
        results.append(run_baseline_pipeline(client, cache_dir, PRO, FLASH_LITE))
        
        print("Running Hybrid Pro...", flush=True)
        results.append(run_hybrid_pro_pipeline(client, cache_dir, PRO))
        
        print("Running Hybrid Lite+Pro...", flush=True)
        results.append(run_hybrid_lite_pro_pipeline(client, cache_dir, PRO, FLASH_LITE))
        
    ts = time.strftime("%Y%m%d_%H%M%S")
    out_file = PROJECT_ROOT / "outputs" / "benchmarks" / f"hybrid_comparison_{ts}.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(results, indent=2), encoding="utf-8")
    
    print(f"\nBenchmark complete. Results saved to {out_file}", flush=True)
    
    # Print summary table
    print("\nSUMMARY:", flush=True)
    print(f"{'Pipeline':<20} | {'Total Time':<10} | {'Bottom Line First 50 chars'}", flush=True)
    print("-" * 60, flush=True)
    for r in results:
        bl = r["brief"]["bottom_line"][:50] + "..."
        print(f"{r['pipeline']:<20} | {r['total_time']:>9.1f}s | {bl}", flush=True)

if __name__ == "__main__":
    main()
