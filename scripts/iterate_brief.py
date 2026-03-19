"""Fast CEO brief iteration — LLM only, uses stashed insight cards.

Usage:
  python scripts/iterate_brief.py                    # default model
  BRIEF_MODEL=gemini-3-flash-preview python scripts/iterate_brief.py
  python scripts/iterate_brief.py --run 3            # run 3 iterations
"""
import json, os, sys, time, io, argparse
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "0"
from dotenv import load_dotenv
load_dotenv(PROJECT / ".env")
# Also check parent dirs for .env
load_dotenv(PROJECT.parent / ".env", override=False)
if not os.environ.get("GOOGLE_API_KEY"):
    print("ERROR: GOOGLE_API_KEY not set. Add it to .env")
    sys.exit(1)

parser = argparse.ArgumentParser()
parser.add_argument("--run", type=int, default=1, help="Number of iterations")
parser.add_argument("--model", default=os.environ.get("BRIEF_MODEL", "gemini-2.5-flash"))
parser.add_argument("--temp", type=float, default=0.2)
args = parser.parse_args()

# Load stashed insight cards (digest + Level 2 cards)
cache_dir = sorted((PROJECT / "outputs/tableau-ops_metrics_weekly/global/all").iterdir())[-1]
digest = json.loads((cache_dir / ".cache/digest.json").read_text())["digest"]

# Extract Level 2 terminal insight cards from metric JSONs
terminal_lines = []
for jf in cache_dir.glob("metric_*.json"):
    payload = json.loads(jf.read_text())
    h = payload.get("hierarchical_analysis", {})
    l2 = h.get("level_2", {})
    cards = l2.get("insight_cards", [])
    if cards:
        metric = jf.stem.replace("metric_", "")
        items = []
        for c in cards[:3]:
            name = c.get("title", "").replace("Level 2 Variance Driver: ", "")
            ev = c.get("evidence", {})
            pct = ev.get("variance_pct")
            dollar = ev.get("variance_dollar", 0)
            pct_str = f"{pct:+.1f}%" if pct is not None else ""
            items.append(f"{name} ({pct_str}, ${abs(dollar):,.0f})")
        terminal_lines.append(f"  {metric}: {', '.join(items)}")

terminal_block = ""
if terminal_lines:
    terminal_block = "TERMINAL/DIVISION DRIVERS (Level 2 insight cards):\n" + "\n".join(terminal_lines) + "\n\n"

# Build cross-metric synthesis from insight cards (code-computed, not LLM)
cross_metric = ""
try:
    metrics_data = {}
    for jf in cache_dir.glob("metric_*.json"):
        p = json.loads(jf.read_text())
        m = jf.stem.replace("metric_", "")
        l0 = p.get("hierarchical_analysis", {}).get("level_0", {}).get("insight_cards", [])
        if l0:
            ev = l0[0].get("evidence", {})
            metrics_data[m] = {
                "current": ev.get("current", 0),
                "prior": ev.get("prior", 0),
                "var_pct": ev.get("variance_pct"),
                "var_dollar": ev.get("variance_dollar", 0),
            }

    lines = ["CROSS-METRIC SYNTHESIS (pre-computed from insight cards):"]

    # Network totals
    if "ttl_rev_amt" in metrics_data:
        r = metrics_data["ttl_rev_amt"]
        lines.append(f"  Total Revenue: ${r['current']:,.0f} (prior: ${r['prior']:,.0f}, {r['var_pct']:+.1f}% WoW)" if r['var_pct'] else f"  Total Revenue: ${r['current']:,.0f}")
    if "lh_rev_amt" in metrics_data:
        r = metrics_data["lh_rev_amt"]
        lines.append(f"  Line Haul Revenue: ${r['current']:,.0f} ({r['var_pct']:+.1f}% WoW)" if r['var_pct'] else f"  Line Haul Revenue: ${r['current']:,.0f}")

    # Yield signal: compare revenue % decline to volume % decline
    rev_pct = metrics_data.get("ttl_rev_amt", {}).get("var_pct")
    miles_pct = metrics_data.get("ld_trf_mi", {}).get("var_pct")
    if rev_pct is not None and miles_pct is not None:
        if abs(rev_pct) > abs(miles_pct) + 1:
            lines.append(f"  YIELD SIGNAL: Revenue fell {rev_pct:+.1f}% but loaded miles only fell {miles_pct:+.1f}% — yield is compressing faster than volume")
        elif abs(miles_pct) > abs(rev_pct) + 1:
            lines.append(f"  YIELD SIGNAL: Loaded miles fell {miles_pct:+.1f}% but revenue only fell {rev_pct:+.1f}% — yield is improving despite volume loss")

    # Efficiency signal: deadhead vs total miles
    dh_pct = metrics_data.get("dh_miles", {}).get("var_pct")
    ttl_mi_pct = metrics_data.get("ttl_trf_mi", {}).get("var_pct")
    if dh_pct is not None and ttl_mi_pct is not None:
        if dh_pct > 0 and ttl_mi_pct < 0:
            lines.append(f"  EFFICIENCY SIGNAL: Deadhead rose {dh_pct:+.1f}% while total miles fell {ttl_mi_pct:+.1f}% — network efficiency deteriorating")
        elif dh_pct < ttl_mi_pct:
            lines.append(f"  EFFICIENCY SIGNAL: Deadhead {dh_pct:+.1f}% vs total miles {ttl_mi_pct:+.1f}% — deadhead improving relative to network")

    # Capacity utilization: truck count vs loaded miles
    truck_pct = metrics_data.get("truck_count", {}).get("var_pct")
    if truck_pct is not None and miles_pct is not None:
        if truck_pct is not None and abs(truck_pct) < 2 and abs(miles_pct) > 3:
            lines.append(f"  UTILIZATION SIGNAL: Truck count {truck_pct:+.1f}% (flat) but loaded miles {miles_pct:+.1f}% — fleet underutilized")

    # Order mix: compare order count changes across segments from L1 cards
    ordr_l1 = p.get("hierarchical_analysis", {}).get("level_1", {}).get("insight_cards", []) if "ordr_cnt" in [jf.stem.replace("metric_","") for jf in cache_dir.glob("metric_ordr_cnt.json")] else []
    ordr_data = json.loads((cache_dir / "metric_ordr_cnt.json").read_text()) if (cache_dir / "metric_ordr_cnt.json").exists() else {}
    ordr_l1 = ordr_data.get("hierarchical_analysis", {}).get("level_1", {}).get("insight_cards", [])
    pos_orders = [c for c in ordr_l1 if c.get("evidence", {}).get("variance_dollar", 0) > 0]
    neg_orders = [c for c in ordr_l1 if c.get("evidence", {}).get("variance_dollar", 0) < 0]
    if pos_orders and neg_orders:
        pos_name = pos_orders[0].get("title", "").replace("Level 1 Variance Driver: ", "")
        pos_ev = pos_orders[0].get("evidence", {})
        neg_name = neg_orders[0].get("title", "").replace("Level 1 Variance Driver: ", "")
        neg_ev = neg_orders[0].get("evidence", {})
        lines.append(f"  ORDER MIX: {pos_name} orders +{pos_ev.get('variance_pct',0):+.1f}%, but {neg_name} orders {neg_ev.get('variance_pct',0):+.1f}%")

    # Rail revenue vs Rail orders — pricing signal
    rail_rev = None
    rail_ord = None
    for jf_name, key in [("metric_ttl_rev_amt.json", "ttl_rev_amt"), ("metric_lh_rev_amt.json", "lh_rev_amt")]:
        jpath = cache_dir / jf_name
        if jpath.exists():
            d = json.loads(jpath.read_text())
            for c in d.get("hierarchical_analysis", {}).get("level_1", {}).get("insight_cards", []):
                if "Rail" in c.get("title", ""):
                    rail_rev = c.get("evidence", {}).get("variance_pct")
                    break
            if rail_rev: break
    if (cache_dir / "metric_ordr_cnt.json").exists():
        d = json.loads((cache_dir / "metric_ordr_cnt.json").read_text())
        for c in d.get("hierarchical_analysis", {}).get("level_1", {}).get("insight_cards", []):
            if "Rail" in c.get("title", ""):
                rail_ord = c.get("evidence", {}).get("variance_pct")
                break
    if rail_rev is not None and rail_ord is not None and rail_ord > 0 and rail_rev < 0:
        lines.append(f"  RAIL PRICING: Rail orders {rail_ord:+.1f}% but Rail revenue {rail_rev:+.1f}% — taking volume at lower rates")

    if len(lines) > 1:
        cross_metric = "\n".join(lines) + "\n\n"
except Exception as e:
    print(f"Cross-metric synthesis failed: {e}")

# Build user message — insight cards + cross-metric synthesis
metric_names = sorted(jf.stem.replace("metric_", "") for jf in cache_dir.glob("metric_*.json"))
user_msg = (
    "COMPARISON BASIS: All variances are WoW (week-over-week vs prior week).\n"
    "Say 'WoW' or 'vs prior week' - NOT 'vs plan'.\n"
    "Week ending: 2026-02-21\n"
    f"Metrics: {', '.join(metric_names)}\n\n"
    f"{cross_metric}"
    f"{terminal_block}"
    f"{digest}"
)

# Load CEO prompt
prompt = (PROJECT / "config/prompts/executive_brief_ceo.md").read_text(encoding="utf-8").strip()
for k, v in {"metric_count": "2", "analysis_period": "the week ending 2026-02-21",
             "scope_preamble": "", "dataset_specific_append": "", "prompt_variant_append": ""}.items():
    prompt = prompt.replace("{" + k + "}", v)

from google import genai
from google.genai import types

schema = types.Schema(type=types.Type.OBJECT, properties={
    "bottom_line": types.Schema(type=types.Type.STRING),
    "what_moved": types.Schema(type=types.Type.ARRAY, items=types.Schema(type=types.Type.OBJECT, properties={
        "label": types.Schema(type=types.Type.STRING),
        "line": types.Schema(type=types.Type.STRING),
    }, required=["label", "line"])),
    "trend_status": types.Schema(type=types.Type.ARRAY, items=types.Schema(type=types.Type.STRING)),
    "where_it_came_from": types.Schema(type=types.Type.OBJECT, properties={
        "positive": types.Schema(type=types.Type.STRING),
        "drag": types.Schema(type=types.Type.STRING),
        "watch_item": types.Schema(type=types.Type.STRING),
    }, required=["positive", "drag"]),
    "why_it_matters": types.Schema(type=types.Type.STRING),
    "next_week_outlook": types.Schema(type=types.Type.STRING),
    "leadership_focus": types.Schema(type=types.Type.ARRAY, items=types.Schema(type=types.Type.STRING)),
}, required=["bottom_line", "what_moved", "trend_status", "where_it_came_from",
             "why_it_matters", "next_week_outlook", "leadership_focus"])

config = types.GenerateContentConfig(
    system_instruction=prompt,
    response_modalities=["TEXT"],
    response_mime_type="application/json",
    response_schema=schema,
    temperature=args.temp,
)

print(f"Model: {args.model} | Temp: {args.temp} | Runs: {args.run}")
print(f"Digest: {len(digest)} chars | Terminal cards: {len(terminal_lines)} metrics")
print(f"{'='*70}\n")

for i in range(args.run):
    if args.run > 1:
        print(f"\n--- Run {i+1}/{args.run} ---")

    t0 = time.time()
    client = genai.Client()
    r = client.models.generate_content(model=args.model, contents=user_msg, config=config)
    el = time.time() - t0
    b = json.loads(r.text)

    # Save
    out_dir = PROJECT / "benchmarks" / "iterations"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"brief_{args.model}_{args.temp}_{i}.json").write_text(
        json.dumps(b, indent=2), encoding="utf-8")

    # Render like the target examples
    print(f"[{el:.1f}s]")
    print(f"\nWeek Ending February 21, 2026\n")
    print(f"Bottom line: {b['bottom_line']}\n")
    print("What moved the business\n")
    for m in b["what_moved"]:
        print(f"  {m['label']}: {m['line']}")
    print("\nTrend status\n")
    for t in b["trend_status"]:
        print(f"  {t}")
    print("\nWhere it came from\n")
    w = b["where_it_came_from"]
    print(f"  Positive: {w['positive']}")
    print(f"  Drag: {w['drag']}")
    if w.get("watch_item"):
        print(f"  Watch item: {w['watch_item']}")
    print(f"\nWhy it matters: {b['why_it_matters']}")
    print(f"\nNext-week outlook: {b['next_week_outlook']}")
    print("\nLeadership focus\n")
    for a in b["leadership_focus"]:
        print(f"  {a}")
    print()
