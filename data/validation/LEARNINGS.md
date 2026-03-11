# Reviewer Audit Learnings (cron: reviewer-audit-001)

Date: 2026-03-11 06:13 UTC

Scope:
- `git log --oneline -10`
- `git diff HEAD~10..HEAD`
- hardcoded trade-data assumptions grep audit
- unused-import spot check (lightweight AST heuristic)
- prompt character budget audit

## Commit window reviewed (last 10)
```
0906ddd chore: tighten executive brief prompt schema
935b80a feat: tighten executive brief schema and prompt budget
f1cec20 feat: harden brief prompt and trim synthesis payloads
07589d9 feat: tighten executive brief pipeline
d7d59f0 feat: tighten brief prompts and prune unused datasets
6d04774 feat: tighten executive brief prompts and prune unused datasets
e3f256f Make tests warning-free; contract-driven validation config
53df441 fix: Windows-compatible Python venv path in run_manager
e523c18 feat: agent improvements — executive brief, narrative, report synthesis
f6fd8ec test: fix 7 failing tests — skip missing datasets, fix glob, update assertions
```

## Code Review [HEAD~10..HEAD]

### Critical (must fix before merge)
- **`web/app.py` — contract-controlled file path can become arbitrary file read (dimension-values endpoint)**
  - Endpoint pattern: `GET /api/datasets/{dataset_id:path}/dimension-values/{column}`
  - Current flow: loads contract for `dataset_id`, reads `data_source.file` from that contract, then reads that CSV to compute distinct dimension values.
  - If the web UI can upload/edit contracts (it can), an attacker can set `data_source.file` to `../../../../etc/passwd` (or any readable host file) and exfiltrate it via this endpoint.
  - **Fix:** hard-allowlist a root directory for dataset CSVs (e.g. `${PROJECT_ROOT}/data/public/` and/or `${PROJECT_ROOT}/data/uploads/`). After resolving, enforce `full_path.relative_to(allowed_root)` (reject on failure). Do not rely on `.resolve()` alone.

### Warning (fix soon)
- **`data_analyst_agent/sub_agents/executive_brief_agent/agent.py` — section-contract normalization can mask LLM regressions**
  - `_apply_section_contract()` heals missing/invalid sections and fills fallbacks.
  - This is good for renderer stability, but can silently hide model output drift.
  - Follow-up: log when normalization had to add placeholder insights, fill missing sections, or replace empty content.

- **`data_analyst_agent/sub_agents/executive_brief_agent/scope_utils.py` — scoped hierarchy mapping reads the dataset CSV**
  - `_load_hierarchy_level_mapping()` now reads the dataset CSV (contract-driven) to build parent→child maps.
  - Risk: expensive on large datasets at brief time.
  - Follow-up: ensure cache is bounded (dataset+columns), and consider a max-row cap / sampling if file sizes grow.

- **`tests/e2e/test_adk_integration.py` — report assertions loosened too far**
  - Now accepts any session-state key containing `"report"`.
  - Risk: tests pass even if `report_markdown` / `report_synthesis_result` is broken.
  - Follow-up: tighten to an explicit contract (e.g., require `report_markdown` OR `report_synthesis_result`).

### Observations
- Good direction: statistical tools are now `contract.validation` driven (`scenario_id_column`, `anomaly_flag_column`, `datapoints_file`), reducing trade-data coupling.
- Some prompt trimming happened via payload pruning/caps, but the *prompt source files* are still over the budget.

## 2) Hardcoded trade-data assumptions (grep audit)
Command used:
```bash
grep -RIn "trade_value\|hs2\|hs4\|port_code\|region\|imports\|exports" data_analyst_agent/ --include="*.py" \
  | grep -v __pycache__ | grep -v -i test | grep -v contract.yaml
```

### Flagged (not clearly contract-driven / bakes dataset vocabulary into generic logic)
- **`data_analyst_agent/tools/validation_data_loader.py`**
  - Still models the validation long-form output as `(region, terminal, metric, week_ending)` and applies explicit `region_filter`/`terminal_filter`.
  - This is *OK if validation-only*, but it is **not contract-generic**. If this utility is reused for other datasets, it becomes a hidden schema assumption.
  - Suggested guardrail: document and enforce that this loader is only for `validation_ops`-shaped data, or rename it to make that explicit.

- **`data_analyst_agent/__main__.py`**
  - CLI help/examples reference `region` and `Truck Count` explicitly.
  - Not runtime-breaking, but it encodes a particular dataset’s vocabulary in default examples.
  - Suggested follow-up: either label examples as `trade_data` examples, or generate examples from the active contract.

### Informational (low risk)
- **`data_analyst_agent/sub_agents/narrative_agent/tools/generate_narrative_summary.py:101`**
  - Heuristic token checks include `(region, country, market, geo)` for phrasing decisions; low-risk.

## 3) Unused imports (spot-check)
Method: lightweight AST scan (high false-positive rate for intentional re-exports; treat those as informational).

High-confidence candidates worth removing:
- **`web/app.py`**: `os`, `FileResponse`, `JSONResponse`
- **`web/run_manager.py`**: `signal`, `sys as _sys`
- **`data_analyst_agent/semantic/models.py`**: `ContractValidationError`

Additional likely-unused (verify before deleting; some may be intentional for typing/re-exports):
- `conftest.py`: `Mock`
- `data_analyst_agent/sub_agents/executive_brief_agent/report_utils.py`: `Dict`
- `data_analyst_agent/sub_agents/hierarchy_variance_agent/tools/compute_pvm_decomposition.py`: `pandas as pd`, `Dict`, `Any`, `List`
- `tests/conftest.py`: `os`, `numpy as np`
- `tests/integration/test_contract_to_context_flow.py`: `pandas as pd`
- `tests/unit/test_012_dataset_resolver.py`: `MagicMock`, `resolve_dataset_file`

## 4) Prompt token efficiency (character budget audit)
Command used:
```bash
wc -c config/prompts/executive_brief.md \
  data_analyst_agent/sub_agents/narrative_agent/prompt.py \
  data_analyst_agent/sub_agents/report_synthesis_agent/prompt.py
```

Results (flag > 3000 chars):
- **5994** `config/prompts/executive_brief.md` ✅ OVER 3000
- 1255 `data_analyst_agent/sub_agents/narrative_agent/prompt.py`
- **6022** `data_analyst_agent/sub_agents/report_synthesis_agent/prompt.py` ✅ OVER 3000

Recommendations:
- `executive_brief.md`: now that output is schema-contracted *and* normalized in-code, you can likely cut redundant enforcement prose. Keep: schema, required section titles/order, ~5–10 guardrails, numeric formatting.
- `report_synthesis_agent/prompt.py`: consider compact vs verbose variants (env-controlled), and rely more on contract summary + tool layout rather than long rule blocks.

## 5) Dev-agent checklist (actionable)
1. **Security:** lock down contract-driven CSV reads in `web/app.py` with strict allowlisted root + `relative_to` enforcement.
2. Decide whether `validation_data_loader.py` should remain validation-only; if yes, rename/docs/guardrails so it doesn’t look like a general contract-driven loader.
3. Remove unused imports listed above.
4. Trim `executive_brief.md` and `report_synthesis_agent/prompt.py` under 3000 chars (or add prompt variants / debug mode).
5. Tighten e2e report assertions back to a small explicit report-output contract.

---

## 2026-03-11 06:36 UTC — Regression: CLI pipeline never exits after report persistence
- Commands run:
  1. `python -m data_analyst_agent.agent "Analyze all metrics"`
  2. `DATA_ANALYST_METRICS=volume_units python -m data_analyst_agent.agent "Analyze volume"`
- In both runs the workflow completed metric analyses, generated markdown reports, and saved JSON/MD artifacts into `outputs/trade_data/20260311_063105` and `outputs/trade_data/20260311_063428` respectively.
- After `OutputPersistenceAgent` finished, the process remained stuck (no further log lines, no CPU usage) and never returned to the shell. Required manual `kill` of the `python -m data_analyst_agent.agent ...` PIDs to continue.
- Regression risk: automated cron / CI / CLI users will hang indefinitely after successful analysis, blocking subsequent steps and leaving zombie processes.
- Suspect root cause: report synthesis agent’s tool call returns `{'result': '# Error Generating Report\\n\\nError: Unable to parse hierarchical_results'}` after persistence, and higher-level workflow is waiting on additional tool callbacks or cleanup that never occurs.
- Next steps: ensure the target-analysis workflow signals completion once output persistence finishes, even if the markdown generator returns an error payload; audit any lingering async tasks or futures that keep the event loop alive.
