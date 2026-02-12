# Feature Specification: Semantic Core (Wave 1)

**Feature Branch**: `001-semantic-core`  
**Created**: 2025-02-12  
**Status**: Draft  
**Input**: Transform the P&L Analyst Agent into a Universal Operational Insights Agent by replacing all hardcoded domain nouns with a configuration-driven Semantic Layer.

## Vision

Decouple the **mechanism of analysis** (code) from the **meaning of the data** (configuration). The agent should analyze any tabular operational dataset -- Finance, DevOps, Sales, Supply Chain -- without code changes, driven entirely by a `DatasetContract` configuration.

**Approach**: Clean break. The existing P&L-specific agent will be replaced, not wrapped. All 14 existing YAML configs (`chart_of_accounts.yaml`, `materiality_config.yaml`, `business_context.yaml`, `alert_policy.yaml`, etc.) will be migrated into the first `DatasetContract` instance.

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Define a DatasetContract for Any Domain (Priority: P1)

As a data engineer, I can create a YAML `DatasetContract` that fully describes a new dataset (time column, grain, metrics, dimensions, hierarchies, materiality thresholds, and policies) so that the agent can analyze it without code changes.

**Why this priority**: Everything downstream (AnalysisContext, Data Quality Gate, and all future Waves) depends on this schema existing. Without a contract, the agent cannot function.

**Independent Test**: Create a minimal contract for a non-P&L dataset (e.g., web latency metrics). Load it via the `ContractLoader`. Verify all fields parse correctly and that the `DatasetContract` Pydantic model validates.

**Acceptance Scenarios**:

1. **Given** a YAML file conforming to the DatasetContract schema, **When** the ContractLoader parses it, **Then** a validated `DatasetContract` Pydantic object is returned with all fields populated.
2. **Given** a YAML file missing required fields (e.g., no `time` column), **When** the ContractLoader parses it, **Then** a `ContractValidationError` is raised listing all missing/invalid fields.
3. **Given** the existing P&L configs (chart_of_accounts.yaml, materiality_config.yaml, alert_policy.yaml, business_context.yaml), **When** the migration script runs, **Then** a single `pl_contract.yaml` DatasetContract is produced that encodes all existing behavior.

---

### User Story 2 - AnalysisContext Replaces Raw DataFrames (Priority: P1)

As the orchestration agent, I receive an `AnalysisContext` object instead of raw DataFrames, so that all sub-agents reference columns by semantic role (e.g., `context.schema.dimensions['primary']`) instead of hardcoded names (e.g., `df['gl_code']`).

**Why this priority**: This is the refactoring keystone. Every sub-agent (01-07) currently uses hardcoded column names. The `AnalysisContext` is required before any sub-agent can become domain-agnostic.

**Independent Test**: Construct an `AnalysisContext` from the migrated P&L contract + a sample DataFrame. Verify that `context.metric('Revenue')` returns the correct column, that `context.dimension('primary')` resolves to `gl_code`, and that `context.hierarchy_children('level_1')` returns `['level_2']`.

**Acceptance Scenarios**:

1. **Given** a loaded `DatasetContract` and a pandas DataFrame, **When** an `AnalysisContext` is constructed, **Then** it exposes `.metric(name)`, `.dimension(name)`, `.hierarchy_children(level)`, `.time_column`, `.grain_columns`, and `.materiality` accessors.
2. **Given** an `AnalysisContext` for the P&L contract, **When** a sub-agent calls `context.metric('Revenue')`, **Then** it returns the column name `'3100-00'` (or the configured metric column), not a hardcoded string.
3. **Given** an `AnalysisContext`, **When** a sub-agent calls `context.hierarchy_path()`, **Then** it returns `['level_1', 'level_2', 'level_3', 'level_4']` as defined in the contract's `hierarchies` section.

---

### User Story 3 - Auto-Profile Datasets to Draft Contracts (Priority: P2)

As a data engineer onboarding a new dataset, I can run the `DatasetProfiler` on a CSV/DataFrame and receive a **draft** DatasetContract with inferred time columns, metrics, dimensions, and grain, which I then review and finalize.

**Why this priority**: Manual contract authoring is slow and error-prone. Auto-profiling accelerates onboarding of new domains (especially for the Operational Data validation domain).

**Independent Test**: Feed a sample ops-metrics CSV (with columns like `date`, `cost_center`, `miles`, `loads`, `stops`, `revenue`) into the profiler. Verify the draft contract correctly identifies `date` as time, numeric columns as metrics, and string columns as dimensions.

**Acceptance Scenarios**:

1. **Given** a pandas DataFrame with mixed column types, **When** the `DatasetProfiler.profile(df)` is called, **Then** a draft `DatasetContract` YAML is produced with `time`, `metrics`, and `dimensions` sections populated.
2. **Given** a DataFrame with a `date` column and numeric columns, **When** the profiler runs, **Then** it infers `type: Additive` for summable metrics and `type: Non-Additive` for ratio-like columns (detected via heuristic: values between 0-1 or column name contains "rate", "pct", "ratio").
3. **Given** a profiled draft, **When** the user reviews it, **Then** the draft includes `# REVIEW` comments on any field the profiler was uncertain about (e.g., ambiguous grain, unclear optimization direction).

---

### User Story 4 - Data Quality Gate (Priority: P2)

As the orchestration agent, before any analysis runs, a `DataQualityGate` validates the incoming data against the `DatasetContract` and returns a Go/No-Go signal, so that downstream agents never operate on invalid data.

**Why this priority**: Prevents silent failures. Currently, data validation is P&L-specific (checking for period completeness, GL code presence). The universal gate must validate against the contract generically.

**Independent Test**: Create a test DataFrame that violates the contract (e.g., duplicate grain rows, gaps in the time series, non-additive metric that doesn't sum). Verify the gate returns `No-Go` with a structured list of violations.

**Acceptance Scenarios**:

1. **Given** a DataFrame and a DatasetContract, **When** the `DataQualityGate.validate(df, contract)` runs, **Then** it returns a `QualityReport` with `status` (GO/NO_GO/WARNING), `checks` (list of pass/fail), and `violations` (list of issues).
2. **Given** a time column defined as `frequency: monthly`, **When** the DataFrame has gaps (e.g., missing March 2025), **Then** the gate flags `TimeContinuityViolation` with the missing periods listed.
3. **Given** a metric marked `type: Additive`, **When** the DataFrame contains rows where child values don't sum to parent, **Then** the gate flags `AdditivityViolation` with the discrepant rows.
4. **Given** a grain defined as `['date', 'cost_center', 'gl_code']`, **When** duplicate rows exist for the same grain, **Then** the gate flags `GrainUniquenessViolation`.
5. **Given** all checks pass, **When** the gate runs, **Then** it returns `status: GO` and logs duration + record count per the constitution's observability requirements.

---

### User Story 5 - Migrate All Existing P&L Configs into First DatasetContract (Priority: P1)

As the development team, we migrate the 14 existing YAML configs into a single `pl_contract.yaml` that the refactored agent uses, proving the semantic layer works for the existing P&L domain.

**Why this priority**: This is the proof-of-concept. If the migrated contract can reproduce the current agent's behavior for P&L data, the abstraction is validated.

**Independent Test**: Run the migrated agent on cost center 067 with the same test data. Compare the output JSON structure and key variance numbers against the current agent's output. They must match within rounding tolerance.

**Acceptance Scenarios**:

1. **Given** the existing `chart_of_accounts.yaml`, **When** migrated, **Then** the contract's `dimensions` section contains `gl_code` as primary, `canonical_category` as secondary, and `hierarchies` encodes `level_1 -> level_2 -> level_3 -> level_4`.
2. **Given** the existing `materiality_config.yaml`, **When** migrated, **Then** the contract's `materiality` section contains `variance_pct: 5.0`, `variance_dollar: 50000`, `top_categories_count: 5`, `cumulative_variance_pct: 80`.
3. **Given** the existing `business_context.yaml` and `alert_policy.yaml`, **When** migrated, **Then** the contract's `policies` section encodes known patterns, suppression rules, severity thresholds, and ownership mappings.
4. **Given** the migrated `pl_contract.yaml`, **When** the agent analyzes CC 067, **Then** the 3-level output (Executive -> Category -> GL) matches the current agent's output structure.

---

### Edge Cases

- What happens when a DatasetContract references a column that doesn't exist in the DataFrame? -> `AnalysisContext` constructor raises `SchemaColumnMismatchError`.
- How does the system handle a contract with no hierarchies defined? -> The Contribution Tree (Wave 2) skips recursive drill-down; analysis runs flat on the primary dimension only.
- What happens when the profiler encounters a DataFrame with no obvious time column? -> Draft contract omits `time` and adds a `# REVIEW: No time column detected` comment. The `DataQualityGate` will flag this as `NO_GO` if time-series analysis is requested.
- What happens when metric `optimization` direction is ambiguous (e.g., "Headcount")? -> Profiler defaults to `null` with a `# REVIEW` comment; the contract author must specify.

---

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST define a `DatasetContract` Pydantic schema with sections: `time`, `grain`, `metrics`, `dimensions`, `hierarchies`, `materiality`, and `policies`.
- **FR-002**: Each metric in the contract MUST specify: `name`, `column`, `type` (Additive | Non-Additive), `format` (Currency | Percent | Integer | Decimal), and `optimization` (Maximize | Minimize | null).
- **FR-003**: Each dimension MUST specify: `name`, `column`, and `role` (primary | secondary | filter).
- **FR-004**: Hierarchies MUST be expressed as ordered lists of dimension names representing parent-child relationships (e.g., `[level_1, level_2, level_3, level_4]`).
- **FR-005**: The `AnalysisContext` class MUST provide accessor methods: `.metric(name)`, `.dimension(name)`, `.hierarchy_path(name)`, `.hierarchy_children(level)`, `.time_column`, `.grain_columns`, `.materiality`.
- **FR-006**: The `AnalysisContext` constructor MUST validate that all contract columns exist in the DataFrame at construction time.
- **FR-007**: The `DataQualityGate` MUST check: time continuity, grain uniqueness, metric additivity (where declared), null percentage thresholds, and column existence.
- **FR-008**: The `DataQualityGate` MUST return a structured `QualityReport` (Go/No-Go/Warning + check details).
- **FR-009**: The `DatasetProfiler` MUST auto-detect time columns, numeric metrics, and categorical dimensions from a raw DataFrame.
- **FR-010**: The `DatasetProfiler` MUST annotate uncertain inferences with `# REVIEW` comments in the draft YAML.
- **FR-011**: The `ContractLoader` MUST support loading contracts from YAML files by path.
- **FR-012**: The system MUST include a migration utility that converts the existing 14 YAML configs into a single `pl_contract.yaml`.
- **FR-013**: `max_drill_depth` MUST be configurable per contract (default: 5) to control recursive analysis depth in Wave 2.
- **FR-014**: The contract's `policies` section MUST support: known patterns, suppression rules, severity thresholds, root cause types, and ownership mappings (migrated from current YAML configs).

### Key Entities

- **DatasetContract**: The central configuration object. Defines the semantic layer for a single dataset. One YAML file per dataset.
- **AnalysisContext**: Runtime object constructed from a `DatasetContract` + a DataFrame. Passed to all sub-agents instead of raw DataFrames.
- **DataQualityGate**: Validation module. Checks data against the contract before analysis.
- **QualityReport**: Output of the Data Quality Gate. Contains status, checks, and violations.
- **DatasetProfiler**: Utility that auto-generates draft contracts from raw DataFrames.
- **ContractLoader**: Loads and validates `DatasetContract` from YAML files.

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The `DatasetContract` schema validates all 14 existing P&L configs when migrated into a single `pl_contract.yaml` -- zero fields lost.
- **SC-002**: The `AnalysisContext` eliminates 100% of hardcoded column references (`gl_code`, `canonical_category`, `cost_center`, `miles`, `loads`, `stops`) from all sub-agents.
- **SC-003**: The `DataQualityGate` catches at least 5 classes of data defects (time gaps, duplicate grains, non-additive violations, null thresholds, missing columns) with zero false negatives on the existing test data.
- **SC-004**: The `DatasetProfiler` correctly infers time, metrics, and dimensions for at least 3 sample datasets (P&L, Ops Metrics, and a synthetic Operational Data dataset) with 80%+ field accuracy before human review.
- **SC-005**: The refactored agent, using the migrated `pl_contract.yaml`, produces output for CC 067 that matches the current agent's output within 1% variance tolerance on all dollar and percentage values.
- **SC-006**: A new domain (Operational Data) can be onboarded by creating a single YAML contract file + providing data, with zero Python code changes.
