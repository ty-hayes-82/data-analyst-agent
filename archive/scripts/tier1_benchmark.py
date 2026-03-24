"""Tier 1 A/B Tests: Structured Output, Two-Step Pipeline, Why-It-Matters Enforcement."""
import json, os, sys, time, re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
os.chdir(str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")
# Also try parent .env for API keys (but don't override existing)
load_dotenv(PROJECT_ROOT.parent / ".env", override=False)
# Use environment for Vertex AI setting (default to Vertex if SA exists)
if "GOOGLE_GENAI_USE_VERTEXAI" not in os.environ:
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "1" if os.path.exists(PROJECT_ROOT / "service-account.json") or os.getenv("GOOGLE_APPLICATION_CREDENTIALS") else "0"
os.environ["EXECUTIVE_BRIEF_STYLE"] = "ceo"

# Load cached digest — check local outputs or use VPS-synced cache
outputs_base = PROJECT_ROOT / "outputs" / "tableau-ops_metrics_weekly" / "global" / "all"
if not outputs_base.exists():
    # Try to find any cached digest
    for p in PROJECT_ROOT.rglob(".cache/digest.json"):
        outputs_base = p.parent.parent
        break
if outputs_base.exists() and any(outputs_base.iterdir()):
    CACHE_DIR = sorted(outputs_base.iterdir())[-1]
else:
    print("No cached outputs found locally. Syncing latest from VPS 2...")
    import subprocess
    outputs_base.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "scp", "-r",
        "root@187.124.147.182:/data/data-analyst-agent/outputs/tableau-ops_metrics_weekly/global/all/20260319_172228",
        str(outputs_base) + "/",
    ], check=True)
    CACHE_DIR = sorted(outputs_base.iterdir())[-1]

digest_data = json.loads((CACHE_DIR / ".cache" / "digest.json").read_text())
digest = digest_data["digest"]
sep = "=" * 70
print(f"Digest: {len(digest)} chars from {CACHE_DIR.name}")

from google import genai
from google.genai import types

MODEL = "gemini-3-flash-preview"
TEMP = 0.2

OUT = Path("benchmarks") / f"tier1_{time.strftime('%Y%m%d_%H%M%S')}"
OUT.mkdir(parents=True, exist_ok=True)

# CEO Brief Schema for structured output
CEO_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "week_ending": types.Schema(type=types.Type.STRING),
        "bottom_line": types.Schema(type=types.Type.STRING),
        "what_moved": types.Schema(
            type=types.Type.ARRAY,
            items=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "metric": types.Schema(type=types.Type.STRING),
                    "value": types.Schema(type=types.Type.STRING),
                    "change": types.Schema(type=types.Type.STRING),
                    "context": types.Schema(type=types.Type.STRING),
                    "implication": types.Schema(type=types.Type.STRING),
                },
                required=["metric", "value", "change", "implication"],
            ),
        ),
        "trend_status": types.Schema(
            type=types.Type.ARRAY,
            items=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "area": types.Schema(type=types.Type.STRING),
                    "classification": types.Schema(
                        type=types.Type.STRING,
                        enum=["positive momentum", "developing trend", "persistent issue",
                              "structural shift", "one-week noise", "watchable"],
                    ),
                    "detail": types.Schema(type=types.Type.STRING),
                    "duration": types.Schema(type=types.Type.STRING),
                },
                required=["area", "classification", "detail"],
            ),
        ),
        "where_it_came_from": types.Schema(
            type=types.Type.OBJECT,
            properties={
                "positive": types.Schema(type=types.Type.STRING),
                "drag": types.Schema(type=types.Type.STRING),
                "watch_item": types.Schema(type=types.Type.STRING),
            },
            required=["positive", "drag"],
        ),
        "why_it_matters": types.Schema(type=types.Type.STRING),
        "next_week_outlook": types.Schema(type=types.Type.STRING),
        "leadership_focus": types.Schema(
            type=types.Type.ARRAY,
            items=types.Schema(type=types.Type.STRING),
        ),
    },
    required=["bottom_line", "what_moved", "trend_status", "where_it_came_from",
              "why_it_matters", "next_week_outlook", "leadership_focus"],
)

BASE_INSTRUCTION = (
    "You are writing a weekly CEO performance brief for a trucking/logistics company. "
    "The CEO reads this on mobile in 90 seconds. Be direct, declarative, specific. "
    "Use ONLY data from the digest. Do NOT invent numbers. "
    "Every metric must include its business implication. "
    "Only include metrics that change business meaning. Max 5 metrics unless critical. "
    "Keep total brief under 150 words of prose (excluding metric values)."
)

HARD_RULES = (
    "\n\nHARD RULES (RESPONSE REJECTED IF VIOLATED):\n"
    "1. bottom_line: 2-3 sentences, must reference at least 2 specific dollar amounts\n"
    "2. what_moved: 3-5 items, each MUST have implication\n"
    "3. trend_status: each MUST have classification from: positive momentum, developing trend, "
    "persistent issue, structural shift, one-week noise, watchable. Include duration.\n"
    "4. where_it_came_from: 1 positive, 1 drag, 1 watch_item. Each names Region + Terminal.\n"
    "5. why_it_matters: 1-2 sentences connecting execution to margin/earnings with a number\n"
    "6. leadership_focus: 3-5 items, imperative verb first (Hold, Intervene, Rebalance, Correct, Audit)\n"
    "7. NO generic phrases: 'significant increase', 'multiple regions', 'various factors'\n"
)

WHY_ENFORCEMENT = (
    "\n\nCRITICAL WHY-IT-MATTERS RULES:\n"
    "- why_it_matters MUST connect execution quality to earnings/margin quality\n"
    "- Pattern: '[metric] [direction] -> [earnings consequence]'\n"
    "- Example: 'Deadhead +0.8 pts -> margin quality weakened; the $1.4M in empty miles consumed ~6% of revenue gain'\n"
    "- FAIL if generic like 'Performance was mixed'\n"
    "\nIMPLICATION RULES:\n"
    "- Every what_moved item MUST have implication = 1 line connecting metric to business outcome\n"
    "- Example: 'Revenue +$6.7M in East -> strongest regional contribution, offsetting Central weakness'\n"
)

results = []


def count_nums(text):
    patterns = [r'\$[\d,]+(?:\.\d+)?[KMB]?', r'\d+(?:,\d{3})*(?:\.\d+)?%',
                r'\d+(?:,\d{3})*(?:\.\d+)?[KMB](?!\w)', r'\d+(?:,\d{3})*\.\d+',
                r'\d+(?:,\d{3})+']
    return sum(len(re.findall(p, text)) for p in patterns)


def word_count(text):
    return len(re.sub(r'[\$\d,\.%]+', '', text).split())


def score_brief(name, raw, elapsed):
    """Score a brief JSON and add to results."""
    try:
        brief = json.loads(raw)
    except json.JSONDecodeError:
        results.append({"name": name, "status": "JSON_FAIL", "time_s": round(elapsed, 1)})
        return

    bottom = brief.get("bottom_line", "")
    trends = brief.get("trend_status", []) if isinstance(brief.get("trend_status"), list) else []
    valid_cl = {"positive momentum", "developing trend", "persistent issue",
                "structural shift", "one-week noise", "watchable"}
    tc = sum(1 for t in trends if isinstance(t, dict) and t.get("classification", "").lower() in valid_cl)
    movers = brief.get("what_moved", []) if isinstance(brief.get("what_moved"), list) else []
    impl = sum(1 for m in movers if isinstance(m, dict) and m.get("implication"))
    where = brief.get("where_it_came_from", {}) if isinstance(brief.get("where_it_came_from"), dict) else {}
    rc = sum(1 for k in ["positive", "drag", "watch_item"] if where.get(k))
    all_text = json.dumps(brief)

    r = {
        "name": name, "status": "OK", "time_s": round(elapsed, 1),
        "nums": count_nums(all_text), "words": word_count(all_text), "chars": len(raw),
        "has_why": bool(brief.get("why_it_matters")),
        "trend_classified": f"{tc}/{len(trends)}",
        "implications": f"{impl}/{len(movers)}",
        "regions": rc,
        "bottom": bottom[:150],
    }
    results.append(r)
    print(f"  {elapsed:.1f}s | Nums:{r['nums']} Words:{r['words']} Trends:{r['trend_classified']} Impl:{r['implications']} Regions:{rc}")
    print(f"  Bottom: {bottom[:120]}...")


def call_llm(name, instruction, user_msg, schema=None, model=MODEL, temp=TEMP):
    print(f"\n{sep}\nTEST: {name}\n{sep}")
    config_kw = {
        "system_instruction": instruction,
        "response_modalities": ["TEXT"],
        "response_mime_type": "application/json",
        "temperature": temp,
    }
    if schema:
        config_kw["response_schema"] = schema
    config = types.GenerateContentConfig(**config_kw)
    t0 = time.time()
    try:
        client = genai.Client()
        resp = client.models.generate_content(model=model, contents=user_msg, config=config)
        elapsed = time.time() - t0
        raw = resp.text or ""
        (OUT / f"{name}.json").write_text(raw, encoding="utf-8")
        score_brief(name, raw, elapsed)
    except Exception as e:
        elapsed = time.time() - t0
        print(f"  ERROR ({elapsed:.1f}s): {str(e)[:120]}")
        results.append({"name": name, "status": "ERROR", "time_s": round(elapsed, 1), "error": str(e)[:120]})


user_msg = f"Generate the CEO weekly performance brief.\n\nDigest:\n{digest}"

# ── Test A: Free-form JSON (no schema) ──
call_llm("A_freeform", BASE_INSTRUCTION + HARD_RULES, user_msg)

# ── Test B: Structured Output (schema enforced) ──
call_llm("B_structured", BASE_INSTRUCTION + HARD_RULES, user_msg, schema=CEO_SCHEMA)

# ── Test C: Two-Step Pipeline ──
print(f"\n{sep}\nTEST: C_twostep\n{sep}")
t0 = time.time()
try:
    client = genai.Client()
    # Step 1: Extract with cheap model
    s1_config = types.GenerateContentConfig(
        system_instruction="Extract structured operational facts. Return JSON with metrics, variances, regions, trends.",
        response_modalities=["TEXT"], response_mime_type="application/json", temperature=0.1,
    )
    s1 = client.models.generate_content(
        model="gemini-2.5-flash-lite",
        contents=f"Extract facts:\n\n{digest}",
        config=s1_config,
    )
    s1_raw = s1.text or ""
    s1_time = time.time() - t0
    (OUT / "C_twostep_step1.json").write_text(s1_raw, encoding="utf-8")
    print(f"  Step 1 (extract): {s1_time:.1f}s, {len(s1_raw)} chars")

    # Step 2: Render with schema
    t1 = time.time()
    s2_config = types.GenerateContentConfig(
        system_instruction=BASE_INSTRUCTION + HARD_RULES + WHY_ENFORCEMENT,
        response_modalities=["TEXT"], response_mime_type="application/json",
        response_schema=CEO_SCHEMA, temperature=0.2,
    )
    s2 = client.models.generate_content(
        model=MODEL,
        contents=f"Transform these facts into a CEO brief:\n\n{s1_raw}",
        config=s2_config,
    )
    s2_raw = s2.text or ""
    total = time.time() - t0
    (OUT / "C_twostep.json").write_text(s2_raw, encoding="utf-8")
    print(f"  Step 2 (render): {time.time()-t1:.1f}s")
    score_brief("C_twostep", s2_raw, total)
except Exception as e:
    print(f"  ERROR: {str(e)[:120]}")
    results.append({"name": "C_twostep", "status": "ERROR", "time_s": round(time.time()-t0, 1)})

# ── Test D: Structured + Why-It-Matters enforcement ──
call_llm("D_struct_why", BASE_INSTRUCTION + HARD_RULES + WHY_ENFORCEMENT, user_msg, schema=CEO_SCHEMA)

# ── Results ──
print(f"\n\n{'='*115}")
print("TIER 1 A/B TEST RESULTS")
print(f"{'='*115}")
print(f"{'Test':<18} {'Status':<9} {'Time':>6} {'Nums':>5} {'Words':>6} {'Trends':>8} {'Impl':>6} {'Rgn':>4} {'Why':>4} Bottom Line")
print("-" * 115)
for r in results:
    w = "Y" if r.get("has_why") else "N"
    print(f"{r['name']:<18} {r['status']:<9} {r['time_s']:>5.1f}s {r.get('nums',0):>5} {r.get('words',0):>6} "
          f"{r.get('trend_classified','?'):>8} {r.get('implications','?'):>6} {r.get('regions',0):>4} {w:>4} "
          f"{r.get('bottom','')[:55]}")

(OUT / "tier1_results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
print(f"\nSaved to {OUT}")
