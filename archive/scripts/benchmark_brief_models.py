import os
import sys
import json
import time
import re
import asyncio
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Tuple

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from data_analyst_agent.config import config
from google import genai
from google.genai import types

# Import agent components
from data_analyst_agent.sub_agents.executive_brief_agent.agent import (
    EXECUTIVE_BRIEF_RESPONSE_SCHEMA,
    _format_instruction,
)
from data_analyst_agent.sub_agents.executive_brief_agent.prompt import EXECUTIVE_BRIEF_INSTRUCTION

# Benchmark candidates (Vertex AI short names)
# Based on discovery in us-central1
MODELS = [
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-3-flash-preview",
    "gemini-3.1-flash-lite-preview",
    "gemini-3.1-pro-preview",
]

# Latest cache path
def _resolve_cache_path(run_dir: Path) -> Path:
    # New layout: .cache is in the run root
    # Legacy: .cache is in the run root (no change for .cache location itself based on plan)
    # However, plan says "metrics/ metric_*.json", but .cache stays at root for now.
    return run_dir / ".cache" / "digest.json"

RUN_DIR = PROJECT_ROOT / "outputs" / "ops_metrics_ds" / "lob_ref" / "Line_Haul" / "20260323_122337"
CACHE_PATH = _resolve_cache_path(RUN_DIR)

@dataclass
class ModelResult:
    model: str
    iteration: int
    latency_ms: int
    input_chars: int
    output_chars: int
    json_parse_ok: bool
    score: float = 0.0
    scores: Dict[str, float] = None
    raw_response: str = ""

def count_nums(text: str) -> int:
    """Count specific numeric values ($, %, numbers with K/M/B)."""
    patterns = [
        r'\$[\d,]+(?:\.\d+)?[KMB]?', # Dollar amounts
        r'\d+(?:,\d{3})*(?:\.\d+)?%', # Percentages
        r'\d+(?:,\d{3})*(?:\.\d+)?[KMB](?!\w)', # Units with scale
        r'\d+(?:,\d{3})*\.\d+', # Decimals
        r'\b\d{3,}\b', # Large integers (e.g. 195K)
    ]
    return sum(len(re.findall(p, text)) for p in patterns)

def score_brief(brief: Dict[str, Any], source_digest: str) -> Tuple[float, Dict[str, float]]:
    """Composite scoring for a brief JSON."""
    scores = {
        "numeric_density": 0.0,
        "structure": 0.0,
        "trend_classification": 0.0,
        "implication": 0.0,
        "grounding": 0.0,
        "leadership": 0.0
    }
    
    all_text = json.dumps(brief)
    nums = count_nums(all_text)
    # Density: Expect > 15 nums in a network brief for full score
    scores["numeric_density"] = min(1.0, nums / 15.0) * 100
    
    # Structure: Required fields
    required = ["header", "body"]
    if all(k in brief for k in required):
        body = brief.get("body", {})
        sections = body.get("sections", [])
        if sections and len(sections) >= 3:
            scores["structure"] = 100
    
    # Trend classification
    valid_cl = {"positive momentum", "developing trend", "persistent issue", "one-week noise", "watchable", "structural shift"}
    trends = []
    for section in brief.get("body", {}).get("sections", []):
        if "Trends" in section.get("title", ""):
            trends = section.get("insights", [])
    
    if trends:
        classified = sum(1 for t in trends if any(cl in t.get("content", "").lower() for cl in valid_cl))
        scores["trend_classification"] = (classified / len(trends)) * 100
    else:
        # Check if trends are just in prose
        found = sum(1 for cl in valid_cl if cl in all_text.lower())
        scores["trend_classification"] = min(1.0, found / 2.0) * 100

    # Implication/Mechanism: Check if "->" or "because" or "meaning" exists
    implications = len(re.findall(r'->|because|meaning|leads to|results in', all_text.lower()))
    scores["implication"] = min(1.0, implications / 4.0) * 100
    
    # Leadership Focus: Starts with imperative verb
    imperatives = ["Hold", "Intervene", "Rebalance", "Correct", "Audit", "Halt", "Renegotiate", "Audit", "Verify", "Re-evaluate", "Focus", "Direct"]
    leadership_section = next((s for s in brief.get("body", {}).get("sections", []) if "Leadership" in s.get("title", "")), {})
    actions = leadership_section.get("insights", [])
    if actions:
        good_actions = sum(1 for a in actions if any(a.get("content", "").startswith(v) for v in imperatives))
        scores["leadership"] = (good_actions / len(actions)) * 100
    
    # Factual grounding: Check if some cited numbers exist in digest
    brief_nums = re.findall(r'\$[\d,]+(?:\.\d+)?[KMB]?|\d+(?:,\d{3})*(?:\.\d+)?%', all_text)
    if brief_nums:
        matches = sum(1 for n in brief_nums[:10] if n in source_digest)
        scores["grounding"] = (matches / min(len(brief_nums), 10)) * 100
    
    # Weighted composite
    # Density 25%, structure 15%, trends 15%, implication 15%, grounding 15%, leadership 15%
    total = (
        scores["numeric_density"] * 0.25 +
        scores["structure"] * 0.15 +
        scores["trend_classification"] * 0.15 +
        scores["implication"] * 0.15 +
        scores["grounding"] * 0.15 +
        scores["leadership"] * 0.15
    )
    
    return round(total, 1), scores

async def run_benchmark():
    print(f"Loading cached digest from {CACHE_PATH}")
    if not CACHE_PATH.exists():
        print("Cache not found. Run the E2E pipeline first.")
        return
    
    payload = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    digest = payload.get("digest", "")
    metric_names = payload.get("metric_names", [])
    
    instruction = _format_instruction(
        EXECUTIVE_BRIEF_INSTRUCTION,
        metric_count=len(metric_names),
        analysis_period="Dec 07, 2025 - Mar 14, 2026",
        scope_preamble="Analysis for Line Haul division.",
        dataset_specific_append="",
        prompt_variant_append="",
    )
    
    user_message = (
        f"COMPARISON BASIS: WoW (week-over-week vs prior week).\n"
        f"Week ending: 2026-03-14\n"
        f"Metrics: {', '.join(sorted(metric_names))}\n\n"
        f"DIGEST:\n{digest}\n\n"
        "Generate the CEO brief JSON."
    )
    
    print(f"Payload: Instruction={len(instruction)} chars, UserMessage={len(user_message)} chars")
    
    client = genai.Client(vertexai=True)
    results = []
    
    for model_name in MODELS:
        print(f"\nBenchmarking {model_name}...")
        for i in range(1, 4): # N=3 iterations
            t0 = time.perf_counter()
            try:
                # Use a 120s timeout per call
                loop = asyncio.get_running_loop()
                response = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        lambda: client.models.generate_content(
                            model=model_name,
                            contents=user_message,
                            config=types.GenerateContentConfig(
                                system_instruction=instruction,
                                response_mime_type="application/json",
                                response_schema=EXECUTIVE_BRIEF_RESPONSE_SCHEMA,
                                temperature=0.2,
                            )
                        )
                    ),
                    timeout=120
                )
                ms = int((time.perf_counter() - t0) * 1000)
                raw = response.text or ""
                
                try:
                    brief_json = json.loads(raw)
                    parse_ok = True
                    score, sub_scores = score_brief(brief_json, digest)
                except Exception as e:
                    print(f"  Iteration {i} JSON FAIL: {e}")
                    parse_ok = False
                    score = 0.0
                    sub_scores = {}
                
                res = ModelResult(
                    model=model_name,
                    iteration=i,
                    latency_ms=ms,
                    input_chars=len(user_message) + len(instruction),
                    output_chars=len(raw),
                    json_parse_ok=parse_ok,
                    score=score,
                    scores=sub_scores,
                    raw_response=raw
                )
                results.append(res)
                print(f"  Iteration {i}: {ms}ms, score={score}")
                
            except asyncio.TimeoutError:
                print(f"  Iteration {i}: TIMEOUT after 120s")
            except Exception as e:
                print(f"  Iteration {i} ERROR: {e}")
    
    # Save results
    ts = time.strftime("%Y%m%d_%H%M%S")
    out_dir = PROJECT_ROOT / "outputs" / "benchmarks"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"brief_model_benchmark_{ts}.json"
    
    with open(out_file, "w") as f:
        json.dump([asdict(r) for r in results], f, indent=2)
    
    print(f"\nBenchmark complete. Results saved to {out_file}")
    
    # Print summary table
    print("\n" + "="*80)
    print(f"{'Model':<30} {'Avg Latency':>12} {'Avg Score':>10} {'Success'}")
    print("-" * 80)
    
    model_stats = {}
    for r in results:
        if r.model not in model_stats:
            model_stats[r.model] = {"latencies": [], "scores": [], "success": 0}
        model_stats[r.model]["latencies"].append(r.latency_ms)
        if r.json_parse_ok:
            model_stats[r.model]["scores"].append(r.score)
            model_stats[r.model]["success"] += 1
    
    for m, s in model_stats.items():
        avg_lat = int(sum(s["latencies"]) / len(s["latencies"]))
        avg_score = round(sum(s["scores"]) / len(s["scores"]), 1) if s["scores"] else 0.0
        success_rate = f"{s['success']}/{len(s['latencies'])}"
        print(f"{m:<30} {avg_lat:>10}ms {avg_score:>10} {success_rate:>7}")
    print("="*80)

if __name__ == "__main__":
    asyncio.run(run_benchmark())
