"""Section builders for the markdown report."""

from .executive_summary import build_executive_summary
from .variance_table import build_variance_section
from .hierarchy import build_hierarchy_section
from .insight_cards import build_insight_cards_section
from .independent_levels import build_independent_levels_section
from .cross_dimension import build_cross_dimension_section
from .utilization import build_utilization_section
from .data_quality import build_data_quality_section

__all__ = [
    "build_executive_summary",
    "build_variance_section",
    "build_hierarchy_section",
    "build_insight_cards_section",
    "build_independent_levels_section",
    "build_cross_dimension_section",
    "build_utilization_section",
    "build_data_quality_section",
]
