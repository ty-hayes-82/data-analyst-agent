import json
from pathlib import Path

import pandas as pd
import pytest

from data_analyst_agent.semantic.models import AnalysisContext, DatasetContract
from data_analyst_agent.sub_agents.data_cache import clear_all_caches, set_analysis_context
from data_analyst_agent.sub_agents.hierarchy_variance_agent.tools.compute_level_statistics import (
    compute_level_statistics,
)


CONTRACT_PATH = Path("config/datasets/csv/covid_us_counties/contract.yaml")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dimension_filters_skip_redundant_hierarchy_level():
    contract = DatasetContract.from_yaml(CONTRACT_PATH)
    contract._source_path = str(CONTRACT_PATH)

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
