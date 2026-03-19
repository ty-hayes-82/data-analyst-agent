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

# Build user message — insight cards only
user_msg = (
    "COMPARISON BASIS: All variances are WoW (week-over-week vs prior week).\n"
    "Say 'WoW' or 'vs prior week' - NOT 'vs plan'.\n"
    "Week ending: 2026-03-14\n"
    "Metrics: dh_miles, ttl_rev_amt\n\n"
    f"{terminal_block}"
    f"{digest}"
)

# Load CEO prompt
prompt = (PROJECT / "config/prompts/executive_brief_ceo.md").read_text(encoding="utf-8").strip()
for k, v in {"metric_count": "2", "analysis_period": "the week ending 2026-03-14",
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
    print(f"\nWeek Ending March 14, 2026\n")
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
