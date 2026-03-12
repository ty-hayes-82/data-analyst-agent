import pandas as pd
import pytest

from data_analyst_agent.utils.cumulative_series import ensure_effective_metric_series


@pytest.mark.unit
@pytest.mark.csv_mode
def test_public_dataset_cumulative_detection_behaves():
    covid = pd.read_csv("data/public/us_counties_covid_sampled.csv")
    ca = covid[covid["state"] == "California"]
    agg = (
        ca.groupby("date", as_index=False)["cases"]
        .sum()
        .sort_values("date")
        .reset_index(drop=True)
    )

    covid_series = ensure_effective_metric_series(
        agg,
        metric_col="cases",
        time_col="date",
        metric_name="cases",
        time_frequency="daily",
    )

    assert covid_series.is_cumulative is True
    assert covid_series.column_name.startswith("new_")
    assert (covid_series.values < 0).sum() == 0
    assert covid_series.smoothing_window == 7

    co2 = pd.read_csv("data/public/owid_co2_data.csv")
    us = co2[co2["country"] == "United States"]
    agg_co2 = (
        us.groupby("year", as_index=False)["co2"]
        .sum()
        .sort_values("year")
        .reset_index(drop=True)
    )

    co2_series = ensure_effective_metric_series(
        agg_co2,
        metric_col="co2",
        time_col="year",
        metric_name="co2",
        time_frequency="yearly",
    )

    assert co2_series.is_cumulative is False
    assert co2_series.column_name == "co2"
