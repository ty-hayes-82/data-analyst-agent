"""Three-step CEO brief pipeline:

Step 1 (code): Rank all insight cards by significance — no LLM.
Step 2 (LLM): Pick the most significant insights + attach children that explain parents.
Step 3 (LLM): Synthesize curated insights into CEO brief.

Usage:
  python scripts/three_step_brief.py
  python scripts/three_step_brief.py --model gemini-3.1-flash-lite-preview --top 15
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
parser.add_argument("--model", default="gemini-3.1-flash-lite-preview")
parser.add_argument("--top", type=int, default=15, help="Top N ranked insights sent to Step 2")
parser.add_argument("--temp", type=float, default=0.2)
args = parser.parse_args()

cache_dir = sorted((PROJECT / "outputs/tableau-ops_metrics_weekly/global/all").iterdir())[-1]
print(f"Source: {cache_dir.name}")

# ══════════════════════════════════════════════════════════════════════
# STEP 1: Score and rank ALL insight cards (pure code, no LLM)
# ══════════════════════════════════════════════════════════════════════

scored = []


def add_insight(score, category, title, detail, metric, level, children=None):
    entry = {
        "category": category,
        "title": title,
        "detail": detail,
        "metric": metric,
        "level": level,
        "score": round(score, 3),
    }
    if children:
        entry["children"] = children
    scored.append(entry)


# Load all metric JSONs
all_metrics = {}
for jf in sorted(cache_dir.glob("metric_*.json")):
    p = json.loads(jf.read_text())
    m = jf.stem.replace("metric_", "")
    all_metrics[m] = p

# Categorize metric
def categorize(m):
    if "dh_miles" in m: return "Network efficiency"
    if "rev" in m or "fuel_srchrg" in m: return "Revenue / yield"
    if "ordr" in m: return "Volume"
    if "trf_mi" in m or "ld_trf" in m: return "Productivity"
    if "truck" in m: return "Capacity"
    return "Operations"

# ── Hierarchy variance cards ────────────────────────────────────────
for m, p in all_metrics.items():
    cat = categorize(m)
    hierarchy = p.get("hierarchical_analysis", {})

    for level_key in ["level_0", "level_1", "level_2"]:
        level_num = int(level_key[-1])
        level_data = hierarchy.get(level_key, {})
        cards = level_data.get("insight_cards", [])

        for card in cards:
            ev = card.get("evidence", {})
            var_pct = ev.get("variance_pct")
            var_dollar = ev.get("variance_dollar", 0)
            current = ev.get("current", 0)
            prior = ev.get("prior", 0)
            share = ev.get("share_of_total", 0)
            is_new = ev.get("is_new_from_zero", False)
            item = card.get("title", "").replace(f"Level {level_num} Variance Driver: ", "")

            if is_new or var_pct is None:
                continue

            level_weight = {0: 3.0, 1: 2.0, 2: 1.5}.get(level_num, 1.0)
            magnitude = min(abs(var_pct) / 10, 5)
            share_weight = max(share, 0.05)
            score = magnitude * share_weight * level_weight

            direction = "+" if var_pct > 0 else ""
            detail = f"{direction}{var_pct:.1f}% WoW (${abs(var_dollar):,.0f}), current ${current:,.0f} vs prior ${prior:,.0f}"

            # Collect children (next level cards for same metric)
            children = []
            if level_num < 2:
                next_level = f"level_{level_num + 1}"
                next_cards = hierarchy.get(next_level, {}).get("insight_cards", [])
                for nc in next_cards[:3]:
                    nc_ev = nc.get("evidence", {})
                    nc_pct = nc_ev.get("variance_pct")
                    nc_item = nc.get("title", "").replace(f"Level {level_num+1} Variance Driver: ", "")
                    if nc_pct is not None and not nc_ev.get("is_new_from_zero"):
                        children.append({
                            "item": nc_item,
                            "detail": f"{nc_pct:+.1f}% WoW (${abs(nc_ev.get('variance_dollar',0)):,.0f})",
                            "level": f"L{level_num+1}",
                        })

            add_insight(score, cat, f"{item} ({m})", detail, m, f"L{level_num}", children or None)

# ── Statistical trends ──────────────────────────────────────────────
for m, p in all_metrics.items():
    stats = p.get("statistical_summary", {})
    for driver in stats.get("top_drivers", [])[:5]:
        slope = driver.get("slope_3mo")
        p_val = driver.get("slope_3mo_p_value")
        avg = driver.get("avg", 0)
        item = driver.get("item", "")
        if slope and p_val is not None and p_val < 0.2 and avg:
            pct = abs(slope / avg * 100)
            if pct < 0.5:
                continue
            direction = "up" if slope > 0 else "down"
            sig = 1 - p_val
            score = sig * pct * 0.5
            detail = f"trending {direction} ~{pct:.1f}%/wk over 13 weeks (p={p_val:.3f}), avg ${avg:,.0f}"
            add_insight(score, "Trend", f"{item} {m} trend", detail, m, "statistical")

# ── Cross-metric signals ────────────────────────────────────────────
l0_data = {}
for m, p in all_metrics.items():
    l0 = p.get("hierarchical_analysis", {}).get("level_0", {}).get("insight_cards", [])
    if l0:
        ev = l0[0].get("evidence", {})
        l0_data[m] = {"current": ev.get("current", 0), "prior": ev.get("prior", 0), "var_pct": ev.get("variance_pct")}

rev_pct = l0_data.get("ttl_rev_amt", {}).get("var_pct")
miles_pct = l0_data.get("ld_trf_mi", {}).get("var_pct")
if rev_pct is not None and miles_pct is not None and abs(abs(rev_pct) - abs(miles_pct)) > 0.5:
    if abs(rev_pct) > abs(miles_pct):
        detail = f"Revenue {rev_pct:+.1f}% but loaded miles only {miles_pct:+.1f}% — yield compressing"
    else:
        detail = f"Loaded miles {miles_pct:+.1f}% but revenue only {rev_pct:+.1f}% — yield improving"
    add_insight(abs(rev_pct - miles_pct) * 2, "Yield signal", "Yield vs Volume", detail, "cross", "cross")

dh_pct = l0_data.get("dh_miles", {}).get("var_pct")
ttl_mi_pct = l0_data.get("ttl_trf_mi", {}).get("var_pct")
if dh_pct is not None and ttl_mi_pct is not None:
    if dh_pct > 0 and (ttl_mi_pct < 0 or dh_pct > ttl_mi_pct + 3):
        detail = f"Deadhead {dh_pct:+.1f}% while total miles {ttl_mi_pct:+.1f}% — efficiency deteriorating"
        add_insight(abs(dh_pct - (ttl_mi_pct or 0)), "Efficiency signal", "DH vs Miles", detail, "cross", "cross")

# Sort by score
scored.sort(key=lambda x: x["score"], reverse=True)

# Deduplicate
seen = set()
deduped = []
for entry in scored:
    key = (entry["title"], entry["metric"])
    if key not in seen:
        seen.add(key)
        deduped.append(entry)

top_raw = deduped[:args.top]

print(f"\n{'='*70}")
print(f"STEP 1: Scored {len(scored)} -> {len(deduped)} unique -> sending top {len(top_raw)} to Step 2")
print(f"{'='*70}\n")

for i, entry in enumerate(top_raw, 1):
    kids = f" [{len(entry.get('children',[]))} children]" if entry.get("children") else ""
    print(f"  {i:2d}. [{entry['score']:.2f}] {entry['category']}: {entry['title']} — {entry['detail'][:80]}{kids}")


# ══════════════════════════════════════════════════════════════════════
# STEP 2: LLM selects most significant insights + links children
# ══════════════════════════════════════════════════════════════════════

from google import genai
from google.genai import types

# Network totals
totals = {}
for m in ["ttl_rev_amt", "lh_rev_amt", "dh_miles", "ld_trf_mi", "truck_count", "ordr_cnt"]:
    if m in l0_data:
        d = l0_data[m]
        pct = f"{d['var_pct']:+.1f}%" if d.get("var_pct") is not None else "flat"
        totals[m] = f"${d['current']:,.0f} ({pct} WoW)"

step2_input = json.dumps({
    "network_totals": totals,
    "ranked_insights": top_raw,
}, indent=2, default=str)

step2_schema = types.Schema(type=types.Type.OBJECT, properties={
    "selected_insights": types.Schema(type=types.Type.ARRAY, items=types.Schema(type=types.Type.OBJECT, properties={
        "headline": types.Schema(type=types.Type.STRING),
        "detail": types.Schema(type=types.Type.STRING),
        "supporting_evidence": types.Schema(type=types.Type.ARRAY, items=types.Schema(type=types.Type.STRING)),
        "business_implication": types.Schema(type=types.Type.STRING),
        "category": types.Schema(type=types.Type.STRING),
    }, required=["headline", "detail", "supporting_evidence", "business_implication"])),
    "narrative_thesis": types.Schema(type=types.Type.STRING),
    "quality_assessment": types.Schema(type=types.Type.STRING,
        enum=["strong revenue weaker quality", "flat revenue execution pressure",
              "softer revenue healthier fundamentals", "broad decline", "mixed signals"]),
}, required=["selected_insights", "narrative_thesis", "quality_assessment"])

step2_instruction = (
    "You are a senior analyst reviewing pre-ranked operational insight cards for a trucking company.\n\n"
    "SELECT 4-6 insights that tell ONE coherent story about the week.\n"
    "For each, include ALL supporting children/drill-down evidence — do not drop terminal names or percentages.\n\n"
    "RULES:\n"
    "- Preserve exact numbers, percentages, and terminal names from the input\n"
    "- Include trend DURATION from statistical data (e.g. '13-week upward trend', 'p=0.086')\n"
    "- business_implication must name the MECHANISM (yield compression, capacity underutilization) not just 'will pressure margins'\n"
    "- MUST include the highest-ranked POSITIVE signal if one exists (e.g. a metric trending favorably). "
    "If no metric improved, say so explicitly.\n"
    "- quality_assessment drives the entire brief narrative — choose carefully\n\n"
    "Classify the week:\n"
    "- 'strong revenue weaker quality': topline up but efficiency/service declining\n"
    "- 'flat revenue execution pressure': topline stable but operational metrics deteriorating\n"
    "- 'softer revenue healthier fundamentals': topline down but efficiency/service improving\n"
    "- 'broad decline': both topline and operations deteriorating\n"
    "- 'mixed signals': some metrics improving, others declining, no clear pattern"
)

print(f"\n{'='*70}")
print(f"STEP 2: LLM selecting most significant insights ({args.model})")
print(f"{'='*70}")

t0 = time.time()
client = genai.Client()
r2 = client.models.generate_content(model=args.model, contents=step2_input,
    config=types.GenerateContentConfig(system_instruction=step2_instruction, response_modalities=["TEXT"],
        response_mime_type="application/json", response_schema=step2_schema, temperature=0.1))
el2 = time.time() - t0
curated = json.loads(r2.text)

print(f"[{el2:.1f}s]")
print(f"Thesis: {curated.get('quality_assessment', '?')} — {curated.get('narrative_thesis', '?')}")
print(f"Selected {len(curated.get('selected_insights', []))} insights:\n")
for i, ins in enumerate(curated.get("selected_insights", []), 1):
    print(f"  {i}. [{ins.get('category','')}] {ins['headline']}")
    print(f"     {ins['detail'][:100]}")
    for ev in ins.get("supporting_evidence", [])[:2]:
        print(f"       -> {ev[:80]}")
    print(f"     Implication: {ins['business_implication'][:100]}")
    print()


# ══════════════════════════════════════════════════════════════════════
# STEP 3: LLM synthesizes curated insights into CEO brief
# ══════════════════════════════════════════════════════════════════════

prompt = (PROJECT / "config/prompts/executive_brief_ceo.md").read_text(encoding="utf-8").strip()
for k, v in {"metric_count": str(len(all_metrics)),
             "analysis_period": "the week ending 2026-02-21",
             "scope_preamble": "", "dataset_specific_append": "", "prompt_variant_append": ""}.items():
    prompt = prompt.replace("{" + k + "}", v)

step3_input = (
    "Week ending: 2026-02-21. All comparisons are WoW.\n\n"
    f"WEEK THESIS: {curated.get('quality_assessment', 'mixed signals')}\n"
    f"{curated.get('narrative_thesis', '')}\n\n"
    f"NETWORK TOTALS:\n"
    + "\n".join(f"  {k}: {v}" for k, v in totals.items())
    + f"\n\nCURATED INSIGHTS (use ALL of these — do not drop any):\n\n"
    + json.dumps(curated.get("selected_insights", []), indent=2)
    + "\n\nRULES FOR THIS BRIEF:\n"
    "- bottom_line: Open with a VERDICT. 'The week was operationally weak' not 'The week saw a contraction'\n"
    "- what_moved: Each item = ONE metric category, ONE line. 'East DH +9.4%, Syracuse +23.4%, Ocala +8.7%' — not sentences\n"
    "  Labels must be: Revenue / yield, Productivity, Network efficiency, Capacity, or Volume — pick the best fit\n"
    "- trend_status: MUST include duration from the data. '13-week upward trend' or 'down 3 straight weeks'\n"
    "- where_it_came_from positive: ONLY genuinely positive signals (metrics that IMPROVED WoW or show positive trends). "
    "If a metric got worse but less than others, that is NOT positive. "
    "Look for: deadhead declining, volume growing, yield improving. If truly nothing improved, write 'No bright spots this week'\n"
    "- what_moved: MUST have exactly 4 items. Each must cover a DIFFERENT dimension — no two items about the same region or metric\n"
    "- Do NOT repeat the same data point in trend_status AND where_it_came_from. Each fact appears ONCE.\n"
    "- why_it_matters: Do NOT use 'double-hit' or 'recipe for'. Name the specific mechanism: "
    "'yield compression will cost us $X per week in margin' or 'the East is now a net-negative contributor to operating income'\n"
    "- next_week_outlook: VARY the structure. Not always 'If X continues, Y will happen.' Try:\n"
    "  'One more week like this makes the issue material.'\n"
    "  'The setup favors margin recovery if volume stabilizes.'\n"
    "  'We are one rate concession away from structural margin damage.'\n"
    "- leadership_focus: Name TERMINALS not regions. 'Fix Syracuse dispatch' not 'Audit Central region'. "
    "If the action is regional, pick the worst terminal in that region.\n"
    "- bottom_line: Exactly 2 sentences. Do not repeat the same idea in both sentences.\n"
)

brief_schema = types.Schema(type=types.Type.OBJECT, properties={
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
print(f"STEP 3: LLM generating CEO brief ({args.model})")
print(f"{'='*70}")

t0 = time.time()
r3 = client.models.generate_content(model=args.model, contents=step3_input,
    config=types.GenerateContentConfig(system_instruction=prompt, response_modalities=["TEXT"],
        response_mime_type="application/json", response_schema=brief_schema, temperature=args.temp))
el3 = time.time() - t0
b = json.loads(r3.text)

# Save
out_dir = PROJECT / "benchmarks" / "three_step"
out_dir.mkdir(parents=True, exist_ok=True)
(out_dir / "step1_ranked.json").write_text(json.dumps(top_raw, indent=2, default=str), encoding="utf-8")
(out_dir / "step2_curated.json").write_text(json.dumps(curated, indent=2), encoding="utf-8")
(out_dir / "step3_brief.json").write_text(json.dumps(b, indent=2), encoding="utf-8")

print(f"[{el3:.1f}s] (total: Step1=0s + Step2={el2:.1f}s + Step3={el3:.1f}s = {el2+el3:.1f}s)\n")
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
