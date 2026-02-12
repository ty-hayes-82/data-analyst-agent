#!/usr/bin/env python
"""
Agent Health Checker for P&L Analyst Agent

This script performs health checks on all agents:
1. Verifies agent imports work correctly
2. Checks agent configuration and model assignments
3. Validates sub-agent dependencies
4. Tests A2A agent connectivity (if not in TEST_MODE)
5. Validates configuration files

Usage:
    python scripts/check_agent_health.py
    python scripts/check_agent_health.py --skip-a2a  # Skip A2A connectivity checks
    python scripts/check_agent_health.py --verbose
"""

import os
import sys
import argparse
from pathlib import Path
from typing import Dict, List, Tuple, Any
import importlib
import yaml

# Color codes for terminal output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
CYAN = '\033[96m'
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


def print_section(msg: str):
    """Print section header in cyan."""
    print(f"\n{CYAN}{'='*80}")
    print(f"{msg}")
    print(f"{'='*80}{RESET}\n")


def load_agent_models_config() -> Dict[str, Any]:
    """Load agent model tier configurations."""
    project_root = Path(__file__).parent.parent
    config_file = project_root / "config" / "agent_models.yaml"

    if not config_file.exists():
        print_error(f"agent_models.yaml not found at {config_file}")
        return {}

    with open(config_file, 'r') as f:
        return yaml.safe_load(f)


def check_root_agent() -> Tuple[bool, Dict[str, Any]]:
    """
    Check root agent health.

    Returns:
        (success: bool, details: dict)
    """
    try:
        project_root = Path(__file__).parent.parent
        sys.path.insert(0, str(project_root))

        from pl_analyst_agent.agent import root_agent
        from google.adk.agents.base_agent import BaseAgent

        if not isinstance(root_agent, BaseAgent):
            return False, {"error": f"root_agent is not BaseAgent (type: {type(root_agent).__name__})"}

        details = {
            "name": root_agent.name,
            "type": type(root_agent).__name__,
            "description": root_agent.description[:100] + "..." if len(root_agent.description) > 100 else root_agent.description,
        }

        # For SequentialAgent, check sub-agents
        if hasattr(root_agent, 'sub_agents'):
            details["sub_agent_count"] = len(root_agent.sub_agents)
            details["sub_agents"] = [
                getattr(agent, 'name', 'Unknown')
                for agent in root_agent.sub_agents
            ]

        return True, details

    except Exception as e:
        return False, {"error": str(e)}


def check_sub_agents() -> Tuple[bool, List[Dict[str, Any]]]:
    """
    Check all sub-agents can be imported and configured correctly.

    Returns:
        (all_success: bool, agent_details: list)
    """
    sub_agents = [
        ("01_data_validation_agent", "pl_analyst_agent.sub_agents.01_data_validation_agent.agent"),
        ("02_statistical_insights_agent", "pl_analyst_agent.sub_agents.02_statistical_insights_agent.agent"),
        ("03_hierarchy_variance_ranker_agent", "pl_analyst_agent.sub_agents.03_hierarchy_variance_ranker_agent.agent"),
        ("04_report_synthesis_agent", "pl_analyst_agent.sub_agents.04_report_synthesis_agent.agent"),
        ("05_alert_scoring_agent", "pl_analyst_agent.sub_agents.05_alert_scoring_agent.agent"),
        ("06_output_persistence_agent", "pl_analyst_agent.sub_agents.06_output_persistence_agent"),
        ("07_seasonal_baseline_agent", "pl_analyst_agent.sub_agents.07_seasonal_baseline_agent.agent"),
        ("data_analyst_agent", "pl_analyst_agent.sub_agents.data_analyst_agent"),
        ("testing_data_agent", "pl_analyst_agent.sub_agents.testing_data_agent.agent"),
    ]

    results = []
    all_success = True

    for agent_name, module_path in sub_agents:
        try:
            # Import the module
            module = importlib.import_module(module_path)

            # Look for root_agent or the class
            if hasattr(module, 'root_agent'):
                agent = module.root_agent
                agent_type = type(agent).__name__
            elif agent_name == "06_output_persistence_agent" and hasattr(module, 'OutputPersistenceAgent'):
                agent = module.OutputPersistenceAgent
                agent_type = "OutputPersistenceAgent (class)"
            else:
                all_success = False
                results.append({
                    "name": agent_name,
                    "success": False,
                    "error": "No root_agent or expected class found"
                })
                continue

            # Get agent details
            details = {
                "name": agent_name,
                "success": True,
                "type": agent_type,
                "module": module_path,
            }

            # Try to get description if available
            if hasattr(agent, 'description'):
                details["description"] = agent.description[:80] + "..." if len(agent.description) > 80 else agent.description
            elif hasattr(agent, '__doc__') and agent.__doc__:
                details["description"] = agent.__doc__.strip().split('\n')[0][:80]

            results.append(details)

        except Exception as e:
            all_success = False
            results.append({
                "name": agent_name,
                "success": False,
                "error": str(e)
            })

    return all_success, results


def check_model_tier_assignments() -> Tuple[bool, Dict[str, Any]]:
    """
    Check model tier assignments from agent_models.yaml.

    Returns:
        (success: bool, details: dict)
    """
    try:
        config = load_agent_models_config()

        if not config:
            return False, {"error": "Failed to load agent_models.yaml"}

        model_tiers = config.get("model_tiers", {})
        agents_config = config.get("agents", {})

        if not model_tiers:
            return False, {"error": "No model_tiers defined in config"}

        if not agents_config:
            return False, {"error": "No agents defined in config"}

        # Validate all agents have valid tier assignments
        invalid_agents = []
        for agent_name, agent_config in agents_config.items():
            tier = agent_config.get("tier")
            if tier not in model_tiers:
                invalid_agents.append(f"{agent_name} (tier: {tier})")

        details = {
            "model_tiers": model_tiers,
            "total_agents_configured": len(agents_config),
            "tiers_defined": list(model_tiers.keys()),
        }

        if invalid_agents:
            details["invalid_agents"] = invalid_agents
            return False, details

        # Count agents per tier
        tier_counts = {}
        for agent_config in agents_config.values():
            tier = agent_config.get("tier", "unknown")
            tier_counts[tier] = tier_counts.get(tier, 0) + 1

        details["agents_per_tier"] = tier_counts
        return True, details

    except Exception as e:
        return False, {"error": str(e)}


def check_a2a_agents(timeout: int = 5) -> Tuple[bool, Dict[str, Any]]:
    """
    Check A2A agent connectivity (only in non-TEST_MODE).

    Args:
        timeout: HTTP request timeout in seconds

    Returns:
        (success: bool, details: dict)
    """
    # Check if in TEST_MODE
    test_mode = os.environ.get("PL_ANALYST_TEST_MODE", "false").lower() == "true"

    if test_mode:
        return True, {
            "skipped": True,
            "reason": "PL_ANALYST_TEST_MODE=true (A2A agents not used in test mode)"
        }

    try:
        project_root = Path(__file__).parent.parent
        sys.path.insert(0, str(project_root))

        from pl_analyst_agent.agent import verify_tableau_agents

        results = verify_tableau_agents(timeout=timeout)

        all_accessible = results.get("accessible", False)
        agent_details = results.get("agents", {})

        details = {
            "all_accessible": all_accessible,
            "agents": {}
        }

        for agent_name, agent_status in agent_details.items():
            details["agents"][agent_name] = {
                "http_status": agent_status.get("http_status"),
                "card_valid": agent_status.get("card_valid"),
                "instance_valid": agent_status.get("instance_valid"),
                "error": agent_status.get("error"),
            }

        return all_accessible, details

    except Exception as e:
        return False, {"error": str(e)}


def check_config_files() -> Tuple[bool, List[Dict[str, Any]]]:
    """
    Validate all configuration YAML files.

    Returns:
        (all_valid: bool, file_details: list)
    """
    project_root = Path(__file__).parent.parent
    config_dir = project_root / "config"

    config_files = [
        "agent_models.yaml",
        "materiality_config.yaml",
        "alert_policy.yaml",
        "chart_of_accounts.yaml",
        "tier_thresholds.yaml",
        "business_context.yaml",
        "action_items.yaml",
        "action_ownership.yaml",
        "cost_center_to_customer.yaml",
        "phase_logging.yaml",
    ]

    results = []
    all_valid = True

    for config_file in config_files:
        file_path = config_dir / config_file
        details = {"file": config_file}

        if not file_path.exists():
            all_valid = False
            details["exists"] = False
            details["error"] = "File not found"
        else:
            try:
                with open(file_path, 'r') as f:
                    config_data = yaml.safe_load(f)

                details["exists"] = True
                details["valid_yaml"] = True
                details["size_bytes"] = file_path.stat().st_size

                # Count top-level keys
                if isinstance(config_data, dict):
                    details["keys"] = len(config_data)

            except yaml.YAMLError as e:
                all_valid = False
                details["exists"] = True
                details["valid_yaml"] = False
                details["error"] = f"Invalid YAML: {e}"
            except Exception as e:
                all_valid = False
                details["exists"] = True
                details["error"] = str(e)

        results.append(details)

    return all_valid, results


def main():
    """Run all health checks."""
    parser = argparse.ArgumentParser(description="Check agent health for P&L Analyst Agent")
    parser.add_argument("--skip-a2a", action="store_true", help="Skip A2A connectivity checks")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed output")
    args = parser.parse_args()

    print("\n" + "="*80)
    print("Agent Health Checker - P&L Analyst Agent")
    print("="*80)

    all_checks_passed = True

    # 1. Check Root Agent
    print_section("1. Root Agent Health")
    success, details = check_root_agent()
    if success:
        print_success(f"Root agent loaded: {details['name']}")
        if args.verbose:
            print(f"  Type: {details['type']}")
            print(f"  Description: {details['description']}")
            if 'sub_agent_count' in details:
                print(f"  Sub-agents: {details['sub_agent_count']}")
                if args.verbose:
                    for sub_agent in details.get('sub_agents', []):
                        print(f"    - {sub_agent}")
    else:
        print_error(f"Root agent check failed: {details.get('error')}")
        all_checks_passed = False

    # 2. Check Sub-Agents
    print_section("2. Sub-Agent Health")
    success, agent_details = check_sub_agents()
    if success:
        print_success(f"All {len(agent_details)} sub-agents loaded successfully")
        if args.verbose:
            for agent in agent_details:
                print(f"    [OK] {agent['name']} ({agent['type']})")
                if 'description' in agent:
                    print(f"      {agent['description']}")
    else:
        failed_agents = [a for a in agent_details if not a.get('success', True)]
        print_error(f"{len(failed_agents)} sub-agent(s) failed to load")
        for agent in failed_agents:
            print(f"    [ERROR] {agent['name']}: {agent.get('error')}")
        all_checks_passed = False

    # 3. Check Model Tier Assignments
    print_section("3. Model Tier Assignments")
    success, details = check_model_tier_assignments()
    if success:
        print_success("All model tier assignments valid")
        if args.verbose:
            print(f"  Model Tiers:")
            for tier, model in details['model_tiers'].items():
                count = details['agents_per_tier'].get(tier, 0)
                print(f"    - {tier}: {model} ({count} agents)")
    else:
        print_error(f"Model tier validation failed: {details.get('error')}")
        if 'invalid_agents' in details:
            print("  Invalid tier assignments:")
            for agent in details['invalid_agents']:
                print(f"    - {agent}")
        all_checks_passed = False

    # 4. Check A2A Agents (unless skipped)
    if not args.skip_a2a:
        print_section("4. A2A Agent Connectivity")
        success, details = check_a2a_agents()
        if details.get('skipped'):
            print_warning(f"Skipped: {details['reason']}")
        elif success:
            print_success("All A2A agents accessible")
            if args.verbose and 'agents' in details:
                for agent_name, agent_status in details['agents'].items():
                    print(f"    [OK] {agent_name}")
                    print(f"      HTTP: {agent_status['http_status']}, Card Valid: {agent_status['card_valid']}")
        else:
            print_error("A2A agent connectivity check failed")
            if 'agents' in details:
                for agent_name, agent_status in details['agents'].items():
                    if agent_status.get('error'):
                        print(f"    [ERROR] {agent_name}: {agent_status['error']}")
            elif 'error' in details:
                print(f"  Error: {details['error']}")
            all_checks_passed = False
    else:
        print_section("4. A2A Agent Connectivity")
        print_info("Skipped (--skip-a2a flag)")

    # 5. Check Config Files
    print_section("5. Configuration Files")
    success, file_details = check_config_files()
    if success:
        print_success(f"All {len(file_details)} config files valid")
        if args.verbose:
            for file_info in file_details:
                print(f"    [OK] {file_info['file']} ({file_info['size_bytes']:,} bytes, {file_info.get('keys', 'N/A')} keys)")
    else:
        failed_files = [f for f in file_details if f.get('error')]
        print_error(f"{len(failed_files)} config file(s) have issues")
        for file_info in failed_files:
            print(f"    [ERROR] {file_info['file']}: {file_info.get('error')}")
        all_checks_passed = False

    # Summary
    print("\n" + "="*80)
    if all_checks_passed:
        print_success("All health checks passed!")
        print_info("\nYour agents are ready to run:")
        print_info("  $ export PL_ANALYST_TEST_MODE=true")
        print_info("  $ adk run pl_analyst_agent")
    else:
        print_error("Some health checks failed. Please fix the issues above.")

    print("="*80 + "\n")

    return 0 if all_checks_passed else 1


if __name__ == "__main__":
    sys.exit(main())
