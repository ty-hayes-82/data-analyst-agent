# Universal Operational Insights Agent Constitution

## Strategic Direction

This project is being transformed from a P&L-specific Analyst Agent into a **Universal Operational Insights Agent**. The transformation follows 4 waves:

1. **Wave 1 - Semantic Core**: Replace hardcoded domain nouns with a configuration-driven `DatasetContract` and `AnalysisContext`.
2. **Wave 2 - Abstract Math Engine**: Replace fixed 3-level drill-down with recursive Contribution Tree, generic PVM decomposition, and STL time-series analysis.
3. **Wave 3 - Dynamic Orchestration**: Build a Profiler/Planner agent that reads the contract and data to decide which sub-agents to spawn (hybrid: deterministic rules + LLM override).
4. **Wave 4 - Policy & Narrative**: Pluggable rule engine, semantic root-cause classification via LLM, and universal Insight Cards output format.

**Approach**: Clean break. Existing P&L-specific code is replaced, not wrapped. All existing YAML configs are migrated into `DatasetContract` instances.

**Framework**: Google ADK (v1.25.0+). All agents use ADK primitives (`LlmAgent`, `SequentialAgent`, `LoopAgent`, `ParallelAgent`, `BaseAgent`).

**ADK Architecture Reference**: [Developer's guide to multi-agent patterns in ADK](https://developers.googleblog.com/developers-guide-to-multi-agent-patterns-in-adk/)

**Validation Domain**: Operational Data (in addition to the existing P&L/logistics domain) to prove the abstraction works without code changes.

## Core Principles

### I. Code Quality (NON-NEGOTIABLE)

- **Readability First**: Code must be self-documenting with clear naming, modular structure, and purposeful comments where logic is non-obvious.
- **Single Responsibility**: Each module, agent, or function has one clear purpose; avoid god objects and catch-all utilities.
- **Explicit over Implicit**: Prefer explicit types, error handling, and data contracts over implicit behavior.
- **Consistency**: Follow project conventions (e.g., `golfsim.logging.init_logging()` at entrypoints, no emojis in logs, clean text only).
- **DRY with Judgment**: Eliminate duplication, but do not over-abstract; utility code must earn its place.

### II. Testing Standards

- **Test Coverage for Business Logic**: All agents, aggregation logic, materiality filters, and variance calculations must have unit tests.
- **Data Contract Tests**: DatasetContract validation, AnalysisContext construction, and DataQualityGate checks require integration or contract tests.
- **Regression Protection**: Known edge cases (e.g., empty datasets, missing dimensions, schema mismatches, one-time spikes) must be covered.
- **Test Independence**: No shared mutable state; tests run in isolation and can execute in any order.
- **Red-Green-Refactor**: Write failing tests first for new behavior; refactor only with passing tests.

### III. User Experience Consistency

- **Structured Output**: All analysis outputs follow a structured drill-down framework (depth configurable per DatasetContract via `max_drill_depth`); deviations require justification.
- **Materiality as Default**: Apply materiality thresholds as defined in the DatasetContract (default: ±5% and ±$50K); do not introduce ad-hoc cutoffs without documentation.
- **Predictable Formats**: JSON schemas, phase names, and log keys must be consistent across runs and agents.
- **Actionable Insights**: Every finding includes enough context (period, cost center, GL, variance %) for a human to act.
- **No Surprise Failures**: Errors must be logged with context; user-facing messages should explain impact and next steps.

### IV. Performance Requirements

- **Scalability**: Design for 6.3M+ P&L transactions and 37M+ ops metrics; avoid full-scan patterns and unbounded memory growth.
- **Parallelism Where Appropriate**: Use parallel analysis for independent GLs; avoid blocking I/O in hot paths.
- **Incremental Processing**: Prefer streaming or chunked processing over loading entire datasets when possible.
- **Observable Performance**: Phase-based logging must include duration and record counts; slow phases (>5s) require optimization justification.
- **Resource Awareness**: Avoid unnecessary copies of large DataFrames; reuse validated data structures across agents when safe.

### V. ADK Multi-Agent Best Practices (NON-NEGOTIABLE)

Follow the [ADK multi-agent design patterns](https://developers.googleblog.com/developers-guide-to-multi-agent-patterns-in-adk/) for all agent construction:

- **State Management via `output_key`**: Every agent that produces data for downstream consumption MUST use descriptive `output_key` names written to `session.state`. Never use generic keys like `result` or `output`; use `validated_data`, `quality_report`, `variance_summary`, etc.
- **Clear Agent Descriptions**: Every sub-agent MUST have a precise `description` field. When using Coordinator/Dispatcher routing, the description is the LLM's API documentation for deciding which agent to invoke.
- **Single Responsibility per Agent**: Do not overload an agent with mixed responsibilities. A monolithic agent with a complex instruction set leads to degraded adherence and compounding errors. Split into specialist agents instead.
- **Pattern Selection Guide**:
  - **Sequential Pipeline** (`SequentialAgent`): Use for deterministic, ordered workflows (data fetch -> validate -> analyze -> report).
  - **Parallel Fan-Out** (`ParallelAgent`): Use for independent analyses on the same data (statistical, seasonal, ratio agents). Each parallel agent MUST write to a unique `output_key` to prevent state race conditions.
  - **Loop / Generator-Critic** (`LoopAgent`): Use for iterative refinement with quality gates (e.g., variance drill-down with `exit_condition` when materiality threshold is met).
  - **Coordinator/Dispatcher**: Use when the Profiler/Planner agent (Wave 3) needs to route to specialist sub-agents based on data characteristics.
  - **Hierarchical Decomposition** (`AgentTool`): Use when a parent agent needs to invoke a sub-agent's entire workflow as a single tool call.
- **Start Simple**: Begin with a Sequential Pipeline. Only introduce Parallel, Loop, or Coordinator patterns when there is a clear performance or quality justification. Debug the simple version first.
- **Composite Patterns**: Production workflows will combine patterns (e.g., Sequential pipeline containing a Parallel fan-out stage, followed by a Generator-Critic loop for report quality). Document the pattern composition in the agent module's docstring.

## Quality Gates

- **Pre-Merge**: All tests pass; no new linter violations; constitution compliance checked.
- **Data Pipelines**: Validation failures must not silently drop records; completeness metrics logged.
- **Analytical Accuracy**: Variance calculations must be reproducible and traceable to source dimensions and periods as defined in the DatasetContract.

## Development Workflow

- **Spec-Driven**: New features follow `/speckit.specify` → `/speckit.plan` → `/speckit.tasks` → `/speckit.implement` when applicable.
- **Constitution as Reference**: AI agents and developers must consult this document for technical decisions; deviations require documented rationale.
- **Incremental Delivery**: Prefer small, reviewable changes; complex refactors should be broken into sequenced PRs.

## Governance

- This constitution supersedes ad-hoc practices; when in conflict, constitution wins.
- Amendments require: documented rationale, impact assessment, and update to affected specs/plans.
- Complexity must be justified; prefer simple, maintainable solutions over clever optimizations.
- All analysis outputs and logs must align with these principles; non-compliance is a defect.

### VI. Domain Agnosticism (NON-NEGOTIABLE)

- **No Hardcoded Nouns**: Code must never reference domain-specific terms (`gl_code`, `cost_center`, `miles`, `canonical_category`). All column references flow through the `AnalysisContext`.
- **Contract-Driven Behavior**: All thresholds, hierarchies, metric definitions, and policies are read from the `DatasetContract`. Code changes are never required to onboard a new domain.
- **Separation of Concerns**: The Semantic Layer (DatasetContract) defines *what* the data means. The Math Engine defines *how* to analyze it. The Policy Layer defines *what matters* in a given business context.

**Version**: 2.0.0 | **Ratified**: 2025-02-12 | **Last Amended**: 2025-02-12
