"""
Verification script for test infrastructure.

This script checks that all test infrastructure components are properly set up:
- Test directories exist
- Configuration files are valid
- Test data can be loaded
- Fixtures work correctly
- Sample tests can run
"""

import sys
from pathlib import Path
import subprocess

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def print_header(text):
    """Print a formatted header."""
    print(f"\n{'='*70}")
    print(f"  {text}")
    print(f"{'='*70}\n")


def print_success(text):
    """Print a success message."""
    print(f"[PASS] {text}")


def print_error(text):
    """Print an error message."""
    print(f"[FAIL] {text}")


def print_info(text):
    """Print an info message."""
    print(f"[INFO] {text}")


def check_directories():
    """Check that all test directories exist."""
    print_header("Checking Test Directories")

    required_dirs = [
        "tests",
        "tests/unit",
        "tests/integration",
        "tests/workflow",
        "tests/e2e",
        "tests/edge_cases",
        "tests/performance",
        "tests/fixtures",
        "tests/fixtures/mock_data",
        "tests/fixtures/mock_configs",
        "tests/utils",
    ]

    all_exist = True
    for dir_path in required_dirs:
        full_path = project_root / dir_path
        if full_path.exists():
            print_success(f"{dir_path}")
        else:
            print_error(f"{dir_path} - NOT FOUND")
            all_exist = False

    return all_exist


def check_config_files():
    """Check that configuration files exist and are valid."""
    print_header("Checking Configuration Files")

    config_files = [
        "pytest.ini",
        "conftest.py",
        "tests/README.md",
        "tests/__init__.py",
        "tests/utils/__init__.py",
        "tests/utils/test_helpers.py",
        "tests/fixtures/__init__.py",
        "tests/fixtures/test_data_loader.py",
    ]

    all_exist = True
    for file_path in config_files:
        full_path = project_root / file_path
        if full_path.exists():
            print_success(f"{file_path} ({full_path.stat().st_size} bytes)")
        else:
            print_error(f"{file_path} - NOT FOUND")
            all_exist = False

    return all_exist


def check_test_data():
    """Check that test data file exists and can be loaded."""
    print_header("Checking Test Data")

    test_data_path = project_root / "data" / "PL-067-REVENUE-ONLY.csv"

    if not test_data_path.exists():
        print_error(f"Test data file not found: {test_data_path}")
        return False

    print_success(f"Test data file exists: {test_data_path}")
    print_info(f"  File size: {test_data_path.stat().st_size:,} bytes")

    # Try to load it
    try:
        from tests.fixtures.test_data_loader import TestDataLoader

        loader = TestDataLoader()

        # Load as DataFrame
        df = loader.load_pl_067_csv()
        print_success(f"Loaded DataFrame: {len(df)} rows × {len(df.columns)} columns")

        # Convert to time series
        df_ts = loader.convert_to_time_series_format(df)
        print_success(f"Converted to time series: {len(df_ts)} rows")

        # Get ops metrics
        ops_df = loader.get_mock_ops_metrics()
        print_success(f"Generated ops metrics: {len(ops_df)} periods")

        # Get validated data
        validated_csv = loader.get_validated_pl_data_csv()
        print_success(f"Generated validated data: {len(validated_csv)} chars")

        return True

    except Exception as e:
        print_error(f"Failed to load test data: {e}")
        return False


def check_fixtures():
    """Check that pytest fixtures work correctly."""
    print_header("Checking Pytest Fixtures")

    try:
        # Import conftest to trigger fixture registration
        import conftest

        print_success("conftest.py imported successfully")

        # Try to use test helpers
        from tests.utils.test_helpers import (
            assert_dataframe_structure,
            assert_csv_format_valid,
            assert_json_structure
        )

        print_success("Test helpers imported successfully")

        # Try to use test data loader
        from tests.fixtures.test_data_loader import (
            load_test_pl_data,
            load_test_time_series_df
        )

        print_success("Test data loader imported successfully")

        return True

    except Exception as e:
        print_error(f"Failed to load fixtures: {e}")
        return False


def run_sample_tests():
    """Run sample tests to verify infrastructure works."""
    print_header("Running Sample Tests")

    # Check if sample tests exist
    sample_unit_test = project_root / "tests" / "unit" / "test_sample_unit.py"
    sample_integration_test = project_root / "tests" / "integration" / "test_sample_integration.py"

    if not sample_unit_test.exists():
        print_error("Sample unit test not found")
        return False

    if not sample_integration_test.exists():
        print_error("Sample integration test not found")
        return False

    # Run unit tests
    print_info("Running sample unit tests...")
    result_unit = subprocess.run(
        ["pytest", str(sample_unit_test), "-v", "--tb=short"],
        cwd=project_root,
        capture_output=True,
        text=True
    )

    if result_unit.returncode == 0:
        print_success("Sample unit tests PASSED")
        # Count passed tests
        passed_count = result_unit.stdout.count(" PASSED")
        print_info(f"  {passed_count} tests passed")
    else:
        print_error("Sample unit tests FAILED")
        print(result_unit.stdout)
        print(result_unit.stderr)
        return False

    # Run integration tests
    print_info("Running sample integration tests...")
    result_integration = subprocess.run(
        ["pytest", str(sample_integration_test), "-v", "--tb=short"],
        cwd=project_root,
        capture_output=True,
        text=True
    )

    if result_integration.returncode == 0:
        print_success("Sample integration tests PASSED")
        passed_count = result_integration.stdout.count(" PASSED")
        print_info(f"  {passed_count} tests passed")
    else:
        print_error("Sample integration tests FAILED")
        print(result_integration.stdout)
        print(result_integration.stderr)
        return False

    return True


def print_summary(results):
    """Print a summary of verification results."""
    print_header("Verification Summary")

    total_checks = len(results)
    passed_checks = sum(results.values())
    failed_checks = total_checks - passed_checks

    for check_name, passed in results.items():
        status = "[PASS]" if passed else "[FAIL]"
        print(f"{status}  {check_name}")

    print(f"\n{'='*70}")
    print(f"Total: {passed_checks}/{total_checks} checks passed")

    if failed_checks == 0:
        print_success("All verification checks passed!")
        print_info("Test infrastructure is ready to use.")
        print_info("")
        print_info("Next steps:")
        print_info("1. Run: pytest tests/unit/test_sample_unit.py -v")
        print_info("2. Run: pytest tests/integration/test_sample_integration.py -v")
        print_info("3. Start writing tests for individual tools and agents")
        print_info("4. Update docs/INTEGRATION_TESTING_STATUS.md with progress")
        return True
    else:
        print_error(f"{failed_checks} verification checks failed")
        print_info("Please fix the issues above before proceeding.")
        return False


def main():
    """Run all verification checks."""
    print_header("P&L Analyst Agent - Test Infrastructure Verification")
    print_info(f"Project root: {project_root}")

    results = {
        "Test Directories": check_directories(),
        "Configuration Files": check_config_files(),
        "Test Data": check_test_data(),
        "Pytest Fixtures": check_fixtures(),
        "Sample Tests": run_sample_tests(),
    }

    success = print_summary(results)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
