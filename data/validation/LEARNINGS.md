# Reviewer Audit Learnings (cron: reviewer-audit-001)

Date: 2026-03-10 (UTC)
Scope: `git diff HEAD~10..HEAD`

## Commit window reviewed
```
8f7186e harden: 5 fixes for dataset-agnostic pipeline reliability
d9e0cbe chore: log 2026-03-10 13:46 iter
3af1a29 chore: log 2026-03-10 13:31 iter
3413c69 chore: log 2026-03-10 13:16 iter
be5b2eb chore: log 2026-03-10 13:01 iter
ade327e chore: log 2026-03-10 12:46 iter
cbb0aca chore: log 2026-03-10 12:31 iter
addbb9a chore: log 2026-03-10 12:16 iter
b54d8cf chore: log 2026-03-10 12:01 iter
658ab9a chore: log 2026-03-10 11:31 iter
```

Files changed (stat):
- `data_analyst_agent/agent.py` (+30)
- `data_analyst_agent/core_agents/cli.py` (+10)
- `data_analyst_agent/utils/timing_utils.py` (+12)
- `data_analyst_agent/sub_agents/executive_brief_agent/agent.py` (+16/-?)
- `data_analyst_agent/sub_agents/executive_brief_agent/prompt_utils.py` (+15)
- `data_analyst_agent/sub_agents/hierarchy_variance_agent/tools/compute_level_statistics.py` (+29/-?)
- validation scoreboard/log churn + tiny e2e assert update

---

## Critical (fix before relying on results)

### 1) Error swallowing can produce silently-wrong downstream outputs
- `data_analyst_agent/utils/timing_utils.py` (new `except Exception` in `TimedAgentWrapper.run_async`)
  - Current behavior: any wrapped agent exception is converted into an `Event` with `state_delta={"<agent>_error": "..."}` and the pipeline continues.
  - Risk: downstream agents run with partial/missing session state (classic cascading failure mode) and produce plausible-but-wrong narratives/reports.
  - Fix suggestion:
    - Decide: do we want the pipeline to *halt* on certain stages (ContractLoader/DataFetcher/AnalysisContext), vs continue only for non-critical stages?
    - At minimum: set a shared `fatal_error` flag + stop the sequential pipeline (or raise) for critical stages.
    - Also consider recording a structured error payload (type/stage/traceback) instead of just `str(exc)`.

---

## Warning (fix soon)

### 2) Executive brief fallback formatting is extremely brittle / hard to maintain
- `data_analyst_agent/sub_agents/executive_brief_agent/prompt_utils.py:109-113`
  - `_format_brief_with_fallback()` uses `strftime(chr(37) + "Y-" + ...)` to build the format string.
  - This *works* (valid Python inside f-string expression), but it’s opaque and looks like a quoting bug at a glance.
  - Fix suggestion: replace with the normal literal `"%Y-%m-%d %H:%M UTC"` (same as `_format_brief()` uses earlier in the file).

### 3) Output dir initializer: OK idea, but make sure contract + session state assumptions hold
- `data_analyst_agent/agent.py` (new `_OutputDirInitializer`)
  - Good: enforces a per-run output directory and sets `DATA_ANALYST_OUTPUT_DIR`.
  - Watch-outs:
    - It pulls `dataset_contract` from `ctx.session.state`; if ContractLoader fails (see “error swallowing” above), this defaults to `unknown` and still creates directories.
    - It yields an empty event when already set; may be fine, but consider always setting `state_delta["output_dir"]` even if env already set (for consistency).

### 4) Contract-metric fallback: good change, but check types / serialization expectations
- `data_analyst_agent/core_agents/cli.py`
  - New fallback sets `extracted_targets_raw` to a JSON list of contract metrics when CLI env doesn’t specify metrics.
  - Ensure downstream expects metric **names** not objects; the list comprehension handles dict + objects, but if contract metric entries have different shapes, you may get `str(m)` noise.

---

## Hardcoded trade-data assumptions (dataset-agnostic risk)

Command used:
```
grep -rn "trade_value\|hs2\|hs4\|port_code\|region\|imports\|exports" data_analyst_agent/ --include="*.py" | grep -v __pycache__ | grep -v test | grep -v contract.yaml
```

High-risk / non-contract-driven items to address:

1) `data_analyst_agent/sub_agents/statistical_insights_agent/tools/compute_anomaly_indicators.py:1+`
   - File explicitly targets “trade_data synthetic benchmark”.
   - It hardcodes scenario-specific HS4 filters:
     - `scenario_id == "B1" ... hs4 == 2711` (and similar for D1/A1/E1)
   - This is not contract-driven; if this tool runs for any non-trade dataset, the narrative example extraction becomes nonsense.
   - Fix options:
     - Gate execution: only run when `contract.name == "trade_data"` (or a `contract.validation_profile == "trade_scenarios"`).
     - Move under a clearly validation-only package and ensure production pipeline cannot call it.
     - Replace with contract-driven “example row selection” rules (dimensions list from contract).

2) `data_analyst_agent/sub_agents/narrative_agent/tools/generate_narrative_summary.py`
   - Uses keys like `port_code`, `port_name`, `hs2`, `hs4`, `region` *from example dicts*.
   - This is slightly safer because it uses `ex.get()` and builds a label only if present, but it still bakes in trade terminology.
   - Fix suggestion: build location/commodity labels based on contract dimensions (e.g., from `contract.dimensions` / `contract.hierarchies`) and/or include a mapping in contract metadata.

3) Validation-specific loaders and fetchers assume `region`/`terminal` columns
   - `data_analyst_agent/tools/validation_data_loader.py` and `data_analyst_agent/tools/config_data_loader.py`
   - `data_analyst_agent/sub_agents/validation_csv_fetcher.py` / `config_csv_fetcher.py`
   - Likely OK *if strictly test/validation-only*, but confirm these tools are never invoked for real datasets without matching contract.

---

## Unused imports (spot-check, high-confidence)

Note: I ran a lightweight AST-based unused-import detector. It produces many false positives for re-export-only `__init__.py` modules and some `__future__` patterns. The following are *high-confidence* and worth cleaning:

- `data_analyst_agent/sub_agents/report_synthesis_agent/prompt.py:19` → `import os` appears unused.
- `data_analyst_agent/sub_agents/executive_brief_agent/agent.py:20` → `from datetime import timezone` appears unused.
- `data_analyst_agent/tools/config_data_loader.py:22` → `import os` appears unused.

If you want to enforce this systematically, add a linter (ruff/pyflakes) to CI; current environment didn’t have `ruff` installed (`python -m ruff` failed).

---

## Prompt token efficiency (over 3000 chars)

Command used:
```
wc -c config/prompts/executive_brief.md \
      data_analyst_agent/sub_agents/narrative_agent/prompt.py \
      data_analyst_agent/sub_agents/report_synthesis_agent/prompt.py
```

Results:
- `config/prompts/executive_brief.md` → **7846 chars** (OVER 3000)
- `data_analyst_agent/sub_agents/report_synthesis_agent/prompt.py` → **6022 chars** (OVER 3000)
- `data_analyst_agent/sub_agents/narrative_agent/prompt.py` → 2562 chars (OK)

Recommendations:
- Prefer moving long static instructions into markdown templates and referencing them once (you’re already doing this in report_synthesis with `config/prompts/report_synthesis.md`—good). If the template is long, consider:
  - Splitting into: “system rules” (short) + “format/schema” (short JSON schema) + “examples” (optional, only loaded in debug/validation mode).
  - Avoid repeating global rules in multiple prompts (centralize in a shared snippet included by multiple prompts).
- For `executive_brief.md`: trim redundant admonitions and move examples to an opt-in variant.

---

## Summary: what to do next (actionable)
1) Decide pipeline failure policy: which stages must halt on exception; implement consistent `fatal_error` / stop behavior (don’t silently continue for core stages).
2) Gate or quarantine trade-specific tools (`compute_anomaly_indicators`, trade terms in narrative summary) behind contract flags.
3) Remove a few obvious unused imports and consider adding ruff/pyflakes to CI to keep this from regressing.
4) Reduce prompt sizes >3000 chars; keep examples optional.
