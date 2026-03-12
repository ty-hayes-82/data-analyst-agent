# Code Review — Last 10 Commits (HEAD~10..HEAD)
**Reviewer:** Arbiter | **Date:** 2026-03-12 | **Range:** `718723b..3792577`

## Scope Summary
13 files changed, 1150 insertions, 250 deletions. Focus: executive brief prompt optimization (51% token reduction), thinking budget tuning, section title enforcement moved to system instruction, test fixture updates.

---

## Critical (must fix before merge)

### 1. Hardcoded "Truck Count" aggregation logic
- **`data_analyst_agent/sub_agents/statistical_insights_agent/tools/stat_summary/period_totals.py:118`**
  ```python
  if denom_metric == "Truck Count" and "truck_count" in nd_df.columns ...
  ```
- **`data_analyst_agent/sub_agents/hierarchy_variance_agent/tools/level_stats/ratio_metrics.py:178`**
  ```python
  ratio_config.get("denominator_metric") == "Truck Count"
  ```
- **Issue:** These are dataset-specific hardcodes that will silently produce wrong results for any non-Swoop dataset. The new TODO comment at `period_totals.py:112-114` acknowledges this but doesn't fix it.
- **Fix:** Add an `aggregation_method` property to the contract metric schema. Read it at runtime instead of string-matching `"Truck Count"`.

---

## Warning (fix soon)

### 2. `regional_analysis` / `regional_distribution` hardcoded card tags
- **`report_synthesis_agent/tools/report_markdown/formatting.py:18`** — `"regional_analysis"` in ordered tag list
- **`report_synthesis_agent/tools/report_markdown/sections/insight_cards.py:34-39`** — tag matching logic uses hardcoded `{"regional_distribution", "hierarchy", "regional_analysis"}`
- **Issue:** These tags assume a "region" dimension exists. For datasets without regions, the narrative grouping logic silently skips these cards — not broken, but fragile and opaque.
- **Fix:** Make tag-to-dimension mapping contract-driven or at least document the fallback behavior.

### 3. `Recommended Actions` insights changed from optional to required — test updated but schema not enforced
- **`tests/unit/test_executive_brief_fallback.py`** — test now expects non-empty `insights` array for "Recommended Actions"
- **`config/prompts/executive_brief.md`** — prompt says "array of 2-3 action items (REQUIRED — cannot be empty array)"
- **Issue:** The JSON schema validation in the agent code should enforce `minItems: 2` on the Recommended Actions insights array. Currently only the prompt says it's required — the LLM can still return `[]` and pass validation.
- **Fix:** Add schema-level enforcement in the section contract validator, not just prompt instructions.

### 4. `executive_brief_optimized.md` added but appears unused
- **`config/prompts/executive_brief_optimized.md`** — 142 lines added
- **Issue:** No code references this file. If it's a candidate replacement, it should be wired up via `EXECUTIVE_BRIEF_PROMPT_VARIANT` or deleted.
- **Fix:** Either integrate it as a variant or remove it to avoid config drift.

---

## ADK Compliance

### Section title enforcement moved to system instruction ✅
- Previously injected in user message, now appended to system instruction (`instruction = instruction + section_title_enforcement`). This is correct for Gemini — system instructions carry more weight than user-turn text.
- **Minor concern:** The enforcement block is built *before* `_format_instruction()` for network briefs but *after* for scoped briefs. The ordering difference is cosmetic (both append to instruction) but inconsistent — could confuse future maintainers.

### Scoped brief retry budget reduced from 3 → 2 ✅
- Comment says "up to 2 attempts for scoped briefs" — sensible given scoped briefs are less prone to title drift.

---

## Prompt Token Efficiency

| File | Size (chars) | Status |
|------|-------------|--------|
| `config/prompts/executive_brief.md` | 12,337 | ⚠️ Over 3K (4x threshold) |
| `sub_agents/narrative_agent/prompt.py` | 2,791 | ✅ Under 3K |
| `sub_agents/report_synthesis_agent/prompt.py` | 6,022 | ⚠️ Over 3K (2x threshold) |

- **`executive_brief.md`** was reduced from ~18.8K → 12.3K (36% reduction, good progress). Still 4x the 3K target. The removal of examples and verbose instructions is the right direction — consider further cuts to the COMPARISON LANGUAGE and DIGEST HANDLING sections which have significant overlap with the WRITING STYLE section.
- **`report_synthesis_agent/prompt.py`** at 6K — review for redundant instructions.

---

## Unused Imports

**166 suspected unused imports** detected across the codebase. Most are:
- `from __future__ import annotations` (41 instances) — these are PEP 563 annotations, **not actually unused** (they change runtime behavior). **False positives — ignore.**
- `from typing import Optional/Dict/Any/List` — many of these ARE used in type hints that the AST scanner misses in string annotations mode. **Likely false positives given `__future__.annotations`.**

**Genuine suspects worth checking:**
- `data_analyst_agent/sub_agents/dynamic_parallel_agent.py:8` — `import time` (appears unused in method bodies)
- `data_analyst_agent/sub_agents/statistical_insights_agent/tools/detect_mad_outliers.py:27` — `from io import StringIO`
- `data_analyst_agent/sub_agents/statistical_insights_agent/tools/detect_change_points.py:30` — `from io import StringIO`
- `data_analyst_agent/sub_agents/statistical_insights_agent/tools/compute_outlier_impact.py:26` — `from scipy import stats`

**Recommendation:** Run `ruff check --select F401 data_analyst_agent/` for authoritative unused import detection rather than AST heuristics.

---

## Observations

1. **Good:** The prompt optimization work is well-structured — examples removed, redundant sections consolidated, token count tracked in commit messages.
2. **Good:** Moving section title enforcement from user message to system instruction is the right ADK pattern for Gemini models.
3. **Risk:** The `executive_brief_optimized.md` file looks like dead config. Track it or remove it.
4. **Pattern:** The codebase has a growing number of `# TODO` comments for contract-driven refactors (Truck Count, aggregation methods). These should become tracked issues, not code comments.
5. **Thinking budget:** Reducing from 16K → 14K tokens is a reasonable optimization. Monitor for quality regression in complex multi-metric scenarios.
