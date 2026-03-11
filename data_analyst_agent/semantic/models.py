from typing import List, Dict, Optional, Literal, Union, Any
from pydantic import BaseModel, Field, field_validator, ConfigDict
import yaml
import pandas as pd
from datetime import datetime
from .exceptions import ContractValidationError

class MetricDefinition(BaseModel):
    name: str = Field(..., description="Semantic name of the metric (e.g., 'Revenue')")
    # column is optional for derived metrics that have no direct physical column
    column: Optional[str] = Field(None, description="The physical column name in the CSV/DB")
    type: Literal["additive", "non_additive", "ratio", "derived"] = Field("additive")
    format: Literal["currency", "percent", "integer", "float"] = Field("float")
    optimization: Literal["maximize", "minimize", "neutral"] = Field("maximize")
    tags: List[str] = Field(default_factory=list, description="Policy tags (e.g., 'revenue', 'controllable')")
    pvm_role: Optional[Literal["price", "volume", "total"]] = None
    parent_metric: Optional[str] = None  # For PVM relationships
    description: Optional[str] = None
    # Derived metric support
    formula: Optional[str] = Field(None, description="SQL/Python formula for derived metrics (pipeline-computed only)")
    depends_on: Optional[List[str]] = Field(None, description="Names of base metrics this is derived from")
    derived_from: Optional[List[str]] = Field(None, description="Alias for depends_on (backwards compat)")
    computed_by: Optional[Literal["a2a_agent", "pipeline"]] = Field(
        None,
        description=(
            "Who pre-computes this derived metric. "
            "'a2a_agent' means the A2A Hyper query already outputs it as a column; "
            "'pipeline' means the analysis pipeline computes it locally. "
            "None = legacy behaviour (pipeline computes)."
        )
    )
    lag_periods: Optional[int] = Field(
        None,
        description=(
            "Number of periods of expected data lag. When set, the pipeline "
            "treats 'latest' as Today - N periods and suppresses variance "
            "signals in the incomplete lag window."
        )
    )

    @field_validator("lag_periods")
    @classmethod
    def _validate_lag_periods(cls, v):
        if v is not None and v < 0:
            raise ValueError("lag_periods must be >= 0")
        return v

class DimensionDefinition(BaseModel):
    name: str = Field(..., description="Semantic name (e.g., 'Region')")
    column: str = Field(..., description="Physical column name")
    role: Literal["primary", "secondary", "time", "auxiliary"] = Field("primary")
    tags: List[str] = Field(default_factory=list)
    description: Optional[str] = None

class TimeConfig(BaseModel):
    column: str
    frequency: Literal["daily", "weekly", "monthly", "quarterly", "yearly"]
    temporal_grain_override: Optional[Literal["weekly", "monthly"]] = None
    format: str = Field("%Y-%m-%d", description="Strftime format")
    timezone: str = "UTC"
    range_months: Optional[int] = None

class DataSourceConfig(BaseModel):
    type: Literal["csv", "synthetic", "tableau_hyper"] = "tableau_hyper"
    file: Optional[str] = Field(
        default=None,
        description="Path to the backing dataset file (relative to the repository root).",
    )
    encoding: Optional[str] = Field(default=None, description="Optional file encoding override.")
    # tableau_hyper source fields
    tdsx_file: Optional[str] = None
    tdsx_path: Optional[str] = None
    default_table: Optional[str] = None

class GrainConfig(BaseModel):
    columns: List[str] = Field(..., description="Columns that define the uniqueness of a row")
    description: Optional[str] = None

class ReportingConfig(BaseModel):
    """Configuration for report generation and analysis depth."""
    max_drill_depth: int = Field(3, description="Max depth for hierarchical drill-down")
    executive_brief_drill_levels: int = Field(0, description="Levels of scoped briefs to generate")
    max_scope_entities: int = Field(10, description="Max entities to process per level in scoped briefs")
    min_scope_share_of_total: float = Field(
        0.0,
        description=(
            "Minimum share-of-total (0-1) required for scoped executive brief "
            "entity inclusion. Example: 0.01 means entities below 1% are skipped."
        ),
    )
    output_format: Literal["pdf", "md", "both"] = Field("pdf", description="Final report format")

class HierarchyNode(BaseModel):
    name: str
    parent: Optional[str] = None
    children: List[str] = Field(default_factory=list)
    level_names: Dict[int, str] = Field(default_factory=dict, description="Map level index to human-readable name")


class CrossDimensionConfig(BaseModel):
    """Declares an auxiliary dimension to cross-analyze against hierarchy levels."""
    name: str = Field(..., description="References a DimensionDefinition.name")
    apply_at_levels: Union[Literal["all"], List[int]] = Field(
        "all",
        description="Hierarchy levels to cross-analyze at ('all' or list of ints)",
    )
    min_sample_size: int = Field(10, description="Exclude aux-dim values with fewer observations per cell")
    max_cardinality: int = Field(50, description="Skip if aux dim has more unique values than this at a level")

    @field_validator("apply_at_levels", mode="before")
    @classmethod
    def _coerce_apply_at_levels(cls, v):
        if isinstance(v, str) and v.lower() == "all":
            return "all"
        if isinstance(v, list):
            return [int(x) for x in v]
        return v

    def applies_at_level(self, level: int) -> bool:
        if self.apply_at_levels == "all":
            return True
        return level in self.apply_at_levels


class DatasetContract(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    version: str
    display_name: Optional[str] = None
    description: Optional[str] = None
    # Label used wherever the pipeline refers to the unit being analysed
    # (the "current_analysis_target").
    # operational datasets can set "Metric", "Route", "Terminal", etc.
    # Defaults to "Analysis Target" so generic code is always readable.
    target_label: str = "Analysis Target"
    data_source: Optional[DataSourceConfig] = None
    time: TimeConfig
    grain: GrainConfig
    metrics: List[MetricDefinition]
    dimensions: List[DimensionDefinition]
    hierarchies: List[HierarchyNode] = Field(default_factory=list)
    cross_dimensions: List[CrossDimensionConfig] = Field(
        default_factory=list,
        description="Auxiliary dimensions to cross-analyze against hierarchy levels",
    )
    materiality: Dict[str, Any] = Field(default_factory=dict, description="Thresholds for absolute and percentage variance")
    presentation: Dict[str, Any] = Field(default_factory=dict, description="Rules for display, sign correction, and units")
    reporting: ReportingConfig = Field(default_factory=ReportingConfig, description="Report generation and analysis depth settings")
    policies: Dict[str, Any] = Field(default_factory=dict, description="Domain-specific rules")
    validation: Dict[str, Any] = Field(
        default_factory=dict,
        description="Optional dataset-specific validation/fixture configuration (contract-driven).",
    )
    
    # Internal mappings for fast lookup
    _metric_map: Dict[str, MetricDefinition] = {}
    _dim_map: Dict[str, DimensionDefinition] = {}
    _source_path: Optional[str] = None

    def __init__(self, **data):
        super().__init__(**data)
        self._metric_map = {m.name: m for m in self.metrics}
        self._dim_map = {d.name: d for d in self.dimensions}

    @classmethod
    def from_yaml(cls, path: str) -> "DatasetContract":
        with open(path, 'r') as f:
            data = yaml.safe_load(f)
        obj = cls(**data)
        obj._source_path = path
        return obj

    @property
    def capabilities(self) -> List[str]:
        """Returns a list of analytical capabilities supported by this contract."""
        caps = []
        if self.hierarchies:
            caps.append("hierarchical_drill_down")
        
        # Check for PVM roles
        if any(m.pvm_role for m in self.metrics):
            caps.append("pvm_decomposition")
            
        # Check for policies
        if self.policies:
            caps.append("policy_driven_analysis")

        if self.cross_dimensions:
            caps.append("cross_dimension_analysis")
            
        return caps

    def get_cross_dimensions_for_level(self, level: int) -> List[CrossDimensionConfig]:
        """Return cross-dimension configs that apply at the given hierarchy level."""
        return [cd for cd in self.cross_dimensions if cd.applies_at_level(level)]

    def get_metric(self, name: str) -> MetricDefinition:
        if name not in self._metric_map:
            raise KeyError(f"Metric '{name}' not found in contract '{self.name}'")
        return self._metric_map[name]

    def get_dimension(self, name: str) -> DimensionDefinition:
        if name not in self._dim_map:
            raise KeyError(f"Dimension '{name}' not found in contract '{self.name}'")
        return self._dim_map[name]

    def get_effective_lag(self, metric: Union[str, MetricDefinition], _seen: Optional[set] = None) -> int:
        """Return the effective lag periods for a metric, inheriting from dependencies if needed."""
        if isinstance(metric, str):
            metric = self.get_metric(metric)
            
        if metric.lag_periods is not None:
            return metric.lag_periods
            
        if not metric.depends_on:
            return 0
            
        # Inherit max lag from dependencies
        _seen = _seen or set()
        if metric.name in _seen:
            return 0 # Circular dependency
        _seen.add(metric.name)
        
        max_lag = 0
        for dep_name in metric.depends_on:
            try:
                dep_lag = self.get_effective_lag(dep_name, _seen=_seen)
                max_lag = max(max_lag, dep_lag)
            except KeyError:
                continue # Skip missing dependencies
                
        return max_lag

    def is_lagging_metric(self, metric: Union[str, MetricDefinition]) -> bool:
        """True if the metric or its dependencies declare a data lag."""
        return self.get_effective_lag(metric) > 0

class QualityReport(BaseModel):
    contract_name: str
    timestamp: datetime = Field(default_factory=datetime.now)
    is_valid: bool
    checks: Dict[str, bool]
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    metrics_summary: Dict[str, Any] = Field(default_factory=dict)

class InsightCard(BaseModel):
    """Standardized narrative output for any analytical finding."""
    title: str
    what_changed: str
    why: str
    evidence: Dict[str, Any]
    now_what: str
    priority: Literal["low", "medium", "high", "critical"] = "medium"
    root_cause: Optional[str] = None
    tags: List[str] = Field(default_factory=list)

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
    temporal_grain: Literal["weekly", "monthly", "unknown"] = "unknown"
    temporal_grain_confidence: float = 0.0
    detected_anchor: Optional[str] = None
    period_end_column: Optional[str] = None

    def get_metric_data(self) -> pd.Series:
        """Returns the series for the target metric."""
        if self.target_metric.column is None:
            raise ValueError(
                f"Metric '{self.target_metric.name}' is a derived metric with no direct "
                "physical column. Use the formula to compute it instead."
            )
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
