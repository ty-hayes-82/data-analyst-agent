# Agent Learnings Log

Agents: after each session, append what you learned here. Before starting work, read this file to avoid repeating mistakes.

## How to use
- Before starting: `cat /data/data-analyst-agent/data/validation/LEARNINGS.md`
- After finishing: append your learnings with the date and what you found

## Learnings

### 2026-03-09 — Initial Setup
- data_cache uses sys.modules registry; setting cache vars to None breaks clear_all_caches()
- ops_metrics sample data column names must match contract.yaml exactly
- Tests in test_010_contract_schema_sync.py hardcode Windows paths — skip them
- Always run `python -m pytest --tb=short -q` (not `source .venv/bin/activate`)
- Always push after committing: `git push origin dev`
- USE ONLY trade_data dataset — no ops_metrics, no Tableau/Hyper files

### 2026-03-09 — Trade dataset validation
- Run pytest via `./.venv/bin/python -m pytest` or `./.venv/bin/pytest`; system python misses google.adk deps and causes module import errors.
- Full suite currently fails in data_analyst_agent/agent.py because `TestModeReportSynthesisAgent` is referenced but never defined; expect four deterministic failures until that shim exists.
- Fixture C (LAX HS4 8542) reproduces scenario A1; anomaly average matches validation JSON, but baseline comes from the minified fixture, so expect ~5% drift from the canonical value when writing tests.
- `scripts/track_results.py` automatically runs the full test suite plus trade e2e tests and writes scoreboard/results files whenever it’s executed.

### 2026-03-09 — Tester E2E run
- Full-suite collection currently errors on four files because they import google.adk Agent/BaseAgent classes; add lightweight stubs/mocks or install the dependency before expecting the run to pass.
- Trade data E2E (`tests/e2e/test_trade_data_e2e.py`) passes in ~0.02s and verifies fixture C against validation datapoints, so it’s a reliable regression guard for anomaly detection.
- `scripts/track_results.py` logs the latest pytest + e2e status into SCOREBOARD.md; rerun it after every test cycle to keep the iteration history current.

### 2026-03-09 — Root agent modularization
- Split the 1.2K-line `agent.py` by extracting loader, proxy, CLI/test-mode, fetcher, alerting, and target-iteration agents into `data_analyst_agent/core_agents/`; keep helper functions (e.g., `create_target_analysis_pipeline`) with the new modules.
- Pydantic BaseAgent subclasses require optional fields (like `alert_agent`) to use `Field(..., default=None, exclude=True)` or they raise ValidationError at import time.
- Importing from the new modules happens at module import, so ensure every dependency (e.g., `Field`) is imported locally or `pytest` will fail during collection.
- `scripts/track_results.py` re-runs the full suite + trade e2e and writes SCOREBOARD/iteration_results; run it after each commit so the metrics reflect the latest refactor.
