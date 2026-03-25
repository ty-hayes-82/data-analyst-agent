# Run Pipeline

Execute a test analysis pipeline run using validation CSV mode.

**Options:** $ARGUMENTS (e.g., `ops_metrics`, `account_research`, or custom query text)

## Steps

1. Set up environment:
   ```
   cd /data/data-analyst-agent
   source .venv/bin/activate
   export DATA_ANALYST_VALIDATION_CSV_MODE=true
   export DATA_ANALYST_TEST_MODE=true
   export USE_CODE_INSIGHTS=true
   ```

2. Run the pipeline:
   - Default: `python -m data_analyst_agent 2>&1 | tail -n 100`
   - With custom query: `DATA_ANALYST_QUERY="<argument>" python -m data_analyst_agent 2>&1 | tail -n 100`
   - With specific metrics: `DATA_ANALYST_METRICS="<argument>" python -m data_analyst_agent 2>&1 | tail -n 100`

3. Check outputs:
   - `ls -la outputs/ | tail -n 20`
   - Read the latest executive brief or report synthesis output

4. Report: execution time, agents that ran, any errors/warnings, output files produced
