# Code Review — 2026-03-13 (Arbiter Audit)

**Commit range:** `92aee99..acf7567` (10 commits)
**Scope:** 7 files changed, 875 insertions, 19 deletions

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

---

## Warning (fix soon)

### 3. `period_totals.py:123-135` — Fragile contract metric lookup
```python
denom_metric_config = next(
    (m for m in getattr(ctx.contract, "metrics", []) 
     if getattr(m, "name", "") == denom_metric),
    None
)
```
**Issue:** Good that this was made contract-driven (the original hardcoded `"Truck Count"` was removed). However, the fallback on exception is `pass` with `denom_needs_daily_avg = False`, which silently falls back to `sum` aggregation. If the contract is misconfigured, you get wrong numbers with no warning.

**Fix:** Log a warning when the metric isn't found in the contract. Add a state assertion in dev/test mode.

### 4. `agent.py:1168,1176` — Hardcoded example values in prompt enforcement blocks
```python
"- Vague references: \"significant increase\", \"multiple regions\"\n"
...
"The West region contributed $31.66M (32.6% of network variance)..."
```
**Issue:** The numeric enforcement examples reference "West region", "$31.66M", and other trade-data-specific values. These are baked into the prompt template, not dynamically generated from the actual dataset. This biases the LLM toward outputting trade-data-like language for any dataset.

**Fix:** Either make examples generic (no domain-specific entity names) or template them from session state / contract metadata.

### 5. Prompt token bloat — `executive_brief.md` at 7,843 chars
| File | Chars | Status |
|------|-------|--------|
| `config/prompts/executive_brief.md` | 7,843 | ⚠️ Over 3,000 limit (2.6×) |
| `report_synthesis_agent/prompt.py` | 6,022 | ⚠️ Over 3,000 limit (2.0×) |
| `narrative_agent/prompt.py` | 2,791 | ✅ Under limit |

The executive brief prompt *plus* the new inline numeric enforcement blocks (added in this batch) compound the token cost significantly. Every network brief LLM call now sends the 7.8K prompt + ~1.5K enforcement block + all the data context.

**Fix:** Consider extracting the numeric enforcement into a reusable few-shot template referenced by name, or move validation to post-processing only (you already have `_validate_structured_brief`).

### 6. `agent.py` — Duplicate enforcement blocks (network vs scoped)
Lines 1153–1187 and 1430–1462 contain near-identical numeric enforcement text, differing only in the threshold (3 vs 2 numeric values). This is ~60 lines of duplication.

**Fix:** Extract to a helper function: `_build_numeric_enforcement(min_values: int, is_scoped: bool) -> str`.

---

## ADK Compliance

- ✅ `_apply_section_contract` correctly normalizes LLM output post-hoc (good defensive pattern)
- ✅ `_validate_structured_brief` adds forbidden-title detection — good belt-and-suspenders
- ✅ `period_totals.py` now reads `aggregation_method` from contract (Production Learning #1 compliance)
- ⚠️ `ratio_metrics.py` still has 2 hardcoded TODOs — partial compliance only

---

## Unused Imports (cleanup)

**57 potentially unused imports detected.** Most are `from __future__ import annotations` (harmless) and `from typing import ...` (used as type hints in signatures, not at runtime). Notable actionable ones:

| File | Import | Action |
|------|--------|--------|
| `dynamic_parallel_agent.py:1` | `import time` | Remove if unused |
| `compute_new_lost_same_store.py:29` | `import numpy as np` | Verify usage |
| `detect_mad_outliers.py:27` | `from io import StringIO` | Verify usage |
| `detect_change_points.py:30` | `from io import StringIO` | Verify usage |
| `compute_forecast_baseline.py:27` | `from io import StringIO` | Verify usage |
| `compute_seasonal_decomposition.py:29` | `from io import StringIO` | Verify usage |
| `compute_derived_metrics.py:39` | `from io import StringIO` | Verify usage |
| `compute_outlier_impact.py:26` | `from scipy import stats` | Verify usage |

**Recommendation:** Run `pylint --disable=all --enable=W0611` or `ruff check --select F401` for definitive dead import detection.

---

## Observations

1. **Good trajectory:** The last 10 commits show a clear pattern of removing hardcoded assumptions and making things contract-driven. The `period_totals.py` change is a textbook fix.

2. **ratio_metrics.py is the last holdout:** It's the only file still gating logic on literal metric names (`"Truck Count"`). Both TODOs should be addressed before this pattern is forgotten.

3. **Prompt engineering arms race:** The numeric enforcement blocks are a workaround for LLM non-compliance. This adds token cost on every call. Consider whether the post-hoc validation in `_validate_structured_brief` is sufficient alone — if validation catches and retries, you may not need the verbose in-prompt enforcement.

4. **4 doc files in 10 commits:** `DEVLOG`, `DEV_ITERATION`, `DEV_ITERATION_REPORT`, `DEV_SESSION` — that's a lot of session logging. Consider consolidating to one format.

---

*Generated by Arbiter (reviewer agent) — 2026-03-13 02:17 UTC*
