# Code Review — Reviewer Audit 2026-03-12

**Commit range:** `7dd5b39..87f3346` (last 10 commits)
**Scope:** 17 files changed, 69,424 insertions, 158 deletions

---

## Critical (must fix before merge)

_None identified._ Recent commits are docs, contract fixes, and executive brief refactoring — no data integrity or pipeline stability risks.

---

## Warning (fix soon)

### W1 — Hardcoded "regional_analysis" tag in report formatting
- `data_analyst_agent/sub_agents/report_synthesis_agent/tools/report_markdown/formatting.py:18` — `"regional_analysis"` is hardcoded in `_DERIVED_TAGS`
- `data_analyst_agent/sub_agents/report_synthesis_agent/tools/report_markdown/sections/insight_cards.py:34-39` — `"regional_distribution"`, `"regional_analysis"` hardcoded in tag matching
- **Risk:** These tags assume a "regional" dimension concept. For datasets like `us_airfare` (which uses route/carrier, not region), this logic is inert but creates dead code paths. Consider making tag categories contract-driven or at least documenting why these are universal.

### W2 — Prompt token bloat: `executive_brief.md` = 14,027 chars
- `config/prompts/executive_brief.md` — **14,027 chars** (threshold: 3,000)
- `data_analyst_agent/sub_agents/report_synthesis_agent/prompt.py` — **6,022 chars** (threshold: 3,000)
- `data_analyst_agent/sub_agents/narrative_agent/prompt.py` — **1,853 chars** ✅ (under threshold)
- **Impact:** At ~4 chars/token, `executive_brief.md` is ~3,500 tokens per invocation. On Gemini 2.5 at $10/M input tokens, that's ~$0.035/run — acceptable for production but worth watching. Consider extracting static formatting rules into a tool or system instruction to reduce per-call overhead.

### W3 — Massive unused import debt (130+ instances across codebase)
- **Most common:** `from __future__ import annotations` imported but unused in ~40 files (these are zero-cost at runtime but clutter the codebase)
- **Actually wasteful (real modules imported but never used):**
  - `data_analyst_agent/sub_agents/dynamic_parallel_agent.py:8` — `import time` (dead import)
  - `data_analyst_agent/sub_agents/statistical_insights_agent/tools/compute_new_lost_same_store.py:29` — `import numpy as np` (unused, wastes load time)
  - `data_analyst_agent/sub_agents/statistical_insights_agent/tools/stat_summary/per_item_metrics.py:6` — `import pandas as pd` (unused)
  - `data_analyst_agent/sub_agents/statistical_insights_agent/tools/compute_seasonal_decomposition.py:26` — `import numpy as np` (unused)
  - `data_analyst_agent/sub_agents/hierarchy_variance_agent/tools/compute_pvm_decomposition.py:28` — `import pandas as pd` (unused)
  - `data_analyst_agent/sub_agents/hierarchy_variance_agent/tools/compute_mix_shift_analysis.py:27` — `import pandas as pd` (unused)
  - `data_analyst_agent/sub_agents/hierarchy_variance_agent/tools/level_stats/hierarchy.py:6` — `import pandas as pd` (unused)
  - `data_analyst_agent/sub_agents/report_synthesis_agent/prompt.py:26` — `import os` (unused)
  - `data_analyst_agent/sub_agents/report_synthesis_agent/tools/export_pdf_report.py:44` — `from weasyprint import CSS` (unused, heavy import)
  - `data_analyst_agent/sub_agents/tableau_hyper_fetcher/fetcher.py:37` — `HyperConnectionManager` (unused)
  - `data_analyst_agent/semantic/quality.py:2` — `import numpy as np` (unused)
  - `data_analyst_agent/semantic/quality.py:5` — `QualityGateError` (unused)
  - `data_analyst_agent/semantic/models.py:6` — `ContractValidationError` (unused)
  - `data_analyst_agent/semantic/policies.py:2` — `List, Dict, Union` (all unused)
- **Recommendation:** Run `ruff check --select F401 data_analyst_agent/` and auto-fix with `ruff check --select F401 --fix`. This is a 5-minute cleanup that reduces import time and cognitive load.

---

## ADK Compliance

- ✅ Recent commits don't introduce new agents or modify agent wiring
- ✅ `severity_guard.py` (new, +123 lines) is a utility module, not an agent — no ADK pattern concerns
- ✅ No new global state or cross-agent communication patterns introduced

---

## Hardcoded Dataset Assumptions

Most `region`/`imports`/`exports` references are **safe** — they appear in:
- Comment strings and docstrings (`__main__.py`, `scope_utils.py`)
- Generic column mapping logic (`validation_data_loader.py` — maps from CSV headers)
- Narrative heuristics (`generate_narrative_summary.py:101` — checks if dimension *name* contains "region" to adjust phrasing)

**One concern:**
- `data_analyst_agent/sub_agents/report_synthesis_agent/tools/report_markdown/sections/insight_cards.py:34-35` — Hardcoded `{"regional_distribution", "regional_analysis"}` tag set. These come from the insight card builder, not from contract. If a dataset uses "zone" or "district" instead of "region," the narrative dedup logic won't fire. Low risk (fails safe — just shows slightly more cards) but should be documented or made contract-aware.

---

## Observations

1. **Recent commit quality is high.** The last 10 commits show disciplined work: separate test commits, proper contract schema updates for the new `us_airfare` dataset, and clean feature additions.
2. **69K+ insertions is mostly the new dataset.** The `us_airfare` contract and related data files account for the bulk — actual code changes are surgical.
3. **`annotations` imports everywhere.** The codebase consistently imports `from __future__ import annotations` for PEP 604 style hints, but many files don't actually use type hints. Not harmful but adds noise.
4. **No test regressions.** Executive brief fallback tests were updated alongside the feature change — good practice.
5. **Import cleanup is the highest-ROI action.** The `weasyprint.CSS` unused import is especially wasteful — weasyprint is heavy. Removing it avoids loading a C library that's never used in that code path.

---

*Generated by Arbiter (reviewer agent) — 2026-03-12 14:34 UTC*
