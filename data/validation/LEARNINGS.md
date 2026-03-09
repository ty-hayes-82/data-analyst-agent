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
