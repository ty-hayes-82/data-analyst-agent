# ADK Agent Audit

Audit the specified sub-agent against Google ADK best practices.

**Target agent:** $ARGUMENTS (e.g., `statistical_insights_agent`, `hierarchical_analysis_agent`)

## Audit Checklist

Read the agent's `agent.py` and all modules in its directory. Evaluate against these ADK patterns:

### 1. Agent Type Selection
- Is the correct ADK agent type used? (SequentialAgent for pipelines, LoopAgent for iteration, LlmAgent for LLM calls, BaseAgent for custom logic)
- Are agents composed hierarchically rather than monolithically?
- Does the agent avoid mixing orchestration with business logic?

### 2. State Management
- Is `session.state` used correctly for inter-agent communication?
- Are state keys namespaced to avoid collisions (e.g., `agent_name:key`)?
- Is state_delta used in EventActions rather than mutating session.state directly?
- Are large objects (DataFrames, raw data) kept OUT of session state?

### 3. Error Handling & Resilience
- Does the agent handle failures gracefully without crashing the pipeline?
- Are there appropriate try/except blocks around external calls?
- Is there a clear failure mode (skip vs retry vs abort)?

### 4. Tool Design
- Are tools pure functions with clear input/output contracts?
- Do tools avoid side effects where possible?
- Are tool descriptions clear enough for LLM agents to use correctly?

### 5. Code Quality
- No print() statements (use logging module instead)
- No hardcoded file paths
- Type hints on public functions
- Docstrings on classes and public methods
- No circular imports

### 6. ADK Anti-Patterns
- Avoid putting business logic in agent instructions (use tools instead)
- Avoid overly long agent instructions (>2000 chars)
- Avoid agents that do too many things (single responsibility)
- Avoid passing raw DataFrames through LLM context

## Output Format

For each category, report: PASS / WARN / FAIL with specific line references and suggested fixes. End with a prioritized action list.
