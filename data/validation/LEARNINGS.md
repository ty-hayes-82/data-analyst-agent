# Reviewer Audit Learnings (cron: reviewer-audit-001)

Date: 2026-03-11 02:33 UTC
Scope:
- `git log --oneline -10`
- `git diff HEAD~10..HEAD`
- `grep` audit for trade-data hardcoding
- unused-import spot check
- prompt character budget audit

## Commit window reviewed (last 10)
```
d7d59f0 feat: tighten brief prompts and prune unused datasets
6d04774 feat: tighten executive brief prompts and prune unused datasets
e3f256f Make tests warning-free; contract-driven validation config
53df441 fix: Windows-compatible Python venv path in run_manager
e523c18 feat: agent improvements — executive brief, narrative, report synthesis
f6fd8ec test: fix 7 failing tests — skip missing datasets, fix glob, update assertions
7b369d2 chore: tighten executive brief JSON prompt
5262234 chore(prompt): enforce strict executive brief json
c7f1839 fix: cross-platform path handling (Windows-safe)
ec9ace4 feat: real-time progress tracking in monitor view
```

## Code Review [HEAD~10..HEAD]

### Critical (must fix before merge)
- **`web/app.py:~109-144` — path traversal / arbitrary file read via dimension-values endpoint**
  - Endpoint: `GET /api/datasets/{dataset_id:path}/dimension-values/{column}`
  - Current behavior:
    - loads contract (`contract_loader.load_contract(dataset_id)`)
    - reads `data_source.file` from contract
    - resolves `full_path = (project_root / file_path).resolve()` and reads it
  - **Risk:** if a user can create/edit contracts via the web UI (and they can — see contract upload/save path), they can set `data_source.file` to `../../../../etc/passwd` (or any readable file on the host) and exfiltrate it via this API.
  - **Fix:** enforce an allowlisted root (e.g., `PROJECT_ROOT/data/` or `PROJECT_ROOT/data/uploads/` or `PROJECT_ROOT/data/public/`) and reject anything outside it. Use the same safe pattern already used elsewhere:
    - `full_path.relative_to(allowed_root)` (raise 400/404 on `ValueError`)

### Warning (fix soon)
- **`data_analyst_agent/sub_agents/executive_brief_agent/agent.py` — big “contract enforcement” surface area**
  - You added `_apply_section_contract()` + network/scoped section contracts and now “normalize” any LLM JSON into the required section list.
  - Good for renderer stability, but it can **silently drop** unexpected LLM sections/keys (and potentially hide model regressions).
  - Suggested follow-up: log when the contract normalization had to repair missing sections / rename content, so failures are visible.

- **`data_analyst_agent/sub_agents/executive_brief_agent/scope_utils.py` — hierarchy mapping now reads full CSV**
  - `_load_hierarchy_level_mapping()` now loads the dataset CSV via pandas to build parent→child maps.
  - Risk: on large datasets this is expensive during brief generation.
  - Suggested follow-up: ensure this is limited (usecols already helps) and consider caching per run/session (you added a module cache; make sure it can’t grow unbounded across different datasets).

- **`tests/e2e/test_adk_integration.py` now loosens assertions on report output**
  - Assertions changed from “must have report_markdown” to “any key containing ‘report’”.
  - Risk: tests may pass even if report generation regresses, as long as some unrelated key includes “report”.
  - Suggested follow-up: tighten to a clear contract (e.g., `report_markdown` OR `report_synthesis_result` only).

### Observations
- Good direction: converting trade-data synthetic validation flags (`scenario_id`, `anomaly_flag`) into **contract-driven** config (added `DatasetContract.validation` + contract fields in trade_data).
- Good direction: removing hardcoded hierarchy names (“Region”, “Terminal”) from markdown report section rendering.

## 2) Hardcoded trade-data assumptions (grep audit)
Command used:
```bash
grep -RIn "trade_value\|hs2\|hs4\|port_code\|region\|imports\|exports" data_analyst_agent/ --include="*.py" \
  | grep -v __pycache__ | grep -v -i test | grep -v contract.yaml
```

### Flagged (not clearly contract-driven)
- **`data_analyst_agent/utils/dimension_filters.py:14`**
  - Contains `_UNFILTERED` tokens including `"all regions"`, `"all terminals"`.
  - Not a crash risk, but it bakes trade/ops vocabulary into generic filter parsing. Prefer contract role labels (primary dimension / total label) where possible.

- **`data_analyst_agent/sub_agents/tableau_hyper_fetcher/fetcher.py:49`**
  - `_UNFILTERED` includes `"all regions"`, `"all terminals"`.
  - Same note as above.

### Likely acceptable (validation/test-only)
- **`data_analyst_agent/tools/validation_data_loader.py`**
  - Still uses `region`/`terminal` columns heavily. This is OK *if* this loader is strictly for the validation fixture dataset and not used in general contract-driven fetchers.

### Informational
- **`data_analyst_agent/sub_agents/narrative_agent/tools/generate_narrative_summary.py:101`**
  - Uses heuristic token checks `(region, country, market, geo)` to pick phrasing.
  - Heuristic-y, but not tied to trade_value/hs codes; low risk.

## 3) Unused imports (spot-check)
Method: AST scan of a few high-change files (expect false positives; ignore `from __future__ import annotations`).

High-confidence cleanup candidates:
- **`web/app.py`**
  - `import os` unused
  - `FileResponse` unused
  - `JSONResponse` unused
- **`web/run_manager.py`**
  - `import signal` unused

## 4) Prompt token efficiency (character budget audit)
Command used:
```bash
wc -c config/prompts/executive_brief.md \
  data_analyst_agent/sub_agents/narrative_agent/prompt.py \
  data_analyst_agent/sub_agents/report_synthesis_agent/prompt.py
```

Results (flag >3000 chars):
- **6134** `config/prompts/executive_brief.md` ✅ OVER 3000
- 1255 `data_analyst_agent/sub_agents/narrative_agent/prompt.py`
- **6022** `data_analyst_agent/sub_agents/report_synthesis_agent/prompt.py` ✅ OVER 3000

Recommendation:
- Now that executive brief output is schema-normalized in-code, you can likely cut `executive_brief.md` substantially (or split into `default` vs `verbose/debug` variant).
- Consider a similar compact/verbose split for report synthesis.

## 5) Dev-agent checklist (actionable)
1. **Security:** Fix dimension-values endpoint file-path allowlisting (`web/app.py`).
2. Replace hardcoded `"all regions"/"all terminals"` unfiltered tokens in generic utilities with contract-driven labels (or keep but fence behind dataset type).
3. Remove unused imports in `web/app.py` and `web/run_manager.py`.
4. Trim `executive_brief.md` + `report_synthesis_agent/prompt.py` under 3000 chars (or add env-controlled prompt variants).
5. Tighten e2e report assertions to a stricter state key contract (`report_markdown` OR `report_synthesis_result`).
