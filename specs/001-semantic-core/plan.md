# Implementation Plan: Semantic Core (Wave 1)

**Branch**: `001-semantic-core` | **Date**: 2025-02-12 | **Spec**: `specs/001-semantic-core/spec.md`
**Input**: Feature specification from `/specs/001-semantic-core/spec.md`

## Summary

Replace all hardcoded domain nouns in the P&L Analyst Agent with a configuration-driven Semantic Layer. The deliverables are: (1) a `DatasetContract` Pydantic schema loaded from YAML, (2) an `AnalysisContext` runtime class that wraps DataFrames with semantic accessors, (3) a `DataQualityGate` that validates data against the contract, (4) a `DatasetProfiler` that auto-generates draft contracts, and (5) a migration of all 14 existing YAML configs into a single `pl_contract.yaml`.

## Technical Context

**Language/Version**: Python 3.14 (system), compatible with 3.10+  
**Primary Dependencies**: google-adk 1.25.0, pydantic 2.12+, pandas 2.2+, pyyaml 6.0+, numpy 1.26+  
**Storage**: File-based (YAML contracts in `contracts/` directory, temp-file data cache)  
**Testing**: pytest 7.4+ (unit, integration, contract tests)  
**Target Platform**: Windows 10 (dev), Linux (deployment)  
**Project Type**: Single project (agent package)  
**Performance Goals**: Contract loading < 100ms, DataQualityGate < 2s for 6.3M rows, AnalysisContext construction < 50ms  
**Constraints**: Must preserve ADK agent architecture (LlmAgent, SequentialAgent, LoopAgent, BaseAgent). Zero hardcoded column names after migration.  
**Scale/Scope**: 14 YAML configs migrated, 8 sub-agents refactored, ~30 files touched

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Code Quality | PASS | Single-responsibility modules; Pydantic enforces explicit types |
| II. Testing Standards | PASS | Contract tests for DatasetContract; unit tests for AnalysisContext, DataQualityGate, DatasetProfiler |
| III. User Experience Consistency | PASS | Output structure defined by contract `max_drill_depth`; materiality from contract |
| IV. Performance Requirements | PASS | Phase-based logging retained; DataQualityGate logs duration + record counts |
| V. ADK Multi-Agent Best Practices | PASS | Descriptive `output_key` on every agent; unique keys for ParallelAgent; precise `description` fields; composite pattern (Sequential + Parallel + Loop) documented |
| VI. Domain Agnosticism | PASS | This feature implements the principle; zero hardcoded nouns after migration |

## Project Structure

### Documentation (this feature)

```text
specs/001-semantic-core/
├── plan.md              # This file
├── data-model.md        # Pydantic schema definitions
└── spec.md              # Feature specification
```

### Source Code (repository root)

```text
pl_analyst_agent/
├── agent.py                          # Root orchestration (refactor to use AnalysisContext)
├── config.py                         # Environment config (unchanged)
├── prompt.py                         # System prompts (genericize domain nouns)
├── auth_config.py                    # Auth (unchanged)
│
├── semantic/                         # NEW: Semantic Layer package
│   ├── __init__.py                   # Public API exports
│   ├── contract.py                   # DatasetContract Pydantic models (FR-001..004, FR-013, FR-014)
│   ├── context.py                    # AnalysisContext class (FR-005, FR-006)
│   ├── loader.py                     # ContractLoader - YAML loading + validation (FR-011)
│   ├── quality_gate.py               # DataQualityGate + QualityReport (FR-007, FR-008)
│   ├── profiler.py                   # DatasetProfiler - auto-draft contracts (FR-009, FR-010)
│   └── exceptions.py                 # ContractValidationError, SchemaColumnMismatchError, etc.
│
├── sub_agents/                       # Existing agents (refactored)
│   ├── 01_data_validation_agent/     # Refactor: use context instead of hardcoded columns
│   ├── 02_statistical_insights_agent/# Refactor: thresholds from context.materiality
│   ├── 03_hierarchy_variance_ranker_agent/  # Refactor: hierarchy from context
│   ├── 04_report_synthesis_agent/    # Refactor: output structure from contract
│   ├── 05_alert_scoring_agent/       # Refactor: policies from contract
│   ├── 06_output_persistence_agent/  # Refactor: metadata from contract
│   ├── 07_seasonal_baseline_agent/   # Refactor: time config from contract
│   ├── data_analyst_agent/           # Refactor: hierarchy drill-down from context
│   ├── data_cache.py                 # Refactor: store AnalysisContext metadata alongside data
│   └── testing_data_agent/           # Refactor: test mode uses contract
│
├── tools/                            # Existing tools (refactored)
│   ├── calculate_date_ranges.py      # Refactor: time range from contract
│   ├── iterate_cost_centers.py       # Refactor: primary dimension from context
│   └── ...
│
└── utils/                            # Existing utilities
    ├── phase_logger.py               # Refactor: generic dimension names in log entries
    └── safe_parallel_wrapper.py      # Unchanged

contracts/                            # NEW: Contract YAML files (at project root)
├── pl_contract.yaml                  # Migrated P&L contract (US5)
└── ops_data_contract.yaml            # Operational Data validation contract (US3/SC-006)

scripts/
└── migrate_configs.py                # NEW: Migration utility (FR-012)

tests/
├── unit/
│   ├── test_contract.py              # DatasetContract schema validation
│   ├── test_context.py               # AnalysisContext accessor tests
│   ├── test_quality_gate.py          # DataQualityGate check tests
│   └── test_profiler.py              # DatasetProfiler inference tests
├── integration/
│   └── test_pl_migration.py          # End-to-end: load pl_contract.yaml, build context, run gate
└── fixtures/
    ├── minimal_contract.yaml         # Minimal valid contract for testing
    ├── invalid_contract.yaml         # Contract with missing fields
    ├── sample_pl_data.csv            # Sample P&L data for integration tests
    └── sample_ops_data.csv           # Sample operational data for profiler tests
```

**Structure Decision**: The `semantic/` package is added inside the existing `pl_analyst_agent/` package to keep all agent code co-located. Contract YAML files live at `contracts/` (project root) since they are user-facing configuration, not code.

---

## ADK Architecture: Pattern Mapping

Reference: [Developer's guide to multi-agent patterns in ADK](https://developers.googleblog.com/developers-guide-to-multi-agent-patterns-in-adk/)

The refactored Universal Insights Agent uses a **Composite Pattern** -- multiple ADK patterns composed together. This section maps each stage of the pipeline to a specific pattern and documents the `output_key` state flow.

### Pattern Composition Diagram

```text
root_agent (SequentialAgent)
  |
  +-- request_analyzer (LlmAgent)                    # Pattern: Sequential Pipeline
  |     output_key: "request_analysis"
  |
  +-- contract_loader_agent (BaseAgent)               # Pattern: Sequential Pipeline
  |     output_key: "loaded_contract"
  |     Reads: contract path from request_analysis
  |     Writes: serialized DatasetContract to state
  |
  +-- dimension_extractor (LlmAgent)                  # Pattern: Sequential Pipeline
  |     output_key: "target_dimensions"
  |     Reads: "request_analysis", "loaded_contract"
  |     (replaces cost_center_extractor -- now generic)
  |
  +-- dimension_loop (LoopAgent)                      # Pattern: Generator-Critic Loop
        condition_key: "has_more_dimensions"
        |
        +-- data_fetch_pipeline (SequentialAgent)      # Pattern: Sequential Pipeline
        |     +-- date_initializer (BaseAgent)
        |     |     output_key: "date_ranges"
        |     +-- data_source_agents (SequentialAgent)  # A2A agents
        |           output_key: "raw_data"
        |
        +-- quality_gate_agent (BaseAgent)             # Pattern: Sequential (Go/No-Go)
        |     output_key: "quality_report"
        |     Reads: "raw_data", "loaded_contract"
        |     Decision: GO -> continue, NO_GO -> escalate
        |
        +-- context_builder_agent (BaseAgent)          # Pattern: Sequential
        |     output_key: "analysis_context_path"
        |     Reads: "raw_data", "loaded_contract"
        |     Writes: AnalysisContext metadata to cache
        |
        +-- analysis_agents (ParallelAgent)            # Pattern: Parallel Fan-Out
        |     +-- statistical_agent (LlmAgent)
        |     |     output_key: "statistical_report"
        |     +-- seasonal_agent (LlmAgent)
        |     |     output_key: "seasonal_report"
        |     +-- hierarchy_ranker_agent (LlmAgent)
        |     |     output_key: "hierarchy_report"
        |     +-- alert_scoring_agent (LlmAgent)
        |           output_key: "alert_report"
        |
        +-- report_synthesizer (LlmAgent)              # Pattern: Gather (post Fan-Out)
        |     output_key: "synthesis_report"
        |     Reads: all 4 parallel reports from state
        |
        +-- output_persistence (BaseAgent)             # Pattern: Sequential
              output_key: "output_path"
```

### Key ADK Best Practices Applied

**1. Descriptive `output_key` naming (state management)**

Every agent writes to a unique, descriptive key. Downstream agents reference these keys in their instructions via `{key_name}` template syntax. This eliminates ambiguity about data lineage.

| Agent | output_key | Content |
|-------|-----------|---------|
| request_analyzer | `request_analysis` | Parsed user intent + requested dimensions |
| contract_loader_agent | `loaded_contract` | Serialized DatasetContract JSON |
| quality_gate_agent | `quality_report` | QualityReport JSON (GO/NO_GO/WARNING) |
| statistical_agent | `statistical_report` | Statistical findings per dimension value |
| seasonal_agent | `seasonal_report` | Seasonal decomposition results |
| hierarchy_ranker_agent | `hierarchy_report` | Ranked variance drivers by hierarchy |
| alert_scoring_agent | `alert_report` | Scored and prioritized alerts |
| report_synthesizer | `synthesis_report` | Final structured output |

**2. Parallel Fan-Out with unique keys (no race conditions)**

The 4 analysis agents run in `ParallelAgent` and each writes to a distinct `output_key`. This follows the ADK guidance: "make sure each agent writes its data to a unique key" to prevent state corruption.

**3. Generator-Critic via LoopAgent (dimension iteration)**

The `dimension_loop` iterates over target dimensions (formerly cost centers). The loop exit is controlled by `condition_key: "has_more_dimensions"` with `exit_condition: "false"`. Each iteration processes one dimension value through the full pipeline.

**4. Quality Gate as Go/No-Go decision point**

The `quality_gate_agent` (BaseAgent) implements a policy decision. If `quality_report.status == "NO_GO"`, the agent triggers `escalate=True` in its `EventActions`, causing the LoopAgent to skip this dimension and proceed to the next. This follows the Generator-Critic pattern where the gate acts as the critic.

**5. Clear agent descriptions for future Dispatcher routing (Wave 3)**

Every agent includes a precise `description` field. When Wave 3 introduces the Profiler/Planner agent (Coordinator/Dispatcher pattern), these descriptions serve as the routing documentation for the LLM dispatcher to decide which analysis agents to spawn based on contract characteristics.

**6. Hierarchical Decomposition ready (Wave 2)**

The `hierarchy_ranker_agent` is designed to use `AgentTool` in Wave 2, wrapping a recursive drill-down sub-agent as a tool call. The current Wave 1 implementation keeps it flat but structures the agent interface so the `AgentTool` wrapper can be added without changing the parent pipeline.

---

## Core Design Decisions

### D1: DatasetContract as a Pydantic BaseModel Hierarchy

The `DatasetContract` is a deeply structured Pydantic v2 model. This gives us:
- **Validation at load time**: Missing fields, wrong types, invalid enums all caught immediately.
- **Serialization**: `model_dump()` / `model_validate()` for round-tripping to YAML/JSON.
- **IDE support**: Full autocomplete and type checking.

See `data-model.md` for the complete schema.

### D2: AnalysisContext is Immutable After Construction

Once built from a `DatasetContract` + DataFrame, the `AnalysisContext` is frozen (`model_config = ConfigDict(frozen=True)` in Pydantic, or `@dataclass(frozen=True)`). This prevents sub-agents from mutating shared state, which aligns with the constitution's testing standards (no shared mutable state).

**Implementation**: `AnalysisContext` is a Python `dataclass(frozen=True)` (not Pydantic -- it wraps a DataFrame which isn't serializable). The contract is stored as a Pydantic model; the DataFrame reference is stored but not serialized.

### D3: DataQualityGate Returns a Report, Never Raises

The gate returns a `QualityReport` object instead of raising exceptions. This allows the orchestration agent to decide policy (e.g., proceed with warnings, abort on NO_GO). Individual check failures are captured as `Violation` objects in the report.

### D4: DatasetProfiler Produces YAML Strings with Comments

The profiler outputs YAML strings (not Pydantic objects) because it needs to embed `# REVIEW` comments inline. The user edits the YAML, then the `ContractLoader` parses the finalized version.

### D5: Migration Script is a One-Time Utility

`scripts/migrate_configs.py` reads the 14 existing YAML files and produces `contracts/pl_contract.yaml`. It is not part of the runtime agent -- it runs once during the transition.

### D6: File-Based Data Cache Preserved (Augmented)

The existing `data_cache.py` pattern (temp files for cross-agent data sharing) is preserved because ADK's module isolation makes in-memory sharing unreliable. The cache is augmented to store a serialized contract ID alongside data, so the `AnalysisContext` can be reconstructed on the receiving side.

### D7: Dual State Strategy (session.state + file cache)

ADK's `session.state` (via `output_key`) is used for lightweight coordination data (reports, analysis summaries, quality verdicts). Large data (DataFrames, CSV blobs) continues to use the file-based cache. This hybrid approach follows ADK best practices:

- **session.state**: JSON-serializable strings under 100KB. Used for agent-to-agent communication of results, decisions, and metadata.
- **File cache**: DataFrames, validated CSV data. Referenced by path in session.state (e.g., `state["analysis_context_path"] = "/tmp/pl_analyst_cache/ctx_067.json"`).

This prevents the session from becoming a bottleneck while preserving the ADK state management pattern for orchestration flow.

### D8: Agent Description as Documentation

Every agent's `description` field is written as a one-sentence capability statement, not an implementation detail. This follows the ADK guidance that descriptions are "API documentation for the LLM" when using Coordinator/Dispatcher routing:

- Good: `"Validates incoming data against the DatasetContract and produces a Go/No-Go quality report."`
- Bad: `"Runs 5 checks on a DataFrame."`

This investment pays off in Wave 3 when the Profiler/Planner uses these descriptions to decide which agents to spawn.

---

## Implementation Phases

### Phase A: Semantic Layer Foundation (US1, US2 -- P1)

**Goal**: Build `DatasetContract`, `ContractLoader`, and `AnalysisContext` as standalone, testable modules.

**Steps**:
1. Create `pl_analyst_agent/semantic/` package.
2. Implement `contract.py` -- the full Pydantic model hierarchy (see data-model.md).
3. Implement `exceptions.py` -- `ContractValidationError`, `SchemaColumnMismatchError`.
4. Implement `loader.py` -- `ContractLoader.load(path: Path) -> DatasetContract`.
5. Implement `context.py` -- `AnalysisContext(contract, df)` with all accessors.
6. Write unit tests for contract validation (valid, invalid, edge cases).
7. Write unit tests for AnalysisContext construction and accessor methods.

**Checkpoint**: `ContractLoader` can parse a hand-written YAML into a validated `DatasetContract`. `AnalysisContext` wraps a DataFrame and resolves columns by semantic name.

### Phase B: Data Quality Gate (US4 -- P2)

**Goal**: Build the universal data validation layer.

**Steps**:
1. Implement `quality_gate.py` -- `DataQualityGate.validate(df, contract) -> QualityReport`.
2. Implement 5 check classes: `TimeContinuityCheck`, `GrainUniquenessCheck`, `AdditivityCheck`, `NullThresholdCheck`, `ColumnExistenceCheck`.
3. Implement `QualityReport` model with `status`, `checks`, `violations`.
4. Write unit tests for each check class (pass/fail scenarios).
5. Write integration test: load a contract + DataFrame, run full gate.

**Checkpoint**: The gate validates P&L-shaped data against a contract and produces actionable reports.

### Phase C: P&L Config Migration (US5 -- P1)

**Goal**: Prove the semantic layer works by migrating all existing configs.

**Steps**:
1. Write `scripts/migrate_configs.py` that reads all 14 YAML configs.
2. Map `chart_of_accounts.yaml` -> contract `dimensions` + `hierarchies`.
3. Map `materiality_config.yaml` -> contract `materiality`.
4. Map `business_context.yaml` + `alert_policy.yaml` -> contract `policies`.
5. Map `ops_metrics_ratios_config.yaml` + `pl_ratios_config.yaml` -> contract `metrics` (calculated fields).
6. Map remaining configs (tier_thresholds, cost_center_to_customer, action_ownership, etc.) -> contract `policies.ownership` and `policies.patterns`.
7. Output `contracts/pl_contract.yaml`.
8. Write integration test: load `pl_contract.yaml`, construct `AnalysisContext` with sample data, verify all accessors return correct values.

**Checkpoint**: `contracts/pl_contract.yaml` exists and fully encodes the current P&L domain.

### Phase D: Sub-Agent Refactoring (US2 continuation -- P1)

**Goal**: Remove all hardcoded column names from the 8 sub-agents. Apply ADK multi-agent best practices (output_key, description, pattern alignment).

**ADK Compliance Checklist** (apply to every sub-agent):
- [ ] Add descriptive `output_key` to every agent that produces data for downstream use.
- [ ] Write a precise `description` field (one-sentence capability statement).
- [ ] Replace all hardcoded column references with `AnalysisContext` accessors.
- [ ] Ensure parallel agents write to unique state keys (no collisions).

**Steps** (per sub-agent):
1. `01_data_validation_agent/tools/` -- Replace `gl_account`, `canonical_category`, `period`, `amount` with context lookups. Replace `flip_revenue_signs` logic with contract-defined `sign_flip` flag. Set `output_key="validated_data"`. Description: `"Validates and enriches raw data against the DatasetContract, producing a clean DataFrame for analysis."`
2. `02_statistical_insights_agent/tools/` -- Replace hardcoded z-score/correlation thresholds with `context.materiality` and `context.analysis` values. Replace `str(acc).startswith('3')` with `context.metric_by_tag('revenue')`. Set `output_key="statistical_report"`. Description: `"Computes statistical summaries (YoY, MoM, moving averages, z-scores) for all material metrics."`
3. `03_hierarchy_variance_ranker_agent/` -- Replace `level_1..level_4` with `context.hierarchy_path()`. Set `output_key="hierarchy_report"`. Description: `"Ranks variance drivers by contribution across configured hierarchies."`
4. `04_report_synthesis_agent/` -- Replace 3-level structure with `max_drill_depth` from contract. Set `output_key="synthesis_report"`. Description: `"Synthesizes parallel analysis reports into a structured drill-down output."`
5. `05_alert_scoring_agent/` -- Replace hardcoded severity rules with `context.policies.severity`. Set `output_key="alert_report"`. Description: `"Scores and prioritizes alerts by financial impact, confidence, and novelty."`
6. `06_output_persistence_agent/` -- Use contract metadata for output JSON structure. Set `output_key="output_path"`. Description: `"Persists analysis results as structured JSON to the configured output directory."`
7. `07_seasonal_baseline_agent/` -- Replace hardcoded time logic with `context.time_column` and `contract.time.frequency`. Set `output_key="seasonal_report"`. Description: `"Detects seasonal patterns and baseline deviations using configured time frequency."`
8. `data_analyst_agent/` -- Replace hierarchy drill-down with `context.hierarchy_children()`. Set `output_key="drilldown_report"`. Description: `"Performs hierarchical drill-down analysis, descending through configured dimension levels."`
9. `tools/calculate_date_ranges.py` -- Replace `timedelta(days=730)` and `timedelta(days=90)` with `contract.time.range_months` and `contract.time.order_detail_months`.
10. `tools/iterate_cost_centers.py` -- Rename to `iterate_dimensions.py`. Replace `cost_center` with `context.dimension_by_role(DimensionRole.FILTER)`.
11. `utils/phase_logger.py` -- Replace `cost_center` parameter with generic `primary_dimension_value`. Log entries use dimension names from the contract.
12. `sub_agents/data_cache.py` -- Add contract ID to cache keys; store contract path in `session.state["analysis_context_path"]` for reconstruction.

**Checkpoint**: `grep -r "gl_code\|gl_account\|canonical_category\|cost_center\|miles\|loads\|stops" pl_analyst_agent/` returns zero matches (excluding comments and contract files). Every agent has a non-empty `output_key` and `description`.

### Phase E: Dataset Profiler (US3 -- P2)

**Goal**: Auto-generate draft contracts from raw data.

**Steps**:
1. Implement `profiler.py` -- `DatasetProfiler.profile(df) -> str` (YAML string).
2. Time column detection: check for datetime dtype, column names matching `date|time|timestamp|period`.
3. Metric detection: numeric columns -> `type: Additive` by default; columns with "rate", "pct", "ratio" in name or values in [0,1] -> `type: Non-Additive`.
4. Dimension detection: string/categorical columns -> dimensions. Column with most unique values -> `role: primary`.
5. Grain inference: combination of time + dimensions that produces unique rows.
6. Inject `# REVIEW` comments for uncertain fields.
7. Write unit tests with 3 sample datasets: P&L, Ops Metrics, synthetic Operational Data.

**Checkpoint**: Profiler generates draft contracts for 3 datasets with 80%+ accuracy.

### Phase F: Validation & Polish

**Goal**: End-to-end validation and documentation.

**Steps**:
1. Create `contracts/ops_data_contract.yaml` manually (or from profiler output) for the Operational Data domain.
2. Run full agent pipeline with `pl_contract.yaml` on CC 067 test data. Compare output against baseline.
3. Run full agent pipeline with `ops_data_contract.yaml` on synthetic operational data. Verify it works with zero code changes (SC-006).
4. Update `prompt.py` to remove P&L-specific language.
5. Update `README.md` with new contract-based onboarding instructions.
6. Run all tests (unit + integration). Fix failures.

**Checkpoint**: SC-001 through SC-006 all pass.

---

## Refactoring Map: Hardcoded References to Replace

| Current Hardcoded Reference | Replacement | Source |
|-----------------------------|-------------|--------|
| `df['gl_account']` / `df['gl_code']` | `df[context.dimension('gl_account')]` | `contract.dimensions[role=primary].column` |
| `df['canonical_category']` | `df[context.dimension('canonical_category')]` | `contract.dimensions[role=secondary].column` |
| `df['cost_center']` / `df['gl_cst_ctr_cd']` | `df[context.dimension('cost_center')]` | `contract.dimensions[role=filter].column` |
| `df['period']` | `df[context.time_column]` | `contract.time.column` |
| `df['amount']` | `df[context.metric('amount')]` | `contract.metrics[name=amount].column` |
| `df['miles']`, `df['loads']`, `df['stops']` | `df[context.metric('miles')]` etc. | `contract.metrics[name=miles].column` |
| `level_1..level_4` | `context.hierarchy_path('account_hierarchy')` | `contract.hierarchies[name=account_hierarchy].levels` |
| `str(acc).startswith('3')` | `context.metric_by_tag('revenue')` or contract dimension metadata | `contract.dimensions[].tags` |
| `variance_pct: 5.0`, `variance_dollar: 50000` | `context.materiality.variance_pct` | `contract.materiality.variance_pct` |
| `timedelta(days=730)` | `contract.time.range_months * 30` | `contract.time.range_months` |
| `suppress_severity_below: 0.6` | `context.policies.suppression_rules[].threshold` | `contract.policies.suppression_rules` |

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| ADK module isolation breaks AnalysisContext passing | Medium | High | Use dual state strategy (D7): lightweight JSON in session.state, DataFrames in file cache. Reconstruct context from contract path stored in state. |
| ParallelAgent state race conditions | Medium | High | Every parallel agent writes to a unique `output_key`. No two agents share a key. Unit test verifies key uniqueness at agent construction time. |
| Pydantic v2 validation too strict for flexible YAML | Low | Medium | Use `Optional` fields with sensible defaults; allow `extra='allow'` on policy sections |
| Migration misses an edge case in 4500+ GL accounts | Medium | Medium | Integration test compares migrated contract output vs baseline for CC 067 |
| Sub-agent refactoring breaks LLM prompt behavior | Medium | High | Keep prompt changes minimal. Agent descriptions follow D8 (capability statements). Context accessor names should be self-documenting for LLM consumption. |
| DatasetProfiler heuristics produce poor drafts | Low | Low | Profiler is P2 and always requires human review; 80% accuracy target is conservative |
| Session state grows too large with analysis reports | Low | Medium | Keep state values under 100KB each. Large reports stored in file cache; only summary/path written to state. |

## Complexity Tracking

No constitution violations identified. The `semantic/` package adds one new sub-package (6 files) which is justified by the core strategic direction (Wave 1 of 4).
