"""
Import helpers for test modules.

Provides convenience functions for importing tools from sub-agent directories.
"""

import importlib.util
from pathlib import Path
from typing import Any


def import_tool(sub_agent_dir: str, tool_name: str) -> Any:
    """
    Import a tool from a sub-agent directory.

    Args:
        sub_agent_dir: Sub-agent directory name (e.g., "statistical_insights_agent")
        tool_name: Tool module name (e.g., "compute_statistical_summary")

    Returns:
        The imported module

    Example:
        >>> stats_module = import_tool("statistical_insights_agent", "compute_statistical_summary")
        >>> compute = stats_module.compute_statistical_summary
    """
    project_root = Path(__file__).parent.parent.parent
    tool_path = project_root / "data_analyst_agent" / "sub_agents" / sub_agent_dir / "tools" / f"{tool_name}.py"

    if not tool_path.exists():
        raise FileNotFoundError(f"Tool not found: {tool_path}")

    spec = importlib.util.spec_from_file_location(tool_name, tool_path)
    module = importlib.util.module_from_spec(spec)

    module.__package__ = f"data_analyst_agent.sub_agents.{sub_agent_dir}.tools"

    spec.loader.exec_module(module)

    return module


def import_statistical_insights_tool(tool_name: str) -> Any:
    """Import a tool from the Statistical Insights Agent."""
    return import_tool("statistical_insights_agent", tool_name)


def import_hierarchy_ranker_tool(tool_name: str) -> Any:
    """Import a tool from the Hierarchy Variance Agent."""
    return import_tool("hierarchy_variance_agent", tool_name)


def import_report_synthesis_tool(tool_name: str) -> Any:
    """Import a tool from the Report Synthesis Agent."""
    return import_tool("report_synthesis_agent", tool_name)


def import_alert_scoring_tool(tool_name: str) -> Any:
    """Import a tool from the Alert Scoring Agent."""
    return import_tool("alert_scoring_agent", tool_name)


def import_output_persistence_tool(tool_name: str) -> Any:
    """Import a tool from the Output Persistence Agent."""
    return import_tool("output_persistence_agent", tool_name)


def import_hierarchical_analysis_tool(tool_name: str) -> Any:
    """Import a tool from the Hierarchical Analysis Agent."""
    return import_tool("hierarchical_analysis_agent", tool_name)


def import_seasonal_baseline_tool(tool_name: str) -> Any:
    """Import a tool from the Seasonal Baseline Agent."""
    return import_tool("seasonal_baseline_agent", tool_name)
