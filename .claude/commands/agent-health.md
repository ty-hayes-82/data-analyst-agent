# Agent Health Check

Check the health, configuration, and dependencies of the data-analyst-agent on VPS 2.

## Steps

1. **Runtime status**:
   - Container status: `docker ps --filter name=swoop-agent --format "{{.Status}}"`
   - Python version: `python --version`
   - Venv status: check `.venv/bin/python` exists

2. **Git status**:
   - Current branch and clean/dirty state
   - Commits ahead/behind origin

3. **Configuration**:
   - Active dataset: check `ACTIVE_DATASET` env var or default
   - Model config: summarize `config/agent_models.yaml` tiers
   - Feature flags: list all `USE_*` and `*_MODE` env vars in use

4. **Dependencies**:
   - Check `google-adk` version: `pip show google-adk 2>/dev/null | head -5`
   - Check for outdated packages: `pip list --outdated 2>/dev/null | head -10`
   - Verify imports work: `python -c "from google.adk import Agent; print('ADK OK')" 2>&1`

5. **Test baseline**:
   - Quick test run: `python -m pytest tests/ --co -q 2>&1 | tail -5` (count only)

6. **Disk/output status**:
   - Output directory size: `du -sh outputs/ 2>/dev/null`
   - Latest output timestamp

## Output
Summary table of all checks with status indicators.
