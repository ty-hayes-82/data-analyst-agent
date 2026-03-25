# Refactor Agent

Guided refactor of a specific sub-agent following Google ADK best practices.

**Target:** $ARGUMENTS (e.g., `statistical_insights_agent`, `narrative_agent`)

## Refactoring Steps

1. **Read current implementation** — Read all files in the target sub-agent directory
2. **Identify ADK pattern** — Determine which ADK pattern fits best:
   - **Sequential**: Pipeline stages that must run in order
   - **Loop**: Iterative refinement until a condition is met
   - **Parallel**: Independent analyses that can run concurrently
   - **LLM Agent**: Tasks requiring language model reasoning
   - **Custom BaseAgent**: Complex orchestration logic
3. **Check against ADK best practices**:
   - Single responsibility per agent
   - State management via state_delta in EventActions (not direct mutation)
   - Proper use of InvocationContext
   - Tools as pure functions
   - Logging via module logger, not print()
   - Type hints and docstrings
   - Error handling with graceful degradation
4. **Apply refactoring**:
   - Extract mixed concerns into separate agents
   - Replace print() with structured logging
   - Add proper type hints
   - Ensure state keys are namespaced
   - Add/fix docstrings
   - Remove dead code
5. **Validate** — Run tests for the refactored agent

## Rules
- Work on the `refactor` branch only
- Commit each sub-agent refactor separately with descriptive messages
- Do not change external interfaces (state keys read/written) without updating dependent agents
- Keep backwards compatibility with existing pipeline
