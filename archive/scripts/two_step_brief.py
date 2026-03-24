"""Two-step CEO brief: 1) Rank insight cards by significance, 2) Send ranked cards to LLM.

Step 1 is pure code — no LLM. Scores every insight card across all metrics,
ranks them, selects top N, and builds a focused context block.

Step 2 sends only the ranked cards to the LLM for narrative synthesis.

Usage:
  python scripts/two_step_brief.py
  python scripts/two_step_brief.py --model gemini-3.1-flash-lite-preview --top 5
"""
import json, os, sys, time, io, argparse
from pathlib import Path
from collections import defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "0"
from dotenv import load_dotenv
load_dotenv(PROJECT / ".env")

parser = argparse.ArgumentParser()
parser.add_argument("--model", default="gemini-3.1-flash-lite-preview")
parser.add_argument("--top", type=int, default=8, help="Top N ranked insights to send to LLM")
parser.add_argument("--temp", type=float, default=0.2)
args = parser.parse_args()

# ══════════════════════════════════════════════════════════════════════
# STEP 1: Score and rank ALL insight cards (pure code, no LLM)
# ══════════════════════════════════════════════════════════════════════

cache_dir = sorted((PROJECT / "outputs/tableau-ops_metrics_weekly/global/all").iterdir())[-1]
print(f"Source: {cache_dir.name}")

# Collect all scored insights
scored = []  # list of (score, category, insight_dict)


def add_insight(score, category, title, detail, metric, source, drill_down=None):
    """Add a scored insight to the ranking pool."""
    entry = {
        "category": category,
        "title": title,
        "detail": detail,
        "metric": metric,
        "source": source,
        "score": round(score, 3),
    }
    if drill_down:
        entry["drill_down"] = drill_down
    scored.append((score, category, entry))


# ── Hierarchy variance cards (WoW changes) ──────────────────────────
for jf in sorted(cache_dir.glob("metric_*.json")):
    p = json.loads(jf.read_text())
    m = jf.stem.replace("metric_", "")

    for level_key in ["level_0", "level_1", "level_2"]:
        level = p.get("hierarchical_analysis", {}).get(level_key, {})
        for card in level.get("insight_cards", []):
            ev = card.get("evidence", {})
            var_pct = ev.get("variance_pct")
            var_dollar = ev.get("variance_dollar", 0)
            current = ev.get("current", 0)
            prior = ev.get("prior", 0)
            share = ev.get("share_of_total", 0)
            is_new = ev.get("is_new_from_zero", False)
            item = card.get("title", "").replace(f"Level {level_key[-1]} Variance Driver: ", "")

            if is_new or var_pct is None:
                continue

            # Score: absolute % change * share of total * level weight
            level_weight = {0: 3.0, 1: 2.0, 2: 1.5}.get(int(level_key[-1]), 1.0)
            magnitude = min(abs(var_pct) / 10, 5)  # cap at 50%
            share_weight = max(share, 0.05)
            score = magnitude * share_weight * level_weight

            # Determine category
            if "dh_miles" in m or "deadhead" in m.lower():
                cat = "Network efficiency"
            elif "rev" in m:
                cat = "Revenue / yield"
            elif "ordr" in m:
                cat = "Volume"
            elif "trf_mi" in m or "miles" in m:
                cat = "Productivity"
            elif "truck" in m:
                cat = "Capacity"
            else:
                cat = "Operations"

            direction = "+" if var_pct > 0 else ""
            detail = f"{item}: {m} {direction}{var_pct:.1f}% WoW (${abs(var_dollar):,.0f})"
            if current and prior:
                detail += f", current ${current:,.0f} vs prior ${prior:,.0f}"

            # Attach L2 drill-down if this is L1
            drill = None
            if level_key == "level_1":
                l2_cards = p.get("hierarchical_analysis", {}).get("level_2", {}).get("insight_cards", [])
                for l2c in l2_cards[:2]:
                    l2_ev = l2c.get("evidence", {})
                    l2_pct = l2_ev.get("variance_pct")
                    l2_item = l2c.get("title", "").replace("Level 2 Variance Driver: ", "")
                    if l2_pct is not None:
                        drill = f"{l2_item} {l2_pct:+.1f}% WoW"
                        break

            add_insight(score, cat, item, detail, m, f"hierarchy_{level_key}", drill)


# ── Statistical trends (3-month slopes) ─────────────────────────────
for jf in sorted(cache_dir.glob("metric_*.json")):
    p = json.loads(jf.read_text())
    m = jf.stem.replace("metric_", "")
    stats = p.get("statistical_summary", {})

    for driver in stats.get("top_drivers", [])[:5]:
        slope = driver.get("slope_3mo")
        p_val = driver.get("slope_3mo_p_value")
        avg = driver.get("avg", 0)
        item = driver.get("item", "")
        cv = driver.get("cv", 0)

        if slope and p_val is not None and p_val < 0.2 and avg:
            pct = abs(slope / avg * 100)
            if pct < 0.5:
                continue
            direction = "up" if slope > 0 else "down"

            # Score: significance * magnitude
            sig = 1 - p_val
            score = sig * pct * 0.5  # weight trends slightly less than WoW

            cat = "Trend"
            detail = f"{item}: {m} trending {direction} ~{pct:.1f}%/wk over 13 weeks (p={p_val:.3f})"
            if avg:
                detail += f", avg ${avg:,.0f}"

            add_insight(score, cat, f"{item} {m} trend", detail, m, "statistical_trend")


# ── Cross-metric signals (computed) ─────────────────────────────────
l0_data = {}
for jf in sorted(cache_dir.glob("metric_*.json")):
    p = json.loads(jf.read_text())
    m = jf.stem.replace("metric_", "")
    l0 = p.get("hierarchical_analysis", {}).get("level_0", {}).get("insight_cards", [])
    if l0:
        ev = l0[0].get("evidence", {})
        l0_data[m] = {"current": ev.get("current", 0), "prior": ev.get("prior", 0), "var_pct": ev.get("variance_pct")}

rev_pct = l0_data.get("ttl_rev_amt", {}).get("var_pct")
miles_pct = l0_data.get("ld_trf_mi", {}).get("var_pct")
if rev_pct is not None and miles_pct is not None:
    gap = abs(rev_pct) - abs(miles_pct)
    if abs(gap) > 0.5:
        if abs(rev_pct) > abs(miles_pct):
            detail = f"Revenue fell {rev_pct:+.1f}% but loaded miles only {miles_pct:+.1f}% — yield compressing"
            score = abs(gap) * 2
        else:
            detail = f"Loaded miles fell {miles_pct:+.1f}% but revenue only {rev_pct:+.1f}% — yield improving"
            score = abs(gap) * 2
        add_insight(score, "Yield signal", "Yield vs Volume", detail, "cross_metric", "cross_metric")

dh_pct = l0_data.get("dh_miles", {}).get("var_pct")
ttl_mi_pct = l0_data.get("ttl_trf_mi", {}).get("var_pct")
if dh_pct is not None and ttl_mi_pct is not None:
    if (dh_pct > 0 and ttl_mi_pct < 0) or (dh_pct > 0 and dh_pct > ttl_mi_pct + 3):
        detail = f"Deadhead {dh_pct:+.1f}% while total miles {ttl_mi_pct:+.1f}% — efficiency deteriorating"
        add_insight(abs(dh_pct - ttl_mi_pct), "Efficiency signal", "DH vs Miles", detail, "cross_metric", "cross_metric")

# Rail pricing signal
rail_rev_pct = None
rail_ord_pct = None
for jf in [cache_dir / "metric_ttl_rev_amt.json", cache_dir / "metric_lh_rev_amt.json"]:
    if jf.exists():
        d = json.loads(jf.read_text())
        for c in d.get("hierarchical_analysis", {}).get("level_1", {}).get("insight_cards", []):
            if "Rail" in c.get("title", ""):
                rail_rev_pct = c.get("evidence", {}).get("variance_pct")
                break
        if rail_rev_pct:
            break
if (cache_dir / "metric_ordr_cnt.json").exists():
    d = json.loads((cache_dir / "metric_ordr_cnt.json").read_text())
    for c in d.get("hierarchical_analysis", {}).get("level_1", {}).get("insight_cards", []):
        if "Rail" in c.get("title", ""):
            rail_ord_pct = c.get("evidence", {}).get("variance_pct")
            break
if rail_rev_pct is not None and rail_ord_pct is not None and rail_ord_pct > 0 and rail_rev_pct < 0:
    detail = f"Rail orders {rail_ord_pct:+.1f}% but revenue {rail_rev_pct:+.1f}% — taking volume at lower rates"
    add_insight(abs(rail_ord_pct - rail_rev_pct), "Pricing signal", "Rail pricing", detail, "cross_metric", "cross_metric")


# ── Sort and select top N ───────────────────────────────────────────
scored.sort(key=lambda x: x[0], reverse=True)

# Deduplicate: keep highest-scored insight per item+metric combo
seen = set()
deduped = []
for s, cat, entry in scored:
    key = (entry.get("title", ""), entry.get("metric", ""))
    if key not in seen:
        seen.add(key)
        deduped.append((s, cat, entry))

top_insights = deduped[:args.top]

print(f"\n{'='*70}")
print(f"STEP 1: Ranked {len(scored)} raw insights -> {len(deduped)} unique -> top {len(top_insights)}")
print(f"{'='*70}\n")

for i, (score, cat, entry) in enumerate(top_insights, 1):
    drill = f" [drill: {entry['drill_down']}]" if entry.get("drill_down") else ""
    print(f"  {i}. [{score:.2f}] {cat}: {entry['detail']}{drill}")

# ══════════════════════════════════════════════════════════════════════
# STEP 2: Send ranked cards to LLM for narrative synthesis
# ══════════════════════════════════════════════════════════════════════

# Build focused context from ranked insights
insight_block = "TOP RANKED INSIGHTS (by statistical significance and business impact):\n\n"
for i, (score, cat, entry) in enumerate(top_insights, 1):
    insight_block += f"{i}. [{cat}] {entry['detail']}"
    if entry.get("drill_down"):
        insight_block += f"\n   Drill-down: {entry['drill_down']}"
    insight_block += "\n"

# Network totals for context
totals_block = "\nNETWORK TOTALS (current week vs prior week):\n"
for m in ["ttl_rev_amt", "lh_rev_amt", "dh_miles", "ld_trf_mi", "truck_count", "ordr_cnt"]:
    if m in l0_data:
        d = l0_data[m]
        pct = f"{d['var_pct']:+.1f}%" if d.get("var_pct") is not None else "N/A"
        totals_block += f"  {m}: ${d['current']:,.0f} ({pct} WoW)\n"

# Load prompt
prompt = (PROJECT / "config/prompts/executive_brief_ceo.md").read_text(encoding="utf-8").strip()
for k, v in {"metric_count": str(len(list(cache_dir.glob("metric_*.json")))),
             "analysis_period": "the week ending 2026-02-21",
             "scope_preamble": "", "dataset_specific_append": "", "prompt_variant_append": ""}.items():
    prompt = prompt.replace("{" + k + "}", v)

user_msg = (
    "COMPARISON BASIS: All variances are WoW (week-over-week).\n"
    "Week ending: 2026-02-21\n\n"
    f"{totals_block}\n"
    f"{insight_block}\n"
    "Synthesize these ranked insights into a CEO brief. "
    "The insights are pre-ranked by significance — lead with the highest-ranked ones. "
    "Use the drill-down details to name specific terminals in 'where it came from'."
)

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

print(f"\n{'='*70}")
print(f"STEP 2: Sending {len(top_insights)} ranked insights to LLM ({args.model})")
print(f"{'='*70}\n")

t0 = time.time()
client = genai.Client()
r = client.models.generate_content(model=args.model, contents=user_msg,
    config=types.GenerateContentConfig(system_instruction=prompt, response_modalities=["TEXT"],
        response_mime_type="application/json", response_schema=schema, temperature=args.temp))
el = time.time() - t0
b = json.loads(r.text)

# Save
out_dir = PROJECT / "benchmarks" / "two_step"
out_dir.mkdir(parents=True, exist_ok=True)
(out_dir / "ranked_insights.json").write_text(json.dumps([e for _, _, e in top_insights], indent=2), encoding="utf-8")
(out_dir / "brief.json").write_text(json.dumps(b, indent=2), encoding="utf-8")
(out_dir / "user_message.txt").write_text(user_msg, encoding="utf-8")

# Render
print(f"[{el:.1f}s]\n")
print(f"Week Ending February 21, 2026\n")
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
