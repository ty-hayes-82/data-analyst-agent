# Reviewer Audit Learnings — 2026-03-10

Scope: last 10 commits (`HEAD~10..HEAD`). Focused on: regression risk, contract compliance, trade-data hardcoding, unused imports, and prompt token efficiency.

## 1) Last 10 commits — quality review
Commits:
- 5befeb3 test: sync incremental narrative keywords with contract
- da3329d test: align narrative assertions with contract terms
- a4b2448 fix: backfill missing insight titles for executive brief
- 5ceb9d4 feat: enhance contract detector currency/percent and hierarchies
- d442d14 feat: surface analysis focus in narrative and brief
- a13ea9d feat: wire analysis focus into planner and stats
- 3bb30d8 feat: persist analysis focus directives in state
- b2b4dbe feat: contract-aware alert extraction
- 246cece refactor: contract-driven narrative dimension hints
- b346924 fix: enable csv datasets and harden exec brief

### Critical (must fix before merge)
None found in this commit range.

### Warnings (fix soon)
- **`data_analyst_agent/sub_agents/executive_brief_agent/agent.py`**
  - File grew by ~179 LOC in this range and is trending “monolith-y”. The new helpers are useful (schema, title backfills, scope labels), but this file is now doing *prompt rendering + schema definition + post-processing + scope logic*.
  - Action: consider splitting (e.g., `schema.py`, `title_backfill.py`, `instruction_format.py`) to reduce merge-conflict risk.

- **`data_analyst_agent/core_agents/cli.py`**
  - `analysis_focus`/`custom_focus` are now always written into session state (even empty), whereas previously they were conditionally set. That’s probably fine, but it changes behavior for runs where upstream has populated focus earlier and CLI injector runs later.
  - Action: confirm the intended precedence. If CLI should not clobber pre-set focus, gate updates on env presence.

- **`data_analyst_agent/sub_agents/statistical_insights_agent/tools/stat_summary/data_prep.py` + `.../anomaly_signals.py` + `.../result_builder.py`**
  - Focus directives now influence statistical thresholds (e.g., z-threshold, focus_periods). Good capability, but it is easy to make results unstable across runs if focus inputs are noisy.
  - Action: ensure focus settings are deterministic for a given request (normalize list already added—good) and add guardrails (min/max bounds).

### Observations
- Contract-aware dimension labeling work is headed in the right direction:
  - `extract_alerts_from_analysis(..., contract=...)` now uses contract-derived dimension labels and target display names.
  - Narrative summary builder now uses contract dimensions/hierarchies where available, with dataset-agnostic fallback heuristics.

## 2) Hardcoded trade-data assumptions (grep audit)
Command used:
`grep -RIn "trade_value|hs2|hs4|port_code|region|imports|exports" data_analyst_agent/ --include="*.py" | grep -v __pycache__ | grep -v -i test`

### Flagged items (not clearly contract-driven)
- **`data_analyst_agent/sub_agents/executive_brief_agent/scope_utils.py`**
  - `_filter_alerts_for_scope()` checks `alert.get("region")` directly.
  - Risk: assumes alerts have a `region` field (trade/ops-specific). For other datasets, this should be derived from contract dimension roles / the alert’s `dimension_value` / `item_name` conventions.
  - Action: refactor to be contract-driven (e.g., look up primary dimension name from contract; or avoid dimension-specific fields entirely).

- **`data_analyst_agent/sub_agents/validation_csv_fetcher.py`** (validation-only path)
  - Uses `primary_dimension` default of `"terminal"` and filters `region/terminal` explicitly.
  - This is acceptable *if and only if* it is strictly scoped to the `validation_ops` dataset mode. Document that it is intentionally dataset-specific and not used for general contract-driven datasets.

- **`data_analyst_agent/tools/validation_data_loader.py`** (validation-only path)
  - Hardcodes `_ID_COLS = ["Region", "Terminal", "Metric"]` and output columns `region/terminal/metric/week_ending/value`.
  - Again, acceptable if confined to validation CSV support, but it is not contract-driven.

### Likely acceptable / informational
- `data_analyst_agent/__main__.py` includes example CLI usage with `--dimension region`.
- `data_analyst_agent/utils/dimension_filters.py` contains phrases like “all regions”. (If this is intended to be dataset-agnostic, consider making it role-based rather than name-based.)

## 3) Unused imports (spot check)
No linter is installed (ruff/pyflakes not available), so I ran a small AST-based heuristic on *changed files only*.

### High-confidence unused imports
- **`data_analyst_agent/sub_agents/executive_brief_agent/agent.py`**
  - `from datetime import timezone` appears unused.
  - `from prompt_utils import _format_brief` appears unused (but `_format_brief_with_fallback` is used).

- **`data_analyst_agent/sub_agents/statistical_insights_agent/tools/stat_summary/data_prep.py`**
  - `import numpy as np` appears unused.

- **`web/contract_detector.py`**
  - `import math` appears unused.
  - `from collections import Counter, defaultdict` appear unused.

Note: `from __future__ import annotations` was flagged by the heuristic as “unused” but that’s a false positive; it is fine.

## 4) Prompt token efficiency (character budget audit)
Command used:
`wc -c config/prompts/executive_brief.md data_analyst_agent/sub_agents/narrative_agent/prompt.py data_analyst_agent/sub_agents/report_synthesis_agent/prompt.py`

Results (flagging any > 3000 chars):
- **10884** `config/prompts/executive_brief.md`  ✅ FLAG (over 3000)
- 1880 `data_analyst_agent/sub_agents/narrative_agent/prompt.py`
- **6022** `data_analyst_agent/sub_agents/report_synthesis_agent/prompt.py` ✅ FLAG (over 3000)

Actions:
- Executive brief prompt is very long; consider extracting repeated policy text into a compact rubric, or moving large static examples into a “debug variant” controlled by env (`EXECUTIVE_BRIEF_PROMPT_VARIANT`).
- Report synthesis prompt similarly: remove redundant instructions, and prefer short schema-driven guidance where possible.

## 5) Suggested next actions (dev agent checklist)
1. Remove unused imports (agent.py timezone + _format_brief; data_prep numpy; contract_detector math/Counter/defaultdict).
2. Make `scope_utils.py` stop reading `alert.region` directly; use contract-driven dimension semantics or generic `dimension_value`.
3. Decide precedence rules for `analysis_focus/custom_focus` injection in `CLIParameterInjector` (avoid clobbering upstream state if unintended).
4. Reduce prompt sizes for `executive_brief.md` and `report_synthesis_agent/prompt.py` (target <3000 chars each).
