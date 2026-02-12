#!/usr/bin/env python
"""
ADK Configuration Validator for P&L Analyst Agent

This script validates that the project structure is compatible with ADK CLI.
It checks:
1. Agent module structure (pl_analyst_agent/agent.py)
2. Root agent export exists and is valid
3. Environment configuration
4. Dependencies are installed
5. Sub-agents are properly configured

Usage:
    python scripts/validate_adk_config.py
    python scripts/validate_adk_config.py --verbose
"""

import os
import sys
from pathlib import Path
import importlib.util
import argparse
from typing import Dict, List, Tuple

# Color codes for terminal output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'


def print_success(msg: str):
    """Print success message in green."""
    print(f"{GREEN}[OK] {msg}{RESET}")


def print_error(msg: str):
    """Print error message in red."""
    print(f"{RED}[ERROR] {msg}{RESET}")


def print_warning(msg: str):
    """Print warning message in yellow."""
    print(f"{YELLOW}[WARN] {msg}{RESET}")


def print_info(msg: str):
    """Print info message in blue."""
    print(f"{BLUE}[INFO] {msg}{RESET}")


def check_agent_structure() -> Tuple[bool, str]:
    """
    Check if agent folder structure is compatible with ADK CLI.

    ADK CLI expects one of these patterns:
    - pl_analyst_agent/agent.py (with root_agent)
    - pl_analyst_agent/__init__.py (with root_agent)
    - pl_analyst_agent/root_agent.yaml

    Returns:
        (success: bool, message: str)
    """
    project_root = Path(__file__).parent.parent
    agent_dir = project_root / "pl_analyst_agent"

    if not agent_dir.exists():
        return False, f"Agent directory not found: {agent_dir}"

    agent_py = agent_dir / "agent.py"
    init_py = agent_dir / "__init__.py"
    yaml_config = agent_dir / "root_agent.yaml"

    if agent_py.exists():
        return True, f"Found agent.py at {agent_py}"
    elif init_py.exists():
        return True, f"Found __init__.py at {init_py}"
    elif yaml_config.exists():
        return True, f"Found root_agent.yaml at {yaml_config}"
    else:
        return False, "No valid agent entry point found (agent.py, __init__.py, or root_agent.yaml)"


def check_root_agent_export() -> Tuple[bool, str]:
    """
    Check if root_agent is properly exported from the module.

    Returns:
        (success: bool, message: str)
    """
    try:
        # Add project root to path
        project_root = Path(__file__).parent.parent
        sys.path.insert(0, str(project_root))

        # Try to import the agent module
        from pl_analyst_agent.agent import root_agent

        # Check if it's a BaseAgent instance
        from google.adk.agents.base_agent import BaseAgent

        if not isinstance(root_agent, BaseAgent):
            return False, f"root_agent is not a BaseAgent instance (type: {type(root_agent).__name__})"

        # Get agent properties
        agent_name = getattr(root_agent, 'name', 'Unknown')
        agent_desc = getattr(root_agent, 'description', 'No description')

        return True, f"root_agent loaded: {agent_name} ({type(root_agent).__name__})"

    except ImportError as e:
        return False, f"Failed to import root_agent: {e}"
    except Exception as e:
        return False, f"Error loading root_agent: {e}"


def check_environment_config() -> Tuple[bool, str]:
    """
    Check if .env file exists and has required variables.

    Returns:
        (success: bool, message: str)
    """
    project_root = Path(__file__).parent.parent
    env_file = project_root / ".env"
    env_example = project_root / ".env.example"

    if not env_file.exists():
        if env_example.exists():
            return False, f".env not found. Copy from .env.example: cp {env_example} {env_file}"
        else:
            return False, ".env file not found and no .env.example to copy from"

    # Check for required variables
    required_vars = [
        "GOOGLE_CLOUD_PROJECT",
        "GOOGLE_CLOUD_LOCATION",
        "ROOT_AGENT_MODEL",
    ]

    missing_vars = []
    with open(env_file, 'r') as f:
        env_content = f.read()
        for var in required_vars:
            if var not in env_content:
                missing_vars.append(var)

    if missing_vars:
        return False, f".env missing required variables: {', '.join(missing_vars)}"

    return True, f".env file found with all required variables"


def check_test_mode_data() -> Tuple[bool, str]:
    """
    Check if CSV test data exists for TEST_MODE.

    Returns:
        (success: bool, message: str)
    """
    project_root = Path(__file__).parent.parent
    csv_file = project_root / "data" / "PL-067-REVENUE-ONLY.csv"

    if not csv_file.exists():
        return False, f"CSV test data not found: {csv_file}"

    # Check file size
    file_size = csv_file.stat().st_size
    if file_size < 100:  # Less than 100 bytes is suspicious
        return False, f"CSV file exists but appears empty or corrupted (size: {file_size} bytes)"

    return True, f"CSV test data found: {csv_file} ({file_size:,} bytes)"


def check_dependencies() -> Tuple[bool, str]:
    """
    Check if required dependencies are installed.

    Returns:
        (success: bool, message: str)
    """
    required_packages = [
        ("google.adk", "google-adk"),
        ("a2a_sdk", "a2a-sdk"),
        ("pandas", "pandas"),
        ("numpy", "numpy"),
        ("yaml", "pyyaml"),
    ]

    missing_packages = []
    for module_name, package_name in required_packages:
        try:
            importlib.import_module(module_name)
        except ImportError:
            missing_packages.append(package_name)

    if missing_packages:
        return False, f"Missing packages: {', '.join(missing_packages)}. Run: pip install -r requirements.txt"

    return True, "All required dependencies installed"


def check_sub_agents() -> Tuple[bool, str]:
    """
    Check if sub-agents are properly configured.

    Returns:
        (success: bool, message: str)
    """
    project_root = Path(__file__).parent.parent
    sub_agents_dir = project_root / "pl_analyst_agent" / "sub_agents"

    if not sub_agents_dir.exists():
        return False, f"Sub-agents directory not found: {sub_agents_dir}"

    # Expected sub-agents
    expected_agents = [
        "01_data_validation_agent",
        "02_statistical_insights_agent",
        "03_hierarchy_variance_ranker_agent",
        "04_report_synthesis_agent",
        "05_alert_scoring_agent",
        "06_output_persistence_agent",
        "07_seasonal_baseline_agent",
        "data_analyst_agent",
        "testing_data_agent",
    ]

    found_agents = []
    missing_agents = []

    for agent_name in expected_agents:
        agent_path = sub_agents_dir / agent_name
        if agent_path.exists():
            # Check for agent.py or __init__.py
            if (agent_path / "agent.py").exists() or (agent_path / "__init__.py").exists():
                found_agents.append(agent_name)
            else:
                missing_agents.append(f"{agent_name} (missing agent.py/__init__.py)")
        else:
            missing_agents.append(agent_name)

    if missing_agents:
        return False, f"Missing or incomplete sub-agents: {', '.join(missing_agents)}"

    return True, f"All {len(found_agents)} sub-agents found and configured"


def check_config_files() -> Tuple[bool, str]:
    """
    Check if required config YAML files exist.

    Returns:
        (success: bool, message: str)
    """
    project_root = Path(__file__).parent.parent
    config_dir = project_root / "config"

    if not config_dir.exists():
        return False, f"Config directory not found: {config_dir}"

    required_configs = [
        "agent_models.yaml",
        "materiality_config.yaml",
        "alert_policy.yaml",
        "chart_of_accounts.yaml",
    ]

    missing_configs = []
    for config_file in required_configs:
        if not (config_dir / config_file).exists():
            missing_configs.append(config_file)

    if missing_configs:
        return False, f"Missing config files: {', '.join(missing_configs)}"

    return True, f"All {len(required_configs)} required config files found"


def check_adk_cli_available() -> Tuple[bool, str]:
    """
    Check if ADK CLI is available in the environment.

    Returns:
        (success: bool, message: str)
    """
    try:
        import subprocess
        result = subprocess.run(
            ["adk", "--version"],
            capture_output=True,
            text=True,
            timeout=5
        )

        if result.returncode == 0:
            version = result.stdout.strip()
            return True, f"ADK CLI available: {version}"
        else:
            return False, "ADK CLI command found but returned error"

    except FileNotFoundError:
        return False, "ADK CLI not found in PATH. Install: pip install google-adk"
    except subprocess.TimeoutExpired:
        return False, "ADK CLI command timed out"
    except Exception as e:
        return False, f"Error checking ADK CLI: {e}"


def main():
    """Run all validation checks."""
    parser = argparse.ArgumentParser(description="Validate ADK configuration for P&L Analyst Agent")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed output")
    args = parser.parse_args()

    print("\n" + "="*80)
    print("ADK Configuration Validator - P&L Analyst Agent")
    print("="*80 + "\n")

    checks = [
        ("Agent Folder Structure", check_agent_structure),
        ("Root Agent Export", check_root_agent_export),
        ("Environment Configuration", check_environment_config),
        ("CSV Test Data", check_test_mode_data),
        ("Dependencies", check_dependencies),
        ("Sub-Agents", check_sub_agents),
        ("Config Files", check_config_files),
        ("ADK CLI Availability", check_adk_cli_available),
    ]

    results = []
    for check_name, check_func in checks:
        print(f"Checking {check_name}...", end=" ")
        try:
            success, message = check_func()
            results.append((check_name, success, message))

            if success:
                print_success(message if args.verbose else "OK")
            else:
                print_error(message if args.verbose else "FAILED")
                if not args.verbose:
                    print(f"  └─ {message}")
        except Exception as e:
            results.append((check_name, False, f"Unexpected error: {e}"))
            print_error(f"ERROR: {e}")

    # Summary
    print("\n" + "="*80)
    total_checks = len(results)
    passed_checks = sum(1 for _, success, _ in results if success)
    failed_checks = total_checks - passed_checks

    if failed_checks == 0:
        print_success(f"All {total_checks} checks passed!")
        print_info("\nYour project is ready to run with ADK CLI:")
        print_info("  $ adk run pl_analyst_agent")
        print("="*80 + "\n")
        return 0
    else:
        print_warning(f"{passed_checks}/{total_checks} checks passed, {failed_checks} failed")
        print_error("\nPlease fix the issues above before running with ADK CLI")
        print("="*80 + "\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
