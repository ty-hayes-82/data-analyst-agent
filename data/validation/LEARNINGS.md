# Code Review — Reviewer Audit 2026-03-12T17:47Z

**Commit range:** `647e93a..b8af281` (last 10 commits)
**Scope:** 33 files changed, +2881 / -516 lines
**Focus areas:** Production refactoring, executive brief prompt v2, temporal grain fix, safety callbacks, telemetry, logging, iterrows→vectorized conversions

---

## Critical (must fix before merge)

### 1. `callbacks/safety_guardrails.py:87` — `import os` at bottom of file

`rate_limit_check()` calls `os.getenv()` at line 68, but `import os` is the **last line** of the file (line 87). Python executes top-down — this will raise `NameError: name 'os' is not defined` on every invocation.

**Fix:** Move `import os` to line 2-3 with the other imports. This is a guaranteed runtime crash.

### 2. `callbacks/safety_guardrails.py` — `LlmResponse(blocked=True)` is not valid ADK API

The ADK `LlmResponse` class does not accept a `blocked` keyword argument. Both `content_safety_filter()` and `rate_limit_check()` construct `LlmResponse(content=..., blocked=True)`. This will raise `TypeError` on the first PII detection or rate limit hit.

**Fix:** Verify `google.adk.models.llm_response.LlmResponse` constructor signature. The ADK callback contract likely expects returning a `LlmResponse` with content only, or raising an exception. Check ADK docs for the correct rejection pattern.

### 3. `telemetry.py` — module-level side effect with missing dependency

`tracer = setup_telemetry()` runs at import time (line 43). If `opentelemetry` or `gcp.trace_exporter` packages aren't installed, **importing any module that transitively imports telemetry.py will crash the entire pipeline**. No try/except guard.

**Fix:** Wrap the import block in a try/except that gracefully degrades:
```python
try:
    from opentelemetry import trace
    # ...
except ImportError:
    trace = None
```

---

## Warning (fix soon)

### 4. `config/prompts/executive_brief.md` — 18,785 chars (6x over 3,000 char budget)

This is the v1 prompt at **18.8KB**. That's enormous token overhead on every executive brief generation. The v2 (`executive_brief_v2.md`) is 5,771 chars — better but still almost 2x the 3K target.

**Status:** Unclear which prompt is actually loaded at runtime. If v1 is still active, this is burning ~4,700 tokens per call unnecessarily.

**Action:** Confirm v2 is wired in, archive v1, and consider trimming v2 further.

### 5. `sub_agents/report_synthesis_agent/prompt.py` — 6,022 chars (2x over budget)

At 6KB this prompt is the second-largest. Review for redundant instructions or examples that could be moved to few-shot state injection instead of static prompt text.

### 6. `core_agents/loaders.py` — temporal grain precedence change is correctness-sensitive

The new logic checks `ctx.session.state.get("temporal_grain")` before contract/env detection. This means if **any** upstream agent accidentally writes a stale `temporal_grain` to session state, it will silently override the contract-specified grain with confidence=1.0.

**Risk:** No validation that the existing grain was actually set by the aggregation step (vs. a leftover from a previous run in the same session). Consider using a more specific key like `"aggregated_temporal_grain"` to avoid collisions.

### 7. `logging_config.py` — `pythonjsonlogger` dependency not guarded

If `pythonjsonlogger` isn't installed, any import chain that touches `logging_config` will fail. This is a new hard dependency introduced in these commits.

**Fix:** Add to `requirements.txt` / `pyproject.toml` if not already there, or guard with try/except.

---

## ADK Compliance

### ✅ Good: Executive brief now uses analyzed metrics
`executive_brief_agent/agent.py` line 1006: `metric_names = sorted(reports.keys())` — correctly scopes the brief to only metrics that were actually analyzed, not all contract metrics. This prevents hallucinated synthesis of non-analyzed metrics. Solid fix.

### ✅ Good: Temporal grain persistence via session state
The pattern of setting `ctx.session.state["temporal_grain"]` in the aggregation step and reading it downstream is correct ADK state management. Just needs the collision guard noted in Warning #6.

### ⚠️ Safety callbacks not wired into any agent
`callbacks/safety_guardrails.py` defines `content_safety_filter` and `rate_limit_check` but I see no evidence they're registered as `before_model_callback` on any agent. Dead code until wired in.

---

## Unused Imports (172 detected)

**High-priority (in changed files):**
- `callbacks/safety_guardrails.py` — `os` imported at wrong location (Critical #1)
- `sub_agents/dynamic_parallel_agent.py:1` — `List`, `Any` unused; `time` imported but unused
- `sub_agents/statistical_insights_agent/tools/compute_new_lost_same_store.py:29-30` — `np`, `Dict`, `Any`, `List` all unused after vectorization refactor

**Systemic pattern:** 172 potentially unused imports across the codebase. Many are `from __future__ import annotations` (harmless) and typing imports that may be used in type comments. Recommend running `autoflake --check` for a definitive count.

**Action:** At minimum, clean up the imports in files touched by this PR. The statistical_insights tools shed their `iterrows` loops but kept the old typing imports.

---

## Hardcoded Domain References

Grep found **no hardcoded trade_data column assumptions** outside of contract-driven paths. Key findings:

- `validation_data_loader.py` — References `region`, `terminal`, `metric` but these are **generic column names** read from the validation CSV schema, not trade-data specific. ✅
- `report_synthesis_agent/.../insight_cards.py:34-39` — Checks for `"regional_distribution"`, `"regional_analysis"` tags. These are **insight card tags**, not column names, but they embed domain knowledge about what "regional" means. **Minor smell** — could be contract-driven tag categories.
- `narrative_agent/tools/generate_narrative_summary.py:101` — Pattern-matches on `"region", "country", "market", "geo"` tokens to detect geographic dimensions. **Moderate smell** — this is a heuristic that assumes geographic dimension naming conventions. Works for now but fragile for non-geographic datasets.
- `weather_context_agent/prompt.py:20,31` — References "region" in LLM prompt instructions. Fine — this is natural language guidance to the LLM, not code logic.

**Verdict:** No critical hardcoding. Two moderate heuristics that should eventually be contract-driven.

---

## Performance: iterrows → Vectorized Conversions

The bulk of code changes (8 files) convert `iterrows()` loops to `.apply(lambda, axis=1).tolist()` patterns. Assessment:

### ⚠️ `.apply(axis=1)` is NOT truly vectorized
Using `df.apply(lambda row: {...}, axis=1)` is syntactically cleaner than `iterrows()` but has **nearly identical performance** — both iterate row-by-row in Python. True vectorization uses column-wise operations without row lambdas.

**Files affected:**
- `compute_mix_shift_analysis.py`
- `compute_pvm_decomposition.py`
- `level_stats/core.py`
- `compute_anomaly_indicators.py`
- `compute_new_lost_same_store.py`
- `compute_seasonal_decomposition.py`
- `compute_variance_decomposition.py`
- `cross_dimension/patterns.py`

**Reality check:** For the data volumes in this pipeline (typically <1000 rows per tool call), the performance difference is negligible. This is a **style improvement** not a performance improvement. Don't let commit messages claim "vectorized" — it's misleading.

**True optimization path:** Use `df.to_dict('records')` with pre-computed columns, which avoids the per-row lambda overhead entirely. Several of the `compute_new_lost_same_store.py` changes already do this correctly — good pattern to follow.

---

## Observations

1. **Documentation bloat in repo root:** 7 new markdown files (`DEV_ITERATION_REPORT.md`, `NIGHT_SHIFT_SUMMARY.md`, `REFACTORING_SUMMARY.md`, etc.) totaling ~1,500 lines. These are session logs, not project docs. Should live in `docs/session-logs/` or be gitignored.

2. **Two executive brief prompts coexist:** `executive_brief.md` (v1, 18KB) and `executive_brief_v2.md` (5.7KB). Unclear which is loaded. Risk of confusion — archive the unused one.

3. **`deployment/a2a/` scaffolding is empty:** `__init__.py` has 1 line, `server.py` has 51 lines. Looks like A2A server scaffolding that's not connected to anything yet. Fine as scaffolding, but don't let it ship to production without integration tests.

4. **Good pattern:** The `level_stats/core.py` change adds optional ratio fields (`ratio_current`, `ratio_prior`, `ratio_variance`) using `**({} if ... else {})` spread — clean way to handle optional keys without None pollution.

---

## Summary

| Category | Count |
|----------|-------|
| Critical (must fix) | 3 |
| Warning (fix soon) | 4 |
| ADK compliance issues | 1 (callbacks unwired) |
| Unused imports | 172 (systemic), 8 in changed files |
| Hardcoded assumptions | 0 critical, 2 moderate heuristics |
| Prompt token concerns | 2 files over budget |

**Bottom line:** The safety_guardrails.py file has two guaranteed runtime crashes (Critical #1 and #2) — do not merge until fixed. The telemetry.py import guard (Critical #3) is a deployment time-bomb. Everything else is solid incremental improvement, with the caveat that the "vectorization" claims in commit messages overstate the actual performance gain.
