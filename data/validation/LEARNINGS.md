# Code Review — Reviewer Audit 2026-03-12T17:20Z

**Commit range:** `783a491..d0985a2` (last 10 commits)
**Scope:** 30 files changed, +2362 / -529 lines
**Focus areas:** Production refactoring, executive brief fixes, temporal grain, deployment scaffolding, safety callbacks

---

## Critical (must fix before merge)

### 1. `safety_guardrails.py:87` — `import os` at bottom of file, `os` used before import

The `rate_limit_check` function calls `os.getenv("MAX_LLM_CALLS_PER_SESSION", "100")` at line 68, but `import os` is at the very last line of the file (line 87). This will raise `NameError: name 'os' is not defined` at runtime whenever `rate_limit_check` is called.

**Fix:** Move `import os` to the top of the file with the other imports (line 2-3 area).

### 2. `safety_guardrails.py` — `LlmResponse(blocked=True)` not a valid ADK constructor

The ADK `LlmResponse` class doesn't accept a `blocked` kwarg. This will crash on the first PII detection. Verify the ADK API — likely need to raise an exception or return a sentinel response per ADK callback contract.

**Fix:** Check `google.adk.models.llm_response.LlmResponse` constructor. Probably should return a proper `LlmResponse` with content only, or raise a custom exception that the callback framework catches.

### 3. `report_synthesis_agent/prompt.py:26` — unused `import os` (dead code in prompt module)

`os` is imported but never used. This is a new unused import introduced in the recent changes.

---

## Warning (fix soon)

### 4. Executive brief `metric_names` changed from contract → report keys (agent.py ~line 1006)

```python
# Old: metric_names from contract_metadata.get("metrics")
# New: metric_names = sorted(reports.keys())
```

This is a **correct fix** (prevents synthesizing non-analyzed metrics), but it means `metric_names` now depends on whatever keys `reports` dict contains — if a stage fails silently and doesn't populate a report key, the brief won't mention the missing metric at all. Pair this with a pre-flight check that validates all expected metrics have report entries before brief generation.

### 5. `loaders.py` temporal grain priority change is fragile

The new logic at line ~326 checks `ctx.session.state.get("temporal_grain")` and if it exists, skips all detection. This means any upstream agent that accidentally writes to `temporal_grain` state key will silently override the detection logic. The key is not namespaced — consider `"temporal_grain__aggregated"` or adding a `grain_source` check.

### 6. `compute_mix_shift_analysis.py` — `.apply(lambda, axis=1)` is NOT faster than `iterrows()`

The refactoring replaces `iterrows()` with `.apply(lambda row: {...}, axis=1).tolist()`. This is a common misconception — `DataFrame.apply(axis=1)` is internally just a Python loop over rows with more overhead. For actual vectorization, use `.to_dict('records')` with pre-computed columns (like the `compute_new_lost_same_store.py` changes correctly do). Same issue in:
- `compute_pvm_decomposition.py`
- `level_stats/core.py`
- `compute_anomaly_indicators.py`
- `compute_seasonal_decomposition.py`
- `compute_variance_decomposition.py` (still uses `for idx in` loop — inconsistent with stated goal)

**Fix:** Either use the `.to_dict('records')` pattern consistently (truly vectorized), or leave `iterrows()` where dict construction is complex. The `.apply(axis=1)` pattern is strictly worse than both.

### 7. `telemetry.py` — imports `opentelemetry` and GCP exporter at module level

If `opentelemetry` or `gcp-trace-exporter` packages aren't installed, importing `telemetry.py` will crash even if `OTEL_ENABLED=false`. The conditional check is inside `setup_telemetry()` but the imports are at the top.

**Fix:** Move OTEL imports inside the `if os.getenv("OTEL_ENABLED")` guard, or wrap in try/except with a graceful fallback.

### 8. `deployment/a2a/server.py` — `to_a2a()` called at module level (import side-effect)

Importing this module triggers `root_agent` initialization and A2A server creation. If any agent init fails, the entire module import crashes. This should be wrapped in a factory function.

---

## ADK Compliance

### `safety_guardrails.py` — Callback signature may not match ADK v1 contract

ADK `before_model_callback` expects `(callback_context, llm_request) -> Optional[LlmResponse]`. Verify the return type contract — returning an `LlmResponse` with arbitrary content may not signal "blocked" to the framework. Check if ADK expects `None` (proceed) vs raising an exception (block).

### Monthly enforcement block (agent.py ~line 1062)

The `monthly_enforcement_block` is injected as a raw string into the user message. This is prompt engineering, not agent architecture — but it adds ~400 tokens per monthly-grain run. Consider moving this to the prompt template in `config/prompts/executive_brief.md` with a conditional `{monthly_enforcement}` variable.

---

## Prompt Token Efficiency

| File | Size | Status |
|------|------|--------|
| `config/prompts/executive_brief.md` | **18,785 chars** | 🔴 **6.3x over limit** |
| `report_synthesis_agent/prompt.py` | **6,022 chars** | 🔴 **2x over limit** |
| `narrative_agent/prompt.py` | 1,853 chars | ✅ Under 3,000 |

**`executive_brief.md` at 18.8KB is the biggest token cost in the pipeline.** Every brief generation burns ~4,700 tokens just on the system prompt. This is the #1 optimization target for cost reduction.

**Recommendation:** Extract the section contract schema, formatting rules, and examples into separate files. Load only what's needed per run. The monthly enforcement block (Warning #8) adds even more.

---

## Unused Imports (131 total across codebase)

**Worst offenders by module:**

| Module | Count | Notable |
|--------|-------|---------|
| `statistical_insights_agent/tools/` | 48 | Bulk `from __future__ import annotations`, unused `Dict`, `Any`, `List`, `StringIO`, `numpy` |
| `hierarchy_variance_agent/tools/` | 16 | Unused `pandas`, `Dict`, `Any`, `List`, `Tuple`, `get_thresholds_for_category` |
| `report_synthesis_agent/` | 12 | Unused `os` (new!), bulk `from __future__ import annotations` |
| `sub_agents/` (misc) | 8 | `time`, `HyperConnectionManager` |
| `utils/` | 12 | Bulk `from __future__ import annotations`, `Optional`, `List` |
| `semantic/` | 8 | Unused `numpy`, `Dict`, `Any`, `Optional`, `QualityGateError`, `ContractValidationError` |

**The `from __future__ import annotations` imports (40+)** are a special case — they're harmless (PEP 563 deferred evaluation) but indicate the codebase was bulk-annotated without cleanup. Low priority.

**Actually dangerous unused imports:**
- `compute_new_lost_same_store.py:29` — `import numpy` (loads 20MB C extension for nothing)
- `compute_seasonal_decomposition.py:26` — `import numpy` (same)
- `stat_summary/per_item_metrics.py:6` — `import pandas` (redundant if already loaded, but still)
- `level_stats/hierarchy.py:6` — `import pandas`
- `quality.py:2` — `import numpy`
- `export_pdf_report.py:44` — `from weasyprint import CSS` (heavy native dependency)

**Fix:** Run `autoflake --remove-all-unused-imports --in-place -r data_analyst_agent/` to clean all at once.

---

## Hardcoded Trade-Data Assumptions

**Remaining references to trade-specific columns outside of contract-driven paths:**

1. `validation_data_loader.py:143` — Hardcoded column rename map `{"Region": "region", ...}`. This loader is validation-only so it's acceptable, but should have a comment noting it's trade-data-specific.

2. `__main__.py:7,45,60` — CLI help text references `region`, `terminal`. Acceptable (example text).

3. `narrative_agent/tools/generate_narrative_summary.py:101` — Checks `if any(token in kl for token in ("region", "country", "market", "geo"))`. This is a heuristic for geographic detection — fragile but functional. Should read dimension categories from contract metadata instead.

4. `weather_context_agent/prompt.py:20,31` — References "region" in LLM prompt examples. Acceptable (prompt engineering).

5. `report_synthesis_agent/tools/report_markdown/formatting.py:18` — Hardcoded `"regional_analysis"` tag. Should come from contract or be generalized to dimension-based analysis.

6. `report_synthesis_agent/tools/report_markdown/sections/insight_cards.py:34-39` — Hardcoded check for `"regional_distribution"`, `"regional_analysis"` tags. Same issue.

7. `executive_brief_agent/scope_utils.py:322` — Comment references "trade-only fields (e.g., region)". Code is contract-aware but the comment leaks domain assumptions.

**Verdict:** Items 3, 5, 6 are the real risks — they'll silently skip or mislabel sections when running on non-trade datasets. The rest are cosmetic.

---

## Observations

1. **The iterrows→apply refactoring is well-intentioned but misdirected.** The `compute_new_lost_same_store.py` changes (using `.to_dict('records')`) are the correct pattern. The others (`.apply(axis=1)`) should follow that example.

2. **Deployment scaffolding (`a2a/`, `telemetry.py`, `logging_config.py`, `safety_guardrails.py`) appears to be pre-production prep** — none of it is wired into the main pipeline yet. No `before_model_callback` registration found in `agent.py`. Good that it's isolated; needs integration tests before activation.

3. **The temporal grain fix in `loaders.py` is the highest-value change in this batch** — it solves the aggregation-then-re-detection bug. The implementation works but the session state key should be more defensive (see Warning #5).

4. **Commit hygiene is mostly docs commits** (6 of 10 are `docs:` prefix). The actual code changes are in 3-4 commits. Consider squashing the doc commits before merging to main.

5. **Test coverage for new code:** No new tests were added for `safety_guardrails.py`, `telemetry.py`, `logging_config.py`, or `deployment/a2a/server.py`. These need at minimum smoke tests.

---

*Review by Arbiter — 2026-03-12T17:20Z*
