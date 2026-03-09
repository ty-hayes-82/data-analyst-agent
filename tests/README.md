# Data Analyst Agent Test Suite

## Directory Structure

```
tests/
├── unit/              # Unit tests for individual tools and functions
├── integration/       # Integration tests for agent pairs and chains
├── workflow/          # Sub-workflow tests (drill-down, alerts, multi-CC)
├── e2e/              # End-to-end full system tests
├── edge_cases/       # Edge cases and error handling
├── performance/      # Performance and load tests
├── fixtures/         # Mock data and test fixtures
│   ├── mock_data/   # CSV, JSON mock data files
│   └── mock_configs/ # Test configuration files
└── utils/            # Test helper utilities
    └── test_helpers.py  # Common test functions
```

## Test Organization Principles

1. **One test file per component** - Each agent or tool gets its own test file
2. **Clear naming convention** - `test_<component_name>.py`
3. **Organized by test type** - Tests grouped by unit/integration/e2e/etc
4. **Shared fixtures** - Common fixtures in root `conftest.py`
5. **No duplication** - Reuse fixtures and helpers

## Running Tests

```bash
# Run all tests
pytest

# Run by phase/type
pytest tests/unit                 # Unit tests only
pytest tests/integration          # Integration tests only
pytest tests/e2e                  # End-to-end tests only

# Run by marker
pytest -m unit                    # All unit tests
pytest -m integration             # All integration tests
pytest -m "not slow"              # Skip slow tests
pytest -m "csv_mode"              # CSV-based tests only

# Run with coverage
pytest --cov=data_analyst_agent --cov-report=html
```

## Test Markers

- `@pytest.mark.unit` - Unit test
- `@pytest.mark.integration` - Integration test
- `@pytest.mark.workflow` - Workflow test
- `@pytest.mark.e2e` - End-to-end test
- `@pytest.mark.edge_case` - Edge case test
- `@pytest.mark.performance` - Performance test
- `@pytest.mark.slow` - Test takes > 5 seconds
- `@pytest.mark.requires_tableau` - Needs Tableau A2A
- `@pytest.mark.requires_db` - Needs SQL Server
- `@pytest.mark.requires_llm` - Needs LLM API
- `@pytest.mark.csv_mode` - Uses CSV test data

## Migration from Root-Level Tests

Migration from root-level test files to the organized `tests/` structure is complete.
All tests now live under `tests/unit/`, `tests/integration/`, `tests/workflow/`, `tests/e2e/`, or `tests/performance/`.

## Writing New Tests

### Example Unit Test

```python
import pytest
from tests.utils.test_helpers import assert_dataframe_structure

@pytest.mark.unit
def test_compute_statistical_summary(mock_pl_data_csv):
    """Test the compute_statistical_summary tool."""
    from data_analyst_agent.sub_agents.statistical_insights_agent.tools.compute_statistical_summary import compute_statistical_summary
    # ... test implementation ...
```

### Example Integration Test

```python
import pytest

@pytest.mark.integration
@pytest.mark.csv_mode
async def test_analysis_context_initialization(ops_metrics_contract):
    """Test AnalysisContext initialization with a dataset contract."""
    from data_analyst_agent.semantic.models import AnalysisContext
    ctx = AnalysisContext(
        contract=ops_metrics_contract,
        df=mock_df,
        target_metric=ops_metrics_contract.metrics[0],
        primary_dimension=ops_metrics_contract.dimensions[0],
        run_id="test",
    )
    assert ctx.contract.name == ops_metrics_contract.name
    # Test implementation
    pass
```

### Example E2E Test

```python
import pytest

@pytest.mark.e2e
@pytest.mark.csv_mode
@pytest.mark.slow
async def test_single_cc_full_workflow(mock_cost_center, temp_output_dir):
    """Test full workflow from request to output files."""
    # Test implementation
    pass
```

## Test Data Management

- **Mock data** is generated via fixtures in `conftest.py`
- **Static test files** go in `tests/fixtures/mock_data/`
- **Use CSV mode** (`DATA_ANALYST_TEST_MODE=true`) to avoid external dependencies
- **Reuse fixtures** instead of generating data in each test

## Performance Testing

Performance tests should measure:
- Execution time (must be < baseline target)
- Memory usage (must be < 2GB peak)
- Success rate (must be > 95%)

Use the `performance_timer` and `memory_profiler` fixtures.

## Continuous Integration

All tests should:
- Run without external dependencies in CSV mode
- Complete in < 10 minutes total
- Have no side effects (use temp directories)
- Clean up after themselves

## Reporting Issues

Use the `docs/INTEGRATION_TESTING_STATUS.md` document to track:
- Test pass/fail status
- Known issues and blockers
- Performance metrics
- Coverage percentages
