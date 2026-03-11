import pandas as pd
import pytest
from types import SimpleNamespace

from data_analyst_agent.sub_agents.statistical_insights_agent.tools.stat_summary.period_totals import (
    compute_monthly_totals,
)
from data_analyst_agent.sub_agents.statistical_insights_agent.tools.stat_summary.state import (
    SummaryState,
)


def test_compute_monthly_totals_handles_numeric_period_columns():
    df = pd.DataFrame(
        {
            "account": ["a", "a", "b", "b"],
            "period": [2023, 2024, 2023, 2024],
            "value": [10.0, 15.0, 5.0, 20.0],
            "name": ["Alpha", "Alpha", "Beta", "Beta"],
        }
    )
    pivot = df.pivot_table(
        index="account",
        columns="period",
        values="value",
        aggfunc="sum",
        fill_value=0,
    )

    state = SummaryState(
        df=df,
        pivot=pivot,
        ctx=SimpleNamespace(contract=None),
        time_col="period",
        metric_col="value",
        grain_col="account",
        name_col="name",
        names_map={"a": "Alpha", "b": "Beta"},
        current_metric_name="value",
        temporal_grain="monthly",
        period_unit="month",
        latest_period="2024",
        prev_period="2023",
        lag=0,
        lag_window=["2023", "2024"],
        latest_period_value=2024,
        prev_period_value=2023,
    )

    compute_monthly_totals(state)

    assert state.monthly_totals == {"2023": 15.0, "2024": 35.0}
    assert state.contribution_share["a"] == pytest.approx(0.25)
    assert state.contribution_share["b"] == pytest.approx(0.75)
