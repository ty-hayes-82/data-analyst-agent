"""
Unit tests for HyperQueryBuilder — validates SQL generation from loader configs.
"""

import pytest
from data_analyst_agent.sub_agents.tableau_hyper_fetcher.loader_config import (
    HyperLoaderConfig,
    HyperConfig,
    AggregationRule,
    DerivedMetricDef,
)
from data_analyst_agent.sub_agents.tableau_hyper_fetcher.query_builder import HyperQueryBuilder
from data_analyst_agent.sub_agents.tableau_hyper_fetcher.ranked_subset import RankedSubsetSpec


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def simple_config():
    """Config with no aggregation — plain SELECT *."""
    return HyperLoaderConfig(
        hyper=HyperConfig(tdsx_file="test.tdsx", tdsx_path="data", default_table="Extract.Extract"),
    )


@pytest.fixture
def agg_config():
    """Config with month-end aggregation, group-by, sums, and a derived metric."""
    return HyperLoaderConfig(
        hyper=HyperConfig(tdsx_file="test.tdsx", default_table="Extract.Extract"),
        aggregation=AggregationRule(
            period_type="month_end",
            date_column="cal_dt",
            period_alias="period_end_date",
            group_by_columns=["region", "division"],
            sum_columns=["revenue", "miles"],
            derived_metrics=[
                DerivedMetricDef(
                    name="revenue_per_mile",
                    sql='CASE WHEN "miles" > 0 THEN "revenue" / "miles" ELSE NULL END',
                )
            ],
        ),
    )


@pytest.fixture
def day_config():
    """Config with day-level aggregation."""
    return HyperLoaderConfig(
        hyper=HyperConfig(tdsx_file="test.tdsx", default_table="Extract.Extract"),
        aggregation=AggregationRule(
            period_type="day",
            date_column="sale_date",
            period_alias="sale_date",
            group_by_columns=["genre"],
            sum_columns=["revenue", "quantity"],
        ),
    )


@pytest.fixture
def week_config():
    """Config with week-end aggregation."""
    return HyperLoaderConfig(
        hyper=HyperConfig(tdsx_file="test.tdsx", default_table="Extract.Extract"),
        aggregation=AggregationRule(
            period_type="week_end",
            date_column="cal_dt",
            period_alias="week_ending",
            group_by_columns=["location"],
            sum_columns=["sales"],
        ),
    )


@pytest.fixture
def year_month_config():
    """Config using year_column + month_column instead of date_column."""
    return HyperLoaderConfig(
        hyper=HyperConfig(tdsx_file="test.tdsx", default_table="Extract.Extract"),
        aggregation=AggregationRule(
            period_type="month_end",
            year_column="fiscal_year",
            month_column="fiscal_month",
            period_alias="period",
            group_by_columns=["dept"],
            sum_columns=["amount"],
        ),
    )


# ---------------------------------------------------------------------------
# Tests — Simple (no aggregation)
# ---------------------------------------------------------------------------

class TestSimpleQuery:
    def test_no_aggregation_produces_select_star(self, simple_config):
        builder = HyperQueryBuilder(simple_config)
        sql = builder.build_query()
        assert "SELECT *" in sql
        assert '"Extract"."Extract"' in sql

    def test_no_aggregation_with_dimension_filter(self, simple_config):
        builder = HyperQueryBuilder(simple_config)
        sql = builder.build_query(filters={"region": ["East"]})
        assert "region" in sql
        assert "East" in sql
        assert "WHERE" in sql


# ---------------------------------------------------------------------------
# Tests — Aggregated queries
# ---------------------------------------------------------------------------

class TestAggregatedQuery:
    def test_month_end_period_expression(self, agg_config):
        builder = HyperQueryBuilder(agg_config)
        sql = builder.build_query()
        assert "DATE_TRUNC" in sql
        assert "month" in sql.lower()
        assert "period_end_date" in sql

    def test_sum_columns_present(self, agg_config):
        builder = HyperQueryBuilder(agg_config)
        sql = builder.build_query()
        assert 'SUM("revenue")' in sql
        assert 'SUM("miles")' in sql

    def test_group_by_columns_present(self, agg_config):
        builder = HyperQueryBuilder(agg_config)
        sql = builder.build_query()
        assert '"region"' in sql
        assert '"division"' in sql
        assert "GROUP BY" in sql

    def test_derived_metric_in_outer_select(self, agg_config):
        builder = HyperQueryBuilder(agg_config)
        sql = builder.build_query()
        assert "revenue_per_mile" in sql
        assert "_inner" in sql  # Subquery alias

    def test_date_range_filter(self, agg_config):
        builder = HyperQueryBuilder(agg_config)
        sql = builder.build_query(date_start="2024-01-01", date_end="2024-06-30")
        assert "2024-01-01" in sql
        assert "2024-06-30" in sql
        assert "WHERE" in sql

    def test_dimension_filter_multi_value(self, agg_config):
        builder = HyperQueryBuilder(agg_config)
        sql = builder.build_query(filters={"region": ["East", "West"]})
        assert "IN" in sql
        assert "East" in sql
        assert "West" in sql

    def test_single_value_filter_uses_equals(self, agg_config):
        builder = HyperQueryBuilder(agg_config)
        sql = builder.build_query(filters={"region": ["East"]})
        assert "= '" in sql

    def test_extreme_date_filter(self, agg_config):
        """Queries should filter out 9999-12-31 placeholder dates."""
        builder = HyperQueryBuilder(agg_config)
        sql = builder.build_query(date_start="2024-01-01")
        assert "2100" in sql  # Sentinel upper bound

    def test_combined_date_and_dimension_filters(self, agg_config):
        builder = HyperQueryBuilder(agg_config)
        sql = builder.build_query(
            date_start="2024-01-01",
            date_end="2024-12-31",
            filters={"region": ["East"]},
        )
        assert "2024-01-01" in sql
        assert "East" in sql
        assert "AND" in sql


class TestDayAggregation:
    def test_day_period_is_cast_to_date(self, day_config):
        builder = HyperQueryBuilder(day_config)
        sql = builder.build_query()
        assert "CAST" in sql
        assert "AS DATE" in sql
        # Should NOT have INTERVAL logic for month/week
        assert "INTERVAL" not in sql


class TestWeekEndAggregation:
    def test_week_end_uses_dow_expression(self, week_config):
        builder = HyperQueryBuilder(week_config)
        sql = builder.build_query()
        assert "DOW" in sql
        assert "week_ending" in sql


class TestYearMonthAggregation:
    def test_year_month_columns_used(self, year_month_config):
        builder = HyperQueryBuilder(year_month_config)
        sql = builder.build_query()
        assert "fiscal_year" in sql
        assert "fiscal_month" in sql

    def test_year_month_with_date_filter(self, year_month_config):
        builder = HyperQueryBuilder(year_month_config)
        sql = builder.build_query(date_start="2024-01-01", date_end="2024-12-31")
        assert "2024" in sql


# ---------------------------------------------------------------------------
# Tests — Schema and bulk export
# ---------------------------------------------------------------------------

class TestSchemaAndExport:
    def test_schema_query_returns_limit_zero(self, simple_config):
        builder = HyperQueryBuilder(simple_config)
        sql = builder.build_schema_query()
        assert "LIMIT 0" in sql

    def test_bulk_export_wraps_in_copy(self, agg_config):
        builder = HyperQueryBuilder(agg_config)
        sql = builder.build_bulk_export_sql()
        assert "COPY" in sql
        assert "CSV" in sql
        assert "HEADER" in sql


# ---------------------------------------------------------------------------
# Tests — SQL safety
# ---------------------------------------------------------------------------

class TestRankedSubsetQuery:
    """Contract-resolved ranked subset wraps aggregation in WITH + allowed_pairs join."""

    @pytest.fixture
    def weekly_lane_like_config(self):
        return HyperLoaderConfig(
            hyper=HyperConfig(tdsx_file="Tolls.tdsx", default_table="Extract.Extract"),
            aggregation=AggregationRule(
                period_type="week_end",
                date_column="empty_call_dt",
                period_alias="empty_call_dt",
                group_by_columns=["shpr_prnt_nm", "stop_location_w_cust"],
                sum_columns=["toll_expense", "toll_revenue"],
            ),
        )

    def test_ranked_sql_has_ctes_limits_and_join(self, weekly_lane_like_config):
        spec = RankedSubsetSpec(
            rank_col="toll_expense",
            column_level_0="shpr_prnt_nm",
            column_level_1="stop_location_w_cust",
            top_level_0=25,
            top_level_1_per_level_0=100,
        )
        sql = HyperQueryBuilder(weekly_lane_like_config).build_query(
            date_start="2025-12-23",
            date_end="2026-03-24",
            ranked_spec=spec,
        )
        assert sql.startswith("WITH")
        assert "ranked_top_level_0 AS" in sql
        assert "agg_level_0_level_1 AS" in sql
        assert "allowed_level_0_level_1 AS" in sql
        assert "LIMIT 25" in sql
        assert "rn <= 100" in sql
        assert "INNER JOIN allowed_level_0_level_1 AS _a" in sql
        assert "_f.\"shpr_prnt_nm\" = _a.l0" in sql
        assert "_f.\"stop_location_w_cust\" = _a.l1" in sql
        assert "2025-12-23" in sql
        assert "2026-03-24" in sql

    def test_ranked_sql_three_level_ctes_and_join(self):
        cfg = HyperLoaderConfig(
            hyper=HyperConfig(tdsx_file="Tolls.tdsx", default_table="Extract.Extract"),
            aggregation=AggregationRule(
                period_type="week_end",
                date_column="empty_call_dt",
                period_alias="empty_call_dt",
                group_by_columns=["shpr_prnt_nm", "shpr_nm", "stop_location_w_cust"],
                sum_columns=["toll_expense", "toll_revenue"],
            ),
        )
        spec = RankedSubsetSpec(
            rank_col="toll_expense",
            column_level_0="shpr_prnt_nm",
            column_level_1="shpr_nm",
            column_level_2="stop_location_w_cust",
            top_level_0=20,
            top_level_1_per_level_0=20,
            top_level_2_per_level_1=30,
        )
        sql = HyperQueryBuilder(cfg).build_query(
            date_start="2025-12-23",
            date_end="2026-03-24",
            ranked_spec=spec,
        )
        assert "allowed_level_0_level_1_level_2 AS" in sql
        assert "INNER JOIN allowed_level_0_level_1_level_2 AS _a" in sql
        assert "_f.\"shpr_prnt_nm\" = _a.l0" in sql
        assert "_f.\"shpr_nm\" = _a.l1" in sql
        assert "_f.\"stop_location_w_cust\" = _a.l2" in sql
        assert "rn <= 30" in sql
        assert "PARTITION BY l0, l1" in sql

    def test_ranked_sql_qualifies_date_in_where(self, weekly_lane_like_config):
        spec = RankedSubsetSpec(
            rank_col="toll_expense",
            column_level_0="p",
            column_level_1="c",
            top_level_0=3,
            top_level_1_per_level_0=5,
        )
        sql = HyperQueryBuilder(weekly_lane_like_config).build_query(
            date_start="2025-01-01",
            date_end="2025-01-31",
            ranked_spec=spec,
        )
        assert "_f.\"empty_call_dt\"" in sql

    def test_ranked_diagnostic_sqls(self, weekly_lane_like_config):
        spec = RankedSubsetSpec(
            rank_col="toll_expense",
            column_level_0="shpr_prnt_nm",
            column_level_1="stop_location_w_cust",
            top_level_0=20,
            top_level_1_per_level_0=20,
        )
        diag = HyperQueryBuilder(weekly_lane_like_config).build_ranked_fetch_diagnostic_sqls(
            "2025-12-23", "2026-03-24", {}, spec
        )
        assert set(diag) == {
            "distinct_level_0_in_range",
            "top_level_0_rank_slots_used",
            "allowed_level_0_level_1",
        }
        assert "COUNT(DISTINCT" in diag["distinct_level_0_in_range"]
        assert "FROM allowed_level_0_level_1" in diag["allowed_level_0_level_1"]
        assert "LIMIT 20" in diag["top_level_0_rank_slots_used"]


class TestSQLSafety:
    def test_single_quote_escaped_in_filter(self, agg_config):
        builder = HyperQueryBuilder(agg_config)
        sql = builder.build_query(filters={"region": ["O'Brien"]})
        assert "O''Brien" in sql  # Escaped single quote

    def test_identifiers_are_double_quoted(self, agg_config):
        builder = HyperQueryBuilder(agg_config)
        sql = builder.build_query()
        assert '"region"' in sql
        assert '"division"' in sql

    def test_empty_filter_list_ignored(self, agg_config):
        builder = HyperQueryBuilder(agg_config)
        sql = builder.build_query(filters={"region": []})
        # Empty filter should not produce a WHERE clause for that column
        assert "region" not in sql.split("WHERE")[-1] if "WHERE" in sql else True
