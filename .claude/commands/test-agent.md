# Test Agent

Run tests scoped to a specific sub-agent or module.

**Target:** $ARGUMENTS (e.g., `statistical_insights`, `hierarchical_analysis`, `narrative`, or `all`)

## Steps

1. Activate the venv: `source /data/data-analyst-agent/.venv/bin/activate`
2. Run the appropriate test command:
   - If target is a sub-agent name: `python -m pytest tests/ -k "<target>" -v --tb=short 2>&1 | tail -n 50`
   - If target is `all`: `python -m pytest tests/ -v --tb=short 2>&1 | tail -n 80`
   - If target is `unit`: `python -m pytest tests/unit/ -v --tb=short 2>&1 | tail -n 50`
   - If target is `integration`: `python -m pytest tests/integration/ -v --tb=short 2>&1 | tail -n 50`
3. Summarize: total passed, failed, skipped, errors
4. For any failures, read the failing test file and the agent code it tests to suggest fixes

## Important
- Always run from `/data/data-analyst-agent/`
- Use `tail` to limit output
- Set `DATA_ANALYST_TEST_MODE=true` for tests that need it
