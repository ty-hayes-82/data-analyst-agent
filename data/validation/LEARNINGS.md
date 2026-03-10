# Reviewer Audit Learnings (cron: reviewer-audit-001)

Date: 2026-03-10 19:21 UTC
Scope:
- `git log --oneline -10`
- `git diff HEAD~10..HEAD`
- Targeted audits: trade-data hardcoding grep, unused imports spot-check, prompt size budgets

## Commit window reviewed (last 10)
```
7b369d2 chore: tighten executive brief JSON prompt
5262234 chore(prompt): enforce strict executive brief json
c7f1839 fix: cross-platform path handling (Windows-safe)
ec9ace4 feat: real-time progress tracking in monitor view
0671a28 chore: sync validation scoreboard and learnings
f6bc9b0 fix: proper error handling in submitRun and dataset loading
8182510 fix: inject missing hierarchy editor JS functions
34a5edd feat: hierarchy editing and dimension filtering in web UI
4c5301e docs: comprehensive README with usage guide and public dataset examples
51ab4e5 security: remove proprietary CSV data (P&L revenue, ops metrics)
```

## Code Review [HEAD~10..HEAD]

### Critical (must fix before merge)
- **`web/app.py` (dimension values endpoint)**
  - The new endpoint `/api/datasets/{dataset_id}/dimension-values/{column}` resolves `data_source.file` from the contract to a filesystem path and reads it.
  - It currently does:
    - `project_root = Path(__file__).resolve().parent.parent`
    - `full_path = (project_root / file_path).resolve()`
    - then reads the file if it exists.
  - **Risk:** if contracts can be created/edited via the Web UI (human-in-the-loop detector), a malicious or mistaken contract could set `file: ../../../../etc/passwd` (or any readable host path). This becomes an arbitrary file read via API.
  - **Fix:** enforce that `full_path` is inside an allowlisted directory (e.g., `project_root / "data"` or `project_root / "data/public"`) using `full_path.relative_to(allowed_root)` (same pattern as you already applied in `web/contract_loader.py` and `web/run_manager.py`). Reject otherwise.

### Warning (fix soon)
- **`config/prompts/executive_brief.md`**
  - Prompt is still large (see §4). Given you now enforce JSON output via schema + mime type, a lot of the prose policy is redundant and expensive.
  - Action: create a compact “default” prompt + an env-controlled “debug/verbose” variant for experimentation.

- **`web/static/app.js`**
  - `pollRun()` interval reduced to **2000ms** and it now fetches 3 endpoints every tick (`run`, `log`, `progress`).
  - Risk: unnecessary load on slower VPS deployments or multiple concurrent users.
  - Action: consider exponential backoff or longer interval once the run passes early stages (or only fetch `progress` every N ticks).

- **`data_analyst_agent/core_agents/cli.py`**
  - `hierarchy_filters` is written into `request_analysis` unconditionally (even when empty). Probably fine, but similar state precedence issues as focus directives: confirm that later injectors aren’t overwriting earlier state unintentionally.

### Observations
- Nice security hardening patterns were added in `web/contract_loader.py` and `web/run_manager.py` using `Path.relative_to()` checks. Reuse that exact pattern in the new dimension-values endpoint.
- The hierarchy editor + filters feature is useful, but it adds multiple new cross-cutting state keys (`custom_hierarchy_levels`, `hierarchy_filters`). Add a short “session state contract” note somewhere so downstream agents don’t silently depend on optional keys.

## 2) Hardcoded trade-data assumptions (grep audit)
Command used:
```bash
grep -RIn "trade_value\|hs2\|hs4\|port_code\|region\|imports\|exports" data_analyst_agent/ --include="*.py" \
  | grep -v __pycache__ | grep -v -i test | grep -v contract.yaml
```

### Critical / contract-noncompliant
- **`data_analyst_agent/sub_agents/executive_brief_agent/scope_utils.py:281-282`**
  - `_filter_alerts_for_scope()` reads `alert.get("region")` directly.
  - **Risk:** dataset-specific. For non-trade datasets (or any dataset whose geo dimension isn’t literally `region`), scoped briefs may filter incorrectly.
  - **Fix:** drive scope matching off the contract’s dimension roles (preferred) or off generic alert fields (e.g., `dimension`, `dimension_value`, `entity`, `item_name`). Avoid fixed keys like `region`.

### Likely acceptable (validation-only, but keep it fenced)
- **`data_analyst_agent/tools/validation_data_loader.py`**
  - Uses `region`/`terminal` strongly (schema: `region, terminal, metric, week_ending, value`).
  - OK if this stays strictly in validation/test paths; document as such and ensure it’s not used in general contract-driven pipelines.

- **`data_analyst_agent/sub_agents/validation_csv_fetcher.py`**
  - Reads optional `region`/`terminal` filters and has `_UNFILTERED` values including `"all regions"`.
  - Same note: OK if validation-only.

### Informational (heuristics / wording)
- **`data_analyst_agent/sub_agents/narrative_agent/tools/generate_narrative_summary.py:101`**
  - Checks tokens like `(region, country, market, geo)` to select language.
  - Heuristic-y but not truly trade-specific.

- **`data_analyst_agent/sub_agents/tableau_hyper_fetcher/fetcher.py:49`** and **`data_analyst_agent/utils/dimension_filters.py:14`**
  - Include strings like `"all regions"` / `"all terminals"`.
  - Prefer role-based naming long term, but not a release blocker.

## 3) Unused imports (spot-check)
Approach: lightweight AST-based scan over python files changed in `HEAD~10..HEAD` (expect false positives for typing-only imports). High-confidence candidates:

- **`data_analyst_agent/core_agents/loaders.py`**
  - `import json` inside `AnalysisContextInitializer._run_async_impl()` appears unused (near the top of that method).

- **`web/app.py`**
  - `import os` unused.
  - `FileResponse` and `JSONResponse` imported but not referenced in the file.

- **`web/run_manager.py`**
  - `import signal` unused.

## 4) Prompt token efficiency (character budget audit)
Command used:
```bash
wc -c config/prompts/executive_brief.md \
      data_analyst_agent/sub_agents/narrative_agent/prompt.py \
      data_analyst_agent/sub_agents/report_synthesis_agent/prompt.py
```

Results (flagging any > 3000 chars):
- **5563** `config/prompts/executive_brief.md` ✅ OVER 3000
- 1880 `data_analyst_agent/sub_agents/narrative_agent/prompt.py`
- **6022** `data_analyst_agent/sub_agents/report_synthesis_agent/prompt.py` ✅ OVER 3000

Recommendations:
- Executive brief: since you now enforce strict JSON/schema, trim repeated rubric text and move examples into an optional variant.
- Report synthesis: reduce redundancy and prefer schema-driven constraints over long prose rules.

## 5) Dev-agent checklist (actionable)
1. **Fix the arbitrary file read risk** in `web/app.py` dimension-values endpoint by enforcing the contract `data_source.file` path stays under an allowlisted directory.
2. Refactor scoped brief filtering to stop reading `alert.region` directly; make it contract-driven or rely on generic alert fields.
3. Remove the high-confidence unused imports listed in §3.
4. Reduce prompt sizes for `executive_brief.md` and `report_synthesis_agent/prompt.py` (or implement env-controlled prompt variants) to get under 3000 chars.


## Regression Log — 2026-03-10 19:40 UTC
- Trigger: tester-e2e-001 cron full-suite run
- Result: `python -m pytest tests/ --tb=short -q` exited with 7 failures (baseline expected 236 pass / 0 fail)
- Root Cause Summary:
  - Public dataset v2 tests (`tests/e2e/test_public_datasets_v2.py`) fail for covid_us_counties_v2, co2_global_regions, worldbank_population_regions because their `config/datasets/csv/*/contract.yaml` files are missing after recent cleanup (FileNotFoundError).
  - Contract-to-context integration guard (`tests/integration/test_contract_to_context_flow.py::test_all_contracts_loadable`) now sees zero dataset contract files under `config/datasets`, asserting `len(contract_files) >= 3`.
  - Dataset resolver unit tests (`tests/unit/test_012_dataset_resolver.py`) expect ops_metrics contracts to exist; removing proprietary datasets now throws FileNotFoundError and trips folder-count assertion.
  - Aggregate-then-derive unit test (`tests/unit/test_025_aggregate_then_derive.py::test_statistical_summary_additive_metric_unchanged`) loads `validation_ops` contract, which was deleted.
- Action Needed:
  1. Decide whether public dataset contracts should be bundled in this workspace; if so, restore CSV contracts under `config/datasets/csv/`.
  2. Update dataset resolver + integration tests to tolerate trade_data-only environments (e.g., guard with `pytest.skip` when optional datasets absent) or adjust fixture expectations.
  3. Provide replacement validation contracts for ops_metrics/validation_ops or refactor tests to rely on trade_data fixtures instead.

## Regression Log — 2026-03-10 19:45 UTC
- Trigger: cron tester-e2e-001 full-suite run (`python -m pytest tests/ --tb=short -q`)
- Result: 7 failed / 213 passed / 28 skipped (baseline expected >=236 pass, 0 fail)
- Root Cause Summary:
  1. **Report synthesis agent crash** – `MAX_STATS_TOP_DRIVERS` is referenced in `report_synthesis_agent/agent.py` but only `_MAX_STATS_TOP_DRIVERS` is defined. This NameError bubbles up as missing `report_markdown`, causing `tests/e2e/test_adk_integration.py::{test_target_analysis_pipeline_accumulates_state,test_root_agent_run_async_completes_with_report_and_alerts}` to fail.
  2. **Missing public dataset contracts** – `config/datasets/csv/{covid_us_counties_v2,co2_global_regions,worldbank_population_regions}/contract.yaml` no longer exist. Related v2 smoke tests and `tests/integration/test_contract_to_context_flow.py::test_all_contracts_loadable` fail with FileNotFoundError / len(contract_files == 0).
  3. **Validation contract removed** – `config/datasets/validation_ops/contract.yaml` was deleted; `tests/unit/test_025_aggregate_then_derive.py::test_statistical_summary_additive_metric_unchanged` now fails trying to load it.
- Follow-up Needed:
  - Reintroduce or stub the missing contract files, or mark dependent tests `xfail/skip` when datasets are intentionally absent.
  - Fix the report synthesis constant typo so pipeline emits `report_markdown` again.
