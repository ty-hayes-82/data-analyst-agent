# Code Review — Reviewer Audit 2026-03-12

**Commit range:** `770eeb8..b1b7a40` (last 10 commits)
**Test status:** 297 passed, 1 failed, 6 skipped
**Scope:** 247 files changed, +151K / -8K lines

---

## Critical (must fix before merge)

### 1. Failing test: `test_contract_hardcodes[trade_value_usd]`
- **File:** `data_analyst_agent/core_agents/loaders.py:255`
- **Issue:** The hardcodes test flags `trade_value_usd` in a *comment* (`# e.g., flow='trade_value_usd'`). Either the comment should be reworded to avoid the literal, or the test should exclude comments. Either way, the suite is red — fix before merge.
- **Action:** Remove or rephrase the comment on line 255 so `trade_value_usd` doesn't appear as a literal string. The test is correct to enforce this; comments still create grep-able coupling.

### 2. `executive_brief.md` prompt is 18,785 chars (~4,700 tokens)
- **File:** `config/prompts/executive_brief.md`
- **Issue:** This single prompt file is nearly 19KB. At ~4.7K tokens it burns significant context window on every executive brief generation. The prompt has grown 604 lines in this commit range.
- **Action:** Refactor into modular sections loaded on-demand, or trim redundant instructions. Target < 8KB.

---

## Warning (fix soon)

### 3. 130+ unused imports across the codebase
- **Severity:** Medium — bloats modules, confuses readers, triggers linter warnings
- **Worst offenders (non-`__future__` annotations):**
  - `data_analyst_agent/sub_agents/dynamic_parallel_agent.py:8` — unused `time`
  - `data_analyst_agent/sub_agents/statistical_insights_agent/tools/compute_new_lost_same_store.py:29` — unused `numpy`
  - `data_analyst_agent/sub_agents/statistical_insights_agent/tools/compute_outlier_impact.py:26` — unused `scipy.stats`
  - `data_analyst_agent/sub_agents/report_synthesis_agent/prompt.py:26` — unused `os`
  - `data_analyst_agent/sub_agents/report_synthesis_agent/tools/export_pdf_report.py:44` — unused `CSS` from weasyprint
  - `data_analyst_agent/sub_agents/hierarchy_variance_agent/tools/compute_pvm_decomposition.py:28` — unused `pandas`
  - `data_analyst_agent/sub_agents/hierarchy_variance_agent/tools/compute_mix_shift_analysis.py:27` — unused `pandas`
  - `data_analyst_agent/sub_agents/hierarchy_variance_agent/tools/level_stats/hierarchy.py:6` — unused `pandas`
  - `data_analyst_agent/sub_agents/hierarchy_variance_agent/tools/level_stats/materiality.py:6` — unused `get_thresholds_for_category`
  - `data_analyst_agent/sub_agents/statistical_insights_agent/tools/stat_summary/per_item_metrics.py:6` — unused `pandas`
  - `data_analyst_agent/sub_agents/hierarchical_analysis_agent/agent.py:10` — unused `DrillDownDecisionAgent`
  - `data_analyst_agent/sub_agents/tableau_hyper_fetcher/fetcher.py:37` — unused `HyperConnectionManager`
  - `data_analyst_agent/semantic/quality.py:5` — unused `QualityGateError`
  - `data_analyst_agent/semantic/models.py:6` — unused `ContractValidationError`
  - Plus ~50 unused `from __future__ import annotations` and ~30 unused typing imports (`Optional`, `Dict`, `Any`, `List`, `StringIO`)
- **Action:** Run `ruff check --select F401 --fix` or equivalent automated cleanup. The `from __future__ import annotations` ones are harmless but noisy; the real imports (`numpy`, `pandas`, `scipy.stats`, `weasyprint.CSS`) add unnecessary load time.

### 4. `report_synthesis_agent/prompt.py` is 6,022 chars (over 3K threshold)
- **File:** `data_analyst_agent/sub_agents/report_synthesis_agent/prompt.py`
- **Issue:** At 6KB, this prompt is borderline. Not as urgent as the 19KB executive brief, but worth trimming.
- **Action:** Review for redundant instructions; target < 4KB.

### 5. Hardcoded "regional" tag assumptions in report synthesis
- **Files:**
  - `data_analyst_agent/sub_agents/report_synthesis_agent/tools/report_markdown/sections/insight_cards.py:34-39`
  - `data_analyst_agent/sub_agents/report_synthesis_agent/tools/report_markdown/formatting.py:18`
- **Issue:** Tags like `"regional_analysis"`, `"regional_distribution"` are hardcoded strings that assume a regional dimension exists. For datasets without a regional dimension (e.g., bookshop, temperature), this logic is dead code at best, misleading at worst.
- **Action:** Derive grouping section tags from the contract's dimension hierarchy, not hardcoded strings.

### 6. 33 session summary MDs committed to git history
- **Issue:** Files like `SPRINT_COMPLETE.md`, `NIGHT_SHIFT_SUMMARY.md`, `DEV_ITERATE_001_SUMMARY.md` etc. were committed to the repo (visible in the 10-commit diff). They appear to have been moved to `docs/archive/session_logs/` (untracked) but the committed versions still bloat history.
- **Action:** Add `docs/archive/` to `.gitignore`. Session logs are agent workspace artifacts, not project source. Consider `git filter-branch` or BFG to remove from history if repo size matters.

---

## ADK Compliance

### Agent patterns — OK
- Custom agents correctly extend `BaseAgent` with `_run_async_impl`
- `output_key` values are descriptive and unique
- State access uses `.get()` with fallback handling
- `TimedAgentWrapper` is applied to measured stages
- Parallel agents write to isolated state keys

### Minor ADK notes
- `data_analyst_agent/sub_agents/hierarchical_analysis_agent/agent.py:10` imports `DrillDownDecisionAgent` but never uses it — suggests incomplete refactoring or dead code path
- `narrative_agent/tools/generate_narrative_summary.py:101` uses heuristic keyword matching (`"region", "country", "market", "geo"`) to detect geographic dimensions — fragile; should read dimension roles from contract instead

---

## Observations

1. **Massive commit range.** 151K lines added across 247 files in 10 commits. This is too large for meaningful per-commit review. Commits should be smaller and more focused. The Bookshop dataset alone added 57K lines of CSV data.

2. **Test coverage is solid.** 297 passing tests including new unit tests for contract hardcodes, severity guard, cumulative series, hierarchy filters, mix-shift analysis, and temporal grain. Good defensive testing.

3. **Contract-driven architecture is working.** The `week_ending` → contract-driven time column refactor (commit `6be435a`) is exactly the right pattern. More of this.

4. **Deployment scaffolding added.** Full GCP/Vertex AI deployment configs, Terraform, cloudbuild, monitoring. Good structure but should be validated with a dry-run deploy.

5. **`narrative_agent/prompt.py` at 2,791 chars** — under the 3K threshold, no action needed.

6. **The `from __future__ import annotations` pattern** is used pervasively but often not needed (no forward references in scope). Not harmful but adds noise — consider removing during the unused-import cleanup.

---

## Recommended Priority

| # | Item | Effort | Impact |
|---|------|--------|--------|
| 1 | Fix failing hardcodes test (comment rewording) | 5 min | Unblocks CI |
| 2 | Unused import cleanup (`ruff --select F401 --fix`) | 15 min | Code hygiene |
| 3 | Trim executive_brief.md prompt (19KB → <8KB) | 1-2 hr | Token cost savings |
| 4 | Replace hardcoded regional tags with contract-derived | 30 min | Dataset portability |
| 5 | Gitignore session summary MDs | 5 min | Repo hygiene |
| 6 | Trim report_synthesis prompt | 30 min | Minor token savings |

---

*Generated by Arbiter (reviewer agent) — 2026-03-12 18:52 UTC*
