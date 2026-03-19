"""Regional CEO briefs: network-level + one per region, same insight cards.

Step 1 (code): Score all insight cards once.
Step 2+3 (LLM): Run for network, then for each region (filtered cards).
Output: Combined document with all briefs.

Usage:
  python scripts/regional_briefs.py
  python scripts/regional_briefs.py --model gemini-3.1-flash-lite-preview
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
parser.add_argument("--temp", type=float, default=0.2)
parser.add_argument("--top", type=int, default=12, help="Top N insights per scope")
args = parser.parse_args()

cache_dir = sorted((PROJECT / "outputs/tableau-ops_metrics_weekly/global/all").iterdir())[-1]

# Load contract
import yaml
contract_path = PROJECT / "config" / "datasets" / "tableau" / "ops_metrics_weekly" / "contract.yaml"
contract = yaml.safe_load(contract_path.read_text(encoding="utf-8")) if contract_path.exists() else {}

_metric_cat = {}
_metric_label = {}
for md in contract.get("metrics", []):
    _metric_cat[md["name"]] = md.get("brief_category", "Operations")
    _metric_label[md["name"]] = md.get("brief_label", md.get("display_name", md["name"]))

def categorize(m): return _metric_cat.get(m, "Operations")
def label_for(m): return _metric_label.get(m, m)

# Load all metric data
all_metrics = {}
for jf in sorted(cache_dir.glob("metric_*.json")):
    all_metrics[jf.stem.replace("metric_", "")] = json.loads(jf.read_text())

# Collect L0 totals for derived KPIs
_l0_cur = {}
_l0_pri = {}
for m, p in all_metrics.items():
    l0 = p.get("hierarchical_analysis", {}).get("level_0", {}).get("insight_cards", [])
    if l0:
        ev = l0[0].get("evidence", {})
        _l0_cur[m] = ev.get("current", 0)
        _l0_pri[m] = ev.get("prior", 0)
    else:
        l1 = p.get("hierarchical_analysis", {}).get("level_1", {}).get("insight_cards", [])
        if l1:
            _l0_cur[m] = sum(c.get("evidence", {}).get("current", 0) for c in l1)
            _l0_pri[m] = sum(c.get("evidence", {}).get("prior", 0) for c in l1)

# Compute derived KPIs
derived_kpis = {}
for kd in contract.get("derived_kpis", []):
    nc = _l0_cur.get(kd.get("numerator", ""))
    np_ = _l0_pri.get(kd.get("numerator", ""))
    dc = _l0_cur.get(kd.get("denominator", ""))
    dp = _l0_pri.get(kd.get("denominator", ""))
    mult = kd.get("multiply", 1)
    dd = kd.get("divide_by_days", 1)
    if nc and dc and dc > 0 and dp and dp > 0:
        cv = (nc / dc / dd) * mult
        pv = (np_ / dp / dd) * mult
        derived_kpis[kd["name"]] = {
            "label": kd.get("brief_label", kd["name"]),
            "category": kd.get("brief_category", "Operations"),
            "current": cv, "prior": pv,
            "change_pct": (cv - pv) / abs(pv) * 100 if pv else 0,
            "format": kd.get("format", "float"),
        }

# ══════════════════════════════════════════════════════════════════════
# STEP 1: Score ALL insight cards once (code, no LLM)
# ══════════════════════════════════════════════════════════════════════

all_scored = []  # list of dicts with _score, _region, etc.

for m, p in all_metrics.items():
    cat = categorize(m)
    hierarchy = p.get("hierarchical_analysis", {})
    stats = p.get("statistical_summary", {})

    # Stat context — compute 4-week avg from recent periods if available
    stat_ctx = {}
    # Get all periods from the statistical data to compute short-term averages
    for driver in stats.get("top_drivers", []):
        item = driver.get("item", "")
        avg_13wk = driver.get("avg", 0)
        stat_ctx[item] = {
            "avg_13wk": avg_13wk,
            "slope_pct": abs(driver.get("slope_3mo", 0) / avg_13wk * 100) if avg_13wk else 0,
            "slope_dir": "up" if driver.get("slope_3mo", 0) > 0 else "down",
            "slope_p": driver.get("slope_3mo_p_value"),
            "min": driver.get("min", 0), "max": driver.get("max", 0),
            "accel": driver.get("acceleration_3mo", 0),
        }
    # Alias for backward compat
    for item in stat_ctx:
        stat_ctx[item]["avg"] = stat_ctx[item]["avg_13wk"]

    # Anomaly lookup
    ss = stats.get("summary_stats", {})
    first_p = ss.get("period_range", "").split(" to ")[0] if ss.get("period_range") else ""
    anom_lookup = {}
    for anom in stats.get("anomalies", []):
        if anom.get("period") == first_p: continue
        ai = anom.get("item", "")
        if ai not in anom_lookup and abs(anom.get("z_score", 0)) > 2.0:
            anom_lookup[ai] = anom

    l1_cards = hierarchy.get("level_1", {}).get("insight_cards", [])
    l2_cards = hierarchy.get("level_2", {}).get("insight_cards", [])

    for card in l1_cards:
        ev = card.get("evidence", {})
        var_pct = ev.get("variance_pct")
        var_dollar = ev.get("variance_dollar", 0)
        current = ev.get("current", 0)
        share = ev.get("share_of_total", 0)
        if ev.get("is_new_from_zero") or var_pct is None: continue
        item = card.get("title", "").replace("Level 1 Variance Driver: ", "")

        magnitude = min(abs(var_pct) / 10, 5)
        score = magnitude * max(share, 0.05) * 2.0

        parts = [f"{var_pct:+.1f}% WoW (${abs(var_dollar):,.0f}), current ${current:,.0f}"]
        sc = stat_ctx.get(item, {})
        if sc.get("avg_13wk") and current:
            vs_13wk = (current - sc["avg_13wk"]) / sc["avg_13wk"] * 100
            if abs(vs_13wk) > 3: parts.append(f"{vs_13wk:+.0f}% vs 13-wk avg")
            if sc.get("max") and current >= sc["max"] * 0.95: parts.append("near 13-wk high")
            elif sc.get("min") and current <= sc["min"] * 1.05: parts.append("near 13-wk low")
        if sc.get("slope_p") is not None and sc["slope_p"] < 0.15 and sc.get("slope_pct", 0) > 0.5:
            accel = " and accelerating" if sc.get("accel") and sc["avg"] and abs(sc["accel"] / sc["avg"]) > 0.02 else ""
            parts.append(f"13-wk trend {sc['slope_dir']} ~{sc['slope_pct']:.1f}%/wk{accel}")
            score *= 1.5
        anom = anom_lookup.get(item)
        if anom:
            parts.append(f"z-score {anom['z_score']:.1f} outlier")
            score *= 1.3

        children = []
        for l2c in l2_cards[:3]:
            l2_ev = l2c.get("evidence", {})
            l2_pct = l2_ev.get("variance_pct")
            l2_item = l2c.get("title", "").replace("Level 2 Variance Driver: ", "")
            if l2_pct is not None and not l2_ev.get("is_new_from_zero"):
                children.append({"item": l2_item, "detail": f"{l2_pct:+.1f}% WoW (${abs(l2_ev.get('variance_dollar', 0)):,.0f})", "level": "L2"})

        all_scored.append({
            "category": cat, "title": f"{item} ({label_for(m)})", "detail": ", ".join(parts),
            "metric": m, "level": "L1", "_score": round(score, 3), "_region": item,
            **({"children": children} if children else {}),
        })

    # Trends
    for driver in stats.get("top_drivers", [])[:5]:
        slope = driver.get("slope_3mo")
        p_val = driver.get("slope_3mo_p_value")
        avg = driver.get("avg", 0)
        item = driver.get("item", "")
        if slope and p_val is not None and p_val < 0.2 and avg:
            pct = abs(slope / avg * 100)
            if pct < 0.5: continue
            direction = "up" if slope > 0 else "down"
            score = (1 - p_val) * pct * 0.5
            all_scored.append({
                "category": "Trend", "title": f"{item} {label_for(m)} trend",
                "detail": f"trending {direction} ~{pct:.1f}%/wk over 13 weeks (p={p_val:.3f}), avg ${avg:,.0f}",
                "metric": m, "level": "statistical", "_score": round(score, 3), "_region": item,
            })

# Derived KPI cards
for kn, kv in derived_kpis.items():
    fmt = f"${kv['current']:.2f}" if kv["format"] == "currency" else (f"{kv['current']:.1f}%" if kv["format"] == "percentage" else f"{kv['current']:,.0f}")
    all_scored.append({
        "category": kv["category"], "title": f"{kv['label']} (derived)",
        "detail": f"{fmt}, {kv['change_pct']:+.1f}% WoW",
        "metric": kn, "level": "derived_kpi", "_score": round(abs(kv["change_pct"]) * 0.8, 3), "_region": "Network",
    })

# Cross-metric: yield signal
rev_pct = None; mi_pct = None
for e in all_scored:
    if e["metric"] == "ttl_rev_amt" and e["level"] == "L1" and e["_region"] == "East":
        pass  # use L0 data instead
for m2, p2 in all_metrics.items():
    l0 = p2.get("hierarchical_analysis", {}).get("level_0", {}).get("insight_cards", [])
    if l0:
        if m2 == "ttl_rev_amt": rev_pct = l0[0].get("evidence", {}).get("variance_pct")
        if m2 == "ld_trf_mi": mi_pct = l0[0].get("evidence", {}).get("variance_pct")
if rev_pct is not None and mi_pct is not None and abs(abs(rev_pct) - abs(mi_pct)) > 0.5:
    if abs(rev_pct) > abs(mi_pct):
        detail = f"Revenue {rev_pct:+.1f}% but loaded miles only {mi_pct:+.1f}% -- yield compressing"
    else:
        detail = f"Loaded miles {mi_pct:+.1f}% but revenue only {rev_pct:+.1f}% -- yield improving"
    all_scored.append({"category": "Yield signal", "title": "Yield vs Volume", "detail": detail,
                       "metric": "cross", "level": "cross", "_score": abs(rev_pct - mi_pct) * 2, "_region": "Network"})

all_scored.sort(key=lambda x: x["_score"], reverse=True)

# Deduplicate
seen = set()
deduped = []
for e in all_scored:
    key = (e["title"], e["metric"])
    if key not in seen:
        seen.add(key)
        deduped.append(e)

# Discover regions
regions = sorted(set(e["_region"] for e in deduped if e["level"] == "L1"))
print(f"Scored {len(all_scored)} insights, {len(deduped)} unique, regions: {regions}")

# ══════════════════════════════════════════════════════════════════════
# Generate briefs: network + each region
# ══════════════════════════════════════════════════════════════════════

from google import genai
from google.genai import types

prompt = (PROJECT / "config/prompts/executive_brief_ceo.md").read_text(encoding="utf-8").strip()
for k, v in {"metric_count": str(len(all_metrics)), "analysis_period": "the week ending 2026-02-21",
             "scope_preamble": "", "dataset_specific_append": "", "prompt_variant_append": ""}.items():
    prompt = prompt.replace("{" + k + "}", v)

step2_instruction = (
    "You are a senior analyst reviewing pre-ranked insight cards.\n"
    "SELECT 4-6 insights that tell ONE coherent story.\n"
    "Include ALL children/drill-downs. Preserve numbers and terminal names.\n"
    "Fill vs_average, trend_duration, anomaly_flag where available.\n"
    "MUST include highest-ranked positive signal if one exists.\n"
    "business_implication must name the MECHANISM.\n"
)

step2_schema = types.Schema(type=types.Type.OBJECT, properties={
    "selected_insights": types.Schema(type=types.Type.ARRAY, items=types.Schema(type=types.Type.OBJECT, properties={
        "headline": types.Schema(type=types.Type.STRING),
        "detail": types.Schema(type=types.Type.STRING),
        "supporting_evidence": types.Schema(type=types.Type.ARRAY, items=types.Schema(type=types.Type.STRING)),
        "business_implication": types.Schema(type=types.Type.STRING),
    }, required=["headline", "detail", "supporting_evidence", "business_implication"])),
    "narrative_thesis": types.Schema(type=types.Type.STRING),
    "quality_assessment": types.Schema(type=types.Type.STRING,
        enum=["strong revenue weaker quality", "flat revenue execution pressure",
              "softer revenue healthier fundamentals", "broad decline", "mixed signals"]),
}, required=["selected_insights", "narrative_thesis", "quality_assessment"])

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


def generate_brief(scope_name, scope_insights, scope_totals):
    """Run Steps 2+3 for a scope (network or region)."""
    clean = [{k: v for k, v in e.items() if not k.startswith("_")} for e in scope_insights]

    # Step 2: Curate
    s2_input = json.dumps({"scope": scope_name, "totals": scope_totals, "ranked_insights": clean}, indent=2, default=str)
    client = genai.Client()
    r2 = client.models.generate_content(model=args.model, contents=s2_input,
        config=types.GenerateContentConfig(system_instruction=step2_instruction, response_modalities=["TEXT"],
            response_mime_type="application/json", response_schema=step2_schema, temperature=0.1))
    curated = json.loads(r2.text)

    # Step 3: Synthesize
    scope_prompt = prompt
    if scope_name != "Network":
        scope_prompt += f"\n\nSCOPE: This brief covers the {scope_name} region ONLY. All insights must be specific to {scope_name}."
    s3_input = (
        f"Week ending: 2026-02-21. Scope: {scope_name}. WoW comparisons.\n\n"
        f"THESIS: {curated.get('quality_assessment', 'mixed')} -- {curated.get('narrative_thesis', '')}\n\n"
        f"TOTALS:\n" + "\n".join(f"  {k}: {v}" for k, v in scope_totals.items())
        + f"\n\nCURATED INSIGHTS:\n" + json.dumps(curated.get("selected_insights", []), indent=2)
        + "\n\nRules: fragments not sentences in what_moved. Duration in trends. Terminals in leadership."
    )
    r3 = client.models.generate_content(model=args.model, contents=s3_input,
        config=types.GenerateContentConfig(system_instruction=scope_prompt, response_modalities=["TEXT"],
            response_mime_type="application/json", response_schema=brief_schema, temperature=args.temp))
    return json.loads(r3.text), curated.get("quality_assessment", "mixed")


def render_brief(scope_name, brief, thesis):
    lines = [f"\n## {scope_name}", f"*Thesis: {thesis}*\n"]
    lines.append(f"**Bottom line:** {brief['bottom_line']}\n")
    lines.append("**What moved the business**\n")
    for m in brief["what_moved"]:
        lines.append(f"- {m['label']}: {m['line']}")
    lines.append("\n**Trend status**\n")
    for t in brief["trend_status"]:
        lines.append(f"- {t}")
    w = brief["where_it_came_from"]
    lines.append("\n**Where it came from**\n")
    lines.append(f"- Positive: {w['positive']}")
    lines.append(f"- Drag: {w['drag']}")
    if w.get("watch_item"): lines.append(f"- Watch item: {w['watch_item']}")
    lines.append(f"\n**Why it matters:** {brief['why_it_matters']}")
    lines.append(f"\n**Next-week outlook:** {brief['next_week_outlook']}")
    lines.append("\n**Leadership focus**\n")
    for a in brief["leadership_focus"]:
        lines.append(f"- {a}")
    return "\n".join(lines)


# ── Build totals ────────────────────────────────────────────────────
network_totals = {}
for m in ["ttl_rev_amt", "lh_rev_amt", "dh_miles", "ld_trf_mi", "truck_count", "ordr_cnt"]:
    if m in _l0_cur:
        pct_data = None
        for e in deduped:
            if e["metric"] == m and e["level"] == "L1":
                break
        # Use L0 variance
        for mm, pp in all_metrics.items():
            if mm == m:
                l0c = pp.get("hierarchical_analysis", {}).get("level_0", {}).get("insight_cards", [])
                if l0c:
                    pct_data = l0c[0].get("evidence", {}).get("variance_pct")
        pct_str = f"{pct_data:+.1f}%" if pct_data is not None else ""
        network_totals[label_for(m)] = f"${_l0_cur[m]:,.0f} ({pct_str} WoW)"
for kn, kv in derived_kpis.items():
    fmt = f"${kv['current']:.2f}" if kv["format"] == "currency" else f"{kv['current']:.1f}%"
    network_totals[kv["label"]] = f"{fmt} ({kv['change_pct']:+.1f}% WoW)"

# ── Generate briefs ─────────────────────────────────────────────────
all_briefs = []
t_total = time.time()

# Network brief
print(f"\n{'='*60}\nGenerating: NETWORK\n{'='*60}")
t0 = time.time()
network_insights = deduped[:args.top]
nb, nt = generate_brief("Network", network_insights, network_totals)
print(f"  [{time.time()-t0:.1f}s] Thesis: {nt}")
all_briefs.append(render_brief("Network Overview", nb, nt))

# Regional briefs
for region in regions:
    if region in ("Corporate", "Target Dedicated"):  # skip minor segments
        continue
    print(f"\n{'='*60}\nGenerating: {region}\n{'='*60}")
    t0 = time.time()

    # Filter insights for this region
    region_insights = [e for e in deduped if e["_region"] == region or e["_region"] == "Network"][:args.top]

    # Build region totals from L1 cards
    region_totals = {}
    for m, p in all_metrics.items():
        for card in p.get("hierarchical_analysis", {}).get("level_1", {}).get("insight_cards", []):
            item = card.get("title", "").replace("Level 1 Variance Driver: ", "")
            if item == region:
                ev = card.get("evidence", {})
                pct = ev.get("variance_pct")
                pct_str = f"{pct:+.1f}%" if pct is not None else ""
                region_totals[label_for(m)] = f"${ev.get('current', 0):,.0f} ({pct_str} WoW)"

    if region_insights:
        rb, rt = generate_brief(region, region_insights, region_totals)
        print(f"  [{time.time()-t0:.1f}s] Thesis: {rt}")
        all_briefs.append(render_brief(f"{region} Region", rb, rt))
    else:
        print(f"  Skipped — no insights")

# ── Output combined document ────────────────────────────────────────
total_time = time.time() - t_total
header = f"# Weekly Performance Brief — Week Ending February 21, 2026\n\n*Generated in {total_time:.1f}s | {len(all_briefs)} sections | {args.model}*\n"
combined = header + "\n---\n".join(all_briefs)

out_path = PROJECT / "benchmarks" / "regional_brief.md"
out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text(combined, encoding="utf-8")

print(f"\n\n{'='*60}")
print(f"COMBINED BRIEF ({total_time:.1f}s total)")
print(f"{'='*60}")
print(combined)
