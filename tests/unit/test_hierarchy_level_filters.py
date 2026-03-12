import json
from pathlib import Path

import pandas as pd
import pytest

from data_analyst_agent.semantic.models import AnalysisContext, DatasetContract
from data_analyst_agent.sub_agents.data_cache import clear_all_caches, set_analysis_context
from data_analyst_agent.sub_agents.hierarchy_variance_agent.tools.compute_level_statistics import (
    compute_level_statistics,
)


TEST_CONTRACT_DATA = {
    "name": "test_counties",
    "version": "1.0.0",
    "display_name": "Test Counties",
    "description": "Synthetic county dataset for hierarchy filter tests",
    "time": {
        "column": "date",
        "frequency": "daily",
        "format": "%Y-%m-%d",
        "range_months": 12,
    },
    "grain": {"columns": ["date", "state", "county"]},
    "metrics": [
        {
            "name": "cases",
            "column": "cases",
            "type": "additive",
            "format": "integer",
            "optimization": "maximize",
            "description": "Reported cases",
            "tags": [],
        }
    ],
    "dimensions": [
        {"name": "date", "column": "date", "role": "time", "description": "Date"},
        {"name": "state", "column": "state", "role": "primary", "description": "State"},
        {"name": "county", "column": "county", "role": "secondary", "description": "County"},
    ],
    "hierarchies": [
        {
            "name": "geographic",
            "description": "State > County",
            "children": ["state", "county"],
            "level_names": {0: "State", 1: "County"},
        }
    ],
    "materiality": {"variance_pct": 5.0, "variance_absolute": 1000},
    "presentation": {"unit": "cases"},
    "reporting": {
        "max_drill_depth": 3,
        "executive_brief_drill_levels": 1,
        "max_scope_entities": 10,
        "output_format": "md",
    },
}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dimension_filters_skip_redundant_hierarchy_level():
    contract = DatasetContract.model_validate(TEST_CONTRACT_DATA)

    df = pd.DataFrame(
        {
            "date": ["2020-01-01", "2020-01-02"],
            "state": ["California", "California"],
            "county": ["Los Angeles", "San Diego"],
            "cases": [100, 150],
            "deaths": [1, 2],
        }
    )

    ctx = AnalysisContext(
        contract=contract,
        df=df,
        target_metric=contract.get_metric("cases"),
        primary_dimension=contract.get_dimension("state"),
        run_id="test-dimension-filter",
        max_drill_depth=3,
        dimension_filters={"state": "California"},
    )

    set_analysis_context(ctx)
    try:
        payload = json.loads(
            await compute_level_statistics(level=1, hierarchy_name="geographic")
        )
    finally:
        clear_all_caches()

    assert payload.get("is_duplicate") is True
    assert payload.get("dimension_filter_applied") is True
    assert "California" in (payload.get("skip_reason") or "")
