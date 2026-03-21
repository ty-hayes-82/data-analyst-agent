"""
Unit tests for HyperLoaderConfig — validates Pydantic model parsing and path resolution.
"""

import pytest
import tempfile
import os
from pathlib import Path

import yaml

from data_analyst_agent.sub_agents.tableau_hyper_fetcher.loader_config import (
    HyperLoaderConfig,
    HyperConfig,
    AggregationRule,
    DateParsingConfig,
    SourceConfig,
    DerivedMetricDef,
)


# ---------------------------------------------------------------------------
# Tests — Model construction
# ---------------------------------------------------------------------------

class TestHyperLoaderConfigConstruction:
    def test_minimal_config(self):
        cfg = HyperLoaderConfig(
            hyper=HyperConfig(tdsx_file="test.tdsx"),
        )
        assert cfg.hyper.tdsx_file == "test.tdsx"
        assert cfg.hyper.default_table == "Extract.Extract"
        assert cfg.source.type == "tableau_hyper"
        assert cfg.aggregation is None
        assert cfg.filter_columns == {}

    def test_full_config(self):
        cfg = HyperLoaderConfig(
            source=SourceConfig(type="tableau_hyper", format="long"),
            hyper=HyperConfig(
                tdsx_file="Ops.tdsx",
                tdsx_path="data/tableau",
                default_table="Extract.Extract",
                extract_dir="temp_extracted/ops",
            ),
            filter_columns={"region": "gl_rgn_nm", "date": "cal_dt"},
            aggregation=AggregationRule(
                period_type="month_end",
                date_column="cal_dt",
                period_alias="period_end_date",
                group_by_columns=["gl_rgn_nm"],
                sum_columns=["revenue"],
                derived_metrics=[
                    DerivedMetricDef(name="rpm", sql='"revenue" / "miles"'),
                ],
            ),
            column_mapping={"period_end_date": "cal_dt"},
            date_parsing=DateParsingConfig(
                source_column="cal_dt",
                output_column="cal_dt",
                output_format="%Y-%m",
            ),
            output_columns=["cal_dt", "gl_rgn_nm", "revenue"],
        )
        assert cfg.aggregation.period_type == "month_end"
        assert len(cfg.aggregation.sum_columns) == 1
        assert len(cfg.aggregation.derived_metrics) == 1
        assert cfg.date_parsing.output_format == "%Y-%m"

    def test_aggregation_avg_and_count_distinct(self):
        cfg = HyperLoaderConfig(
            hyper=HyperConfig(tdsx_file="test.tdsx"),
            aggregation=AggregationRule(
                period_type="day",
                date_column="dt",
                group_by_columns=["cat"],
                sum_columns=["amount"],
                avg_columns=["price"],
                count_distinct_columns=["customer_id"],
            ),
        )
        assert cfg.aggregation.avg_columns == ["price"]
        assert cfg.aggregation.count_distinct_columns == ["customer_id"]


# ---------------------------------------------------------------------------
# Tests — YAML parsing
# ---------------------------------------------------------------------------

class TestYAMLParsing:
    def test_from_yaml_file(self, tmp_path):
        loader_yaml = {
            "source": {"type": "tableau_hyper", "format": "long"},
            "hyper": {
                "tdsx_file": "Bookshop.tdsx",
                "tdsx_path": "data/tableau",
                "default_table": "Extract.Extract",
                "extract_dir": "temp_extracted/bookshop",
            },
            "filter_columns": {"genre": "Genre"},
            "aggregation": {
                "period_type": "day",
                "date_column": "Sale Date",
                "period_alias": "sale_date",
                "group_by_columns": ["Genre"],
                "sum_columns": ["Revenue"],
            },
        }
        yaml_path = tmp_path / "loader.yaml"
        with open(yaml_path, "w") as f:
            yaml.dump(loader_yaml, f)

        cfg = HyperLoaderConfig.from_yaml(yaml_path)
        assert cfg.hyper.tdsx_file == "Bookshop.tdsx"
        assert cfg.aggregation.date_column == "Sale Date"
        assert "Genre" in cfg.aggregation.group_by_columns

    def test_from_yaml_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            HyperLoaderConfig.from_yaml(tmp_path / "nonexistent.yaml")


# ---------------------------------------------------------------------------
# Tests — Path resolution
# ---------------------------------------------------------------------------

class TestPathResolution:
    def test_resolve_extract_dir(self):
        cfg = HyperLoaderConfig(
            hyper=HyperConfig(
                tdsx_file="test.tdsx",
                extract_dir="temp_extracted/test",
            ),
        )
        project_root = Path("/data/data-analyst-agent")
        result = cfg.resolve_extract_dir(project_root)
        assert result == Path("/data/data-analyst-agent/temp_extracted/test")

    def test_resolve_tdsx_path_relative(self):
        cfg = HyperLoaderConfig(
            hyper=HyperConfig(
                tdsx_file="Ops.tdsx",
                tdsx_path="data/tableau",
            ),
        )
        project_root = Path("/data/data-analyst-agent")
        result = cfg.resolve_tdsx_path(project_root)
        # Should include the tdsx_path + file
        assert "data/tableau" in str(result) or "data\\tableau" in str(result)
        assert str(result).endswith("Ops.tdsx")


# ---------------------------------------------------------------------------
# Tests — Defaults and edge cases
# ---------------------------------------------------------------------------

class TestDefaults:
    def test_source_defaults_to_tableau_hyper(self):
        cfg = HyperLoaderConfig(hyper=HyperConfig(tdsx_file="x.tdsx"))
        assert cfg.source.type == "tableau_hyper"
        assert cfg.source.format == "long"

    def test_aggregation_defaults(self):
        agg = AggregationRule(
            date_column="dt",
            group_by_columns=["g"],
            sum_columns=["s"],
        )
        assert agg.period_type == "month_end"
        assert agg.period_alias == "period_end_date"
        assert agg.avg_columns == []
        assert agg.count_distinct_columns == []
        assert agg.derived_metrics == []

    def test_date_parsing_defaults(self):
        dp = DateParsingConfig(source_column="dt")
        assert dp.input_format == "%Y-%m-%d"
        assert dp.output_column == "period"
        assert dp.output_format == "%Y-%m-%d"
