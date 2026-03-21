# Plan: Ops Metrics Brief Refinement

**Goal:** Run analysis on the Ops Metrics Weekly dataset, cache insight cards for iterative brief refinement, and upgrade the executive brief to match the CEO-quality format (Version 1 style).

**Dataset:** `Ops Metrics DS.tdsx` (44MB, uploaded to VPS 2)
**Contract:** `config/datasets/tableau/ops_metrics_weekly/contract.yaml`

---

## Phase 1: Model Configuration Overhaul

### Problem
- `executive_brief_agent` is on `lite` tier (gemini-3-flash-preview, no thinking) — optimized for test speed, not brief quality
- `narrative_agent` on `advanced` (gemini-3-flash-preview, thinking budget 14k) — works but expensive
- `report_synthesis_agent` on `standard` (no thinking) — too weak for quality synthesis
- Several agents reference `gemini-3.1-pro-preview` and `gemini-3-flash-preview` which may not be available

### Changes to `config/agent_models.yaml`

**New tier: `brief`** — purpose-built for executive brief generation:
```yaml
brief:
  model: "gemini-2.5-flash"
  thinking_budget: 1024
  description: "Gemini 2.5 Flash with thinking — optimized for executive brief rendering"
```

**Agent reassignments:**

| Agent | Current Tier | New Tier | Rationale |
|-------|-------------|----------|-----------|
| `executive_brief_agent` | lite (no thinking) | **brief** (2.5-flash + thinking 1024) | Brief quality is critical; 2.5-flash is best price/performance for structured output |
| `narrative_agent` | advanced (3-flash, 14k thinking) | **flash_2_5_thinking** (2.5-flash, 8k thinking) | Reduce cost; 2.5-flash handles narrative well |
| `report_synthesis_agent` | standard (no thinking) | **flash_2_5** (2.5-flash, no thinking) | Synthesis is structured; no thinking needed but better model |
| `statistical_insights_agent` | standard | *unchanged* | Code-based when USE_CODE_INSIGHTS=true |
| `hierarchy_variance_agent` | standard | *unchanged* | Code-based when USE_CODE_INSIGHTS=true |

**Extraction/classification agents (unchanged):**
- `request_analyzer`, `dimension_extractor`, `output_persistence_agent` stay on `lite`

### Files to modify
- `config/agent_models.yaml` — add `brief` tier, reassign agents

---

## Phase 2: Insight Card Caching Layer

### Problem
Currently, insight cards are generated during the pipeline and passed through session state. To refine the brief, you must re-run the entire pipeline (~131s for 2 metrics). There's no way to re-generate just the brief from cached cards.

### Design

**New module:** `data_analyst_agent/cache/insight_cache.py`

```python
class InsightCache:
    """File-based cache for insight cards and analysis artifacts."""

    def __init__(self, output_dir: str):
        self.cache_dir = os.path.join(output_dir, ".cache")

    def save_stage(self, stage: str, metric: str, data: dict) -> str:
        """Save a pipeline stage result. Returns cache path."""
        # Stages: statistical_cards, hierarchy_cards, narrative_cards,
        #         alerts, synthesis, digest, brief

    def load_stage(self, stage: str, metric: str) -> dict | None:
        """Load cached stage result. Returns None if not cached."""

    def get_digest(self) -> dict | None:
        """Load the pre-computed brief digest (all metrics combined)."""

    def save_digest(self, digest: dict) -> str:
        """Save the brief digest for re-use."""

    def is_analysis_cached(self) -> bool:
        """True if all analysis stages are cached (brief can be regenerated)."""
```

**Cache structure:**
```
outputs/<dataset>/<timestamp>/
├── .cache/
│   ├── statistical_cards_<metric>.json
│   ├── hierarchy_cards_<metric>.json
│   ├── narrative_cards_<metric>.json
│   ├── alerts_<metric>.json
│   ├── synthesis_<metric>.json
│   └── digest.json              ← pre-computed brief input
├── metric_<name>.md
├── metric_<name>.json
├── brief.md
├── brief.json
└── brief.pdf
```

### Integration points

1. **OutputPersistenceAgent** — after saving metric JSON, also save individual stage caches
2. **CrossMetricExecutiveBriefAgent** — before building digest, check if cached digest exists
3. **New CLI flag:** `--from-cache <output_dir>` — skip analysis, load cached cards, regenerate brief only

### Files to modify
- `data_analyst_agent/cache/__init__.py` — new module
- `data_analyst_agent/cache/insight_cache.py` — cache implementation
- `data_analyst_agent/sub_agents/output_persistence_agent/agent.py` — save stage caches
- `data_analyst_agent/sub_agents/executive_brief_agent/agent.py` — load cached digest
- `data_analyst_agent/__main__.py` — add `--from-cache` flag

---

## Phase 3: Executive Brief Prompt & Format Overhaul

### Problem
Current brief format produces generic structured JSON with `header > body > sections`. The target format (Version 1) is a sharper CEO brief with specific sections: "Bottom line", "What moved the business", "Trend status", "Where it came from", "Why it matters", "Next-week outlook", "Leadership focus".

### New Brief Format Schema

Replace `EXECUTIVE_BRIEF_RESPONSE_SCHEMA` with:

```python
EXECUTIVE_BRIEF_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "week_ending": {"type": "string"},
        "bottom_line": {"type": "string"},  # 2-3 sentences, thesis of the week
        "what_moved_the_business": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "metric": {"type": "string"},
                    "value": {"type": "string"},
                    "change": {"type": "string"},
                    "context": {"type": "string"}  # vs target, vs average, etc.
                }
            }
        },
        "trend_status": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "trend": {"type": "string"},
                    "status": {"type": "string"},  # positive momentum | developing trend | persistent issue | watchable
                    "detail": {"type": "string"}
                }
            }
        },
        "where_it_came_from": {
            "type": "object",
            "properties": {
                "positive": {"type": "array", "items": {"type": "string"}},
                "drag": {"type": "array", "items": {"type": "string"}},
                "watch_items": {"type": "array", "items": {"type": "string"}}
            }
        },
        "why_it_matters": {"type": "string"},  # 1-2 sentences, earnings quality
        "next_week_outlook": {"type": "string"},  # conditional forward view
        "leadership_focus": {
            "type": "array",
            "items": {"type": "string"}  # 3-5 action items
        }
    }
}
```

### New Brief Instruction Prompt

The instruction must produce Version 1 style output. Key prompt elements:

1. **Tone:** Direct, declarative, no hedging. CEO reading on mobile.
2. **Bottom line:** Lead with the thesis — was the week good or bad, and why the headline doesn't tell the full story.
3. **Metrics:** Use computed KPIs (LRPM, TRPM, Rev/truck/day, Miles/truck/week, Deadhead %, OTD %) not raw additive totals.
4. **Trend status:** Classify each trend as: positive momentum | developing trend | persistent issue | watchable. Include duration ("up 3 straight weeks").
5. **Where it came from:** Always name Region + Terminal. Split into Positive / Drag / Watch item.
6. **Why it matters:** Connect execution quality to earnings quality. Not just "revenue up" but "revenue up but lower quality because..."
7. **Leadership focus:** 3-5 imperative sentences. Verbs first: "Hold", "Intervene", "Rebalance", "Correct", "Audit".

### Derived KPI Computation

The contract has raw additive metrics. The brief needs computed KPIs. Add a pre-brief KPI computation step:

```python
def compute_derived_kpis(metric_data: dict) -> dict:
    """Compute CEO-facing KPIs from raw additive metrics."""
    return {
        "lrpm": lh_rev_amt / ld_trf_mi,           # Line-haul Revenue Per Mile
        "trpm": ttl_rev_amt / ttl_trf_mi,          # Total Revenue Per Mile
        "rev_per_truck_day": ttl_rev_amt / (truck_count * days),
        "miles_per_truck_week": ttl_trf_mi / (truck_count * weeks),
        "deadhead_pct": dh_miles / ttl_trf_mi * 100,
        "loaded_pct": ld_trf_mi / ttl_trf_mi * 100,
        "fuel_efficiency": ttl_trf_mi / ttl_fuel_qty,
        "idle_pct": idle_engn_tm / ttl_engn_tm * 100,
        "orders_per_truck": ordr_cnt / truck_count,
        "rev_per_order": ttl_rev_amt / ordr_cnt,
        "rev_per_mile": ttl_rev_amt / ordr_miles,
    }
```

### Files to modify
- `data_analyst_agent/sub_agents/executive_brief_agent/agent.py` — new schema, new prompt, KPI computation
- `data_analyst_agent/sub_agents/executive_brief_agent/kpi_calculator.py` — new file for derived KPIs
- `data_analyst_agent/sub_agents/executive_brief_agent/brief_format.py` — new file for markdown rendering of the new schema

---

## Phase 4: Model Settings for Brief Generation

### Executive Brief Agent Config

```python
GenerateContentConfig(
    response_mime_type="application/json",
    response_schema=EXECUTIVE_BRIEF_RESPONSE_SCHEMA,
    temperature=0.3,       # Slightly creative for narrative quality
    top_p=0.95,            # Default, don't change
    candidate_count=1,
    # thinking_budget=1024 (set via agent_models.yaml tier)
)
```

### Narrative Agent Config (for insight card generation)

```python
GenerateContentConfig(
    response_mime_type="application/json",
    temperature=0.15,      # Low — factual extraction
    top_p=0.95,
    candidate_count=1,
    # thinking_budget=8192 (set via tier)
)
```

### Report Synthesis Config

```python
GenerateContentConfig(
    temperature=0.1,       # Very low — structured assembly
    top_p=0.95,
    candidate_count=1,
)
```

### Model Selection Rationale
- **gemini-2.5-flash** for brief: Best price/performance, supports structured output + thinking, GA (not preview)
- **gemini-2.5-flash** for narrative: Same model, higher thinking budget for causal reasoning
- **gemini-2.5-flash** for synthesis: No thinking needed, fast structured assembly
- **Avoid gemini-3-flash-preview**: Preview model, higher cost, may be discontinued
- **Avoid gemini-3.1-pro-preview**: Overkill for this task, preview status

---

## Phase 5: Ops Metrics Dataset Setup

### Steps

1. **Update contract `data_source.file`** to point to the uploaded TDSX:
   ```yaml
   data_source:
     type: "tableau_hyper"
     file: "/data/data-analyst-agent/Ops Metrics DS.tdsx"
     table: "Extract.Extract"
   ```

2. **Add derived KPI definitions to contract** (new section):
   ```yaml
   derived_metrics:
     - name: "lrpm"
       display_name: "Line-Haul Revenue Per Mile"
       formula: "lh_rev_amt / ld_trf_mi"
       format: "currency"
       optimization: "maximize"
     - name: "deadhead_pct"
       display_name: "Deadhead %"
       formula: "dh_miles / ttl_trf_mi * 100"
       format: "percentage"
       optimization: "minimize"
       target: 13.5
     # ... etc
   ```

3. **Create `.env` on VPS 2:**
   ```bash
   GOOGLE_API_KEY=<key>
   ACTIVE_DATASET=tableau/ops_metrics_weekly
   USE_CODE_INSIGHTS=true
   EXECUTIVE_BRIEF_OUTPUT_FORMAT=pdf
   DATA_ANALYST_METRICS=ttl_rev_amt,lh_rev_amt,dh_miles,ordr_cnt
   ```

4. **Install dependencies:**
   ```bash
   cd /data/data-analyst-agent
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

5. **Run initial analysis:**
   ```bash
   python -m data_analyst_agent --dataset tableau/ops_metrics_weekly \
     --metrics "ttl_rev_amt,lh_rev_amt,dh_miles,ordr_cnt"
   ```

6. **Inspect cached cards, refine brief:**
   ```bash
   python -m data_analyst_agent --from-cache outputs/ops_metrics_weekly/<timestamp>/ \
     --brief-only
   ```

---

## Implementation Order

| Step | Phase | Description | Agent |
|------|-------|-------------|-------|
| 1 | Phase 1 | Update `agent_models.yaml` with new tiers and assignments | coder |
| 2 | Phase 4 | Update model settings (temperature, thinking) in brief/narrative agents | coder |
| 3 | Phase 2 | Build insight cache module | coder |
| 4 | Phase 2 | Integrate cache into output persistence and brief agents | coder |
| 5 | Phase 3 | New brief schema + prompt + KPI calculator | coder |
| 6 | Phase 3 | New markdown/PDF renderer for CEO brief format | coder |
| 7 | Phase 5 | Dataset setup on VPS 2 (contract, .env, dependencies) | coder |
| 8 | Phase 5 | Dataset setup on VPS 2 (contract, .env, dependencies) | coder |
| 9 | Phase 5 | Run initial analysis, inspect results | orchestrator |
| 10 | Phase 5 | Iterate brief from cache with refined prompts | orchestrator |
| 11 | Phase 6 | Model A/B testing — run brief generation across model matrix | orchestrator |

**Estimated diff:** ~8 files modified, 4 new files, ~700 lines of code

---

## Phase 6: Model A/B Testing

### Goal
Systematically test different models and settings against the same cached insight cards to find the best combination for each pipeline stage, especially the executive brief.

### Test Matrix — Executive Brief Agent

| Model | Temperature | Thinking | Notes |
|-------|------------|----------|-------|
| gemini-2.5-flash | 0.2 | off | Baseline: cheap, fast, deterministic |
| gemini-2.5-flash | 0.3 | budget 512 | Light thinking for cross-metric synthesis |
| gemini-2.5-flash | 0.3 | budget 1024 | Recommended starting point |
| gemini-2.5-flash | 0.4 | budget 2048 | More creative narrative, deeper reasoning |
| gemini-2.5-flash-lite | 0.2 | off | Cheapest option — test if quality holds |
| gemini-3-flash-preview | 0.3 | medium | Preview model comparison |
| gemini-3-flash-preview | 0.3 | high (14k) | Max quality preview comparison |

### Test Matrix — Narrative Agent

| Model | Temperature | Thinking | Notes |
|-------|------------|----------|-------|
| gemini-2.5-flash | 0.1 | budget 4096 | Tight extraction, moderate reasoning |
| gemini-2.5-flash | 0.15 | budget 8192 | Recommended starting point |
| gemini-2.5-flash | 0.2 | budget 8192 | Slightly more interpretive |
| gemini-2.5-flash-lite | 0.1 | off | Cost floor — test quality threshold |

### Test Matrix — Report Synthesis Agent

| Model | Temperature | Thinking | Notes |
|-------|------------|----------|-------|
| gemini-2.5-flash | 0.1 | off | Structured assembly, no creativity needed |
| gemini-2.5-flash-lite | 0.1 | off | Cheaper, test if quality holds |
| gemini-2.5-flash | 0.15 | budget 512 | Light thinking for better integration |

### Evaluation Criteria

Score each output 1-5 on:
1. **Bottom line clarity** — Does it tell the CEO what happened in 2 sentences?
2. **Metric precision** — Uses computed KPIs with exact values and % changes?
3. **Earnings quality insight** — Does it distinguish headline vs underlying performance?
4. **Regional attribution** — Names specific regions/terminals with positive/drag/watch?
5. **Trend classification** — Correct momentum/developing/persistent/watchable labels?
6. **Leadership actions** — Imperative, specific, actionable (not generic advice)?
7. **Brevity** — Could a CEO read this in 90 seconds on mobile?

### Implementation

**New script:** `scripts/model_benchmark.py`

```python
"""
Run the executive brief against multiple model/settings combos
using cached insight cards. Outputs comparison report.

Usage:
  python scripts/model_benchmark.py \
    --cache-dir outputs/ops_metrics_weekly/<timestamp>/ \
    --matrix brief        # or: narrative, synthesis, all
    --output-dir benchmarks/<run_id>/
"""
```

**Workflow:**
1. Run analysis once (Phase 5 step 9) — cards get cached
2. Run `model_benchmark.py --matrix brief` — generates one brief per model/settings combo
3. All briefs saved to `benchmarks/<run_id>/brief_<model>_<temp>_<thinking>.md`
4. Side-by-side comparison for manual scoring
5. Winner gets locked into `agent_models.yaml`

**Config override mechanism** (already exists):
```python
from config.model_loader import set_config_override
set_config_override("benchmarks/config_variant_a.yaml")
# ... run brief ...
clear_config_override()
```

Each benchmark variant is a modified `agent_models.yaml` with different tier settings. The script generates these automatically from the test matrix.

### Files to create
- `scripts/model_benchmark.py` — benchmark runner
- `scripts/benchmark_configs/` — auto-generated variant YAML files

---

## Risks

1. **TDSX extraction** — `tableauhyperapi` must be installed on VPS 2 (Linux x64). May need system deps.
2. **Google API quota** — If using Vertex AI, need project + credentials on VPS 2. If API key, need GOOGLE_API_KEY.
3. **Derived KPIs** — Division by zero if truck_count or miles are 0 for a period. Need guards.
4. **Structured output schema** — gemini-2.5-flash structured output has field count limits. May need to simplify schema.
5. **Brief validation** — Existing 3-layer section title enforcement assumes old format. Must update validators.

---

## Success Criteria

- [ ] Analysis runs end-to-end on Ops Metrics dataset
- [ ] Insight cards cached to `.cache/` directory after first run
- [ ] Brief can be regenerated from cache in <15s (no re-analysis)
- [ ] Brief output matches Version 1 structure: bottom_line, what_moved, trends, where_from, why_matters, outlook, leadership_focus
- [ ] Brief uses computed KPIs (LRPM, Deadhead %, Rev/truck/day) not raw totals
- [ ] All 344+ existing tests still pass
- [ ] Model benchmark produces side-by-side brief comparisons for at least 5 model/settings combos
- [ ] Best model/settings combo identified and locked into `agent_models.yaml`
