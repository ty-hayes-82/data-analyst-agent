"""Quick single-shot CEO brief test."""
import json, os, sys, time, io
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "0"
from dotenv import load_dotenv
load_dotenv(PROJECT / ".env")

digest = json.loads((sorted((PROJECT / "outputs/tableau-ops_metrics_weekly/global/all").iterdir())[-1] / ".cache/digest.json").read_text())["digest"]

prompt = (PROJECT / "config/prompts/executive_brief_ceo.md").read_text(encoding="utf-8").strip()
for k, v in {"metric_count": "2", "analysis_period": "the week ending 2026-03-14",
             "scope_preamble": "", "dataset_specific_append": "", "prompt_variant_append": ""}.items():
    prompt = prompt.replace("{" + k + "}", v)

from google import genai
from google.genai import types

schema = types.Schema(type=types.Type.OBJECT, properties={
    "bottom_line": types.Schema(type=types.Type.STRING, description="Exactly 2 sentences. Sentence 1=headline. Sentence 2=the 'but' about quality."),
    "what_moved": types.Schema(type=types.Type.ARRAY, items=types.Schema(type=types.Type.OBJECT, properties={
        "label": types.Schema(type=types.Type.STRING, description="Short category: Revenue / yield, Productivity, Network efficiency, Service, Capacity"),
        "line": types.Schema(type=types.Type.STRING, description="Single line: KPI value, change%, context. Example: LRPM $2.48, +1.9%, above 4-week avg"),
    }, required=["label", "line"])),
    "trend_status": types.Schema(type=types.Type.ARRAY, items=types.Schema(type=types.Type.STRING,
        description="One sentence per trend with classification embedded. Example: 'Deadhead is now a developing trend'")),
    "where_it_came_from": types.Schema(type=types.Type.OBJECT, properties={
        "positive": types.Schema(type=types.Type.STRING, description="Region / Terminal - reason"),
        "drag": types.Schema(type=types.Type.STRING, description="Region / Terminal - reason"),
        "watch_item": types.Schema(type=types.Type.STRING, description="Terminal - anomaly"),
    }, required=["positive", "drag"]),
    "why_it_matters": types.Schema(type=types.Type.STRING, description="Exactly 1 sentence connecting execution to earnings."),
    "next_week_outlook": types.Schema(type=types.Type.STRING, description="1-2 sentences. Conditional: If X then Y; if not, Z."),
    "leadership_focus": types.Schema(type=types.Type.ARRAY, items=types.Schema(type=types.Type.STRING,
        description="Imperative verb first, under 12 words. Example: Hold price; do not trade yield for weak volume")),
}, required=["bottom_line", "what_moved", "trend_status", "where_it_came_from", "why_it_matters", "next_week_outlook", "leadership_focus"])

# Build terminal block from JSON data
cache_dir = sorted((PROJECT / "outputs/tableau-ops_metrics_weekly/global/all").iterdir())[-1]
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
    terminal_block = "TERMINAL/DIVISION DRIVERS (Level 2):\n" + "\n".join(terminal_lines) + "\n\n"

user_msg = (
    "COMPARISON BASIS: All variances are WoW (week-over-week vs prior week).\n"
    "Say 'WoW' or 'vs prior week' - NOT 'vs plan'.\n"
    "Week ending: 2026-03-14\n"
    "Metrics: dh_miles, ttl_rev_amt\n\n"
    f"{terminal_block}"
    f"{digest}"
)

t0 = time.time()
client = genai.Client()
MODEL = os.environ.get("BRIEF_MODEL", "gemini-2.5-flash")
print(f"Model: {MODEL}")
r = client.models.generate_content(model=MODEL, contents=user_msg,
    config=types.GenerateContentConfig(system_instruction=prompt, response_modalities=["TEXT"],
        response_mime_type="application/json", response_schema=schema, temperature=0.2))
el = time.time() - t0
b = json.loads(r.text)

# Save raw
(PROJECT / "benchmarks" / "latest_brief.json").write_text(json.dumps(b, indent=2), encoding="utf-8")

# Render
print(f"[{el:.1f}s]\n")
print(f"Bottom line: {b['bottom_line']}\n")
print("What moved the business:")
for m in b["what_moved"]:
    label = m.get("label", m.get("metric", ""))
    line = m.get("line", m.get("value", ""))
    print(f"  {label}: {line}")
print()
print("Trend status:")
for t in b["trend_status"]:
    if isinstance(t, str):
        print(f"  {t}")
    else:
        print(f"  {t.get('detail', t)}")
print()
w = b["where_it_came_from"]
print("Where it came from:")
print(f"  Positive: {w['positive']}")
print(f"  Drag: {w['drag']}")
if w.get("watch_item"): print(f"  Watch item: {w['watch_item']}")
print()
print(f"Why it matters: {b['why_it_matters']}\n")
print(f"Next-week outlook: {b['next_week_outlook']}\n")
print("Leadership focus:")
for a in b["leadership_focus"]:
    print(f"  {a}")
