# Tasks: Semantic Core (Wave 1)

**Input**: Design documents from `/specs/001-semantic-core/`
**Prerequisites**: plan.md (required), spec.md (required), data-model.md (required)

**Tests**: Tests are included for all core modules (DatasetContract, AnalysisContext, DataQualityGate, DatasetProfiler) per constitution Principle II.

**Organization**: Tasks are grouped by implementation phase (A-F) from plan.md, which map to user stories from spec.md.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1-US5)
- Include exact file paths in descriptions

---

## Phase 1: Setup (Shared Infrastructure) [COMPLETED]

**Purpose**: Create the `semantic/` package skeleton and test fixtures.

- [x] T001 Create package directory `pl_analyst_agent/semantic/` with `__init__.py`
- [x] T002 [P] Create `pl_analyst_agent/semantic/exceptions.py` with `ContractValidationError`, `SchemaColumnMismatchError`, `QualityGateError`
- [x] T003 [P] Create `contracts/` directory at project root
- [x] T004 [P] Create test fixture `tests/fixtures/minimal_contract.yaml` (minimal valid DatasetContract for a generic 3-column dataset)
- [x] T005 [P] Create test fixture `tests/fixtures/invalid_contract.yaml` (missing `time`, wrong enum values, duplicate dimension names)
- [x] T006 [P] Create test fixture `tests/fixtures/sample_pl_data.csv` (50-row sample of P&L data with period, cost_center, gl_account, amount columns)
- [x] T007 [P] Create test fixture `tests/fixtures/sample_ops_data.csv` (50-row sample with date, region, latency, requests, error_rate columns)

**Checkpoint**: Package skeleton exists. Test fixtures ready.

---

## Phase 2: Foundational - DatasetContract Schema (US1) [COMPLETED]

**Purpose**: The DatasetContract Pydantic model hierarchy. Everything depends on this.

- [x] T008 [US1] Implement enum classes in `pl_analyst_agent/semantic/models.py`
- [x] T009 [US1] Implement leaf models (`TimeConfig`, `GrainConfig`, etc.) in `pl_analyst_agent/semantic/models.py`
- [x] T012 [US1] Implement top-level `DatasetContract` model in `pl_analyst_agent/semantic/models.py`
- [x] T013 [US1] Implement `DatasetContract.from_yaml(path)` in `pl_analyst_agent/semantic/models.py`
- [x] T015 [US1] Unit test: valid contract loads successfully in `pl_analyst_agent/semantic/tests/test_dataset_contract.py`
- [x] T016 [US1] Unit test: missing required fields raises error in `pl_analyst_agent/semantic/tests/test_dataset_contract.py`

**Checkpoint**: `DatasetContract` schema validates correctly. Typed Pydantic models.

---

## Phase 3: User Story 2 - AnalysisContext [COMPLETED]

**Goal**: Runtime object that wraps DataFrames with semantic accessors.

- [x] T020 [US2] Implement `AnalysisContext` frozen model in `pl_analyst_agent/semantic/models.py`
- [x] T021 [US2] Implement metric accessors (`get_metric_data`)
- [x] T022 [US2] Implement dimension accessors (`get_dimension_data`)
- [x] T030 [US2] Unit test: context is frozen in `pl_analyst_agent/semantic/tests/test_analysis_context.py`

**Checkpoint**: AnalysisContext fully functional and immutable.

---

## Phase 4: User Story 4 - Data Quality Gate [COMPLETED]

**Goal**: Universal data validation that checks any DataFrame against its DatasetContract.

- [x] T037 [US4] Implement `DataQualityGate.validate(df) -> QualityReport` in `pl_analyst_agent/semantic/quality.py`
- [x] T043 [US4] Unit test: full gate returns valid for clean data in `pl_analyst_agent/semantic/tests/test_quality_gate.py`

**Checkpoint**: DataQualityGate functional with 4 core checks (Schema, Grain, Time, Metrics).

---

## Phase 5: User Story 5 - Migration (Priority: P1) [IN PROGRESS]

**Goal**: Migrate existing YAML configs into `contracts/pl_contract.yaml`.

- [x] T052 [US5] Create `contracts/pl_contract.yaml` manually (initial version)
- [x] T053 [US5] Create `contracts/ops_contract.yaml` manually (initial version)
- [ ] T045 [US5] Write `scripts/migrate_configs.py` to automate the 14-config merge
- [ ] T054 [US5] Integration test: load `pl_contract.yaml`, build context from sample data

---

## Phase 6: User Story 2 (continued) - Sub-Agent Refactoring [IN PROGRESS]

**Goal**: Remove all hardcoded domain nouns from sub-agents.

- [x] T059 [US2] Refactor `pl_analyst_agent/agent.py`: add `ContractLoader` and `AnalysisContextInitializer`
- [x] T072 [US2] Refactor `sub_agents/data_cache.py`: add `set_analysis_context` and `get_analysis_context`
- [ ] T061 [US2] Refactor `01_data_validation_agent/`: integrate `semantic_quality_check` tool (Tool created, agent registration complete)
- [ ] T063 [US2] Refactor `03_hierarchy_variance_ranker_agent/`: `compute_level_statistics.py` partially updated to use `AnalysisContext`
- [ ] T068 [US2] Refactor `data_analyst_agent/`: replace drill-down with `context.max_drill_depth`

---

## Phase 7: User Story 3 - Dataset Profiler (Priority: P2) [PENDING]

- [ ] T077 [US3] Implement column detection heuristics in `pl_analyst_agent/semantic/profiler.py`
- [ ] T082 [US3] Implement `DatasetProfiler.profile(df) -> str` public API

---

## Phase 8: Validation & Polish [PENDING]

- [ ] T090 [US5] End-to-end test: run full agent pipeline with `pl_contract.yaml`
- [ ] T091 [US1] End-to-end test: run full agent pipeline with `ops_contract.yaml`
- [ ] T092 Update `README.md` with new semantic onboarding instructions
