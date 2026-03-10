# Reviewer Audit Learnings (cron: reviewer-audit-001)

Date: 2026-03-10 17:33 UTC
Scope:
- `git log --oneline -10`
- `git diff HEAD~10..HEAD`
- Targeted audits: trade-data hardcoding grep, unused imports spot-check, prompt size budgets

## Commit window reviewed (last 10)
```
4c5301e docs: comprehensive README with usage guide and public dataset examples
51ab4e5 security: remove proprietary CSV data (P&L revenue, ops metrics)
0c6fd93 chore: sync validation scoreboard, learnings, and brief prompt
fd1a976 test: sync incremental narrative keywords with contract
df93ed2 test: align narrative assertions with contract terms
29972f3 fix: backfill missing insight titles for executive brief
8b6fab6 feat: enhance contract detector currency/percent and hierarchies
c9b7f64 feat: surface analysis focus in narrative and brief
a65c8df feat: wire analysis focus into planner and stats
b911c8c feat: persist analysis focus directives in state
```

## 1) Quality review of changes (HEAD~10..HEAD)

### Critical (must fix before merge)
- None found in this commit range.

### Warnings (fix soon)
- **`data_analyst_agent/sub_agents/executive_brief_agent/agent.py`**
  - The file gained substantial responsibility in this range (schema definition, backfilling logic, scope label derivation, focus injection, LLM invocation config).
  - Risk: merge conflicts + brittle future changes. Also increases the chance of subtly breaking executive-brief output parsing.
  - Action: split into small modules (e.g., `schema.py`, `title_backfill.py`, `focus_directives.py`) so future edits stay localized.

- **`data_analyst_agent/core_agents/cli.py`**
  - `analysis_focus` + `custom_focus` are now always written into session state, even when empty.
  - Risk: can clobber focus directives set earlier in the session (e.g., web UI / previous agents) depending on pipeline order.
  - Action: confirm intended precedence. If CLI should only set when env values exist, restore conditional behavior.

- **Executive brief contract enforcement is now stricter**
  - `config/prompts/executive_brief.md` added “Structured JSON Contract (MANDATORY)” and the executive brief agent now sets `response_mime_type="application/json"` + `response_schema=...`.
  - Good direction, but keep in mind: schema enforcement can cause hard failures (or silent truncation) if the model struggles with long prompts or mismatched constraints.
  - Action: ensure there’s a robust fallback path when JSON schema validation fails (log + retry with a minimal schema or lower verbosity).

## 2) Hardcoded trade-data assumptions (must be contract-driven)

Command used:
```bash
grep -RIn "trade_value\|hs2\|hs4\|port_code\|region\|imports\|exports" data_analyst_agent/ --include="*.py" \
  | grep -v __pycache__ | grep -v -i test | grep -v contract.yaml
```

### Flagged (not clearly reading from contract)
- **`data_analyst_agent/sub_agents/executive_brief_agent/scope_utils.py:281-287`**
  - `_filter_alerts_for_scope()` reads `alert.get("region")` directly.
  - Risk: `region` is dataset-specific; alerts for other datasets may not carry this field. This can break scoped brief generation (false negatives when filtering) or implicitly bias toward trade/ops schema.
  - Fix: make scope filtering contract-driven. Options:
    - Use the contract’s primary geo dimension name (if role metadata exists) and look for that key in alerts.
    - Prefer generic alert fields (`dimension`, `dimension_value`, `item_name`) rather than `region`.

### Probably OK (but confirm they stay validation-only)
- **`data_analyst_agent/tools/validation_data_loader.py`**
  - Contains explicit `region`/`terminal` semantics and output columns. Acceptable *only if* used exclusively for validation fixtures.
- **`data_analyst_agent/sub_agents/validation_csv_fetcher.py`**
  - Reads primary dimension filters (region/terminal) and has `_UNFILTERED` strings like “all regions/all terminals”. Again OK if locked to validation modes.

### Informational / low risk
- **`data_analyst_agent/sub_agents/narrative_agent/tools/generate_narrative_summary.py`**
  - Uses token checks like `("region", "country", "market", "geo")` to infer geo-related phrasing. This is heuristic-y but not strongly trade-specific.
- **`data_analyst_agent/utils/dimension_filters.py` + `tableau_hyper_fetcher/fetcher.py`**
  - Contain strings like “all regions”. Consider moving toward role-based terms (primary dimension) where possible, but not urgent.

## 3) Unused imports (spot-check)

Request asked for a lightweight scan. There is no `ruff` in env, so I ran a simple AST heuristic (expect false positives, especially for typing and re-exports). Below are **high-confidence** candidates worth cleaning:

- **`data_analyst_agent/sub_agents/executive_brief_agent/agent.py`**
  - `from datetime import timezone` appears unused.
  - `from .prompt_utils import _format_brief` appears unused (only fallback formatter is referenced).

- **`data_analyst_agent/sub_agents/report_synthesis_agent/prompt.py`**
  - `import os` appears unused.

- **`data_analyst_agent/sub_agents/statistical_insights_agent/tools/stat_summary/data_prep.py`**
  - `import numpy as np` appears unused.

- **`web/contract_detector.py`**
  - `import math` appears unused.
  - `from collections import Counter, defaultdict` appear unused.

Note: the heuristic flags many `typing` imports across the tree; treat those as low-confidence unless you manually confirm.

## 4) Prompt token efficiency (character budget audit)

Command used:
```bash
wc -c config/prompts/executive_brief.md \
      data_analyst_agent/sub_agents/narrative_agent/prompt.py \
      data_analyst_agent/sub_agents/report_synthesis_agent/prompt.py
```

Results (flagging any > 3000 chars):
- **10884** `config/prompts/executive_brief.md`  ✅ OVER BUDGET
- 1880 `data_analyst_agent/sub_agents/narrative_agent/prompt.py`
- **6022** `data_analyst_agent/sub_agents/report_synthesis_agent/prompt.py` ✅ OVER BUDGET

Actions:
- Consider moving long examples / “MANDATORY” policy text into an *optional variant* (env-controlled) so the default prompt stays compact.
- Prefer schema-driven instructions + minimal rubric; long prose rules are expensive and often redundant once `response_schema` is enforced.

## 5) Dev-agent checklist (actionable)
1. Refactor scoped brief filtering to stop reading `alert.region` directly; make it contract-driven or rely on generic alert fields.
2. Remove the high-confidence unused imports listed above.
3. Confirm whether CLI focus injection should overwrite previously-set focus directives; if not, gate on env presence.
4. Trim `executive_brief.md` + `report_synthesis_agent/prompt.py` to <3000 chars (or implement prompt variants).

---

## Regression — 2026-03-10 17:58 UTC (cron: tester-e2e-001)
- **Command:** `python -m pytest tests/ --tb=short -q`
- **Result:** 2 failures (`tests/unit/test_statistical_insights_tools.py::test_compute_statistical_summary_ops_metrics`, `tests/unit/test_statistical_insights_tools.py::test_detect_mad_outliers_ops_metrics`)
- **Root cause:** Both tests load `data/ops_metrics_line_haul_sample.csv` / `data/ops_metrics_067_sample.csv`, which were removed in commit `51ab4e5` (“security: remove proprietary CSV data”). The fixtures now raise `FileNotFoundError`.
- **Minimal repro:**
  ```bash
  cd /data/data-analyst-agent
  python -m pytest tests/unit/test_statistical_insights_tools.py -k ops_metrics -vv
  ```
- **Next steps:** Restore sanitized sample CSVs in `data/` (or update fixtures to rely on public mock data) so ops-metrics statistical insight tests can run without proprietary files.
