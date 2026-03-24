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

load_dotenv(PROJECT_ROOT / ".env")

FLASH_LITE = "gemini-3.1-flash-lite-preview"
PRO = "gemini-3.1-pro-preview"

def parse_args():
    parser = argparse.ArgumentParser(description="Hybrid CEO brief: Rank signals (code) -> Curate (LLM) -> Synthesize (LLM)")
    parser.add_argument("--cache-dir", type=str, help="Path to cache directory with metric_*.json files")
    parser.add_argument("--lite-model", default=FLASH_LITE, help="LLM for Pass 1 (Curation)")
    parser.add_argument("--pro-model", default=PRO, help="LLM for Pass 2 (Synthesis)")
    parser.add_argument("--top-signals", type=int, default=30, help="Number of signals to extract in Pass 0")
    parser.add_argument("--max-curated", type=int, default=12, help="Max signals for Pass 2 after curation")
    parser.add_argument("--skip-curation", action="store_true", help="Skip Pass 1 (LLM curation) and send all Pass 0 signals to Pass 2")
    return parser.parse_args()

def main():
    args = parse_args()
    
    # 0. Discovery
    cache_dir = Path(args.cache_dir) if args.cache_dir else BriefUtils.get_latest_cache_dir()
    if not cache_dir:
        print("No cache directory found.")
        sys.exit(1)
    
    print(f"Using cache: {cache_dir}")
    metrics = BriefUtils.load_metrics(cache_dir)
    totals = BriefUtils.get_network_totals(metrics)
    
    # Pass 0: Rank
    ranker = SignalRanker(metrics)
    signals = ranker.extract_all()
    print(f"Pass 0: Extracted {len(signals)} signals.")
    
    client = genai.Client()
    
    # Pass 1: Curate
    if args.skip_curation:
        print("Pass 1: Skipped.")
        curated_signals = signals[:args.max_curated]
        thesis = "Mixed operational signals."
        curation_results = None
    else:
        print(f"Pass 1: Curating with {args.lite_model}...")
        curation_results = pass1_curate(client, args.lite_model, totals, signals[:args.top_signals], args.max_curated)
        curated_signals = merge_pass1_kept_into_signals(signals, curation_results["kept"])
        thesis = curation_results["narrative_thesis"]
        print(f"Pass 1: Selected {len(curated_signals)} signals. [{curation_results['_elapsed']:.1f}s]")
    
    # Pass 2: Synthesize
    period = "the analysis week" # Could be extracted from metadata
    print(f"Pass 2: Synthesizing brief with {args.pro_model}...")
    brief = pass2_brief(client, args.pro_model, totals, curated_signals, thesis, period)
    print(f"Pass 2: Brief generated. [{brief['_elapsed']:.1f}s]")
    
    # 3. Save Artifacts
    ts = time.strftime("%Y%m%d_%H%M%S")
    out_dir = PROJECT_ROOT / "outputs" / "benchmarks" / "hybrid_runs" / ts
    out_dir.mkdir(parents=True, exist_ok=True)
    
    (out_dir / "pass0_signals.json").write_text(json.dumps(signals, indent=2), encoding="utf-8")
    if curation_results:
        (out_dir / "pass1_curation.json").write_text(json.dumps(curation_results, indent=2), encoding="utf-8")
    (out_dir / "pass2_brief.json").write_text(json.dumps(brief, indent=2), encoding="utf-8")
    (out_dir / "network_totals.json").write_text(json.dumps(totals, indent=2), encoding="utf-8")
    
    # Render to stdout
    print("\n" + "="*80)
    print(f"CEO BRIEF: {period}")
    print("="*80)
    print(f"BOTTOM LINE: {brief['bottom_line']}\n")
    print("WHAT MOVED:")
    for item in brief['what_moved']:
        print(f"  - {item['label']}: {item['line']}")
    print("\nWHERE IT CAME FROM:")
    print(f"  Positive: {brief['where_it_came_from']['positive']}")
    print(f"  Drag: {brief['where_it_came_from']['drag']}")
    print(f"\nWHY IT MATTERS: {brief['why_it_matters']}")
    print(f"\nOUTLOOK: {brief['next_week_outlook']}")
    print("="*80)
    print(f"Run directory: {out_dir}")

if __name__ == "__main__":
    main()
