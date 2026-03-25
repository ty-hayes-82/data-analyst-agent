import os
from pathlib import Path

def _load_instruction_template() -> str:
    """Load the report synthesis instruction template from config/prompts/report_synthesis.md."""
    try:
        # Resolve path relative to project root
        project_root = Path(__file__).resolve().parent.parent.parent.parent
        path = project_root / "config" / "prompts" / "report_synthesis.md"
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
    except Exception as e:
        print(f"[REPORT_SYNTHESIS] Warning: Failed to load instruction template: {e}")
    
    # Fallback to hardcoded string if file missing
    return "You are an Executive Report Synthesis Agent. Combine insight cards into a report for {dataset_display_name}."

REPORT_SYNTHESIS_AGENT_INSTRUCTION_TEMPLATE = _load_instruction_template()



def _short_label(description: str) -> str:
    """Extract a short, readable label from a dimension description.

    Strips parenthetical examples and slash-separated alternatives so that
    "Line of Business (e.g., Line Haul, Dedicated)" becomes "Line of Business"
    and "Terminal / Division name (physical location)" becomes "Terminal".
    """
    label = description.split(" (")[0].split(" /")[0].strip()
    return label or description


def build_report_instruction(contract=None) -> str:
    """Build a dataset-specific report synthesis instruction from a DatasetContract.

    Reads dimension names, hierarchy structure, and dataset metadata from the
    contract so that no domain-specific terminology needs to be hardcoded in
    the prompt template.

    Args:
        contract: A DatasetContract instance loaded from a YAML config file.
                  When None, returns a fully generic fallback instruction.

    Returns:
        A fully formatted instruction string ready to be assigned to the
        report synthesis LLM agent.
    """
    if contract is None:
        return REPORT_SYNTHESIS_AGENT_INSTRUCTION_TEMPLATE.format(
            dataset_display_name="the configured dataset",
            primary_dimension_label="Primary Dimension",
            primary_dimension_column="primary_column",
            hierarchy_sections="",
            data_source_description="configured data source",
        )

    # Primary dimension (role="primary", falling back to first dimension)
    primary_dim = next(
        (d for d in contract.dimensions if d.role == "primary"),
        contract.dimensions[0],
    )
    primary_label = _short_label(primary_dim.description or primary_dim.name.replace("_", " ").title())
    primary_column = primary_dim.column or primary_dim.name

    # Hierarchy-driven breakdown sections
    hierarchy_sections_md = ""
    if contract.hierarchies:
        hierarchy = contract.hierarchies[0]
        dim_map = {d.name: d for d in contract.dimensions}
        children = hierarchy.children  # list of dimension names, ordered from coarse to fine

        # Find where the primary dimension sits in the hierarchy so we can
        # identify which levels represent drill-down targets.
        try:
            primary_idx = children.index(primary_dim.name)
        except ValueError:
            # Primary dimension is not in this hierarchy; start from the beginning.
            primary_idx = -1

        drill_levels = children[primary_idx + 1 :]  # levels below the primary

        # Generate a markdown section for each drill-down level (up to 3 levels).
        for child_name in drill_levels[:3]:
            child_dim = dim_map.get(child_name)
            if child_dim:
                level_label = _short_label(
                    child_dim.description or child_dim.name.replace("_", " ").title()
                )
                hierarchy_sections_md += (
                    f"\n## {level_label} Breakdown\n"
                    f"For each {level_label} in the drill-down:\n"
                    f"- **[{level_label} Name]**: Key metrics (state exact numbers and percentages), contribution to overall performance.\n"
                    f"- **Analysis**: Explain the *causes* behind notable changes or performance, and their *business impact*.\n"
                    f"- Rank by impact (biggest movers first).\n"
                )

    # Data source description (data_source is not a Pydantic field on DatasetContract;
    # use the contract's description or name as a human-readable reference instead).
    data_source_desc = contract.description or f"{contract.name} data source"
    display_name = getattr(contract, 'display_name', contract.name)

    return REPORT_SYNTHESIS_AGENT_INSTRUCTION_TEMPLATE.format(
        dataset_display_name=display_name,
        primary_dimension_label=primary_label,
        primary_dimension_column=primary_column,
        hierarchy_sections=hierarchy_sections_md,
        data_source_description=data_source_desc,
    )


# Generic fallback used at module load time (before any contract is loaded).
# The ReportSynthesisWrapper updates this dynamically at runtime via
# build_report_instruction(contract) once the contract is in session state.
REPORT_SYNTHESIS_AGENT_INSTRUCTION = build_report_instruction(contract=None)
