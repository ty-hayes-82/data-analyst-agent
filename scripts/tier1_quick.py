"""Lean Tier 1 A/B: 4 tests, ~30s total."""
import json, os, sys, time, re
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
os.chdir(str(PROJECT))
sys.path.insert(0, str(PROJECT))
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "0"
os.environ["GOOGLE_API_KEY"] = "AIzaSyBuu7oBUo6qQRXEHDl068CazKdBOnhlTB4"

digest = json.loads((sorted((PROJECT / "outputs/tableau-ops_metrics_weekly/global/all").iterdir())[-1] / ".cache/digest.json").read_text())["digest"]
print(f"Digest: {len(digest)} chars")

from google import genai
from google.genai import types

INST = "You write a CEO weekly trucking brief. 90 seconds on mobile. Direct, declarative. Use ONLY digest data."
HARD = (
    " RULES: bottom_line=2-3 sentences with dollar amounts."
    " what_moved=3-5 items each with implication field."
    " trend_status=classify each as: positive momentum / developing trend / persistent issue / one-week noise / watchable. Include duration."
    " where_it_came_from=1 positive, 1 drag, 1 watch_item naming Region."
    " why_it_matters=connect execution to margin/earnings with a specific number."
    " leadership_focus=3-5 imperative actions (Hold, Intervene, Rebalance, Correct, Audit)."
)
WHY = (
    " WHY-IT-MATTERS ENFORCEMENT: Must connect execution quality to earnings."
    " Pattern: 'Deadhead +0.8pts -> margin weakened; $1.4M empty miles consumed ~6% of revenue gain'."
    " FAIL if generic like 'Performance was mixed'."
    " Every what_moved item implication = 1 line business consequence."
)

schema = types.Schema(type=types.Type.OBJECT, properties={
    "bottom_line": types.Schema(type=types.Type.STRING),
    "what_moved": types.Schema(type=types.Type.ARRAY, items=types.Schema(type=types.Type.OBJECT, properties={
        "metric": types.Schema(type=types.Type.STRING), "value": types.Schema(type=types.Type.STRING),
        "change": types.Schema(type=types.Type.STRING), "implication": types.Schema(type=types.Type.STRING),
    }, required=["metric", "value", "implication"])),
    "trend_status": types.Schema(type=types.Type.ARRAY, items=types.Schema(type=types.Type.OBJECT, properties={
        "area": types.Schema(type=types.Type.STRING),
        "classification": types.Schema(type=types.Type.STRING, enum=[
            "positive momentum", "developing trend", "persistent issue",
            "structural shift", "one-week noise", "watchable"]),
        "detail": types.Schema(type=types.Type.STRING), "duration": types.Schema(type=types.Type.STRING),
    }, required=["area", "classification", "detail"])),
    "where_it_came_from": types.Schema(type=types.Type.OBJECT, properties={
        "positive": types.Schema(type=types.Type.STRING), "drag": types.Schema(type=types.Type.STRING),
        "watch_item": types.Schema(type=types.Type.STRING),
    }, required=["positive", "drag"]),
    "why_it_matters": types.Schema(type=types.Type.STRING),
    "next_week_outlook": types.Schema(type=types.Type.STRING),
    "leadership_focus": types.Schema(type=types.Type.ARRAY, items=types.Schema(type=types.Type.STRING)),
}, required=["bottom_line", "what_moved", "trend_status", "where_it_came_from", "why_it_matters", "leadership_focus"])

msg = f"CEO brief:\n\n{digest}"


def cnt(text):
    pats = [r'\$[\d,]+(?:\.\d+)?[KMB]?', r'\d+(?:,\d{3})*(?:\.\d+)?%',
            r'\d+(?:,\d{3})*\.\d+', r'\d+(?:,\d{3})+']
    return sum(len(re.findall(p, text)) for p in pats)


OUT = PROJECT / "benchmarks" / f"tier1_{time.strftime('%H%M%S')}"
OUT.mkdir(parents=True, exist_ok=True)
results = []

# ── A: Free-form (no schema) ──
print("\n--- A: Free-form ---")
t0 = time.time()
client = genai.Client()
r = client.models.generate_content(model="gemini-3-flash-preview", contents=msg,
    config=types.GenerateContentConfig(system_instruction=INST + HARD, response_modalities=["TEXT"],
        response_mime_type="application/json", temperature=0.2))
el = time.time() - t0
raw = r.text; (OUT / "A_freeform.json").write_text(raw, encoding="utf-8")
b = json.loads(raw)
trends = b.get("trend_status", []); movers = b.get("what_moved", [])
valid = {"positive momentum", "developing trend", "persistent issue", "structural shift", "one-week noise", "watchable"}
tc = sum(1 for t in trends if isinstance(t, dict) and t.get("classification", "").lower() in valid)
imp = sum(1 for m in movers if isinstance(m, dict) and m.get("implication"))
where = b.get("where_it_came_from", {}) if isinstance(b.get("where_it_came_from"), dict) else {}
rc = sum(1 for k in ["positive", "drag", "watch_item"] if where.get(k))
nums = cnt(json.dumps(b))
print(f"  {el:.1f}s | Nums:{nums} Trends:{tc}/{len(trends)} Impl:{imp}/{len(movers)} Rgn:{rc}")
print(f"  Bottom: {b.get('bottom_line', '')[:120]}")
print(f"  Why: {b.get('why_it_matters', '')[:120]}")
results.append({"name": "A_freeform", "time": round(el, 1), "nums": nums,
    "trends": f"{tc}/{len(trends)}", "impl": f"{imp}/{len(movers)}", "regions": rc})

# ── B: Structured Output (schema enforced) ──
print("\n--- B: Structured ---")
t0 = time.time()
r = client.models.generate_content(model="gemini-3-flash-preview", contents=msg,
    config=types.GenerateContentConfig(system_instruction=INST + HARD, response_modalities=["TEXT"],
        response_mime_type="application/json", response_schema=schema, temperature=0.2))
el = time.time() - t0
raw = r.text; (OUT / "B_structured.json").write_text(raw, encoding="utf-8")
b = json.loads(raw)
trends = b.get("trend_status", []); movers = b.get("what_moved", [])
tc = sum(1 for t in trends if isinstance(t, dict) and t.get("classification", "").lower() in valid)
imp = sum(1 for m in movers if isinstance(m, dict) and m.get("implication"))
where = b.get("where_it_came_from", {}) if isinstance(b.get("where_it_came_from"), dict) else {}
rc = sum(1 for k in ["positive", "drag", "watch_item"] if where.get(k))
nums = cnt(json.dumps(b))
print(f"  {el:.1f}s | Nums:{nums} Trends:{tc}/{len(trends)} Impl:{imp}/{len(movers)} Rgn:{rc}")
print(f"  Bottom: {b.get('bottom_line', '')[:120]}")
print(f"  Why: {b.get('why_it_matters', '')[:120]}")
results.append({"name": "B_structured", "time": round(el, 1), "nums": nums,
    "trends": f"{tc}/{len(trends)}", "impl": f"{imp}/{len(movers)}", "regions": rc})

# ── C: Two-Step (extract + render) ──
print("\n--- C: Two-Step ---")
t0 = time.time()
s1 = client.models.generate_content(model="gemini-2.5-flash-lite",
    contents=f"Extract operational facts as JSON:\n{digest}",
    config=types.GenerateContentConfig(system_instruction="Extract structured facts only.",
        response_modalities=["TEXT"], response_mime_type="application/json", temperature=0.1))
print(f"  Step1: {time.time()-t0:.1f}s")
r = client.models.generate_content(model="gemini-3-flash-preview",
    contents=f"Transform to CEO brief:\n{s1.text}",
    config=types.GenerateContentConfig(system_instruction=INST + HARD + WHY, response_modalities=["TEXT"],
        response_mime_type="application/json", response_schema=schema, temperature=0.2))
el = time.time() - t0
raw = r.text; (OUT / "C_twostep.json").write_text(raw, encoding="utf-8")
b = json.loads(raw)
trends = b.get("trend_status", []); movers = b.get("what_moved", [])
tc = sum(1 for t in trends if isinstance(t, dict) and t.get("classification", "").lower() in valid)
imp = sum(1 for m in movers if isinstance(m, dict) and m.get("implication"))
where = b.get("where_it_came_from", {}) if isinstance(b.get("where_it_came_from"), dict) else {}
rc = sum(1 for k in ["positive", "drag", "watch_item"] if where.get(k))
nums = cnt(json.dumps(b))
print(f"  Total: {el:.1f}s | Nums:{nums} Trends:{tc}/{len(trends)} Impl:{imp}/{len(movers)} Rgn:{rc}")
print(f"  Bottom: {b.get('bottom_line', '')[:120]}")
print(f"  Why: {b.get('why_it_matters', '')[:120]}")
results.append({"name": "C_twostep", "time": round(el, 1), "nums": nums,
    "trends": f"{tc}/{len(trends)}", "impl": f"{imp}/{len(movers)}", "regions": rc})

# ── D: Structured + Why enforcement ──
print("\n--- D: Structured + Why ---")
t0 = time.time()
r = client.models.generate_content(model="gemini-3-flash-preview", contents=msg,
    config=types.GenerateContentConfig(system_instruction=INST + HARD + WHY, response_modalities=["TEXT"],
        response_mime_type="application/json", response_schema=schema, temperature=0.2))
el = time.time() - t0
raw = r.text; (OUT / "D_struct_why.json").write_text(raw, encoding="utf-8")
b = json.loads(raw)
trends = b.get("trend_status", []); movers = b.get("what_moved", [])
tc = sum(1 for t in trends if isinstance(t, dict) and t.get("classification", "").lower() in valid)
imp = sum(1 for m in movers if isinstance(m, dict) and m.get("implication"))
where = b.get("where_it_came_from", {}) if isinstance(b.get("where_it_came_from"), dict) else {}
rc = sum(1 for k in ["positive", "drag", "watch_item"] if where.get(k))
nums = cnt(json.dumps(b))
print(f"  {el:.1f}s | Nums:{nums} Trends:{tc}/{len(trends)} Impl:{imp}/{len(movers)} Rgn:{rc}")
print(f"  Bottom: {b.get('bottom_line', '')[:120]}")
print(f"  Why: {b.get('why_it_matters', '')[:120]}")
results.append({"name": "D_struct_why", "time": round(el, 1), "nums": nums,
    "trends": f"{tc}/{len(trends)}", "impl": f"{imp}/{len(movers)}", "regions": rc})

# ── Summary ──
print(f"\n{'='*75}")
print(f"{'Test':<18} {'Time':>6} {'Nums':>5} {'Trends':>8} {'Impl':>7} {'Rgn':>4}")
print("-" * 55)
for r in results:
    print(f"{r['name']:<18} {r['time']:>5.1f}s {r['nums']:>5} {r['trends']:>8} {r['impl']:>7} {r['regions']:>4}")
print(f"\nOutputs: {OUT}")
