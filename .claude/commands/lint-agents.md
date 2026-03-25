# Lint Agents

Scan the codebase for common anti-patterns and code quality issues.

**Scope:** $ARGUMENTS (e.g., `all`, `sub_agents`, `tools`, `utils`, or a specific agent name)

## Checks

### Critical
- [ ] `print()` statements instead of logging (exclude `__main__.py`)
- [ ] Hardcoded file paths (should use Path objects relative to project root or config)
- [ ] Direct `session.state` mutation instead of `state_delta` in EventActions
- [ ] Raw DataFrames stored in session state (should store summaries/paths instead)
- [ ] Missing error handling around A2A/external calls
- [ ] Circular imports between sub-agents

### Warning
- [ ] Missing type hints on public functions/methods
- [ ] Missing docstrings on classes
- [ ] Feature flags read from `os.environ` directly instead of centralized config
- [ ] Duplicate feature flag parsing (same env var parsed in multiple files)
- [ ] Magic numbers without named constants
- [ ] Overly broad except clauses (bare `except:` or `except Exception`)

### Info
- [ ] TODO/FIXME/HACK comments
- [ ] Unused imports
- [ ] Files over 300 lines (consider splitting)
- [ ] Test files without corresponding source changes

## Output Format

Group findings by severity (Critical > Warning > Info). For each finding show file:line and a one-line fix suggestion.
