# Pipeline Optimization Plan

**Created:** 2026-03-23  
**Status:** Implemented (benchmark validation pending)  
**Baseline:** 9 metrics (ops_metrics_ds, Line Haul) = ~3.5-4 min wall-clock  
**Goal:** Sub-60s for 9 metrics; sub-30s stretch target

---

## Current Architecture (Bottleneck Analysis)

### Per-Metric Pipeline (Sequential)

```
AnalysisContextInit (0.05-0.25s)
  -> RuleBasedPlanner (~0s)
    -> DynamicParallel[stats + hierarchy] (0.3-6s)
      -> NarrativeAgent [LLM] (20-27s)           <-- BOTTLENECK
        -> AlertScoringPipeline (0.01-0.2s)
          -> ReportSynthesisAgent [LLM] (18-24s)  <-- BOTTLENECK
            -> OutputPersistenceAgent (0.02-0.15s)
```

### Cross-Metric Parallelism

Controlled by `MAX_PARALLEL_METRICS` (default `4`, currently overridden to `2` in env).
Implemented via `asyncio.Semaphore` in `ParallelDimensionTargetAgent`.

### Where Time Goes (9 Metrics, cap=2)

| Category                  | Per-Metric | Total (overlapped) | % of Wall |
|---------------------------|-----------|-------------------|-----------|
| Narrative LLM             | 20-27s    | ~100s             | ~45%      |
| Report Synthesis LLM      | 18-24s    | ~95s              | ~42%      |
| Stats + Hierarchy compute | 0.3-6s    | ~15s              | ~7%       |
| Data fetch (Hyper SQL)    | -         | 5.8s (once)       | ~3%       |
| Alert scoring (code)      | 0.01-0.2s | ~1s               | <1%       |
| File I/O (persistence)    | 0.02-0.15s| ~1s               | <1%       |

**~87% of wall-clock time is LLM latency.** Computation finishes in seconds.

### Key Observations

1. **Serial LLM chain per metric:** Narrative (LLM) -> Alerts (code) -> Report Synthesis (LLM) = ~45s of serial wait per metric.
2. **Low parallelism cap:** `MAX_PARALLEL_METRICS=2` creates 5 serial waves for 9 metrics.
3. **Report synthesis "Direct-render recovery":** LLM call burns ~20s then falls back to deterministic renderer. Wasted time.
4. **No materiality gate:** Narrative LLM runs even for metrics with all low-materiality findings (e.g. truck_count_avg: all cards tagged `low_materiality`, variance -0.095%).
5. **Alert scoring is independent of narrative:** It only reads `statistical_summary` and `dataset_contract`, but is sequenced after narrative.

---

## Phase 1: Split Compute from LLM (Batch Architecture)

**Goal:** Run ALL statistical/hierarchical analysis across ALL metrics in parallel first, THEN batch LLM calls.  
**Estimated impact:** 60-70% reduction in wall-clock time.  
**Effort:** Large (architectural change to `ParallelDimensionTargetAgent`)

### 1.1 Design the Two-Phase Pipeline

**Current flow (per-metric sequential, capped parallel across metrics):**

```
  Metric 1: [context -> plan -> compute -> NARRATIVE_LLM -> alerts -> REPORT_LLM -> persist]
  Metric 2: [context -> plan -> compute -> NARRATIVE_LLM -> alerts -> REPORT_LLM -> persist]
  ...
  (max 2 concurrent)
```

**Proposed flow (compute-first, then LLM batch):**

```
  Phase A - COMPUTE (all metrics, high concurrency):
    All Metrics in Parallel:
      context_init -> planner -> stats+hierarchy (parallel) -> alert_scoring

  Phase B - LLM GENERATION (all metrics, batched):
    All Metrics in Parallel (capped by API rate limits):
      narrative_agent -> report_synthesis_agent -> output_persistence
```

### 1.2 Validate State Dependencies

Before reordering, confirm the dependency graph supports the split:

| Agent                   | Reads                                              | Writes                          | Phase |
|-------------------------|----------------------------------------------------|---------------------------------|-------|
| AnalysisContextInit     | dataset_contract, CSV data, target                 | analysis_context, temporal_*    | A     |
| RuleBasedPlanner        | contract, focus                                    | execution_plan                  | A     |
| Stats + Hierarchy       | analysis_context, execution_plan                   | statistical_summary, data_analyst_result, level_*_analysis | A |
| AlertScoringPipeline    | statistical_summary, target, contract              | alert_scoring_result            | A     |
| NarrativeAgent (LLM)    | data_analyst_result, statistical_summary, level_*  | narrative_results               | B     |
| ReportSynthesisAgent    | narrative_results, stats, hierarchy, alerts         | report_markdown                 | B     |
| OutputPersistence        | narrative, synthesis, alerts, hierarchy             | files                           | B     |

**Confirmed:** Alert scoring depends only on `statistical_summary` (not on narrative).
Narrative depends on compute outputs. Report synthesis depends on narrative + compute + alerts.
The split is clean.

### 1.3 Implementation: Refactor `ParallelDimensionTargetAgent`

**File:** `data_analyst_agent/core_agents/targets.py`

**Current `_make_pipeline()` (lines 227-243):**

```python
pipeline = SequentialAgent(
    name="target_analysis_pipeline",
    sub_agents=[
        TimedAgentWrapper(AnalysisContextInitializer()),
        TimedAgentWrapper(RuleBasedPlanner()),
        TimedAgentWrapper(DynamicParallelAnalysisAgent()),
        TimedAgentWrapper(create_narrative_agent()),
        TimedAgentWrapper(alert_scoring_agent),
        TimedAgentWrapper(create_report_synthesis_agent()),
        TimedAgentWrapper(OutputPersistenceAgent(level="dimension_value")),
    ],
)
```

**Proposed: Split into two pipeline factories:**

```python
def _make_compute_pipeline() -> BaseAgent:
    """Phase A: All statistical/hierarchical computation + alerts. No LLM."""
    return SequentialAgent(
        name="compute_pipeline",
        sub_agents=[
            TimedAgentWrapper(AnalysisContextInitializer()),
            TimedAgentWrapper(RuleBasedPlanner()),
            TimedAgentWrapper(DynamicParallelAnalysisAgent()),
            TimedAgentWrapper(alert_scoring_agent),
        ],
    )

def _make_llm_pipeline() -> BaseAgent:
    """Phase B: LLM generation + persistence. Runs after all compute completes."""
    return SequentialAgent(
        name="llm_pipeline",
        sub_agents=[
            TimedAgentWrapper(create_narrative_agent()),
            TimedAgentWrapper(create_report_synthesis_agent()),
            TimedAgentWrapper(OutputPersistenceAgent(level="dimension_value")),
        ],
    )
```

**Proposed: Two-phase orchestration in `_run_async_impl`:**

```python
async def _run_async_impl(self, ctx):
    targets = ctx.session.state.get("extracted_targets", [])
    compute_cap = len(targets)  # all metrics at once (compute is cheap)
    llm_cap = _read_parallel_cap()  # respect API rate limits for LLM phase

    # Phase A: Run all compute pipelines in parallel
    compute_runners = [
        SingleTargetRunner(t, _make_compute_pipeline()) for t in targets
    ]
    await _run_parallel(compute_runners, ctx, semaphore_cap=compute_cap)

    # Merge compute results back into shared state for Phase B
    # (each runner's isolated session state needs to be accessible)

    # Phase B: Run all LLM pipelines in parallel (rate-limited)
    llm_runners = [
        SingleTargetRunner(t, _make_llm_pipeline()) for t in targets
    ]
    await _run_parallel(llm_runners, ctx, semaphore_cap=llm_cap)
```

### 1.4 Session State Handoff Between Phases

**Challenge:** `SingleTargetRunner` currently creates an isolated session copy. Phase B needs the state that Phase A produced.

**Options:**

1. **Shared state store (recommended):** Use a dict keyed by target name to store Phase A results. Phase B runners read from this dict to seed their session.
2. **Contextvars + data_cache:** Already have `current_session_id` for cache isolation. Phase B can reuse the same session ID to retrieve cached `AnalysisContext`.
3. **Session persistence:** Write Phase A state to disk (JSON), Phase B reads it back. Heavier but debuggable.

**Recommended approach (option 1):**

```python
# After Phase A completes, collect each runner's final state
compute_results: dict[str, dict] = {}
for runner in compute_runners:
    compute_results[runner.target_val] = runner.final_state

# Phase B runners initialize from compute_results
class LLMTargetRunner(SingleTargetRunner):
    def _run_async_impl(self, inner_ctx):
        # Seed session with Phase A results
        phase_a_state = compute_results[self.target_val]
        inner_ctx.session.state.update(phase_a_state)
        async for event in self.inner_pipeline.run_async(inner_ctx):
            yield event
```

### 1.5 Increase Default Compute Concurrency

**File:** `data_analyst_agent/core_agents/targets.py` (`_read_parallel_cap`)

Add a separate env var for compute parallelism:

- `MAX_PARALLEL_COMPUTE` (default: `0` = unlimited, since compute is CPU/pandas-bound, not API-bound)
- `MAX_PARALLEL_LLM` (default: `4`, respects Gemini API rate limits)

Keep `MAX_PARALLEL_METRICS` as a legacy alias for `MAX_PARALLEL_LLM`.

### 1.6 Projected Timing (Phase 1 Complete)

| Stage                     | Current (cap=2) | Optimized          |
|---------------------------|-----------------|---------------------|
| Phase A: All compute      | Interleaved     | ~6s (all 9 parallel)|
| Phase B: Narrative (LLM)  | ~100s overlapped| ~50s (cap=4)        |
| Phase B: Report Synth     | ~95s overlapped | ~45s (cap=4)        |
| **Total (9 metrics)**     | **~225s**       | **~100s**           |

### 1.7 Sprint Tasks

- [x] Create `_make_compute_pipeline()` and `_make_llm_pipeline()` factories in `targets.py`
- [x] Implement two-phase orchestration in `ParallelDimensionTargetAgent._run_async_impl`
- [x] Design state handoff mechanism (shared dict keyed by target)
- [x] Capture `runner.final_state` after Phase A completes
- [x] Seed Phase B runners from Phase A state
- [x] Preserve `current_session_id` / `data_cache` isolation across phases
- [x] Add `MAX_PARALLEL_COMPUTE` env var (default unlimited)
- [x] Rename/alias `MAX_PARALLEL_METRICS` -> `MAX_PARALLEL_LLM` (default 4)
- [x] Update `.env.example` with new env vars
- [x] Update `target_analysis_pipeline` in `agent.py` to match (keep test pipeline aligned)
- [x] Add integration test: verify Phase A results are available to Phase B
- [ ] Run full 9-metric benchmark, compare with baseline

### 1.8 Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| State key collisions between phases | Use per-target isolated sessions (already exists via `SingleTargetRunner`) |
| `data_analyst_result` overwrite race in parallel stats+hierarchy | Already handled: hierarchy `finalize` is authoritative. No change needed within Phase A since each metric is still isolated. |
| Gemini API rate limits on Phase B | `MAX_PARALLEL_LLM` semaphore; default 4 is safe for 30 RPM limit |
| Phase B runner can't find `AnalysisContext` in cache | Ensure `current_session_id` is set to same value as Phase A before running Phase B |

---

## Phase 2: Quick Wins (Parallel with Phase 1)

**Goal:** Reduce LLM call count and waste with config/env changes. No architectural changes.  
**Estimated impact:** 20-40% reduction in LLM time.  
**Effort:** Small (env vars and minor code changes)

### 2.1 Set `REPORT_SYNTHESIS_EXECUTION_MODE=direct`

**Why:** Report synthesis LLM calls are frequently failing and falling back to `Direct-render recovery`, wasting ~20s per occurrence. The deterministic renderer (`generate_markdown_report`) produces the same output.

**Action:** Set in `.env`:
```
REPORT_SYNTHESIS_EXECUTION_MODE=direct
```

**Files affected:** None (env var only).  
**Risk:** Low. The tool-based renderer already handles all current payloads. Monitor for quality regression on complex hierarchical reports.

**Savings:** ~18-24s per metric where LLM was being called (most metrics).

### 2.2 Increase `MAX_PARALLEL_METRICS` to 4

**Why:** Current value of `2` creates 5 serial waves. Default is `4` (3 waves). Can even go higher.

**Action:** Set in `.env`:
```
MAX_PARALLEL_METRICS=4
```

**Savings:** ~40% reduction from parallelism alone (before Phase 1 lands).

### 2.3 Add Materiality Gate Before Narrative Agent

**Why:** Metrics like `truck_count_avg` (-0.095%), `lrpm` (-0.36%), `trpm` (-0.44%), `avg_loh` (-0.34%) have no material findings but still trigger a 20-27s LLM call.

**Design:** New `ConditionalNarrativeAgent` wrapper:

```python
class ConditionalNarrativeAgent(BaseAgent):
    """Skip narrative LLM when no material findings exist."""

    async def _run_async_impl(self, ctx):
        if _has_material_findings(ctx.session.state):
            async for event in create_narrative_agent().run_async(ctx):
                yield event
        else:
            yield Event(
                actions=EventActions(state_delta={
                    "narrative_results": json.dumps({
                        "insight_cards": [],
                        "narrative_summary": _build_template_summary(ctx.session.state),
                        "recommended_actions": [],
                    })
                })
            )
```

**Materiality check logic:**

```python
def _has_material_findings(state: dict) -> bool:
    contract = state.get("dataset_contract", {})
    mat = contract.get("materiality", {})
    threshold_pct = mat.get("variance_pct", 5)
    threshold_abs = mat.get("variance_absolute", 10000)

    # Check hierarchy cards for any material variance
    for lvl in range(4):
        level_data = state.get(f"level_{lvl}_analysis")
        if not level_data:
            continue
        cards = _extract_cards(level_data)
        for card in cards:
            evidence = card.get("evidence", {})
            if (abs(evidence.get("delta_pct", 0)) >= threshold_pct
                or abs(evidence.get("delta_abs", 0)) >= threshold_abs):
                return True

    # Check statistical anomalies
    stats = state.get("statistical_summary")
    if stats:
        anomalies = _parse_anomalies(stats)
        if any(a.get("severity", "") in ("high", "critical") for a in anomalies):
            return True

    return False
```

**Files:** `data_analyst_agent/core_agents/targets.py` (replace `create_narrative_agent()` in pipeline).  
**New file:** `data_analyst_agent/core_agents/narrative_gate.py`.

**Savings:** ~22s per low-materiality metric. For 9-metric run, typically 4-5 are immaterial = ~90-110s saved.

### 2.4 Sprint Tasks

- [x] Set `REPORT_SYNTHESIS_EXECUTION_MODE=direct` in `.env` and `.env.example`
- [x] Set `MAX_PARALLEL_METRICS=4` in `.env` and document in `.env.example`
- [x] Implement `ConditionalNarrativeAgent` with materiality gate
- [x] Add `SKIP_NARRATIVE_BELOW_MATERIALITY` env var (default `true`, allows opt-out)
- [x] Implement `_build_template_summary()` for the skip path (deterministic one-liner from level stats)
- [x] Unit test: materiality gate correctly identifies material vs immaterial metrics
- [x] Unit test: template summary produces valid `narrative_results` JSON
- [ ] Benchmark: 9-metric run with Phase 2 changes alone

---

## Phase 3: LLM Generation Optimization

**Goal:** Reduce LLM call latency, improve output quality, optimize what gets sent.  
**Estimated impact:** 30-50% reduction in per-call LLM time.  
**Effort:** Medium (model benchmarking, prompt engineering, code changes)

### 3.1 Audit Insight Cards Sent to LLM

**Current flow:** Statistical + hierarchy insight cards flow to narrative as JSON payload.

**Investigation tasks:**

- [ ] Instrument `NarrativeWrapper` to log card counts and total payload size per metric
- [ ] Capture a full run of card payloads across all 9 metrics (save to `outputs/debug/narrative_cards_audit/`)
- [ ] Classify cards: how many are `low_materiality`? How many duplicated across hierarchy levels?
- [ ] Measure: does reducing `NARRATIVE_MAX_HIERARCHY_CARDS` from 2 to 1 change output quality?
- [ ] Measure: does reducing `NARRATIVE_MAX_TOP_DRIVERS` from 3 to 2 change output quality?

**Expected findings:** Many cards are low-priority padding. Reducing card count reduces prompt tokens and latency.

### 3.2 Model Benchmarking

**Current models:**
| Agent | Model | Tier | Avg Latency |
|-------|-------|------|-------------|
| narrative_agent | gemini-2.5-flash | flash_2_5_thinking | 20-27s |
| report_synthesis_agent | gemini-2.5-flash | flash_2_5 | 18-24s |

**Models to benchmark:**
| Candidate | Expected Tradeoff |
|-----------|-------------------|
| gemini-3-flash-preview (standard tier) | Faster inference, similar quality |
| gemini-3-flash-preview + thinking=medium (fast tier) | Better reasoning, comparable speed |
| gemini-3.1-flash-lite-preview (brief tier) | Much faster, possibly lower quality for complex narratives |
| gemini-2.5-flash-lite | Ultra-fast, lower quality |

**Benchmark methodology:**

1. Fix a set of 5 representative metrics (2 high-materiality, 2 medium, 1 low)
2. For each model candidate, run narrative agent 3 times per metric
3. Measure: latency (p50, p95), output token count, JSON parse success rate
4. Quality assessment: compare insight card coverage, narrative coherence, factual accuracy vs statistical data

**Benchmark harness:**

```python
# tests/performance/test_narrative_model_comparison.py
@pytest.mark.parametrize("model_tier", ["flash_2_5", "standard", "fast", "brief", "ultra"])
@pytest.mark.parametrize("metric_fixture", [...])
async def test_narrative_model_latency(model_tier, metric_fixture):
    """Compare narrative agent performance across model tiers."""
    ...
```

### 3.3 Prompt Size Reduction

**Current payload sizes (from logs):**

| Component | Typical Size | Cap Env Var |
|-----------|-------------|-------------|
| instruction | 1,760 chars | (hardcoded) |
| data_analyst_result | up to 3,200 chars | `NARRATIVE_MAX_ANALYST_CHARS` |
| statistical_summary | up to 2,100 chars | `NARRATIVE_MAX_STATS_CHARS` |
| hierarchical (per-level) | up to 2,000 chars | `NARRATIVE_MAX_HIER_CHARS` |
| independent findings | up to 1,200 chars | `NARRATIVE_MAX_INDEPENDENT_CHARS` |
| **Total payload** | **6,500-8,500 chars** | - |

**Reduction strategies:**

- [ ] Audit instruction template: remove redundant constraints, merge overlapping rules
- [ ] For low-materiality metrics, send minimal payload (just top-level totals, no per-entity breakdown)
- [ ] Strip `evidence` sub-objects from cards before sending to narrative (narrative rebuilds from text anyway)
- [ ] Reduce `NARRATIVE_MAX_ANALYST_CHARS` from 3200 to 2000 (test quality impact)
- [ ] Reduce `NARRATIVE_MAX_STATS_CHARS` from 2100 to 1500 (test quality impact)

### 3.4 Report Synthesis: Eliminate LLM Path Entirely

**Observation:** The `generate_markdown_report` deterministic tool already handles all current output patterns. The LLM path adds ~20s and frequently fails (Direct-render recovery).

**Proposal:** Make `REPORT_SYNTHESIS_EXECUTION_MODE=direct` the permanent default.

**Justification:**
- LLM path success rate appears low (multiple Direct-render recovery events per run)
- When LLM succeeds, it calls the same `generate_markdown_report` tool
- The tool produces structured, consistent output
- The narrative agent already provides the "human touch" via insight cards and summary

**Migration path:**
1. Phase 2: Set `direct` via env var (already planned)
2. Phase 3: If quality holds, make `direct` the code default
3. Remove LLM path code (or gate behind `REPORT_SYNTHESIS_EXECUTION_MODE=llm` for edge cases)

### 3.5 Explore Narrative-Free Architecture

**Question:** Can we skip the narrative LLM entirely and go straight to report synthesis with structured data?

**Current narrative output consumed by report synthesis:**
- `insight_cards` -> used in `build_insight_cards_section` (merged with hierarchy cards)
- `narrative_summary` -> used in executive summary section
- `recommended_actions` -> used in recommended actions section

**Feasibility assessment:**
- `insight_cards`: The hierarchy + statistical card generators already produce cards. The narrative agent's primary value is **refining/deduplicating** these cards and writing the `what_changed`/`why` text. If code-generated cards are already good enough, narrative adds only polish.
- `narrative_summary`: Could be generated by a template from top-level stats (similar to what the fallback already does).
- `recommended_actions`: Already templated in the fallback path.

**Decision:** Defer to after Phase 3 model benchmarking. If a fast model (gemini-3.1-flash-lite) can produce narrative in <5s, the ROI of eliminating it is low. If all models remain >15s, a code-based narrative becomes attractive.

### 3.6 Sprint Tasks

- [x] Build card audit instrumentation (log counts, sizes, materiality breakdown)
- [ ] Run card audit on 3 representative datasets, document findings
- [x] Set up model benchmark harness (`tests/performance/`)
- [x] Benchmark narrative agent across 5 model tiers (latency smoke run completed; broader 3x5 matrix still optional)
- [ ] Benchmark report synthesis across 3 model tiers (if keeping LLM path)
- [x] Document benchmark results in `docs/MODEL_BENCHMARK_RESULTS.md`
- [x] Apply best model to `config/agent_models.yaml`
- [ ] Test prompt size reductions (reduce caps, measure quality delta)
- [x] Make `REPORT_SYNTHESIS_EXECUTION_MODE=direct` the code default
- [ ] Evaluate narrative-free architecture feasibility based on benchmark data

---

## Phase 4: Advanced Optimizations

**Goal:** Further architectural improvements after Phases 1-3 are stable.  
**Effort:** Large

### 4.1 Parallel Narrative + Alert Scoring (Within a Metric)

**Current:** narrative -> alerts -> report_synthesis (all serial).  
**Opportunity:** Alerts depend on `statistical_summary`, NOT on `narrative_results`. They can run in parallel with narrative.

**But:** If Phase 1 moves alerts to the compute phase, this becomes moot. Only relevant if keeping the current single-phase architecture.

### 4.2 Streaming/Incremental Report Synthesis

Instead of waiting for all LLM output, stream markdown sections as they become available:
- Header + metadata (immediate, from state)
- Insight cards section (from hierarchy + stats cards, no LLM needed)
- Executive summary (needs narrative or template)
- Hierarchy drilldown section (from level_*_analysis, no LLM)
- Anomaly section (from statistical_summary)
- Recommended actions (template)

Only the executive summary truly benefits from LLM; the rest is deterministic.

### 4.3 Cross-Metric Deduplication Before LLM

Many metrics share the same hierarchy drill-down pattern (e.g. "East region drove the decline" appears for ttl_rev_xf_sr_amt, total_miles_rpt, rev_trk_day). Deduplicate correlated insights before sending to narrative to reduce redundant LLM work.

### 4.4 Executive Brief Optimization

The executive brief (65.9s in prior profiling) runs after all per-metric analysis. Opportunities:
- Start brief generation as soon as first N metrics complete (streaming)
- Use `SKIP_EXECUTIVE_BRIEF_LLM=true` for deterministic fallback
- Reduce `EXECUTIVE_BRIEF_MAX_SCOPED_BRIEFS` from 3 to 1
- Use `gemini-3.1-flash-lite-preview` (already configured as `brief` tier)

### 4.5 Gemini API Optimization

- **Batch API:** If Gemini supports batch inference, send all narrative prompts in a single batch request
- **Prompt caching:** `REPORT_SYNTHESIS_USE_PROMPT_CACHE` exists but may not be active. Evaluate caching the instruction portion across metrics (same system prompt).
- **Rate limit tuning:** Current `GOOGLE_GENAI_RPM_LIMIT=30`. With 9 metrics x 2 LLM calls = 18 calls. At cap=4, that's 4-5 waves, well within 30 RPM. Can increase cap safely.

---

## Sprint Schedule

### Sprint 1 (Week 1): Quick Wins + Design
**Velocity: High impact, low effort**

| Task | Effort | Impact |
|------|--------|--------|
| Set `REPORT_SYNTHESIS_EXECUTION_MODE=direct` | 5 min | -20s/metric |
| Set `MAX_PARALLEL_METRICS=4` | 5 min | -40% wall-clock |
| Design two-phase pipeline split (Phase 1.1-1.2) | 2 days | Foundation |
| Validate state dependency graph | 1 day | De-risk Phase 1 |

**Expected result:** Baseline drops from ~225s to ~120-140s with env changes alone.

**Execution status (2026-03-23):**
- [x] Set `REPORT_SYNTHESIS_EXECUTION_MODE=direct` in defaults (`.env.example`) and code fallback (`_report_synthesis_execution_mode`)
- [x] Set `MAX_PARALLEL_METRICS=4` in `.env.example`
- [x] Complete two-phase pipeline design in this doc (Phase 1.1)
- [x] Validate state dependency graph in this doc (Phase 1.2)
- [ ] Run baseline vs Sprint 1 benchmark in this workspace

### Sprint 2 (Week 2): Compute/LLM Split
**Velocity: Core architectural change**

| Task | Effort | Impact |
|------|--------|--------|
| Implement `_make_compute_pipeline()` and `_make_llm_pipeline()` | 2 days | Core |
| State handoff mechanism (Phase 1.4) | 1 day | Core |
| Two-phase orchestration in `ParallelDimensionTargetAgent` | 2 days | Core |
| Integration tests | 1 day | Safety |

**Expected result:** ~100s wall-clock for 9 metrics.

### Sprint 3 (Week 3): Materiality Gate + Benchmarking Setup
**Velocity: Medium effort, high impact**

| Task | Effort | Impact |
|------|--------|--------|
| Implement `ConditionalNarrativeAgent` | 1 day | -90s for immaterial metrics |
| Build model benchmark harness | 1 day | Foundation for Phase 3 |
| Card audit instrumentation | 0.5 day | Data gathering |
| Run benchmarks across model tiers | 2 days | Data gathering |

**Expected result:** ~70-80s wall-clock. Benchmark data to inform Phase 3.

### Sprint 4 (Week 4): LLM Optimization
**Velocity: Data-driven tuning**

| Task | Effort | Impact |
|------|--------|--------|
| Apply best model from benchmarks | 0.5 day | -5-10s per LLM call |
| Prompt size reductions | 1 day | -2-5s per LLM call |
| Make `direct` report synthesis the default | 0.5 day | Simplification |
| Executive brief optimization | 1 day | -30-40s on brief |
| End-to-end benchmark + documentation | 1 day | Validation |

**Expected result:** Sub-60s for 9 metrics. Sub-30s stretch achievable if narrative can be skipped for most.

---

## Key Files Reference

| Component | Path |
|-----------|------|
| Root pipeline | `data_analyst_agent/agent.py` (lines 288-306) |
| Parallel orchestration | `data_analyst_agent/core_agents/targets.py` (lines 107-270) |
| Parallel cap | `data_analyst_agent/core_agents/targets.py` (`_read_parallel_cap`, lines 273-296) |
| Inner parallel analysis | `data_analyst_agent/sub_agents/dynamic_parallel_agent.py` |
| Narrative wrapper | `data_analyst_agent/sub_agents/narrative_agent/agent.py` (lines 142-477) |
| Report synthesis wrapper | `data_analyst_agent/sub_agents/report_synthesis_agent/agent.py` (lines 415-974) |
| Report markdown tool | `data_analyst_agent/sub_agents/report_synthesis_agent/tools/generate_markdown_report.py` |
| Alert scoring pipeline | `data_analyst_agent/sub_agents/alert_scoring_agent/agent.py` |
| Context initializer | `data_analyst_agent/core_agents/loaders.py` |
| Output persistence | `data_analyst_agent/sub_agents/output_persistence_agent/agent.py` |
| Executive brief | `data_analyst_agent/sub_agents/executive_brief_agent/agent.py` |
| Model config | `config/agent_models.yaml` |
| Session isolation | `data_analyst_agent/sub_agents/data_cache.py` (`current_session_id`) |

## Env Vars Reference (New + Existing)

| Variable | Default | Phase | Purpose |
|----------|---------|-------|---------|
| `MAX_PARALLEL_METRICS` | `4` | Existing | Legacy: overall metric concurrency cap |
| `MAX_PARALLEL_COMPUTE` | `0` (unlimited) | New (Phase 1) | Compute phase concurrency |
| `MAX_PARALLEL_LLM` | `4` | New (Phase 1) | LLM phase concurrency |
| `REPORT_SYNTHESIS_EXECUTION_MODE` | `direct` | Existing | Skip report synthesis LLM |
| `SKIP_NARRATIVE_BELOW_MATERIALITY` | `true` | New (Phase 2) | Skip narrative for immaterial metrics |
| `NARRATIVE_MAX_TOP_DRIVERS` | `3` | Existing | Cap drivers in narrative prompt |
| `NARRATIVE_MAX_HIERARCHY_CARDS` | `2` | Existing | Cap hierarchy cards in prompt |
| `NARRATIVE_MAX_ANALYST_CHARS` | `2000` | Existing | Cap data_analyst_result in prompt |
| `NARRATIVE_MAX_STATS_CHARS` | `1500` | Existing | Cap statistical_summary in prompt |
| `NARRATIVE_CARD_AUDIT_ENABLED` | `true` | New (Phase 3) | Log per-target payload/card audit |

---

## Success Metrics

| Metric | Baseline | Phase 1+2 Target | Phase 3+4 Target |
|--------|----------|------------------|------------------|
| 9-metric wall-clock | ~225s | <100s | <60s |
| Per-metric LLM time | ~45s | ~45s (same, but overlapped) | <20s |
| LLM calls per run | 18 (9 narrative + 9 report) | 8-10 (skip immaterial + direct report) | 4-6 |
| Compute phase duration | Interleaved | <6s (all parallel) | <6s |
| Executive brief | ~65s | ~65s (unchanged) | <30s |
