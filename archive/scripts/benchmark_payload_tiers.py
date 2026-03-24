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
from data_analyst_agent.sub_agents.executive_brief_agent.report_utils import (
    _build_digest_from_json,
    _build_slim_digest,
    _build_slim_digest_from_json,
    _compress_metadata_bullets,
    format_variance_amount,
)

# Benchmark model
MODEL = "gemini-3.1-flash-lite-preview"

# Latest cache path
CACHE_DIR = PROJECT_ROOT / "outputs" / "ops_metrics_ds" / "lob_ref" / "Line_Haul" / "20260323_115554" / ".cache"
CACHE_PATH = CACHE_DIR / "digest.json"

@dataclass
class TierResult:
    tier: str
    iteration: int
    latency_ms: int
    instruction_chars: int
    user_message_chars: int
    output_chars: int
    json_parse_ok: bool
    score: float = 0.0
    scores: Dict[str, float] = None
    raw_response: str = ""
    instruction: str = ""
    user_message: str = ""

def build_coverage_checklist(json_data: Dict[str, Any]) -> str:
    """Extract MUST COVER items from CRITICAL/HIGH cards."""
    must_cover = []
    for metric, payload in json_data.items():
        analysis = payload.get("analysis", {})
        alert_scoring = analysis.get("alert_scoring", {})
        top_alerts = alert_scoring.get("top_alerts", [])
        for alert in top_alerts:
            if alert.get("priority") in ("critical", "high"):
                dim = alert.get("dimension_value", "")
                val = alert.get("variance_pct", 0)
                must_cover.append(f"{dim} ({val:+.1f}%)")
        
        # Also check narrative cards
        narrative = payload.get("narrative_results", {})
        if isinstance(narrative, str):
            try: narrative = json.loads(narrative)
            except: narrative = {}
        cards = narrative.get("insight_cards", [])
        for card in cards:
            if card.get("priority") in ("critical", "high"):
                title = card.get("title", "")
                must_cover.append(title)
                
    # Deduplicate and format
    unique = sorted(list(set(must_cover)))[:5] # Cap at 5
    if not unique:
        return ""
    return "MUST COVER: " + ", ".join(unique)

def build_guardrail_block() -> str:
    return """GUARDRAILS (hard reject if violated):
- Do NOT mention reporting lags, lead indicators, or day-count cadences unless verbatim in the digest.
- Network total revenue is ~$23M. Do NOT cite $9-10M as network revenue (that is a single region).
- Use "$" for dollar amounts. Never say "units" for currency or rate metrics.
"""

def build_structured_digest(json_data: Dict[str, Any]) -> str:
    """Build a compact fact-based digest from hierarchy top_drivers."""
    lines = []
    for metric, payload in sorted(json_data.items()):
        h = payload.get("hierarchical_analysis", {})
        l0 = h.get("level_0", {})
        total_drivers = l0.get("top_drivers", [])
        if not total_drivers: continue
        
        total = total_drivers[0]
        curr = format_variance_amount(total.get("current"), "dollar")
        var_abs = format_variance_amount(total.get("variance_dollar"), "dollar")
        var_pct = total.get("variance_pct", 0)
        
        line = f"{metric.upper()}: {curr} ({var_abs}, {var_pct:+.1f}%)"
        
        # Add top 2 drivers from level 2
        l2 = h.get("level_2", {})
        drivers = l2.get("top_drivers", [])[:2]
        if drivers:
            driver_parts = []
            for d in drivers:
                name = d.get("item")
                d_var = format_variance_amount(d.get("variance_dollar"), "dollar")
                d_pct = d.get("variance_pct", 0)
                driver_parts.append(f"{name} {d_var} ({d_pct:+.1f}%)")
            line += " | " + ", ".join(driver_parts)
        lines.append(line)
    return "\n".join(lines)

def load_prompt(lite: bool = False) -> str:
    path = PROJECT_ROOT / "config" / "prompts" / ("executive_brief_ceo_lite.md" if lite else "executive_brief_ceo.md")
    return path.read_text(encoding="utf-8").strip()

def sanitize_json_data(json_data: Dict[str, Any]) -> Dict[str, Any]:
    """Remove Infinity/NaN and strip bulk alert arrays."""
    cleaned = {}
    for metric, payload in json_data.items():
        # Deep copy to avoid modifying cache
        p = json.loads(json.dumps(payload)) 
        
        # 1. Strip bulk alerts
        if "alert_scoring" in p.get("analysis", {}):
            alert_block = p["analysis"]["alert_scoring"]
            if "all_scored_alerts" in alert_block: del alert_block["all_scored_alerts"]
            if "suppressed_alerts" in alert_block: del alert_block["suppressed_alerts"]
            
        # 2. Filter Corporate when share < 1%
        h = p.get("hierarchical_analysis", {})
        for level in ["level_1", "level_2"]:
            if level in h:
                drivers = h[level].get("top_drivers", [])
                h[level]["top_drivers"] = [d for d in drivers if not (d.get("item") == "Corporate" and d.get("share_current", 1.0) < 0.01)]
        
        # 3. Sanitize Infinity/NaN (recursive)
        def _clean(obj):
            if isinstance(obj, float):
                if obj == float('inf') or obj == float('-inf') or obj != obj: # NaN
                    return None
                return obj
            if isinstance(obj, dict):
                return {k: _clean(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_clean(x) for x in obj]
            return obj
            
        cleaned[metric] = _clean(p)
    return cleaned

def build_tier_payloads(cache_data: Dict[str, Any]) -> Dict[str, Tuple[str, str]]:
    digest_full = cache_data.get("digest", "")
    json_data = cache_data.get("json_data", {})
    metric_names = cache_data.get("metric_names", [])
    analysis_period = cache_data.get("analysis_period", "Dec 07, 2025 - Mar 14, 2026")
    period_end = cache_data.get("period_end", "2026-03-14")
    unit = cache_data.get("presentation_unit")
    
    # --- Tier 0: BASELINE ---
    instr_0 = _format_instruction(load_prompt(False), metric_count=len(metric_names), analysis_period=analysis_period, scope_preamble="", dataset_specific_append="", prompt_variant_append="")
    
    # Terminal block logic from agent.py
    terminal_lines = []
    for m, p in json_data.items():
        h = p.get("hierarchical_analysis") or {}
        l2 = h.get("level_2") or {}
        cards = l2.get("insight_cards", [])
        if cards:
            items = []
            for c in cards[:3]:
                title = c.get("title", "")
                ev = c.get("evidence", {})
                name = title.replace("Level 2 Variance Driver: ", "")
                pct = ev.get("variance_pct")
                dollar = ev.get("variance_dollar", 0)
                items.append(f"{name} ({pct:+.1f}%, ${abs(dollar):,.0f})")
            terminal_lines.append(f"  {m}: {', '.join(items)}")
    terminal_block = "TERMINAL/DIVISION DRIVERS (Level 2):\n" + "\n".join(terminal_lines) + "\n\n"
    
    user_0 = (
        f"COMPARISON BASIS: WoW (week-over-week vs prior week).\n"
        f"Week ending: {period_end}\n"
        f"Metrics: {', '.join(sorted(metric_names))}\n\n"
        f"{terminal_block}"
        f"Dataset Context: Line Haul metrics.\n\n"
        f"{digest_full}\n\n"
        "Generate the CEO brief JSON."
    )
    
    # --- Tier 1: CONSERVATIVE ---
    run_dir = CACHE_DIR.parent
    reports = {}
    
    # Priority 1: metrics/ subfolder
    # Priority 2: root
    metrics_dir = run_dir / "metrics"
    search_dirs = [metrics_dir, run_dir] if metrics_dir.exists() else [run_dir]
    
    processed_files = set()
    for s_dir in search_dirs:
        for md_file in sorted(s_dir.glob("metric_*.md")):
            if md_file.name in processed_files:
                continue
            name = md_file.stem.replace("metric_", "").replace("_", " ").replace("-", "/")
            reports[name] = md_file.read_text(encoding="utf-8")
            processed_files.add(md_file.name)
    
    digest_t1 = _build_slim_digest_from_json(reports, json_data, unit)
    
    user_1 = (
        f"COMPARISON BASIS: WoW (week-over-week vs prior week).\n"
        f"Week ending: {period_end}\n"
        f"Metrics: {', '.join(sorted(metric_names))}\n\n"
        f"{terminal_block}"
        f"Dataset Context: Line Haul metrics.\n\n"
        f"{digest_t1}\n\n"
        "Generate the CEO brief JSON."
    )
    
    # --- Tier 2: MODERATE ---
    filtered_reports = {}
    for name, content in reports.items():
        if "[CRITICAL]" in content or "[HIGH]" in content:
            filtered_reports[name] = content
    
    digest_t2 = _build_slim_digest(filtered_reports)
    
    user_2 = (
        f"COMPARISON BASIS: WoW (week-over-week vs prior week).\n"
        f"Week ending: {period_end}\n"
        f"Metrics: {', '.join(sorted(filtered_reports.keys()))}\n\n"
        f"{digest_t2}\n\n"
        "Generate the CEO brief JSON."
    )
    
    # --- Tier 3: AGGRESSIVE ---
    instr_3 = _format_instruction(load_prompt(True), metric_count=len(filtered_reports), analysis_period=analysis_period, scope_preamble="", dataset_specific_append="", prompt_variant_append="")
    
    guardrails = build_guardrail_block()
    must_cover = build_coverage_checklist(json_data)
    
    user_3 = (
        f"{guardrails}\n"
        f"{must_cover}\n\n"
        f"COMPARISON BASIS: WoW.\n"
        f"Week ending: {period_end}\n\n"
        f"{digest_t2}\n\n"
        "Generate the CEO brief JSON."
    )
    
    # --- Tier 4: MINIMAL ---
    digest_t4 = build_structured_digest(json_data)
    
    user_4 = (
        f"{guardrails}\n"
        f"{must_cover}\n\n"
        f"COMPARISON BASIS: WoW.\n"
        f"Week ending: {period_end}\n\n"
        f"FACTS:\n{digest_t4}\n\n"
        "Generate the CEO brief JSON."
    )

    # --- Tier 5: WINNER CANDIDATE ---
    cleaned_json = sanitize_json_data(json_data)
    # Tier 5 uses Tier 1's digest logic but with cleaned json_data
    digest_t5 = _build_slim_digest_from_json(reports, cleaned_json, unit)
    
    user_5 = (
        f"{guardrails}\n"
        f"{must_cover}\n\n"
        f"COMPARISON BASIS: WoW.\n"
        f"Week ending: {period_end}\n\n"
        f"{digest_t5}\n\n"
        "Generate the CEO brief JSON."
    )
    
    return {
        "Tier 0 (Baseline)": (instr_0, user_0),
        "Tier 1 (Conservative)": (instr_0, user_1),
        "Tier 2 (Moderate)": (instr_0, user_2),
        "Tier 3 (Aggressive)": (instr_3, user_3),
        "Tier 4 (Minimal)": (instr_3, user_4),
        "Tier 5 (Winner Candidate)": (instr_0, user_5),
    }

def score_brief_strict(brief: Dict[str, Any], source_digest: str) -> Tuple[float, Dict[str, float]]:
    """Strict rubric for brief evaluation."""
    scores = {
        "grounding": 0.0,   # 30 pts
        "causal": 0.0,      # 20 pts
        "structure": 0.0,   # 20 pts
        "specificity": 0.0, # 15 pts
        "voice": 0.0        # 15 pts
    }
    
    all_text = json.dumps(brief)
    
    # 1. Grounding (30 pts)
    # Check for specific revenue scale fabrication ($9M-$10M is wrong, should be ~$23M)
    if "9." in all_text or "10." in all_text:
        if "$9." in all_text or "$10." in all_text:
            scores["grounding"] -= 10 # Penalty for wrong network scale
            
    # Check for unit errors ("units" instead of $)
    if "units" in all_text.lower():
        scores["grounding"] -= 5
        
    # Check if numbers exist in source
    nums = re.findall(r'\$[\d,]+(?:\.\d+)?[KMB]?|\d+(?:,\d{3})*(?:\.\d+)?%', all_text)
    if nums:
        matches = sum(1 for n in nums[:10] if n in source_digest)
        scores["grounding"] += (matches / min(len(nums), 10)) * 30
    scores["grounding"] = max(0, min(30, scores["grounding"]))
    
    # 2. Causal (20 pts)
    causal_words = ["driven by", "despite", "offset", "because", "meaning", "leads to"]
    found_causal = sum(1 for w in causal_words if w in all_text.lower())
    scores["causal"] = min(20, (found_causal / 3.0) * 20)
    
    # 3. Structure (20 pts)
    required = ["bottom_line", "what_moved", "trend_status", "where_it_came_from", "why_it_matters", "outlook", "leadership_focus"]
    
    # Check both top-level and section titles
    found_required = set()
    for k in brief.keys():
        k_low = k.lower().replace(" ", "_")
        if k_low in required:
            found_required.add(k_low)
            
    sections = brief.get("body", {}).get("sections", [])
    for s in sections:
        t_low = s.get("title", "").lower().replace(" ", "_")
        if t_low in required:
            found_required.add(t_low)
            
    scores["structure"] = (len(found_required) / len(required)) * 20
    
    # 4. Specificity (15 pts)
    specific_locations = ["Atlanta", "Manteno", "Gary", "Phoenix", "Otay Mesa", "Lathrop"]
    found_locs = sum(1 for loc in specific_locations if loc in all_text)
    scores["specificity"] = min(15, (found_locs / 3.0) * 15)
    
    # 5. Voice (15 pts)
    # Check for leadership imperatives
    leadership = str(brief.get("leadership_focus", ""))
    imperatives = ["Hold", "Intervene", "Rebalance", "Correct", "Audit", "Halt", "Renegotiate", "Stop"]
    found_imp = sum(1 for imp in imperatives if imp in leadership)
    scores["voice"] = min(15, (found_imp / 2.0) * 15)
    
    total = sum(scores.values())
    return round(total, 1), scores

async def run_experiment():
    print(f"Loading cache from {CACHE_PATH}")
    cache_data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    
    tiers = build_tier_payloads(cache_data)
    
    client = genai.Client(vertexai=True)
    all_results = []
    
    for tier_name, (instr, user_msg) in tiers.items():
        print(f"\nBenchmarking {tier_name}...")
        print(f"  Instruction: {len(instr)} chars")
        print(f"  User Message: {len(user_msg)} chars")
        print(f"  Total Payload: {len(instr) + len(user_msg)} chars")
        
        for i in range(1, 4):
            t0 = time.perf_counter()
            try:
                response = await asyncio.wait_for(
                    asyncio.to_thread(
                        client.models.generate_content,
                        model=MODEL,
                        contents=user_msg,
                        config=types.GenerateContentConfig(
                            system_instruction=instr,
                            response_mime_type="application/json",
                            response_schema=EXECUTIVE_BRIEF_RESPONSE_SCHEMA,
                            temperature=0.2,
                        )
                    ),
                    timeout=120
                )
                ms = int((time.perf_counter() - t0) * 1000)
                raw = response.text or ""
                
                try:
                    brief_json = json.loads(raw)
                    parse_ok = True
                except Exception as e:
                    print(f"    Iter {i} JSON FAIL: {e}")
                    parse_ok = False
                
                res = TierResult(
                    tier=tier_name,
                    iteration=i,
                    latency_ms=ms,
                    instruction_chars=len(instr),
                    user_message_chars=len(user_msg),
                    output_chars=len(raw),
                    json_parse_ok=parse_ok,
                    score=0.0,
                    scores={},
                    raw_response=raw,
                    instruction=instr,
                    user_message=user_msg
                )
                all_results.append(res)
                print(f"    Iter {i}: {ms}ms, JSON={parse_ok}")
                
            except Exception as e:
                print(f"    Iter {i} ERROR: {e}")
                
    # Save results
    ts = time.strftime("%Y%m%d_%H%M%S")
    out_file = PROJECT_ROOT / "outputs" / "benchmarks" / f"payload_tier_benchmark_{ts}.json"
    with open(out_file, "w") as f:
        json.dump([asdict(r) for r in all_results], f, indent=2)
    
    # Summary table
    print("\n" + "="*100)
    print(f"{'Tier':<25} {'Payload':>10} {'Latency':>10} {'Success':>8}")
    print("-" * 100)
    
    stats = {}
    for r in all_results:
        if r.tier not in stats:
            stats[r.tier] = {"lat": [], "success": 0, "payload": r.instruction_chars + r.user_message_chars}
        stats[r.tier]["lat"].append(r.latency_ms)
        if r.json_parse_ok:
            stats[r.tier]["success"] += 1
            
    for tier, s in stats.items():
        avg_lat = int(sum(s["lat"]) / len(s["lat"]))
        success_rate = f"{s['success']}/3"
        print(f"{tier:<25} {s['payload']:>10,} {avg_lat:>8}ms {success_rate:>8}")
    print("="*100)

if __name__ == "__main__":
    asyncio.run(run_experiment())
