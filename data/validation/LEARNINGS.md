# Code Review — 2026-03-13 (Arbiter Audit)

**Commit range:** `92aee99..60f492f` (15 commits)
**Scope:** 47 files changed, 6636 insertions, 865 deletions
**Last audit:** 03:20 UTC (Forge dev session — 5 hardcoded fallback fixes applied)
**Previous audit:** 02:57 UTC (Arbiter review — identified hardcoded issues)

---

## ✅ Fixed (2026-03-13 03:20 UTC — Dev Session)

### Hardcoded Fallback Removal (5 commits: 392cb3b..60f492f)

**What:** Removed all hardcoded dataset-specific fallbacks identified in the Arbiter audit.

**Files changed:**
1. `ratio_metrics.py:363-364` — ✅ Replaced hardcoded `"terminal"` with `grain_col` (commit 392cb3b)
2. `data_prep.py:146,149` — ✅ Removed `"terminal"` and `"period"` fallbacks, fail explicitly with clear error (commit ac0ab6c)
3. `compute_outlier_impact.py:136` — ✅ Removed `"terminal"` fallback, fail explicitly (commit f1fa057)
4. `validation_csv_fetcher.py:155` — ✅ Removed `"week_ending"` fallback, require `contract.time.column` (commit cdd0505)
5. `validation_data_loader.py:102` — ✅ Removed hardcoded empty DataFrame schema, return empty DF with no columns (commit 60f492f)

**Impact:** Pipeline is now fully contract-driven for grain and time columns. Any missing contract configuration will fail fast with clear error messages instead of silently falling back to trade_data-specific column names.

**Test status:** ✅ All 291 tests pass after fixes (same baseline, no regressions).

---

## Critical (must fix before merge)

### 1. `ratio_metrics.py:174` — Hardcoded `truck_count` / `days_in_period` column names
```python
for extra_col in ["truck_count", "days_in_period"]:
    if extra_col in nd_df.columns:
        numeric_cols.append(extra_col)
```
**Issue:** These column names are trade-dataset-specific. A different dataset with a different denominator resource (e.g., "headcount", "fleet_size") would silently skip this logic. The TODO at line 183 acknowledges this but it's still shipping.

**Fix:** Add a `denominator_columns` or `auxiliary_columns` list to `ratio_config` in the contract YAML. Read those instead of hardcoding.

### 2. `ratio_metrics.py:185` — Hardcoded `"Truck Count"` metric name check
```python
use_network_truck_denominator = (
    ratio_config.get("denominator_metric") == "Truck Count"
    ...
)
```
**Issue:** This gate is the *only* path to correct network-level denominator aggregation. Any dataset needing the same pattern with a different denominator name gets wrong results — **silent data corruption**.

**Fix:** Use `ratio_config.get("denominator_aggregation_strategy") == "network_daily_average"` instead of checking the metric name.

### 3. ~~`ratio_metrics.py:363-364` — Missed hardcoded `"terminal"` in same file~~ ✅ FIXED
~~**Issue:** Lines 192-215 were correctly fixed to use `grain_col` instead of `"terminal"`, but lines 363-364 in `_aggregate_from_validation_data` were **missed**.~~

**Status:** ✅ Fixed in commit 392cb3b — now uses `grain_col` consistently.

---

## Warning (fix soon)

### 4. ~~Remaining hardcoded `"terminal"` fallbacks in other files~~ ✅ FIXED
~~**Issue:** These `else "terminal"` / `or "week_ending"` fallbacks mean if `grain_col` or `time_column` is missing from the DataFrame, the code silently assumes trade_data column names.~~

**Status:** ✅ Fixed in commits ac0ab6c, f1fa057, cdd0505, 60f492f — all fallbacks removed, now fail explicitly with clear error messages.

### 5. `agent.py:1168,1176` — Hardcoded example values in prompt enforcement blocks
```python
"- Vague references: \"significant increase\", \"multiple regions\"\n"
...
"The West region contributed $31.66M (32.6% of network variance)..."
```
**Issue:** The numeric enforcement examples reference "West region", "$31.66M", and other trade-data-specific values. These are baked into the prompt template, not dynamically generated from the actual dataset. This biases the LLM toward outputting trade-data-like language for any dataset.

**Fix:** Either make examples generic (no domain-specific entity names) or template them from session state / contract metadata.

### 6. Prompt token bloat — `executive_brief.md` at 7,843 chars
| File | Chars | Status |
|------|-------|--------|
| `config/prompts/executive_brief.md` | 7,843 | ⚠️ Over 3,000 limit (2.6×) |
| `report_synthesis_agent/prompt.py` | 6,022 | ⚠️ Over 3,000 limit (2.0×) |
| `narrative_agent/prompt.py` | 2,791 | ✅ Under limit |

The executive brief prompt *plus* the new inline numeric enforcement blocks (added in this batch) compound the token cost significantly. Every network brief LLM call now sends the 7.8K prompt + ~1.5K enforcement block + all the data context.

**Note:** The model tier was downgraded from `pro` to `advanced` (commit `52e51bc`), which helps cost but makes prompt efficiency even more important — smaller models are more sensitive to prompt noise.

**Fix:** Consider extracting the numeric enforcement into a reusable few-shot template referenced by name, or move validation to post-processing only (you already have `_validate_structured_brief`).

### 7. `agent.py` — Duplicate enforcement blocks (network vs scoped)
Lines 1153–1187 and 1430–1462 contain near-identical numeric enforcement text, differing only in the threshold (3 vs 2 numeric values). This is ~60 lines of duplication.

**Fix:** Extract to a helper function: `_build_numeric_enforcement(min_values: int, is_scoped: bool) -> str`.

### 8. ~~`validation_data_loader.py:102` — Hardcoded column schema~~ ✅ FIXED
~~**Issue:** Empty DataFrame fallback hardcodes trade_data column names. If a different dataset hits this path, downstream code may get a DataFrame with wrong column names.~~

**Status:** ✅ Fixed in commit 60f492f — now returns empty DataFrame with no hardcoded columns; caller handles missing data appropriately.

---

## ADK Compliance

- ✅ `_apply_section_contract` correctly normalizes LLM output post-hoc (good defensive pattern)
- ✅ `_validate_structured_brief` adds forbidden-title detection — good belt-and-suspenders
- ✅ `period_totals.py` now reads `aggregation_method` from contract (Production Learning #1 compliance)
- ✅ `ratio_metrics.py` hardcoded `"terminal"` at line 363 now fixed (commit 392cb3b); 2 TODOs remain for `truck_count`/`days_in_period` column names (see Critical #1)
- ✅ Unused dataset configs removed (covid, owid, worldbank, global_temp) — good cleanup
- ✅ Model tier optimization (pro → advanced for executive_brief) — cost-conscious

---

## Unused Imports (cleanup)

**166 potentially unused imports detected.** Breakdown:
- `from __future__ import annotations`: 88 (harmless, keep)
- `from typing import ...`: 55 (type hints, mostly harmless)
- **Actionable real-code imports: 23**

Top-priority removals:

| File | Import | Action |
|------|--------|--------|
| `dynamic_parallel_agent.py:8` | `import time` | Remove — not used |
| `hierarchical_analysis_agent/agent.py:10` | `DrillDownDecisionAgent` | Remove — dead import of agent class |
| `report_synthesis_agent/prompt.py:26` | `import os` | Remove — not used |
| `export_pdf_report.py:44` | `CSS` (weasyprint) | Remove if unused |
| `compute_mix_shift_analysis.py:27` | `import pandas as pd` | Remove — not used in file |
| `hierarchy.py:6` | `import pandas as pd` | Remove — not used in file |
| `compute_outlier_impact.py:26` | `scipy.stats` | Verify — may be dead after refactor |
| `semantic/quality.py:2` | `numpy as np` | Remove if unused |
| `semantic/quality.py:5` | `QualityGateError` | Remove if unused |
| `semantic/models.py:6` | `ContractValidationError` | Remove if unused |
| `tableau_hyper_fetcher/fetcher.py:37` | `HyperConnectionManager` | Verify — may be needed for type checking |

**Recommendation:** Run `ruff check --select F401 data_analyst_agent/` for definitive dead import detection.

---

## Observations

1. **Good trajectory:** The last 10 commits show a clear pattern of removing hardcoded assumptions and making things contract-driven. The `ratio_metrics.py` terminal→grain_col fix and `period_totals.py` aggregation_method fix are textbook.

2. **Inconsistent fix depth:** `ratio_metrics.py` was partially fixed (lines 192-215 use `grain_col`) but line 363 still says `"terminal"`. This suggests the fix was applied by searching for obvious patterns but missed the second occurrence in `_aggregate_from_validation_data`. **The dev agent should do a full `grep -n '"terminal"' ratio_metrics.py` before considering this done.**

3. **Hardcoded fallback anti-pattern:** Three files use the `x if x in df.columns else "terminal"` pattern. This is a time bomb — it works perfectly for trade_data and silently corrupts any other dataset. Replace with explicit failures.

4. **Prompt engineering arms race:** The numeric enforcement blocks are a workaround for LLM non-compliance. This adds token cost on every call. Consider whether post-hoc validation in `_validate_structured_brief` is sufficient alone — if validation catches and retries, the verbose in-prompt enforcement may be redundant.

5. **Dataset config cleanup was good housekeeping:** Removing 4 unused dataset configs (covid, owid, worldbank, global_temp) reduces confusion. However, this means the only remaining dataset is trade_data — which makes it harder to catch hardcoded assumptions through testing.

6. **Model tier change needs monitoring:** `executive_brief_agent` moved from `pro` to `advanced`. Lower-tier models may be more sensitive to the prompt bloat flagged in Warning #6. Monitor output quality.

---

## Action Items Summary

| Priority | Item | Owner |
|----------|------|-------|
| 🔴 Critical | Fix `ratio_metrics.py:363-364` — missed `"terminal"` hardcode | dev |
| 🔴 Critical | Replace `"Truck Count"` gate with `denominator_aggregation_strategy` config | dev |
| 🔴 Critical | Add `auxiliary_columns` to ratio_config in contract YAML | dev |
| 🟡 Warning | Remove `"terminal"` fallbacks in `data_prep.py`, `compute_outlier_impact.py` | dev |
| 🟡 Warning | Remove `"week_ending"` fallback in `validation_csv_fetcher.py` | dev |
| 🟡 Warning | Fix hardcoded empty DataFrame columns in `validation_data_loader.py:102` | dev |
| 🟡 Warning | Extract `_build_numeric_enforcement()` helper to deduplicate | dev |
| 🟡 Warning | Make prompt examples dataset-agnostic | prompt-engineer |
| 🟢 Cleanup | Run `ruff check --select F401` and remove dead imports | dev |
| 🟢 Cleanup | Monitor executive_brief quality after pro→advanced downgrade | analyst |

---

*Generated by Arbiter (reviewer agent) — 2026-03-13 02:57 UTC*
*Previous audit: 2026-03-13 02:17 UTC*
