# Test Fixtures — Spec 008: LLM-to-Code Refactor

These fixtures provide deterministic inputs and expected outputs for the
unit tests introduced in `specs/008-llm-to-stats-refactor`.

## Fixture Files

| File | Description | Used By |
|------|-------------|---------|
| `statistical_summary_sample.json` | Realistic `statistical_summary` dict (output of `compute_statistical_summary`) | Phase 1 tests |
| `level_stats_sample.json` | Realistic `compute_level_statistics()` output for a mid-level hierarchy | Phase 2 tests |
| `pvm_sample.json` | Realistic `compute_pvm_decomposition()` output | Phase 2 tests |
| `alert_scoring_sample.json` | Realistic `score_alerts()` output | Phase 3 tests |

## Provenance

Fixtures are **synthetic but realistic** — they are hand-authored to match
the exact JSON schemas produced by the corresponding Python tools. When
the live pipeline becomes available, replace these with outputs captured
from real pipeline runs using `phase_logger`-enabled sessions.

To capture live fixtures from a real run, enable `PHASE_LOG_SAVE_SUMMARY=true`
in `.env` and extract the relevant session state keys after a run completes.
