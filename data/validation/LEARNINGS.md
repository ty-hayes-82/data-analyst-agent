# Code Review — Last 10 Commits (HEAD~10..HEAD)
**Reviewer:** Arbiter | **Date:** 2026-03-12 20:56 UTC | **Range:** `0d3659b..714cc4e`

## Scope Summary
15 files changed, 1400 insertions, 153 deletions. Focus: executive brief validation hardening (section title enforcement via system instruction), prompt optimization (51% token reduction), narrative agent thinking budget reduction (16K→14K), hardcoded Truck Count assumption documented, docs/session logs.

---

## Critical (must fix before merge)

*None identified.* Recent commits are docs, prompt tuning, and validation improvements — no data-integrity or pipeline-breaking changes.

---

## Warning (fix soon)

### 1. Prompt Token Bloat — `executive_brief.md` (12,337 chars)
- **File:** `config/prompts/executive_brief.md` — 12,337 bytes (~3,100 tokens)
- Despite the 51% optimization in `37dcf7f`, the prompt is still 4× over the 3,000-char target.
- `report_synthesis_agent/prompt.py` is also large at 6,022 bytes.
- `narrative_agent/prompt.py` is fine at 2,791 bytes.
- **Action:** Further compress `executive_brief.md` — move static examples to few-shot config or external reference. Break `report_synthesis_agent/prompt.py` into base + section-specific fragments loaded on demand.

### 2. Massive Unused Import Debt (130+ instances)
Across `data_analyst_agent/`, there are **130+ unused imports**. Hotspots:
- **`from __future__ import annotations`** — ~50 files import this without using any forward-ref annotations. Harmless but noisy.
- **`from typing import Dict, Any, List, Optional`** — ~30 files import typing symbols that are never referenced.
- **Substantive unused imports (higher risk):**
  - `data_analyst_agent/sub_agents/statistical_insights_agent/tools/compute_new_lost_same_store.py:29` — `import numpy` (unused)
  - `data_analyst_agent/sub_agents/statistical_insights_agent/tools/compute_seasonal_decomposition.py:26` — `import numpy` (unused)
  - `data_analyst_agent/sub_agents/statistical_insights_agent/tools/stat_summary/per_item_metrics.py:6` — `import pandas` (unused)
  - `data_analyst_agent/sub_agents/statistical_insights_agent/tools/stat_summary/summary_enhancements.py:5` — `import numpy` (unused)
  - `data_analyst_agent/sub_agents/statistical_insights_agent/tools/compute_outlier_impact.py:26` — `from scipy import stats` (unused, heavy import)
  - `data_analyst_agent/sub_agents/hierarchy_variance_agent/tools/compute_pvm_decomposition.py:28` — `import pandas` (unused)
  - `data_analyst_agent/sub_agents/hierarchy_variance_agent/tools/compute_mix_shift_analysis.py:27` — `import pandas` (unused)
  - `data_analyst_agent/sub_agents/hierarchy_variance_agent/tools/level_stats/hierarchy.py:6` — `import pandas` (unused)
  - `data_analyst_agent/sub_agents/report_synthesis_agent/prompt.py:26` — `import os` (unused)
  - `data_analyst_agent/sub_agents/report_synthesis_agent/tools/export_pdf_report.py:44` — `from weasyprint import CSS` (unused, heavy)
  - `data_analyst_agent/sub_agents/tableau_hyper_fetcher/fetcher.py:37` — `from hyper_connection import HyperConnectionManager` (unused)
  - `data_analyst_agent/sub_agents/hierarchical_analysis_agent/agent.py:10` — `from decisions import DrillDownDecisionAgent` (unused)
  - `data_analyst_agent/sub_agents/hierarchy_variance_agent/tools/level_stats/materiality.py:6` — `from config.materiality_loader import get_thresholds_for_category` (unused)
  - `data_analyst_agent/semantic/quality.py:5` — `from exceptions import QualityGateError` (unused)
  - `data_analyst_agent/semantic/models.py:6` — `from exceptions import ContractValidationError` (unused)
- **Action:** Run `ruff check --select F401 data_analyst_agent/` or autofix with `ruff check --select F401 --fix`. The `from __future__` ones are low-priority; focus on the substantive pandas/numpy/scipy/weasyprint imports first — they add import latency to agent startup.

### 3. `report_synthesis_agent` Hardcoded Tag — "regional_analysis"
- **File:** `data_analyst_agent/sub_agents/report_synthesis_agent/tools/report_markdown/formatting.py:18`
- `_DERIVED_TAGS` includes `"regional_analysis"` as a hardcoded tag. This is a card-tag taxonomy, not a column name, so it's not a data-integrity risk — but if the dataset has no geographic dimension, the tag will never match and the logic is dead code.
- **File:** `data_analyst_agent/sub_agents/report_synthesis_agent/tools/report_markdown/sections/insight_cards.py:34-39`
- `has_regional_narrative` check uses `{"regional_distribution", "hierarchy", "regional_analysis"}` to suppress hierarchy drill-down cards. If the pipeline ever runs on non-geographic data, this gate does nothing (harmless but misleading).
- **Action:** Low priority. Consider making suppression tags configurable via contract metadata.

---

## ADK Compliance

- ✅ Recent commits don't introduce new agents or modify agent registration.
- ✅ `executive_brief_agent/agent.py` changes (152 lines modified) are validation/formatting logic, not agent lifecycle.
- ✅ No global variable abuse — session state patterns intact.
- ✅ `data_cache.py` sys.modules usage unchanged in this range.

---

## Hardcoded Assumptions Audit

Searched for `trade_value|hs2|hs4|port_code|region|imports|exports` across `data_analyst_agent/` (excluding tests and contracts):

| Pattern | Status |
|---------|--------|
| `region` in `validation_data_loader.py` | ✅ Column mapping from CSV headers — driven by data shape, not hardcoded assumption |
| `region` in `__main__.py` | ✅ CLI help text examples only (`--dimension region`) |
| `region` in `narrative_agent/tools/generate_narrative_summary.py:101` | ⚠️ Heuristic priority sorter — prefers geographic keys for display ordering. Not a data-integrity risk but bakes in geographic-first assumption. |
| `region` in `weather_context_agent/prompt.py` | ✅ LLM prompt context — agent is inherently geographic |
| `region` in `executive_brief_agent/scope_utils.py:322` | ✅ Docstring reference |
| `region` in `validation_csv_fetcher.py` | ✅ Filter parameter read from session state |
| `region` in `core_agents/cli.py` | ✅ Docstring example |
| `regional_*` tags in report_synthesis | ⚠️ See Warning #3 above |
| `imports`/`exports` keywords | ✅ Only in Python import statements, not trade-data references |
| `trade_value`, `hs2`, `hs4`, `port_code` | ✅ Zero matches — no hardcoded trade-specific column names |

**Verdict:** No critical hardcoded dataset assumptions found. The codebase is contract-driven for column names. Two minor geographic-preference heuristics noted.

---

## Commit Quality Assessment

| Commit | Quality | Notes |
|--------|---------|-------|
| `0d3659b` fix: section title enforcement → system instruction | ✅ Good | Correct Gemini compliance fix |
| `1bd8ff6` perf: reduce thinking budget 16K→14K | ✅ Good | Measurable perf gain |
| `37dcf7f` feat: optimize executive brief prompt (51%) | ✅ Good | Still over target but significant improvement |
| `d177e4c` docs: investigation findings | ✅ Docs | — |
| `ee5de71` docs: session report | ✅ Docs | — |
| `688f0bd` feat: enhance recommendations section | ✅ Good | — |
| `a3f36d9` docs: document Truck Count assumption | ✅ Good | Tech debt documented |
| `3792577` docs: session summary | ✅ Docs | — |
| `da51467` fix: stronger section title validation | ✅ Good | Defensive validation |
| `714cc4e` docs: session log | ✅ Docs | — |

**6/10 commits are docs/session logs.** This is healthy for an iteration cycle but signals the dev agent is spending significant context on documentation. No code-quality issues in the 4 substantive commits.

---

## Observations

1. **Import debt is the biggest hygiene issue.** 130+ unused imports across the codebase. The `from __future__ import annotations` ones are cosmetic, but unused `numpy`, `pandas`, `scipy.stats`, and `weasyprint.CSS` imports add real startup latency. A single `ruff --fix` pass would clean this up.

2. **Prompt size needs a strategy.** The executive brief prompt at 12K chars is the largest single prompt in the system. The 51% reduction was good progress but it's still the #1 token-cost driver per invocation. Consider: (a) structured JSON instruction format instead of prose, (b) moving examples to few-shot, (c) conditional sections loaded based on data shape.

3. **No test regressions in this range.** The test fixture update in `test_executive_brief_fallback.py` aligns with the validation changes. No new test gaps introduced.

4. **Session log volume.** 5 of 15 changed files are session logs/devlogs. These are useful for continuity but are growing the repo. Consider a `docs/sessions/` archive with `.gitignore` for anything older than 7 days, or move to a separate branch.
