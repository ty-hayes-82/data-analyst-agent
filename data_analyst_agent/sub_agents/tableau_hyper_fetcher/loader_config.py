"""
HyperLoaderConfig
=================

Pydantic models for parsing a Tableau Hyper dataset's ``loader.yaml``.

A ``loader.yaml`` for a Hyper-backed dataset adds a ``hyper`` section (TDSX
file location, extraction directory, default table), an optional
``aggregation`` section (pre-aggregation rules for large row-level files), and
the same ``column_mapping``, ``date_parsing``, and ``output_columns`` sections
that the CSV loader already understands.

Example loader.yaml:

    source:
      type: tableau_hyper
      format: long

    hyper:
      tdsx_file: "Ops Metrics Weekly Scorecard.tdsx"
      tdsx_path: "data/tableau"
      default_table: "Extract.Extract"
      extract_dir: "temp_extracted/ops_metrics"

    filter_columns:
      lob: "ops_ln_of_bus_ref_nm"
      date: "cal_dt"
      terminal: "gl_div_nm"

    aggregation:
      period_type: month_end
      date_column: "cal_dt"
      period_alias: "period_end_date"
      group_by_columns:
        - "ops_ln_of_bus_ref_nm"
        - "gl_div_nm"
      sum_columns:
        - "ttl_rev_amt"
        - "ld_trf_mi"
      derived_metrics:
        - name: "revenue_per_loaded_mile"
          sql: 'CASE WHEN "ld_trf_mi" > 0 THEN "ttl_rev_amt" / "ld_trf_mi" ELSE NULL END'

    column_mapping:
      period_end_date: "cal_dt"
      ops_ln_of_bus_ref_nm: "lob"

    date_parsing:
      source_column: "cal_dt"
      input_format: "%Y-%m-%d"
      output_column: "cal_dt"
      output_format: "%Y-%m"

    output_columns:
      - "cal_dt"
      - "lob"
      - "total_revenue"
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Literal, Optional

import yaml
from pydantic import BaseModel, Field


class SourceConfig(BaseModel):
    type: Literal["tableau_hyper", "csv", "tableau_a2a"] = "tableau_hyper"
    format: Literal["long", "wide"] = "long"


class HyperConfig(BaseModel):
    tdsx_file: str
    tdsx_path: str = "."
    default_table: str = "Extract.Extract"
    extract_dir: str = "temp_extracted"


class DerivedMetricDef(BaseModel):
    name: str
    sql: str


class AggregationRule(BaseModel):
    period_type: Literal["month_end", "week_end", "day"] = "month_end"
    date_column: Optional[str] = None
    year_column: Optional[str] = None
    month_column: Optional[str] = None
    period_alias: str = "period_end_date"
    group_by_columns: List[str] = Field(default_factory=list)
    sum_columns: List[str] = Field(default_factory=list)
    avg_columns: List[str] = Field(default_factory=list)
    count_distinct_columns: List[str] = Field(default_factory=list)
    derived_metrics: List[DerivedMetricDef] = Field(default_factory=list)


class DateParsingConfig(BaseModel):
    source_column: str
    input_format: str = "%Y-%m-%d"
    output_column: str = "period"
    output_format: str = "%Y-%m-%d"


class HyperLoaderConfig(BaseModel):
    source: SourceConfig = Field(default_factory=SourceConfig)
    hyper: HyperConfig
    filter_columns: Dict[str, str] = Field(default_factory=dict)
    aggregation: Optional[AggregationRule] = None
    column_mapping: Dict[str, str] = Field(default_factory=dict)
    date_parsing: Optional[DateParsingConfig] = None
    output_columns: Optional[List[str]] = None

    @classmethod
    def from_yaml(cls, path: Path) -> "HyperLoaderConfig":
        """Load and parse a loader.yaml file."""
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        return cls(**raw)

    def resolve_tdsx_path(self, project_root: Path) -> Path:
        """Return the absolute path to the TDSX file.
        
        Prioritizes:
        1. Absolute path if provided
        2. Local file in config/datasets/<dataset>/ (if tdsx_path is ".")
        3. Legacy data/tableau/ folder
        """
        path = Path(self.hyper.tdsx_path)
        if path.is_absolute():
            return path / self.hyper.tdsx_file

        # Check for local file in dataset folder first
        from config.dataset_resolver import get_dataset_dir
        try:
            local_dir = get_dataset_dir()
            resolved = local_dir / path / self.hyper.tdsx_file
            if resolved.exists():
                return resolved
        except Exception:
            pass

        # Fallback to project root + tdsx_path (Legacy or explicit relative)
        return project_root / path / self.hyper.tdsx_file

    def resolve_extract_dir(self, project_root: Path) -> Path:
        """Return the absolute extraction directory for this dataset."""
        return project_root / self.hyper.extract_dir
