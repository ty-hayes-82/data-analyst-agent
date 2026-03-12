# E2E Performance Regression — Narrative Synthesis Timeout (2026-03-12 15:55 UTC)

**Tester:** Sentinel (tester agent)  
**Test Run:** Cron job `tester-e2e-001`  
**Finding:** Pipeline consistently times out during narrative generation (LLM calls >90s)

---

## Issue Summary

### Symptoms
1. **Multi-metric pipeline**: Timeout (300s) during `narrative_agent` LLM call for `trade_value_usd`
   - Analysis stages complete successfully
   - Narrative agent starts, builds prompt (6,751 chars payload + 1,775 chars instruction)
   - LLM call hangs, never returns
   - Killed by SIGTERM after 300s
2. **Single-metric pipeline**: Timeout (90s) during `narrative_agent` LLM call for `volume_units`
   - Analysis completes successfully
   - Narrative agent hangs on LLM call
   - Exit code 124 (timeout)

### Performance Profile
| Stage | Duration | % of Total |
|-------|----------|------------|
| Data fetch | 1.18s | 4% |
| Analysis | 2.96s | 10% |
| Narrative agent | **18.79s+** | **63%+** |
| Alert scoring | 0.20s | <1% |
| Report synthesis | Blocked | — |

**Bottleneck**: Narrative agent LLM call dominates execution time and frequently times out.

### Root Causes (Hypotheses)
1. **Prompt payload size**: 6,751 chars for trade_value_usd (8,526 chars total prompt)
   - Input: insight cards + hierarchical analysis + statistical summary
   - Large context → slower LLM inference
2. **LLM provider latency**: Gemini 2.5 Flash Lite (Google AI API)
   - API call overhead (serialization, network, queue time)
   - No retry logic or fallback
3. **Missing timeout enforcement**: No safeguard at agent level
   - Process-level timeout (300s/90s) is last resort, not graceful

### Impact
- **Production readiness**: ⚠️ **BLOCKED** — Cannot reliably complete multi-metric analysis
- **Test coverage**: ✅ **GOOD** — 298/298 tests pass (unit + integration)
- **Graceful degradation**: ⚠️ **PARTIAL** — Partial artifacts saved before timeout

---

## Action Items

### High Priority (Fix This Week)
1. **Prompt-engineer**: Reduce narrative prompt payload from 6,751 → <3,000 chars
   - Pre-filter insight cards by priority (critical/high only)
   - Summarize statistical summary (drop raw JSON, keep text summaries)
   - Move examples/boilerplate to few-shot appendices
2. **Dev**: Add 60s timeout to `narrative_agent` LLM call
   - Wrap LLM call in `asyncio.wait_for(timeout=60)`
   - Raise `TimeoutError` and propagate to fallback logic
3. **Dev**: Add fallback narrative generation when LLM fails
   - Use insight card summaries + template filling
   - Log warning, proceed with partial report
4. **Dev**: Add LLM call retry logic (max 2 retries with exponential backoff)
   - Handle transient API errors (429, 500, 503)
   - Fail gracefully after retries exhausted

### Medium Priority (Fix Next Sprint)
1. **Profiler**: Profile narrative_agent LLM call overhead
   - Measure: serialization time, network latency, inference time
   - Compare providers: Gemini vs Claude vs GPT
2. **Prompt-engineer**: Test fast-path narrative (code-based, no LLM)
   - Generate narrative from insight cards programmatically
   - Compare quality vs LLM-generated narrative
3. **Dev**: Add concurrent narrative generation for multi-metric pipelines
   - Parallelize narrative_agent calls (one per metric)
   - Use `asyncio.gather()` with timeout per task

### Low Priority (Nice to Have)
1. **Dev**: Add progress indicators during long LLM calls
   - Log "Waiting for LLM response..." every 5s
   - Help distinguish hang vs slow call
2. **Tester**: Add smoke test for narrative agent (max 30s)
   - Run with small payload (1 metric, 1 insight card)
   - Flag regression if >30s

---

## Workarounds (Temporary)

### For Testing
- Use `MAX_DRILL_DEPTH=1` to reduce payload size
- Use single-metric mode (`DATA_ANALYST_METRICS=volume_units`)
- Skip narrative generation in CI (test up to statistical summary)

### For Production
- Enable fast-path report synthesis (skip narrative_agent)
- Use code-based insight cards only (no LLM for insights)
- Set process timeout to 120s (vs 300s) to fail fast

---

## Test Evidence

### Test Suite (298 passed, 6 skipped, 0 failed)
```
============================= slowest 10 durations =============================
5.99s call     tests/e2e/test_adk_integration.py::TestFullPipelineOrchestration::test_root_agent_run_async_completes_with_report_and_alerts
1.79s call     tests/e2e/test_incremental_pipeline.py::TestLevel7_FullPipeline::test_end_to_end_sequence_produces_complete_report
...
======================= 298 passed, 6 skipped in 29.40s ========================
```

### Multi-Metric Pipeline Output (Partial)
```
[TIMER] >>> Starting agent: narrative_agent
[NarrativeAgent] Instruction updated for contract: Trade Data
[NarrativeAgent] Prompt size — instruction=1,775 chars, payload=6,751 chars
[NarrativeAgent] DEBUG: Saved prompt to outputs/trade_data/20260312_155547/debug/narrative_prompt_trade_value_usd.txt
[TIMER] <<< Finished agent: narrative_agent | Duration: 18.79s
[... hangs, never completes report_synthesis_agent]
Process exited with signal SIGTERM.
```

### Single-Metric Pipeline Output (Timeout)
```
[TIMER] >>> Starting agent: narrative_agent
[NarrativeAgent] Instruction updated for contract: Trade Data
[NarrativeAgent] Prompt size — instruction=1,775 chars, payload=2,557 chars
[... hangs]
Process exited with code 124.
```

---

## Recommendations

1. **Immediate**: Add timeout + fallback to narrative_agent (1-2 hours dev time)
2. **Short-term**: Reduce prompt payload size (4-6 hours prompt engineering)
3. **Long-term**: Switch to code-based narrative generation (8-12 hours dev time)
4. **Monitor**: Track LLM call duration in production logs (add instrumentation)

---

# Code Review — Automated Audit (2026-03-12)

**Reviewer:** Arbiter (reviewer agent)  
**Scope:** Last 10 commits (`7bbb361..2a561bd`) — 23 files changed, +2195 / -251 lines  
**Commit range:** Contract fixes, executive brief prompt hardening, UI improvements, docs

---

## Critical (must fix before merge)

### 1. Hardcoded "terminal" fallback in stat tools — breaks non-trade datasets

Several files fall back to `"terminal"` when `grain_col` is missing from the DataFrame, instead of reading the grain column from the contract. This will crash or silently produce wrong results on datasets like `us_airfare` that have no `terminal` column.

| File | Line(s) | Issue |
|------|---------|-------|
| `sub_agents/statistical_insights_agent/tools/stat_summary/data_prep.py` | 146 | `grain_col if grain_col in denom_df.columns else "terminal"` |
| `sub_agents/statistical_insights_agent/tools/compute_outlier_impact.py` | 133 | Same pattern — hardcoded `"terminal"` fallback |
| `sub_agents/hierarchy_variance_agent/tools/level_stats/ratio_metrics.py` | 185-207, 277, 352-353 | 8 references to hardcoded `"terminal"` column |

**Fix:** These should read the grain column from the contract/session state. If missing, raise a clear error rather than guessing `"terminal"`.

### 2. `validation_data_loader.py` is entirely trade-data-specific

`tools/validation_data_loader.py` hardcodes column names `["region", "terminal", "metric", "week_ending", "value"]` (lines 102, 143-144, 154, 172-175, 198). This loader cannot work with any other dataset schema.

**Fix:** Either make it contract-driven or clearly scope it as trade-data-only (rename to `trade_validation_loader.py` and guard entry points).

---

## Warning (fix soon)

### 3. Prompt token bloat — executive_brief.md is 5× over budget

| File | Chars | Status |
|------|-------|--------|
| `config/prompts/executive_brief.md` | **14,920** | 🔴 5× over 3,000 char target |
| `sub_agents/report_synthesis_agent/prompt.py` | **6,022** | 🟡 2× over 3,000 char target |
| `sub_agents/narrative_agent/prompt.py` | 1,853 | ✅ Under budget |

At ~4 tokens/char, `executive_brief.md` burns ~3,700 tokens per invocation. This is a significant cost and latency driver on every pipeline run.

**Fix:** Extract examples and boilerplate into few-shot appendices loaded on demand. Core prompt should be ≤3,000 chars.

### 4. `report_synthesis_agent/prompt.py` has dead `import os`

Line 1 area — `os` is imported but never used. Harmless but sloppy. Part of the larger unused imports issue below.

---

## Unused Imports — 120+ instances

**This is the single largest code hygiene issue in the codebase.** A bulk cleanup pass would reduce cognitive load and import overhead. Key categories:

### Truly dead imports (will cause confusion or hide bugs)
- `compute_new_lost_same_store.py`: unused `numpy`, `Dict`, `Any`, `List`
- `detect_mad_outliers.py`: unused `Dict`, `Any`, `List`, `StringIO`
- `compute_lagged_correlation.py`: unused `Dict`, `Any`, `List`
- `compute_outlier_impact.py`: unused `Dict`, `Any`, `scipy_stats`
- `compute_pvm_decomposition.py`: unused `pandas`, `Dict`, `Any`, `List`
- `compute_mix_shift_analysis.py`: unused `pandas`, `Dict`, `Any`, `List`
- `stat_summary/per_item_metrics.py`: unused `pandas`
- `stat_summary/summary_enhancements.py`: unused `numpy`
- `semantic/quality.py`: unused `numpy`, `Dict`, `Any`, `Optional`, `QualityGateError`
- `semantic/policies.py`: unused `List`, `Dict`, `Union`
- `dynamic_parallel_agent.py`: unused `List`, `Any`, `time`
- `export_pdf_report.py`: unused `CSS` from weasyprint
- `config.py`: unused `Optional`
- `agent.py`: unused `statistical_insights_agent`, `hierarchical_analysis_agent` (these may be side-effect imports — verify)
- `tableau_hyper_fetcher/fetcher.py`: unused `HyperConnectionManager`

### `from __future__ import annotations` — 40+ files
These are technically unused when no forward-reference annotations exist. Low priority but noisy. Consider removing in files that don't need them, or keep consistently everywhere as a project convention (decide and document).

**Recommended action:** Run `autoflake --remove-all-unused-imports --in-place -r data_analyst_agent/` or equivalent. Then manually verify `agent.py` side-effect imports.

---

## ADK Compliance

### Agent name uniqueness — ✅ OK
Recent commits don't introduce duplicate agent names.

### Session state keys — ⚠️ Watch
The hardcoded `"terminal"` fallbacks (Critical #1) suggest some agents may not be reading grain columns from state correctly. Audit all `grain_col` resolution paths.

### Error handling — ✅ Improved
Commit `a6ce3dc` added contract-driven grain column fallback utility, which is the right direction. The stat tools just haven't been updated to use it yet.

---

## Observations

1. **Docs-heavy sprint.** 8 of 10 commits are documentation. The code changes are focused and correct in isolation.
2. **`find_long_functions.py` in repo root** — appears to be a dev utility. Should be in `scripts/` or `.gitignore`'d.
3. **Web UI got significant work** (+303 lines in `index.html`, +137 in `style.css`). No review of frontend was requested but flag for manual testing.
4. **Contract system is maturing.** The `us_airfare` contract addition (`1c57915`) and grain column utility (`a6ce3dc`) show the right architectural direction. The gap is that downstream stat tools haven't caught up.

---

## Priority Action Items for Dev Agent

1. **[P0]** Replace all hardcoded `"terminal"` fallbacks with contract-driven grain column resolution
2. **[P0]** Run `autoflake` to purge dead imports across `data_analyst_agent/`
3. **[P1]** Trim `executive_brief.md` prompt — extract examples to appendix, target ≤3,000 chars
4. **[P1]** Scope `validation_data_loader.py` — rename or make contract-driven
5. **[P2]** Move `find_long_functions.py` to `scripts/`
6. **[P2]** Remove dead `import os` from `report_synthesis_agent/prompt.py`
