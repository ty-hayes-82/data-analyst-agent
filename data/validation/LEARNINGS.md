# Code Review — Reviewer Audit 2026-03-12

**Commit range:** `a6ce3dc..647e93a` (10 commits)
**Scope:** 49 files changed, +9584 / -315 lines (mostly deployment scaffolding + executive brief validation hardening + temporal aggregation)

---

## Critical (must fix before merge)

### 1. Hardcoded `"terminal"` fallbacks still present (3 locations)

The new `get_default_grain_column()` utility was introduced in `a6ce3dc` to replace hardcoded `"terminal"` fallbacks — great. But it was only applied in one place (`period_totals.py:78`). Three other locations still use the old pattern:

- **`data_analyst_agent/sub_agents/statistical_insights_agent/tools/stat_summary/data_prep.py:146`**
  ```python
  _gcol = grain_col if grain_col in denom_df.columns else "terminal"
  ```
- **`data_analyst_agent/sub_agents/statistical_insights_agent/tools/compute_outlier_impact.py:133`**
  ```python
  index=grain_col if grain_col in denominator_df.columns else "terminal",
  ```
- **`data_analyst_agent/sub_agents/hierarchy_variance_agent/tools/level_stats/ratio_metrics.py:277`**
  ```python
  gcol = grain_col if grain_col in nd_df.columns else "terminal"
  ```

**Fix:** Replace all three with `get_default_grain_column(contract, fallback="terminal")` — same pattern as `period_totals.py:78`. This is the whole point of the utility introduced in that commit.

### 2. `validation_data_loader.py` has hardcoded trade-data column schema

- **`data_analyst_agent/tools/validation_data_loader.py:102`** — empty DataFrame fallback with hardcoded columns `["region", "terminal", "metric", "week_ending", "value"]`
- **Lines 143-154** — hardcoded column rename mapping (`"Terminal": "terminal"`, `"Region": "region"`) and sort order
- **Lines 172-198** — hardcoded filter columns (`region`, `terminal`)

This entire file is trade_data-specific. If another dataset is used, it will silently produce wrong columns or crash. Either:
- (a) Make it contract-driven (read column names from contract), or
- (b) Explicitly gate it with `if ACTIVE_DATASET == "trade_data"` and document the limitation

### 3. `hierarchy_variance_agent/tools/level_stats/ratio_metrics.py:185-207,352-353` — Extensive hardcoded `"terminal"` references

Multiple places check `if "terminal" in sub_df.columns` and group by `"terminal"`. These are not fallbacks — they're hardcoded business logic for the trade_data schema. These will silently produce wrong results for any other dataset.

---

## Warning (fix soon)

### 4. `DateInitializer` uses `datetime.now()` instead of UTC — potential date boundary bugs

- **`data_analyst_agent/core_agents/loaders.py:~line 430`** — `today = datetime.now()` uses local server time. On a UTC server this is fine, but if deployed to a different timezone or Vertex AI, date boundaries could shift. Use `datetime.utcnow()` or `datetime.now(timezone.utc)` for determinism.

### 5. `DateInitializer` focus config uses approximate month/year math

- **`data_analyst_agent/core_agents/loaders.py:~line 460`** — `timedelta(days=config["months"] * 30)` and `timedelta(days=config["years"] * 365)` are approximations. For "last 6 months" this can be off by up to 3 days. Use `dateutil.relativedelta` or `pd.DateOffset` for accurate calendar math.

### 6. `_count_numeric_values` imports `re` inside the function body

- **`data_analyst_agent/sub_agents/executive_brief_agent/agent.py:~line 480`** — `import re` inside `_count_numeric_values()`. This is called in a validation loop (once per section, once per insight). Move the import to module top-level. Not a performance issue in practice (Python caches imports), but it's a code smell and violates project conventions.

### 7. `AnalysisContextInitializer` imports `traceback` inside except block

- **`data_analyst_agent/core_agents/loaders.py:~line 237`** — `import traceback` inside an except handler. Move to top-level imports.

---

## ADK Compliance

### State Management ✅ (mostly sound)
- `focus_temporal_grain` correctly flows through state_delta from DateInitializer → AnalysisContextInitializer. Good ADK pattern.
- Scoped brief retry count (`max_scoped_retries`) is env-configurable. Good.

### Production Learnings Compliance
- **#1 Silent failure guards:** ✅ The executive brief agent now validates numeric content density. Good guardrail.
- **#3 Parallel agent isolation:** No new parallel state key conflicts introduced. ✅
- **#4 Pre-flight validation:** The new `_count_numeric_values` + `_validate_structured_brief` enhancements are strong pre-output validation. ✅
- **#5 Env leaking:** New env vars `DATA_ANALYST_FOCUS` / `DATA_ANALYST_CUSTOM_FOCUS` added to output_manager metadata — good traceability. ✅
- **#7 TimedAgentWrapper:** Not checked — no new agents added to pipeline, so no new timing gaps. ✅ (neutral)

### Missing from Production Learnings
- **#8 State assertions:** The new `focus_temporal_grain` state key is consumed in `AnalysisContextInitializer` but there's no assertion if it's an unexpected value. The `if focus_temporal_grain and focus_temporal_grain in ["weekly", "monthly", "yearly"]` check silently skips unknown values — should log a warning for unknown grains.

---

## Unused Imports (30 found across codebase)

Most impactful (in recently-changed files):
- `data_analyst_agent/utils/temporal_aggregation.py:3` — `from __future__ import annotations` (unused)
- `data_analyst_agent/utils/temporal_aggregation.py:6` — `Optional` imported but never used
- `data_analyst_agent/sub_agents/dynamic_parallel_agent.py:1` — `List`, `Any` unused
- `data_analyst_agent/sub_agents/dynamic_parallel_agent.py:8` — `time` unused

Full count: 30 unused imports across `data_analyst_agent/`. Run `ruff check --select F401` to auto-fix.

---

## Prompt Token Efficiency

| File | Size | Status |
|------|------|--------|
| `config/prompts/executive_brief.md` | **18,785 chars** | 🔴 6x over limit |
| `sub_agents/report_synthesis_agent/prompt.py` | **6,022 chars** | 🟡 2x over limit |
| `sub_agents/narrative_agent/prompt.py` | 1,853 chars | ✅ Under limit |

**`executive_brief.md` at 18.8K chars** is the biggest token burn in the pipeline. Every brief generation (network + per-scope) sends this as system prompt. With 5 scoped briefs, that's ~94K chars of prompt alone — roughly 25K tokens per run just for brief instructions.

**Recommendation:** Split `executive_brief.md` into a base prompt (~4K chars) and conditional appendices injected only when relevant (monthly grain rules, scoped brief rules, etc.). The monthly enforcement block added in this diff could be one such appendix instead of always-on prompt text.

---

## Observations

1. **Good architectural direction:** The `get_default_grain_column()` utility and temporal aggregation are the right moves toward dataset-agnostic operation. Just need to finish the migration (Critical #1).

2. **Deployment scaffolding is large but unreviewed here** — 9K+ lines of Terraform, Docker, Cloud Build, monitoring config were added. These need a separate infra review.

3. **Test coverage gap:** `temporal_aggregation.py` (114 lines, non-trivial aggregation logic) has no tests. The grain detection heuristic (`median_diff <= 7 days = weekly`) could produce wrong results for irregular time series. Needs unit tests.

4. **The brief validation hardening is excellent** — numeric value counting, scoped retry tuning, and section contract normalization after retry exhaustion are all production-quality improvements that address real failure modes.

---

*Generated by Arbiter (reviewer agent) — 2026-03-12T16:48Z*
