from typing import List, Dict, Optional, Literal, Union, Any
from pydantic import BaseModel, Field, validator, ConfigDict
import yaml
import pandas as pd
from datetime import datetime
from .exceptions import ContractValidationError

class MetricDefinition(BaseModel):
    name: str = Field(..., description="Semantic name of the metric (e.g., 'Revenue')")
    column: str = Field(..., description="The physical column name in the CSV/DB")
    type: Literal["additive", "non_additive", "ratio"] = Field("additive")
    format: Literal["currency", "percent", "integer", "float"] = Field("float")
    optimization: Literal["maximize", "minimize"] = Field("maximize")
    description: Optional[str] = None

class DimensionDefinition(BaseModel):
    name: str = Field(..., description="Semantic name (e.g., 'Region')")
    column: str = Field(..., description="Physical column name")
    role: Literal["primary", "secondary", "time"] = Field("primary")
    description: Optional[str] = None

class TimeConfig(BaseModel):
    column: str
    frequency: Literal["daily", "weekly", "monthly", "quarterly", "yearly"]
    format: str = Field("%Y-%m-%d", description="Strftime format")
    timezone: str = "UTC"
    range_months: Optional[int] = None

class GrainConfig(BaseModel):
    columns: List[str] = Field(..., description="Columns that define the uniqueness of a row")
    description: Optional[str] = None

class HierarchyNode(BaseModel):
    name: str
    parent: Optional[str] = None
    children: List[str] = Field(default_factory=list)

class DatasetContract(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    version: str
    description: Optional[str] = None
    time: TimeConfig
    grain: GrainConfig
    metrics: List[MetricDefinition]
    dimensions: List[DimensionDefinition]
    hierarchies: List[HierarchyNode] = Field(default_factory=list)
    
    # Internal mappings for fast lookup
    _metric_map: Dict[str, MetricDefinition] = {}
    _dim_map: Dict[str, DimensionDefinition] = {}

    def __init__(self, **data):
        super().__init__(**data)
        self._metric_map = {m.name: m for m in self.metrics}
        self._dim_map = {d.name: d for d in self.dimensions}

    @classmethod
    def from_yaml(cls, path: str) -> "DatasetContract":
        with open(path, 'r') as f:
            data = yaml.safe_load(f)
        return cls(**data)

    def get_metric(self, name: str) -> MetricDefinition:
        if name not in self._metric_map:
            raise KeyError(f"Metric '{name}' not found in contract '{self.name}'")
        return self._metric_map[name]

    def get_dimension(self, name: str) -> DimensionDefinition:
        if name not in self._dim_map:
            raise KeyError(f"Dimension '{name}' not found in contract '{self.name}'")
        return self._dim_map[name]

class QualityReport(BaseModel):
    contract_name: str
    timestamp: datetime = Field(default_factory=datetime.now)
    is_valid: bool
    checks: Dict[str, bool]
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    metrics_summary: Dict[str, Any] = Field(default_factory=dict)

class AnalysisContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)
    
    contract: DatasetContract
    df: pd.DataFrame
    target_metric: MetricDefinition
    primary_dimension: DimensionDefinition
    quality_report: Optional[QualityReport] = None
    
    # Immutable metadata for the run
    run_id: str
    max_drill_depth: int = 3

    def get_metric_data(self) -> pd.Series:
        """Returns the series for the target metric."""
        return self.df[self.target_metric.column]

    def get_dimension_data(self) -> pd.Series:
        """Returns the series for the primary dimension."""
        return self.df[self.primary_dimension.column]

    def get_time_data(self) -> pd.Series:
        """Returns the series for the time column."""
        return self.df[self.contract.time.column]

    def slice_by_dimension(self, dimension_name: str, value: Any) -> pd.DataFrame:
        """Returns a slice of the dataframe filtered by a dimension."""
        dim = self.contract.get_dimension(dimension_name)
        return self.df[self.df[dim.column] == value]
