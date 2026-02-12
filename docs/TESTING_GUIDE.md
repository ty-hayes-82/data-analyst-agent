# P&L Analyst Agent - Testing Guide

## Quick Start

### Run All Tests
```bash
cd C:\Streamlit\development\pl_analyst
pytest
```

### Run Sample Tests to Verify Setup
```bash
# Test the infrastructure
pytest tests/unit/test_sample_unit.py -v

# Test data pipeline
pytest tests/integration/test_sample_integration.py -v
```

## Test Infrastructure Setup

### Directory Structure
```
tests/
├── unit/              # Unit tests (individual tools/functions)
├── integration/       # Integration tests (agent pairs/chains)
├── workflow/          # Sub-workflow tests
├── e2e/              # End-to-end tests
├── edge_cases/       # Edge cases and error handling
├── performance/      # Performance tests
├── fixtures/         # Test data and fixtures
│   ├── test_data_loader.py  # Real data loader (uses PL-067-REVENUE-ONLY.csv)
│   └── mock_configs/        # Mock configuration files
└── utils/            # Test helpers
    └── test_helpers.py      # Utility functions
```

### Configuration Files
- `pytest.ini` - Pytest configuration with markers and settings
- `conftest.py` - Shared fixtures (automatically loaded by pytest)
- `tests/README.md` - Detailed test organization documentation

## Running Tests by Category

### By Test Phase
```bash
# Phase 1: Unit tests
pytest tests/unit -v

# Phase 2: Integration tests
pytest tests/integration -v

# Phase 3: Data source tests
pytest tests/integration -m requires_tableau -v

# Phase 4: Workflow tests
pytest tests/workflow -v

# Phase 5: End-to-end tests
pytest tests/e2e -v

# Phase 6: Edge cases
pytest tests/edge_cases -v
```

### By Test Markers
```bash
# Run only CSV-based tests (no external dependencies)
pytest -m csv_mode -v

# Run only unit tests
pytest -m unit -v

# Run integration tests
pytest -m integration -v

# Skip slow tests
pytest -m "not slow" -v

# Run tests that require LLM
pytest -m requires_llm -v

# Run tests that require Tableau
pytest -m requires_tableau -v
```

### By Specific Component
```bash
# Test specific agent
pytest tests/unit/test_data_validation.py -v

# Test specific tool
pytest tests/unit/test_reshape_validate.py -v

# Test specific workflow
pytest tests/workflow/test_hierarchical_drilldown.py -v
```

## Test Data

### Using Real Test Data (PL-067-REVENUE-ONLY.csv)
All fixtures automatically use the real test data file located at:
```
C:\Streamlit\development\pl_analyst\data\PL-067-REVENUE-ONLY.csv
```

The `TestDataLoader` class in `tests/fixtures/test_data_loader.py` handles:
- Loading the CSV file
- Converting wide format to time-series format
- Generating matching operational metrics
- Creating validated (P&L + ops metrics joined) data

### Available Fixtures

#### Data Fixtures
- `mock_pl_data_df` - Real P&L data from PL-067 as DataFrame
- `mock_pl_data_csv` - Real P&L data from PL-067 as CSV string
- `mock_ops_metrics_df` - Generated ops metrics as DataFrame
- `mock_ops_metrics_csv` - Generated ops metrics as CSV string
- `mock_validated_pl_data_csv` - P&L + ops metrics joined as CSV string

#### Session Fixtures
- `mock_session` - Mock ADK session object
- `mock_session_store` - Mock session store
- `populated_session_state` - Session with all required data pre-loaded

#### Utility Fixtures
- `temp_output_dir` - Temporary directory for test outputs (auto-cleanup)
- `mock_cost_center` - Test cost center ("067")
- `mock_cost_centers` - List of test cost centers
- `mock_date_ranges` - Dictionary of date ranges
- `mock_chart_of_accounts` - Chart of accounts configuration

#### Helper Fixtures
- `assert_csv_valid` - Function to validate CSV format
- `assert_json_valid` - Function to validate JSON format
- `compare_dataframes` - Function to compare DataFrames
- `performance_timer` - Timer for performance tests
- `memory_profiler` - Memory usage profiler

## Writing Tests

### Example Unit Test
```python
import pytest
from tests.utils.test_helpers import assert_dataframe_structure

@pytest.mark.unit
@pytest.mark.csv_mode
def test_my_tool(mock_pl_data_csv):
    """Test description."""
    from pl_analyst_agent.tools.my_tool import my_tool

    result = my_tool(mock_pl_data_csv)

    assert_dataframe_structure(
        result,
        required_columns=["period", "gl_account", "amount"],
        min_rows=1
    )
    assert len(result) > 0
```

### Example Integration Test
```python
import pytest

@pytest.mark.integration
@pytest.mark.csv_mode
async def test_agent_chain(populated_session_state):
    """Test agent A -> agent B chain."""
    from pl_analyst_agent.sub_agents.agent_a import agent_a
    from pl_analyst_agent.sub_agents.agent_b import agent_b

    # Run agent A
    result_a = await agent_a.run_async(populated_session_state, "test input")
    assert result_a is not None

    # Run agent B with result from A
    result_b = await agent_b.run_async(populated_session_state, result_a)
    assert result_b is not None
```

### Example E2E Test
```python
import pytest

@pytest.mark.e2e
@pytest.mark.csv_mode
@pytest.mark.slow
async def test_full_workflow(temp_output_dir):
    """Test complete workflow from request to output."""
    from pl_analyst_agent.agent import root_agent
    from google.adk.sessions import InMemorySessionStore

    session_store = InMemorySessionStore()
    session = session_store.create_session(app_name="pl_analyst")

    result = await root_agent.run_async(
        session,
        "Analyze cost center 067"
    )

    # Verify outputs were created
    assert result is not None
    # Add more assertions
```

## Test Markers Reference

| Marker | Description | Usage |
|--------|-------------|-------|
| `@pytest.mark.unit` | Unit test | Individual component testing |
| `@pytest.mark.integration` | Integration test | Multi-component testing |
| `@pytest.mark.workflow` | Workflow test | Sub-workflow testing |
| `@pytest.mark.e2e` | End-to-end test | Full system testing |
| `@pytest.mark.edge_case` | Edge case test | Error handling testing |
| `@pytest.mark.performance` | Performance test | Benchmarking |
| `@pytest.mark.slow` | Slow test (>5s) | Skip in quick runs |
| `@pytest.mark.requires_tableau` | Needs Tableau | Skip if no Tableau |
| `@pytest.mark.requires_db` | Needs SQL Server | Skip if no DB |
| `@pytest.mark.requires_llm` | Needs LLM API | Skip if no LLM |
| `@pytest.mark.csv_mode` | Uses CSV data | No external deps |

## Performance Testing

### Running Performance Tests
```bash
# Run all performance tests
pytest tests/performance -v

# Run with timing report
pytest tests/performance -v --durations=10
```

### Using Performance Fixtures
```python
@pytest.mark.performance
def test_my_performance(performance_timer, memory_profiler):
    """Test performance metrics."""
    performance_timer.start()
    memory_profiler.start()

    # ... run test ...

    memory_profiler.stop()
    performance_timer.stop()

    assert performance_timer.elapsed() < 10.0  # 10 seconds max
    assert memory_profiler.delta() < 500  # 500 MB max increase
```

## Continuous Integration

### CI/CD Configuration
Tests should:
1. Run in CSV mode (no external dependencies)
2. Complete in < 10 minutes
3. Use temporary directories for outputs
4. Clean up after themselves
5. Be deterministic and repeatable

### GitHub Actions Example
```yaml
- name: Run tests
  run: |
    pytest -m "csv_mode and not slow" -v --tb=short
```

## Troubleshooting

### Test Data Not Found
If you see `FileNotFoundError: Test data file not found`, verify:
```bash
dir "C:\Streamlit\development\pl_analyst\data\PL-067-REVENUE-ONLY.csv"
```

### Import Errors
Make sure you're running pytest from the project root:
```bash
cd C:\Streamlit\development\pl_analyst
pytest
```

### Fixture Not Found
Check that `conftest.py` is in the project root and `tests/` directory.

### Tests Not Discovered
Verify file naming conventions:
- Test files: `test_*.py` or `*_test.py`
- Test classes: `Test*`
- Test functions: `test_*`

## Coverage Reporting

### Generate Coverage Report
```bash
# Install pytest-cov if not already installed
pip install pytest-cov

# Run tests with coverage
pytest --cov=pl_analyst_agent --cov-report=html --cov-report=term-missing

# Open coverage report
start htmlcov\index.html
```

## Test Execution Log

Track test results in:
```
docs/INTEGRATION_TESTING_STATUS.md
```

Update this document after each test run with:
- Pass/fail counts
- Known issues
- Performance metrics
- Coverage percentages

## Next Steps

1. **Verify Infrastructure**: Run sample tests
   ```bash
   pytest tests/unit/test_sample_unit.py -v
   pytest tests/integration/test_sample_integration.py -v
   ```

2. **Create Unit Tests**: For each tool (30+ tools)
   - See `tests/unit/test_sample_unit.py` for examples
   - Use fixtures from `conftest.py`
   - Use helpers from `tests/utils/test_helpers.py`

3. **Create Integration Tests**: For agent chains
   - See `tests/integration/test_sample_integration.py` for examples
   - Test agent pairs and data pipelines
   - Verify state propagation

4. **Create E2E Tests**: For full workflows
   - Test complete request → output flow
   - Verify output files
   - Measure performance

5. **Track Progress**: Update `docs/INTEGRATION_TESTING_STATUS.md`
   - Mark tests as ✅, ❌, or ⚠️
   - Log issues and blockers
   - Record performance metrics
