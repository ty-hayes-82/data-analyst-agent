# Code Review — Last 10 Commits (HEAD~10..HEAD)
**Reviewer:** Arbiter | **Date:** 2026-03-12 21:16 UTC | **Range:** `ee5de71..00cb048`

## Scope Summary
13 files changed, ~1,428 insertions, ~139 deletions. Focus: executive brief section title enforcement hardening (retry → raise on mismatch), `insights_min_2` mode for Recommended Actions, prompt reinforcement in user messages, hardcoded Truck Count TODO documented.

---

## Critical (must fix before merge)

### 1. Hardcoded "Truck Count" Aggregation Logic — Not Contract-Driven
- **File:** `data_analyst_agent/sub_agents/statistical_insights_agent/tools/stat_summary/period_totals.py:118`
  ```python
  if denom_metric == "Truck Count" and "truck_count" in nd_df.columns ...
  ```
- Also: `hierarchy_variance_agent/tools/level_stats/ratio_metrics.py:178`
  ```python
  ratio_config.get("denominator_metric") == "Truck Count"
  ```
- **Impact:** Any dataset that doesn't use "Truck Count" as a denominator metric will silently skip the daily-average aggregation path. This is a **data integrity risk** — ratio metrics will compute wrong values for non-Swoop datasets.
- **Fix:** Add `aggregation_method: daily_average` to contract metric definitions. Read it from contract instead of string-matching metric names. The TODO at line 114 already documents this — time to execute.

### 2. Hardcoded "terminal" Fallbacks Throughout Pipeline
Multiple files fall back to `"terminal"` when the grain column is missing:
- `stat_summary/data_prep.py:146` — `grain_col ... else "terminal"`
- `compute_outlier_impact.py:136` — `index=grain_col ... else "terminal"`
- `ratio_metrics.py:277` — `gcol = grain_col ... else "terminal"`
- `ratio_metrics.py:185-207` — Multiple `if "terminal" in sub_df.columns` branches

**Impact:** Any dataset without a "terminal" column (e.g., trade data with ports/countries) will hit wrong fallback. These should read the contract's default grain dimension.
**Fix:** Use `get_default_grain_column(contract)` consistently (it already exists in `contract_summary.py:227`). Replace all bare `"terminal"` fallbacks.

---

## Warning (fix soon)

### 3. Prompt Token Bloat — 2 Files Over Budget
| File | Size | Budget | Over By |
|---|---|---|---|
| `config/prompts/executive_brief.md` | 12,337 chars | 3,000 | **4.1×** |
| `report_synthesis_agent/prompt.py` | 6,022 chars | 3,000 | **2.0×** |
| `narrative_agent/prompt.py` | 2,791 chars | 3,000 | ✅ Under |

- `executive_brief.md` is the worst offender at ~3,100 tokens per call. With retry logic (up to 3 attempts), worst case is ~9,300 prompt tokens burned on section title enforcement alone.
- **Fix:** Move static examples and forbidden-title lists to a separate reference file loaded only on retry. Base prompt should be ≤3,000 chars.

### 4. Executive Brief Retry Logic — Emoji-Heavy Prompt Engineering
- **File:** `executive_brief_agent/agent.py` (lines ~1016-1040)
- The section title enforcement block uses `⚠️⚠️⚠️` and `❌` emoji as prompt emphasis. This is fragile — different models tokenize emoji differently, and triple-emoji costs 6+ tokens for zero semantic benefit over caps/bold markdown.
- The enforcement text is duplicated in both system instruction AND user message (`section_title_reminder`). This wastes ~200 tokens per call.
- **Fix:** Single enforcement location (system instruction). Use `**CAPS**` not emoji. Remove `section_title_reminder` from user message — it's redundant.

### 5. Retry Logic Change — Silent Normalization Removed
- **File:** `executive_brief_agent/agent.py` (diff lines ~792-810)
- Old behavior: After exhausting retries, `_apply_section_contract()` would normalize wrong titles silently.
- New behavior: Raises `ValueError` after exhausting retries, triggering fallback.
- **This is better** (fail-fast over silent corruption), but verify the fallback path produces a valid brief. If the fallback also fails, the pipeline may crash without recovery.
- **Action:** Add a test that verifies the fallback path handles `ValueError` from `_llm_generate_brief` gracefully.

---

## ADK Compliance

### Section Contract Pattern ✅
The `_apply_section_contract()` function is a solid pattern — enforcing output structure via post-processing rather than trusting LLM output. The `insights_min_2` mode addition is clean.

### State Management ✅ 
No new state key conflicts introduced. Parallel agent isolation looks sound.

### Missing: Silent Failure Guards (ADK Learnings #1)
The retry loop in `_llm_generate_brief` has good logging but **no timeout**. If the LLM hangs on retry, the agent blocks forever. Add `asyncio.wait_for()` around the LLM call with a per-attempt timeout.

---

## Unused Import Debt — 78 Confirmed

**78 unused imports** (excluding `__future__.annotations` which are harmless). Top offenders:

| Module | Count | Types |
|---|---|---|
| `hierarchy_variance_agent/tools/` | 12 | `pd`, `Any`, `Dict`, `List`, `Tuple` |
| `statistical_insights_agent/tools/` | 22 | `Any`, `Dict`, `List`, `StringIO`, `np`, `scipy_stats` |
| `alert_scoring_agent/tools/` | 5 | `Any` |
| `semantic/` | 8 | `Optional`, `Dict`, `List`, `Union`, `np`, `QualityGateError` |
| `sub_agents/dynamic_parallel_agent.py` | 3 | `Any`, `List`, `time` |

**Risk:** Unused `numpy`/`pandas`/`scipy` imports add ~50-200ms to cold-start per module. In a 15-agent pipeline, this compounds.
**Fix:** Run `autoflake --remove-all-unused-imports --in-place -r data_analyst_agent/` or equivalent.

---

## Hardcoded Dataset Assumptions — Full Inventory

Matches for trade-data-specific terms NOT read from contract:

| Location | Term | Risk |
|---|---|---|
| `period_totals.py:118` | `"Truck Count"` | **Critical** — drives aggregation logic |
| `ratio_metrics.py:178` | `"Truck Count"` | **Critical** — drives dedup logic |
| `ratio_metrics.py:185-207` | `"terminal"` (7 refs) | **High** — hardcoded grain fallback |
| `data_prep.py:146` | `"terminal"` | **High** — hardcoded grain fallback |
| `compute_outlier_impact.py:136` | `"terminal"` | **High** — hardcoded grain fallback |
| `formatting.py:18` | `"regional_analysis"` | **Low** — tag name, dataset-agnostic |
| `insight_cards.py:35` | `"regional_distribution"` | **Low** — tag name, dataset-agnostic |
| `narrative_summary.py:101` | `"region"` token check | **Low** — heuristic for geographic narrative |

---

## Observations

1. **Commit quality is improving.** Recent commits are well-scoped (one concern per commit), with clear messages. The `docs:` prefix convention is consistent.
2. **The executive brief is the most actively iterated component** — 6 of 10 commits touch it. Consider stabilizing the section contract and reducing churn.
3. **The `insights_min_2` mode** for Recommended Actions is a good pattern — ensures the LLM generates actionable recommendations instead of placeholder text.
4. **Test coverage gap:** The `executive_brief_agent/agent.py` diff is significant (~80 lines changed) but only `test_executive_brief_fallback.py` was updated (11 lines). The retry→raise behavior change needs dedicated test coverage.
5. **README additions** (266 lines) are comprehensive — good for onboarding. Consider moving CLI/Web UI guides to `docs/` to keep README focused.

---

*Next audit scheduled: 2026-03-13 ~21:00 UTC*
