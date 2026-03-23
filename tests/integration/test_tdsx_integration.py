"""
Integration tests for the TDSX pipeline — end-to-end from TDSX file to DataFrame.

Tests the full flow: loader.yaml -> HyperLoaderConfig -> HyperQueryBuilder -> HyperConnectionManager.
These tests require the actual TDSX files to be present on disk.
"""

import os
import pytest
from pathlib import Path

from data_analyst_agent.sub_agents.tableau_hyper_fetcher.loader_config import HyperLoaderConfig
from data_analyst_agent.sub_agents.tableau_hyper_fetcher.query_builder import HyperQueryBuilder
from data_analyst_agent.sub_agents.tableau_hyper_fetcher.hyper_connection import (
    HyperConnectionManager,
    _MANAGERS,
)

PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()

# ---------------------------------------------------------------------------
# Skip conditions
# ---------------------------------------------------------------------------

BOOKSHOP_TDSX = PROJECT_ROOT / "data" / "tableau" / "Bookshop.tdsx"
OPS_METRICS_TDSX = PROJECT_ROOT / "data" / "tableau" / "Ops Metrics Weekly Scorecard.tdsx"

BOOKSHOP_LOADER = PROJECT_ROOT / "config" / "datasets" / "tableau" / "bookshop_sales" / "loader.yaml"
OPS_METRICS_LOADER = PROJECT_ROOT / "config" / "datasets" / "tableau" / "ops_metrics_weekly" / "loader.yaml"

bookshop_available = BOOKSHOP_TDSX.exists() and BOOKSHOP_LOADER.exists()
ops_metrics_available = OPS_METRICS_TDSX.exists() and OPS_METRICS_LOADER.exists()


# ---------------------------------------------------------------------------
# Bookshop TDSX tests — share ONE manager to avoid file locking
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not bookshop_available, reason="Bookshop TDSX or loader.yaml not available")
class TestBookshopTDSX:

    @pytest.fixture(scope="class")
    def bookshop_config(self):
        return HyperLoaderConfig.from_yaml(BOOKSHOP_LOADER)

    @pytest.fixture(scope="class")
    def bookshop_mgr(self, bookshop_config):
        """Single shared manager for all bookshop tests."""
        _MANAGERS.clear()
        mgr = HyperConnectionManager("bookshop_int", bookshop_config)
        mgr.ensure_extracted(PROJECT_ROOT)
        yield mgr
        mgr.cleanup()
        _MANAGERS.clear()

    def test_loader_config_parses(self, bookshop_config):
        assert bookshop_config.hyper.tdsx_file == "Bookshop.tdsx"
        assert bookshop_config.aggregation is not None
        assert bookshop_config.aggregation.date_column == "Sale Date"

    def test_extract_hyper_from_tdsx(self, bookshop_mgr):
        hyper_path = bookshop_mgr.get_hyper_path()
        assert hyper_path is not None
        assert hyper_path.endswith(".hyper")
        assert os.path.exists(hyper_path)

    def test_query_returns_data(self, bookshop_config, bookshop_mgr):
        builder = HyperQueryBuilder(bookshop_config)
        sql = builder.build_query()
        df = bookshop_mgr.execute_query(sql)
        assert len(df) > 0
        col_lower = [c.lower() for c in df.columns]
        assert any("revenue" in c for c in col_lower)

    def test_query_with_genre_filter(self, bookshop_config, bookshop_mgr):
        builder = HyperQueryBuilder(bookshop_config)

        sql_all = builder.build_query()
        df_all = bookshop_mgr.execute_query(sql_all)

        sql_fiction = builder.build_query(filters={"Genre": ["Fiction"]})
        df_fiction = bookshop_mgr.execute_query(sql_fiction)

        assert len(df_fiction) > 0
        assert len(df_fiction) < len(df_all)

    def test_schema_query(self, bookshop_config, bookshop_mgr):
        builder = HyperQueryBuilder(bookshop_config)
        sql = builder.build_schema_query()
        df = bookshop_mgr.execute_query(sql)
        assert len(df) == 0  # LIMIT 0
        assert len(df.columns) > 0

    def test_aggregation_reduces_rows(self, bookshop_config, bookshop_mgr):
        """Aggregated query should have fewer rows than raw SELECT *."""
        raw_sql = 'SELECT COUNT(*) AS cnt FROM "Extract"."Extract"'
        df_raw = bookshop_mgr.execute_query(raw_sql)
        raw_count = int(df_raw.iloc[0, 0])

        builder = HyperQueryBuilder(bookshop_config)
        sql = builder.build_query()
        df_agg = bookshop_mgr.execute_query(sql)

        assert len(df_agg) < raw_count

    def test_count_distinct_columns(self, bookshop_config, bookshop_mgr):
        """Verify count_distinct_columns produce expected results."""
        builder = HyperQueryBuilder(bookshop_config)
        sql = builder.build_query()
        df = bookshop_mgr.execute_query(sql)
        assert "Title" in df.columns
        assert "OrderID" in df.columns

    def test_avg_columns(self, bookshop_config, bookshop_mgr):
        """Verify avg_columns are calculated."""
        builder = HyperQueryBuilder(bookshop_config)
        sql = builder.build_query()
        df = bookshop_mgr.execute_query(sql)
        assert "Price" in df.columns
        assert "Discount" in df.columns
        # Average price should be reasonable (> 0)
        assert df["Price"].astype(float).mean() > 0


# ---------------------------------------------------------------------------
# Ops Metrics TDSX tests — share ONE manager
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not ops_metrics_available, reason="Ops Metrics TDSX or loader.yaml not available")
class TestOpsMetricsTDSX:

    @pytest.fixture(scope="class")
    def ops_config(self):
        return HyperLoaderConfig.from_yaml(OPS_METRICS_LOADER)

    @pytest.fixture(scope="class")
    def ops_mgr(self, ops_config):
        """Single shared manager for all ops metrics tests."""
        _MANAGERS.clear()
        mgr = HyperConnectionManager("ops_int", ops_config)
        mgr.ensure_extracted(PROJECT_ROOT)
        yield mgr
        mgr.cleanup()
        _MANAGERS.clear()

    def test_loader_config_parses(self, ops_config):
        assert "Ops Metrics" in ops_config.hyper.tdsx_file
        assert ops_config.aggregation is not None
        assert len(ops_config.aggregation.sum_columns) > 5

    def test_extract_and_query(self, ops_config, ops_mgr):
        builder = HyperQueryBuilder(ops_config)
        sql = builder.build_query()
        df = ops_mgr.execute_query(sql)
        assert len(df) > 0
        for col in ["ttl_rev_amt", "ld_trf_mi", "ordr_cnt"]:
            assert col in df.columns, f"Missing expected column: {col}"

    def test_date_range_filter(self, ops_config, ops_mgr):
        builder = HyperQueryBuilder(ops_config)
        sql = builder.build_query(date_start="2025-01-01", date_end="2025-03-31")
        df = ops_mgr.execute_query(sql)
        assert isinstance(df.columns.tolist(), list)

    def test_connection_health_check(self, ops_mgr):
        conn = ops_mgr.get_connection()
        assert conn is not None
        assert ops_mgr.is_ready()
        # Second call should reuse the connection
        conn2 = ops_mgr.get_connection()
        assert conn2 is conn

    def test_group_by_dimensions_present(self, ops_config, ops_mgr):
        builder = HyperQueryBuilder(ops_config)
        sql = builder.build_query()
        df = ops_mgr.execute_query(sql)
        for dim in ["gl_rgn_nm", "gl_div_nm", "ops_ln_of_bus_nm"]:
            assert dim in df.columns, f"Missing dimension: {dim}"

    def test_sql_aggregation_pushdown(self, ops_config):
        """Verify that the generated SQL contains GROUP BY and SUM expressions."""
        builder = HyperQueryBuilder(ops_config)
        sql = builder.build_query(date_start="2025-01-01", date_end="2025-01-07")
        sql_upper = sql.upper()
        
        # Verify push-down aggregation markers
        assert "GROUP BY" in sql_upper
        assert "SUM(" in sql_upper
        assert "SELECT" in sql_upper
        # Ensure it's not a simple SELECT *
        assert "SELECT *" not in sql_upper

    @pytest.mark.slow
    @pytest.mark.ops_metrics
    def test_aggregation_cardinality_is_bounded(self, ops_config, ops_mgr):
        """Verify that aggregated row count is bounded for a given date range."""
        builder = HyperQueryBuilder(ops_config)
        # Pull 3 months of data
        sql = builder.build_query(date_start="2025-01-01", date_end="2025-03-31")
        df = ops_mgr.execute_query(sql)
        
        # 3 months of data at week/dimension grain should be far less than 500k rows
        # (even with a very fine dimension grain)
        assert len(df) < 500000
        print(f"[TEST] Aggregated rows for 3 months: {len(df):,}")

    @pytest.mark.slow
    @pytest.mark.ops_metrics
    def test_raw_vs_aggregated_count_comparison(self, ops_config, ops_mgr):
        """Compare raw row count vs aggregated row count to prove efficiency."""
        # Get raw count for a small slice
        month_start, month_end = "2025-01-01", "2025-01-31"
        
        builder = HyperQueryBuilder(ops_config)
        table = builder._quote_table(ops_config.hyper.default_table)
        raw_count_sql = f"SELECT COUNT(*) FROM {table} WHERE \"cal_dt\" >= '{month_start}' AND \"cal_dt\" <= '{month_end}'"
        df_raw = ops_mgr.execute_query(raw_count_sql)
        raw_count = int(df_raw.iloc[0, 0])
        
        sql_agg = builder.build_query(date_start=month_start, date_end=month_end)
        df_agg = ops_mgr.execute_query(sql_agg)
        agg_count = len(df_agg)
        
        print(f"[TEST] Raw rows: {raw_count:,} | Aggregated rows: {agg_count:,}")
        assert agg_count < raw_count
        assert agg_count > 0
