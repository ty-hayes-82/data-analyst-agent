"""
Import helpers for test modules.

Handles importing from directories with numeric prefixes (e.g., 01_data_validation_agent)
which cannot be imported using standard Python import syntax.
"""

import importlib.util
from pathlib import Path
from typing import Any


def import_tool(sub_agent_dir: str, tool_name: str) -> Any:
    """
    Import a tool from a sub-agent directory.

    Args:
        sub_agent_dir: Sub-agent directory name (e.g., "01_data_validation_agent")
        tool_name: Tool module name (e.g., "reshape_and_validate")

    Returns:
        The imported module

    Example:
        >>> reshape_module = import_tool("01_data_validation_agent", "reshape_and_validate")
        >>> reshape_and_validate = reshape_module.reshape_and_validate
    """
    project_root = Path(__file__).parent.parent.parent
    tool_path = project_root / "pl_analyst_agent" / "sub_agents" / sub_agent_dir / "tools" / f"{tool_name}.py"

    if not tool_path.exists():
        raise FileNotFoundError(f"Tool not found: {tool_path}")

    spec = importlib.util.spec_from_file_location(tool_name, tool_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return module


def import_data_validation_tool(tool_name: str) -> Any:
    """
    Import a tool from the Data Validation Agent (01_data_validation_agent).

    Args:
        tool_name: Tool module name (e.g., "reshape_and_validate")

    Returns:
        The imported module
    """
    return import_tool("01_data_validation_agent", tool_name)


def import_statistical_insights_tool(tool_name: str) -> Any:
    """
    Import a tool from the Statistical Insights Agent (02_statistical_insights_agent).

    Args:
        tool_name: Tool module name (e.g., "compute_statistical_summary")

    Returns:
        The imported module
    """
    return import_tool("02_statistical_insights_agent", tool_name)


def import_hierarchy_ranker_tool(tool_name: str) -> Any:
    """
    Import a tool from the Hierarchy Variance Ranker Agent (03_hierarchy_variance_ranker_agent).

    Args:
        tool_name: Tool module name (e.g., "compute_level_statistics")

    Returns:
        The imported module
    """
    return import_tool("03_hierarchy_variance_ranker_agent", tool_name)


def import_report_synthesis_tool(tool_name: str) -> Any:
    """
    Import a tool from the Report Synthesis Agent (04_report_synthesis_agent).

    Args:
        tool_name: Tool module name

    Returns:
        The imported module
    """
    return import_tool("04_report_synthesis_agent", tool_name)


def import_alert_scoring_tool(tool_name: str) -> Any:
    """
    Import a tool from the Alert Scoring Agent (05_alert_scoring_agent).

    Args:
        tool_name: Tool module name

    Returns:
        The imported module
    """
    return import_tool("05_alert_scoring_agent", tool_name)


def import_output_persistence_tool(tool_name: str) -> Any:
    """
    Import a tool from the Output Persistence Agent (06_output_persistence_agent).

    Args:
        tool_name: Tool module name

    Returns:
        The imported module
    """
    return import_tool("06_output_persistence_agent", tool_name)


def import_seasonal_baseline_tool(tool_name: str) -> Any:
    """
    Import a tool from the Seasonal Baseline Agent (07_seasonal_baseline_agent).

    Args:
        tool_name: Tool module name

    Returns:
        The imported module
    """
    return import_tool("07_seasonal_baseline_agent", tool_name)
