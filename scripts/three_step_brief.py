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
        "_score": round(score, 3),  # internal only, stripped before sending to LLM
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

# Load contract for metric categories and derived KPIs
import yaml
contract_path = PROJECT / "config" / "datasets" / "tableau" / "ops_metrics_weekly" / "contract.yaml"
contract = yaml.safe_load(contract_path.read_text(encoding="utf-8")) if contract_path.exists() else {}

# Build metric → brief_category and brief_label lookups from contract
_metric_cat = {}
_metric_label = {}
for metric_def in contract.get("metrics", []):
    name = metric_def.get("name", "")
    _metric_cat[name] = metric_def.get("brief_category", "Operations")
    _metric_label[name] = metric_def.get("brief_label", metric_def.get("display_name", name))

def categorize(m):
    return _metric_cat.get(m, "Operations")

def label_for(m):
    return _metric_label.get(m, m)

# First pass: collect network totals from L0 cards, fallback to L1 sum
_l0_totals_cur = {}
_l0_totals_pri = {}
for jf in cache_dir.glob("metric_*.json"):
    p_kpi = json.loads(jf.read_text())
    m_kpi = jf.stem.replace("metric_", "")
    l0 = p_kpi.get("hierarchical_analysis", {}).get("level_0", {}).get("insight_cards", [])
    if l0:
        ev = l0[0].get("evidence", {})
        _l0_totals_cur[m_kpi] = ev.get("current", 0)
        _l0_totals_pri[m_kpi] = ev.get("prior", 0)
    else:
        # Fallback: sum L1 cards for network total
        l1 = p_kpi.get("hierarchical_analysis", {}).get("level_1", {}).get("insight_cards", [])
        if l1:
            cur_sum = sum(c.get("evidence", {}).get("current", 0) for c in l1)
            pri_sum = sum(c.get("evidence", {}).get("prior", 0) for c in l1)
            if cur_sum > 0:
                _l0_totals_cur[m_kpi] = cur_sum
                _l0_totals_pri[m_kpi] = pri_sum

# Compute derived KPIs from cross-metric L0 totals
derived_kpis = {}
for kpi_def in contract.get("derived_kpis", []):
    kpi_name = kpi_def["name"]
    num_metric = kpi_def.get("numerator", "")
    den_metric = kpi_def.get("denominator", "")
    multiply = kpi_def.get("multiply", 1)
    divide_days = kpi_def.get("divide_by_days", 1)

    num_cur = _l0_totals_cur.get(num_metric)
    num_pri = _l0_totals_pri.get(num_metric)
    den_cur = _l0_totals_cur.get(den_metric)
    den_pri = _l0_totals_pri.get(den_metric)

    if num_cur and den_cur and den_cur > 0 and den_pri and den_pri > 0:
        cur_val = (num_cur / den_cur / divide_days) * multiply
        pri_val = (num_pri / den_pri / divide_days) * multiply
        change_pct = (cur_val - pri_val) / abs(pri_val) * 100 if pri_val else 0
        derived_kpis[kpi_name] = {
            "label": kpi_def.get("brief_label", kpi_name),
            "category": kpi_def.get("brief_category", "Operations"),
            "current": cur_val,
            "prior": pri_val,
            "change_pct": change_pct,
            "format": kpi_def.get("format", "float"),
        }

if derived_kpis:
    kpi_strs = [f"{k}={v['current']:.2f} ({v['change_pct']:+.1f}%)" for k, v in derived_kpis.items()]
    print(f"Derived KPIs: {', '.join(kpi_strs)}")

# ── Build insight trees: L1 parent → L2 children + stat context ─────
for m, p in all_metrics.items():
    cat = categorize(m)
    hierarchy = p.get("hierarchical_analysis", {})
    stats = p.get("statistical_summary", {})

    # Build statistical context lookup: item → {avg, slope, anomaly, etc.}
    stat_ctx = {}
    for driver in stats.get("top_drivers", []):
        item_name = driver.get("item", "")
        avg = driver.get("avg", 0)
        stat_ctx[item_name] = {
            "avg": avg, "std": driver.get("std", 0), "cv": driver.get("cv", 0),
            "slope_pct": abs(driver.get("slope_3mo", 0) / avg * 100) if avg else 0,
            "slope_dir": "up" if driver.get("slope_3mo", 0) > 0 else "down",
            "slope_p": driver.get("slope_3mo_p_value"),
            "min": driver.get("min", 0), "max": driver.get("max", 0),
            "accel": driver.get("acceleration_3mo", 0),
        }

    # Anomaly lookup (skip first-period anomalies)
    anom_lookup = {}
    ss = stats.get("summary_stats", {})
    first_period = ss.get("period_range", "").split(" to ")[0] if ss.get("period_range") else ""
    for anom in stats.get("anomalies", []):
        if anom.get("period") == first_period:
            continue
        anom_item = anom.get("item", "")
        if anom_item not in anom_lookup and abs(anom.get("z_score", 0)) > 2.0:
            anom_lookup[anom_item] = anom

    l1_cards = hierarchy.get("level_1", {}).get("insight_cards", [])
    l2_cards = hierarchy.get("level_2", {}).get("insight_cards", [])

    for card in l1_cards:
        ev = card.get("evidence", {})
        var_pct = ev.get("variance_pct")
        var_dollar = ev.get("variance_dollar", 0)
        current = ev.get("current", 0)
        prior = ev.get("prior", 0)
        share = ev.get("share_of_total", 0)
        if ev.get("is_new_from_zero") or var_pct is None:
            continue
        item = card.get("title", "").replace("Level 1 Variance Driver: ", "")

        # Base score
        magnitude = min(abs(var_pct) / 10, 5)
        score = magnitude * max(share, 0.05) * 2.0

        # Build detail with multi-timeframe context
        parts = [f"{var_pct:+.1f}% WoW (${abs(var_dollar):,.0f}), current ${current:,.0f}"]

        # vs average
        sc = stat_ctx.get(item, {})
        if sc.get("avg") and current:
            vs_avg = (current - sc["avg"]) / sc["avg"] * 100
            if abs(vs_avg) > 3:
                parts.append(f"{vs_avg:+.0f}% vs 13-wk avg")
            # Historical rank
            if sc.get("max") and current >= sc["max"] * 0.95:
                parts.append("near 13-wk high")
            elif sc.get("min") and current <= sc["min"] * 1.05:
                parts.append("near 13-wk low")

        # Trend context
        if sc.get("slope_p") is not None and sc["slope_p"] < 0.15 and sc.get("slope_pct", 0) > 0.5:
            accel_note = ""
            if sc.get("accel") and sc["avg"] and abs(sc["accel"] / sc["avg"]) > 0.02:
                accel_note = " and accelerating"
            parts.append(f"13-wk trend {sc['slope_dir']} ~{sc['slope_pct']:.1f}%/wk{accel_note}")
            score *= 1.5  # boost for statistically significant trend

        # Anomaly flag
        anom = anom_lookup.get(item)
        if anom:
            parts.append(f"z-score {anom['z_score']:.1f} outlier in {anom['period']}")
            score *= 1.3

        detail = ", ".join(parts)

        # Build children from L2
        children = []
        for l2c in l2_cards[:3]:
            l2_ev = l2c.get("evidence", {})
            l2_pct = l2_ev.get("variance_pct")
            l2_item = l2c.get("title", "").replace("Level 2 Variance Driver: ", "")
            if l2_pct is not None and not l2_ev.get("is_new_from_zero"):
                child_parts = [f"{l2_pct:+.1f}% WoW (${abs(l2_ev.get('variance_dollar', 0)):,.0f})"]
                # Attach L2 anomaly if exists
                l2_anom = anom_lookup.get(l2_item)
                if l2_anom:
                    child_parts.append(f"z={l2_anom['z_score']:.1f}")
                children.append({"item": l2_item, "detail": ", ".join(child_parts), "level": "L2"})

        metric_label = label_for(m)
        add_insight(score, cat, f"{item} ({metric_label})", detail, m, "L1", children or None)

# ── Statistical trends (3-month slopes) ─────────────────────────────
for m, p in all_metrics.items():
    cat = categorize(m)
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

# ── Vs-average context (current week vs 13-week avg) ────────────────
for m, p in all_metrics.items():
    cat = categorize(m)
    stats = p.get("statistical_summary", {})
    hierarchy = p.get("hierarchical_analysis", {})
    l1_cards = hierarchy.get("level_1", {}).get("insight_cards", [])

    for driver in stats.get("top_drivers", [])[:3]:
        item = driver.get("item", "")
        avg = driver.get("avg", 0)
        std = driver.get("std", 0)
        item_min = driver.get("min", 0)
        item_max = driver.get("max", 0)

        # Find current value from hierarchy cards
        current = None
        for card in l1_cards:
            card_item = card.get("title", "").replace("Level 1 Variance Driver: ", "")
            if card_item == item:
                current = card.get("evidence", {}).get("current", 0)
                break

        if current and avg and avg > 0:
            vs_avg_pct = (current - avg) / avg * 100
            if abs(vs_avg_pct) > 5:  # material deviation
                above_below = "above" if vs_avg_pct > 0 else "below"
                detail = f"{item}: current ${current:,.0f} is {vs_avg_pct:+.1f}% vs 13-wk avg (${avg:,.0f})"

                # Historical rank
                if item_max and item_min:
                    if current >= item_max * 0.95:
                        detail += ", near 13-week high"
                    elif current <= item_min * 1.05:
                        detail += ", near 13-week low"

                score = abs(vs_avg_pct) * 0.3
                add_insight(score, f"{cat} vs avg", f"{item} {m} vs avg", detail, m, "vs_average")

# ── Anomalies (z-score outliers) ────────────────────────────────────
for m, p in all_metrics.items():
    cat = categorize(m)
    stats = p.get("statistical_summary", {})
    ss = stats.get("summary_stats", {})

    # Only recent anomalies (not the first partial week)
    period_range = ss.get("period_range", "")
    for anom in stats.get("anomalies", []):
        z = anom.get("z_score")
        item = anom.get("item_name", anom.get("item", ""))
        period = anom.get("period", "")
        value = anom.get("value", 0)
        anom_avg = anom.get("avg", 0)

        # Skip if it's the first period (likely partial week)
        if period and period_range and period == period_range.split(" to ")[0]:
            continue

        if z and abs(z) > 2.5:
            direction = "spike" if z > 0 else "dip"
            detail = f"{item}: {m} {direction} in {period} (z={z:.1f}, value ${value:,.0f} vs avg ${anom_avg:,.0f})"
            score = abs(z) * 0.4
            add_insight(score, "Anomaly", f"{item} {m} anomaly", detail, m, "anomaly")

# ── Acceleration signals (trend changing speed) ─────────────────────
for m, p in all_metrics.items():
    cat = categorize(m)
    stats = p.get("statistical_summary", {})
    for driver in stats.get("top_drivers", [])[:3]:
        slope = driver.get("slope_3mo")
        accel = driver.get("acceleration_3mo")
        avg = driver.get("avg", 0)
        item = driver.get("item", "")

        if slope and accel and avg and abs(accel) > abs(slope) * 0.5:
            # Acceleration is significant relative to slope
            if (slope > 0 and accel > 0) or (slope < 0 and accel < 0):
                detail = f"{item}: {m} trend is ACCELERATING ({'+' if slope > 0 else '-'}slope with same-direction acceleration)"
                score = abs(accel / avg * 100) * 0.2
                if score > 0.3:
                    add_insight(score, "Acceleration", f"{item} {m} acceleration", detail, m, "acceleration")

# ── Derived KPIs as insight cards ────────────────────────────────────
for kpi_name, kpi in derived_kpis.items():
    cur = kpi["current"]
    pri = kpi["prior"]
    chg = kpi["change_pct"]
    if kpi["format"] == "currency":
        val_str = f"${cur:,.2f}"
        pri_str = f"${pri:,.2f}"
    elif kpi["format"] == "percentage":
        val_str = f"{cur:.1f}%"
        pri_str = f"{pri:.1f}%"
    else:
        val_str = f"{cur:,.0f}"
        pri_str = f"{pri:,.0f}"
    detail = f"{val_str}, {chg:+.1f}% WoW (prior: {pri_str})"
    score = abs(chg) * 0.8  # KPIs are high-value signals
    add_insight(score, kpi["category"], f"{kpi['label']} (derived)", detail, kpi_name, "derived_kpi")

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
scored.sort(key=lambda x: x["_score"], reverse=True)

# Deduplicate
seen = set()
deduped = []
for entry in scored:
    key = (entry["title"], entry["metric"])
    if key not in seen:
        seen.add(key)
        deduped.append(entry)

top_raw = deduped[:args.top]

# Strip internal score before sending to LLM
top_for_llm = []
for entry in top_raw:
    clean = {k: v for k, v in entry.items() if not k.startswith("_")}
    top_for_llm.append(clean)

print(f"\n{'='*70}")
print(f"STEP 1: Scored {len(scored)} -> {len(deduped)} unique -> sending top {len(top_raw)} to Step 2")
print(f"{'='*70}\n")

for i, entry in enumerate(top_raw, 1):
    kids = f" [{len(entry.get('children',[]))} children]" if entry.get("children") else ""
    print(f"  {i:2d}. [{entry['_score']:.2f}] {entry['category']}: {entry['title']} — {entry['detail'][:80]}{kids}")


# ══════════════════════════════════════════════════════════════════════
# STEP 2: LLM selects most significant insights + links children
# ══════════════════════════════════════════════════════════════════════

from google import genai
from google.genai import types

# Network totals with contract labels
totals = {}
for m in ["ttl_rev_amt", "lh_rev_amt", "dh_miles", "ld_trf_mi", "truck_count", "ordr_cnt"]:
    if m in l0_data:
        d = l0_data[m]
        pct = f"{d['var_pct']:+.1f}%" if d.get("var_pct") is not None else "flat"
        totals[label_for(m)] = f"${d['current']:,.0f} ({pct} WoW)"

# Add derived KPIs to totals
for kpi_name, kpi in derived_kpis.items():
    if kpi["format"] == "currency":
        totals[kpi["label"]] = f"${kpi['current']:,.2f} ({kpi['change_pct']:+.1f}% WoW)"
    elif kpi["format"] == "percentage":
        totals[kpi["label"]] = f"{kpi['current']:.1f}% ({kpi['change_pct']:+.1f}% WoW)"
    else:
        totals[kpi["label"]] = f"{kpi['current']:,.0f} ({kpi['change_pct']:+.1f}% WoW)"

step2_input = json.dumps({
    "network_totals": totals,
    "ranked_insights": top_for_llm,
}, indent=2, default=str)

step2_schema = types.Schema(type=types.Type.OBJECT, properties={
    "selected_insights": types.Schema(type=types.Type.ARRAY, items=types.Schema(type=types.Type.OBJECT, properties={
        "headline": types.Schema(type=types.Type.STRING),
        "detail": types.Schema(type=types.Type.STRING),
        "supporting_evidence": types.Schema(type=types.Type.ARRAY, items=types.Schema(type=types.Type.STRING)),
        "vs_average": types.Schema(type=types.Type.STRING),
        "trend_duration": types.Schema(type=types.Type.STRING),
        "anomaly_flag": types.Schema(type=types.Type.STRING),
        "business_implication": types.Schema(type=types.Type.STRING),
        "category": types.Schema(type=types.Type.STRING),
    }, required=["headline", "detail", "supporting_evidence", "business_implication"])),
    "narrative_thesis": types.Schema(type=types.Type.STRING),
    "quality_assessment": types.Schema(type=types.Type.STRING,
        enum=["strong revenue weaker quality", "flat revenue execution pressure",
              "softer revenue healthier fundamentals", "broad decline", "mixed signals"]),
    "key_anomalies": types.Schema(type=types.Type.ARRAY, items=types.Schema(type=types.Type.STRING)),
}, required=["selected_insights", "narrative_thesis", "quality_assessment"])

step2_instruction = (
    "You are a senior analyst reviewing pre-ranked operational insight cards for a trucking company.\n\n"
    "SELECT 4-6 insights that tell ONE coherent story about the week.\n"
    "For each, include ALL supporting children/drill-down evidence — do not drop terminal names or percentages.\n\n"
    "RULES:\n"
    "- Preserve exact numbers, percentages, and terminal names from the input\n"
    "- For each insight, fill in vs_average (how it compares to 13-week average) and trend_duration (how many weeks this trend has persisted)\n"
    "- If an insight has an associated anomaly, fill anomaly_flag with the z-score and description\n"
    "- key_anomalies: list the 1-3 most notable statistical outliers from the ranked insights\n"
    "- business_implication must name the MECHANISM (yield compression, capacity underutilization) not just 'will pressure margins'\n"
    "- MUST include the highest-ranked POSITIVE signal if one exists. If no metric improved, say so explicitly.\n"
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
    "- bottom_line: 2 sentences. Sentence 1 = verdict. Sentence 2 = the 'but' quality insight.\n"
    "- what_moved: 4 items, each a different dimension. Fragment format with CONTEXT:\n"
    "  'East DH +9.4% WoW, 19% above 13-wk avg, 13-week upward trend'\n"
    "  Context must reference: vs avg, vs high/low, trend duration, or anomaly\n"
    "- trend_status: Duration + direction + acceleration. 'East DH up 13 straight weeks and accelerating'\n"
    "- where_it_came_from: Include anomaly context. 'Syracuse DH +23.4%, z-score outlier, well outside normal'\n"
    "  Positive = genuinely improving. If nothing improved, 'No bright spots'\n"
    "- why_it_matters: Quantify the mechanism. 'yield compression at 0.7%/wk' not 'margins will suffer'\n"
    "- next_week_outlook: Short, decisive, varied each time.\n"
    "- leadership_focus: 3 items. Name TERMINALS. Specific actions.\n"
    "- No duplication across sections.\n"
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
