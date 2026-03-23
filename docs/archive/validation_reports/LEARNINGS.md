# Code Review — 2026-03-17 17:33 UTC (Arbiter Audit)

**Commit range:** `dae6111..10ff2dc` (last 10 commits)  
**Scope:** 4 source files changed + 12 doc/config/test files, ~1693 insertions  
**Previous audit:** 2026-03-17 17:04 UTC (ff57120)

---

## Critical (must fix before merge)

_None._ No data integrity or pipeline-breaking issues detected.

---

## Warning (fix soon)

### 1. Unused imports — 22 real offenders (4th consecutive flag)

This has been flagged in every audit since 2026-03-13. Still unaddressed.

**High priority (imported heavy libraries doing nothing):**
- `data_analyst_agent/semantic/quality.py:2` — `import numpy` unused
- `data_analyst_agent/sub_agents/hierarchy_variance_agent/tools/compute_mix_shift_analysis.py:27` — `import pandas` unused
- `data_analyst_agent/sub_agents/hierarchy_variance_agent/tools/compute_pvm_decomposition.py:28` — `import pandas` unused
- `data_analyst_agent/sub_agents/hierarchy_variance_agent/tools/level_stats/hierarchy.py:6` — `import pandas` unused
- `data_analyst_agent/sub_agents/statistical_insights_agent/tools/compute_new_lost_same_store.py:29` — `import numpy` unused
- `data_analyst_agent/sub_agents/statistical_insights_agent/tools/compute_seasonal_decomposition.py:26` — `import numpy` unused
- `data_analyst_agent/sub_agents/statistical_insights_agent/tools/stat_summary/per_item_metrics.py:6` — `import pandas` unused
- `data_analyst_agent/sub_agents/statistical_insights_agent/tools/stat_summary/summary_enhancements.py:5` — `import numpy` unused
- `data_analyst_agent/sub_agents/statistical_insights_agent/tools/compute_outlier_impact.py:26` — `from scipy import scipy_stats` unused

**Medium priority (unused module-level imports):**
- `data_analyst_agent/sub_agents/dynamic_parallel_agent.py:8` — `import time` unused
- `data_analyst_agent/sub_agents/report_synthesis_agent/prompt.py:26` — `import os` unused
- `data_analyst_agent/sub_agents/report_synthesis_agent/tools/export_pdf_report.py:44` — `from weasyprint import CSS` unused
- `data_analyst_agent/sub_agents/tableau_hyper_fetcher/fetcher.py:37` — `from hyper_connection import HyperConnectionManager` unused

**Low priority (dead exception/IO imports):**
- `data_analyst_agent/semantic/models.py:6` — `from exceptions import ContractValidationError` unused
- `data_analyst_agent/semantic/quality.py:5` — `from exceptions import QualityGateError` unused
- `data_analyst_agent/sub_agents/statistical_insights_agent/tools/compute_derived_metrics.py:39` — `from io import StringIO` unused
- `data_analyst_agent/sub_agents/statistical_insights_agent/tools/compute_forecast_baseline.py:27` — `from io import StringIO` unused
- `data_analyst_agent/sub_agents/statistical_insights_agent/tools/compute_seasonal_decomposition.py:29` — `from io import StringIO` unused
- `data_analyst_agent/sub_agents/statistical_insights_agent/tools/detect_change_points.py:30` — `from io import StringIO` unused
- `data_analyst_agent/sub_agents/statistical_insights_agent/tools/detect_mad_outliers.py:27` — `from io import StringIO` unused

**Questionable top-level agent imports (may be intentional for ADK registration):**
- `data_analyst_agent/agent.py:79` — `from sub_agents.statistical_insights_agent.agent import statistical_insights_agent`
- `data_analyst_agent/agent.py:80` — `from sub_agents.hierarchical_analysis_agent import hierarchical_analysis_agent`
  - These _may_ be needed for ADK sub-agent registration even without explicit reference. Dev should verify.

### 2. Prompt token bloat — 2 of 3 files over threshold

| File | Size | Status |
|------|------|--------|
| `config/prompts/executive_brief.md` | 4,618 chars | ⚠️ Over 3,000 limit |
| `data_analyst_agent/sub_agents/report_synthesis_agent/prompt.py` | 6,022 chars | ⚠️ Over 3,000 limit (2x threshold) |
| `data_analyst_agent/sub_agents/narrative_agent/prompt.py` | 2,791 chars | ✅ Under limit |

`report_synthesis_agent/prompt.py` is the worst offender at 6KB. Consider extracting examples to a separate few-shot file or trimming redundant instructions.

`executive_brief.md` was flagged last audit — still over threshold.

---

## Hardcoded Dataset Assumptions

**Clean.** No hardcoded `trade_value`, `hs2`, `hs4`, or `port_code` references found in source. All dataset-specific column names route through contract YAML. The `region`/`imports`/`exports` hits in grep are all:
- Generic dimension classification logic (narrative_agent pattern matching)
- Docstring examples in CLI help text
- Comment references in validation_data_loader
- Report section tag names (e.g., `regional_analysis`)

No action needed.

---

## ADK Compliance — Recent Changes

### `executive_brief_agent/agent.py` (main change in this range)
- ✅ Forbidden section title set expanded (`Actions`, `Next Steps`) — good defensive pattern
- ✅ Pre-normalization validation added (check forbidden titles BEFORE auto-fix) — correct ordering
- ✅ Retry loop with fallback on max attempts — proper error handling
- ✅ Prompt instructions updated to match forbidden title list — keeps LLM and code in sync
- ⚠️ `FORBIDDEN_TITLES` set is duplicated in 3 locations (lines ~860, ~579, and in prompt strings at ~1117 and ~1436). Consider extracting to a module constant.

### `tableau_hyper_fetcher/query_builder.py`
- ✅ New `_qcol()` method always double-quotes column identifiers — fixes SQL injection risk from unquoted column names containing special characters
- ✅ Correctly handles already-quoted columns and escapes internal double-quotes

### `narrative_agent/agent.py` + `report_synthesis_agent/agent.py`
- ✅ `max_output_tokens` reduced 4096→2048 — good cost/latency improvement per previous audit recommendation

---

## Observations

1. **Audit compliance improving**: `max_output_tokens` reduction was acted on from prior audit. Forbidden title expansion shows iterative hardening.
2. **Unused imports are now a recurring theme** — 4 consecutive audits. Recommend dev agent batch-fixes these in one commit.
3. **Good test coverage in this range**: 4 new test files (754 lines) for Tableau Hyper support. Integration + unit coverage.
4. **FORBIDDEN_TITLES duplication** is a maintenance risk — when a new forbidden title is added, 3-4 locations must be updated manually.
5. **No new state management issues** — parallel agent keys remain isolated, session state access patterns are clean.
