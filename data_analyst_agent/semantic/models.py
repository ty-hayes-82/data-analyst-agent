from typing import List, Dict, Optional, Literal, Union, Any
from pydantic import BaseModel, Field, field_validator, model_validator, ConfigDict
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
    executive_brief_max_scoped_level: Optional[int] = Field(
        None,
        description=(
            "Cap hierarchy level for per-entity executive briefs (1=first drill e.g. region, "
            "2=second e.g. terminal). None = legacy: min(executive_brief_drill_levels, 2). "
            "Use 1 to keep full hierarchy analysis (max_drill_depth) while emitting only "
            "network + first-level scoped briefs."
        ),
    )
    max_scope_entities: int = Field(10, description="Max entities to process per level in scoped briefs")
    min_scope_share_of_total: float = Field(
        0.0,
        description=(
            "Minimum share-of-total (0-1) required for scoped executive brief "
            "entity inclusion. Example: 0.01 means entities below 1% are skipped."
        ),
    )
    output_format: Literal["pdf", "md", "both"] = Field("pdf", description="Final report format")
    hierarchy_min_drill_impact_score: Optional[float] = Field(
        None,
        description=(
            "Override default 0.15 minimum insight impact_score to continue drilling past level 1. "
            "Use for sparse or low-variance KPIs (e.g. ranked tolls slice)."
        ),
    )
    force_hierarchy_drill_depth: Optional[int] = Field(
        None,
        ge=0,
        description=(
            "When set, keep drilling while current_level < this value (same semantics as env "
            "FORCE_DRILL_DOWN_DEPTH). Env wins when both are set."
        ),
    )
    executive_brief_relax_numeric_validation: bool = Field(
        False,
        description=(
            "When true, relax structured brief numeric floors (fewer required values per insight "
            "and lower total numerics) for small digests."
        ),
    )
    executive_brief_min_total_numerics: Optional[int] = Field(
        None,
        ge=0,
        description="Override minimum total numeric tokens in the brief body (default 15 network / 10 scoped).",
    )
    executive_brief_min_insight_numerics: Optional[int] = Field(
        None,
        ge=0,
        description="Override minimum numeric tokens per Key Findings insight (default 3 network).",
    )
    executive_brief_style: Optional[str] = Field(
        None,
        description=(
            "Sets EXECUTIVE_BRIEF_STYLE when the executive brief agent runs: "
            "'ceo' (default hybrid CEO brief), 'billing_auditor' (billing assurance / customer-lane review), "
            "'default' (standard JSON brief). Overrides CLI default for this dataset."
        ),
    )

class HierarchyNode(BaseModel):
    name: str
    parent: Optional[str] = None
    children: List[str] = Field(default_factory=list, alias="levels")
    level_names: Dict[int, str] = Field(default_factory=dict, description="Map level index to human-readable name")
    
    model_config = ConfigDict(populate_by_name=True)


class RankedSubsetFetchConfig(BaseModel):
    """Optional Hyper fetch: restrict rows to top-N values per hierarchy level by SUM(ranking_metric)."""

    enabled: bool = Field(False, description="When true, apply ranked subset CTEs to the Hyper query.")
    hierarchy_name: Optional[str] = Field(
        None,
        description=(
            "If set (and explicit level dimensions omitted), hierarchy levels[0..1] or [0..2] "
            "give dimension names (2- or 3-level ranked slice)."
        ),
    )
    level_0_dimension: Optional[str] = Field(
        None,
        description="Contract dimension name for hierarchy level 0 (coarsest ranked grouping).",
    )
    level_1_dimension: Optional[str] = Field(
        None,
        description="Contract dimension name for hierarchy level 1.",
    )
    level_2_dimension: Optional[str] = Field(
        None,
        description="When set with level_0 and level_1, enables 3-level ranked slice (finest grain).",
    )
    ranking_metric: Optional[str] = Field(
        None,
        description="Contract metric name used to rank (must be additive with a physical column).",
    )
    top_level_0: int = Field(
        25,
        ge=1,
        le=50_000,
        description="Keep this many distinct level-0 values with highest SUM(ranking_metric) over the date range.",
    )
    top_level_1_per_level_0: int = Field(
        100,
        ge=1,
        le=500_000,
        description=(
            "Per retained level-0 value, keep this many level-1 values (highest SUM(ranking_metric))."
        ),
    )
    top_level_2_per_level_1: Optional[int] = Field(
        None,
        ge=1,
        le=500_000,
        description=(
            "3-level mode only: per retained (level_0, level_1) pair, keep this many level-2 values."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _legacy_ranked_fetch_yaml_keys(cls, data: Any) -> Any:
        """Accept legacy keys top_parents / top_children_per_parent / parent_dimension / child_dimension."""
        if not isinstance(data, dict):
            return data
        out = dict(data)
        if "top_level_0" not in out and "top_parents" in out:
            out["top_level_0"] = out["top_parents"]
        if "top_level_1_per_level_0" not in out and "top_children_per_parent" in out:
            out["top_level_1_per_level_0"] = out["top_children_per_parent"]
        if "level_0_dimension" not in out and "parent_dimension" in out:
            out["level_0_dimension"] = out["parent_dimension"]
        if "level_1_dimension" not in out and "child_dimension" in out:
            out["level_1_dimension"] = out["child_dimension"]
        return out

    @model_validator(mode="after")
    def _require_level_source(self) -> "RankedSubsetFetchConfig":
        if not self.enabled:
            return self
        if not (self.ranking_metric and str(self.ranking_metric).strip()):
            raise ValueError("ranked_subset_fetch: when enabled=true, ranking_metric is required.")
        has_hier = bool(self.hierarchy_name and self.hierarchy_name.strip())
        has_explicit_two = bool(self.level_0_dimension and self.level_1_dimension)
        if not has_hier and not has_explicit_two:
            raise ValueError(
                "ranked_subset_fetch: when enabled=true, set hierarchy_name or both "
                "level_0_dimension and level_1_dimension."
            )
        if self.level_2_dimension and not (self.level_0_dimension and self.level_1_dimension):
            raise ValueError(
                "ranked_subset_fetch: level_2_dimension requires level_0_dimension and level_1_dimension."
            )
        return self


class TierFilterRule(BaseModel):
    """Per drill-level entity filter (matches ``compute_level_statistics`` level: 1 = first hierarchy dimension)."""

    level: int = Field(
        ...,
        ge=1,
        le=128,
        description="Hierarchy drill level (1 = first dimension after Total, 2 = second, ...).",
    )
    mode: Literal["top_pct", "top_n"] = Field(
        "top_pct",
        description="top_pct: cumulative share of ranking metric; top_n: keep N entities by rank.",
    )
    value: float = Field(
        ...,
        gt=0,
        description="For top_pct: percent of total (0-100). For top_n: maximum entities to keep.",
    )
    partition_by_dimension: Optional[str] = Field(
        None,
        description=(
            "Optional contract dimension name. When set, top_pct/top_n applies within each "
            "parent value (e.g. top shippers per shipper parent)."
        ),
    )

    @model_validator(mode="after")
    def _validate_rule(self) -> "TierFilterRule":
        if self.mode == "top_pct" and self.value > 100:
            raise ValueError("tier filter top_pct value must be <= 100")
        if self.mode == "top_n" and int(self.value) < 1:
            raise ValueError("tier filter top_n value must be >= 1")
        return self


class HierarchyEntityFilterConfig(BaseModel):
    """Analysis-time filtering of entities at each hierarchy drill level."""

    hierarchy_name: Optional[str] = Field(
        None,
        description="If set, only apply when this hierarchy is selected (matches drill hierarchy_name).",
    )
    ranking_metric: str = Field(
        ...,
        min_length=1,
        description="Contract metric name used to rank entities (additive column required in dataframe).",
    )
    levels: List[TierFilterRule] = Field(
        default_factory=list,
        description="Rules keyed by drill level (see TierFilterRule.level).",
    )


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




class AnalysisConfig(BaseModel):
    """Contract-driven analysis thresholds. Defaults match prior hardcoded values."""
    outlier_z_threshold: float = Field(3.5, description="MAD outlier detection z-score threshold")
    anomaly_z_threshold: float = Field(2.0, description="Anomaly flagging z-score threshold")
    significance_level: float = Field(0.05, description="Statistical significance p-value cutoff")
    cumulative_detection_threshold: float = Field(0.85, description="Monotonic growth detection threshold")
    aggregation_row_threshold: int = Field(100_000, description="Auto-aggregate to weekly above this row count")
    max_insights_per_level: int = Field(10, description="Top-N insights per hierarchy level")
    max_top_drivers: int = Field(10, description="Max top variance drivers to report")
    max_anomalies: int = Field(20, description="Max anomalies to surface")
    forecast_train_split: float = Field(0.8, description="Forecast model train/test split ratio")


class PriorityThresholds(BaseModel):
    """Alert priority classification thresholds."""
    critical: float = Field(0.7, description="Score >= this is critical")
    high: float = Field(0.6, description="Score >= this is high")
    medium: float = Field(0.3, description="Score >= this is medium; below is low")


class AlertPolicyConfig(BaseModel):
    """Contract-driven alert scoring weights and thresholds."""
    impact_weight: float = Field(0.6, description="Weight for impact component in composite score")
    confidence_weight: float = Field(0.25, description="Weight for confidence component")
    persistence_weight: float = Field(0.15, description="Weight for persistence component")
    priority_thresholds: PriorityThresholds = Field(default_factory=PriorityThresholds)
    volatility_alert_threshold: float = Field(0.5, description="Coefficient of variation threshold for volatility alerts")


class NarrativeConfig(BaseModel):
    """Contract-driven narrative generation parameters."""
    min_share_threshold: float = Field(0.10, description="Skip dimension slices below this share of total")
    min_variance_explanation: float = Field(0.60, description="Include low-share slices if they explain this much variance")
    max_top_drivers: int = Field(3, description="Max top drivers in narrative")
    max_anomalies: int = Field(3, description="Max anomalies in narrative")
    max_hierarchy_cards: int = Field(2, description="Max hierarchy cards in narrative")


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
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig, description="Analysis thresholds (z-scores, p-values, limits)")
    alert_policy: AlertPolicyConfig = Field(default_factory=AlertPolicyConfig, description="Alert scoring weights and priority thresholds")
    narrative: NarrativeConfig = Field(default_factory=NarrativeConfig, description="Narrative generation parameters")
    low_activity_dimension_values: List[str] = Field(
        default_factory=list,
        description=(
            "Dimension values that are operationally low-signal and should be "
            "suppressed from anomaly/alert extraction."
        ),
    )
    policies: Dict[str, Any] = Field(default_factory=dict, description="Domain-specific rules")
    validation: Dict[str, Any] = Field(
        default_factory=dict,
        description="Optional dataset-specific validation/fixture configuration (contract-driven).",
    )
    derived_kpis: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Optional Tableau-style KPI definitions; merged into metrics as type=derived when valid.",
    )
    ranked_subset_fetch: Optional[RankedSubsetFetchConfig] = Field(
        None,
        description=(
            "Optional ranked subset for Tableau Hyper fetch: top parents and top children per parent "
            "by ranking_metric over the requested date range."
        ),
    )
    hierarchy_entity_filters: Optional[HierarchyEntityFilterConfig] = Field(
        None,
        description=(
            "Optional per-drill-level entity filtering during hierarchy statistics (top %% or top N), "
            "after data load. Independent of ranked_subset_fetch (SQL fetch caps)."
        ),
    )

    # Internal mappings for fast lookup
    _metric_map: Dict[str, MetricDefinition] = {}
    _dim_map: Dict[str, DimensionDefinition] = {}
    _source_path: Optional[str] = None

    @model_validator(mode="after")
    def _merge_derived_kpis_into_metrics(self) -> "DatasetContract":
        """Register derived_kpis as first-class metrics so CLI and pipeline can target them."""
        if self.derived_kpis:
            base_names = {m.name for m in self.metrics}
            from .derived_kpi_formula import derived_kpis_to_metric_definitions

            extra_dicts = derived_kpis_to_metric_definitions(self.derived_kpis, base_names, list(self.metrics))
            merged = list(self.metrics)
            seen = {m.name for m in merged}
            for d in extra_dicts:
                if d["name"] in seen:
                    continue
                merged.append(MetricDefinition(**d))
                seen.add(d["name"])
            self.metrics = merged
        # Rebuild lookup maps here so they stay in sync (model_post_init can run before some validators in edge cases).
        self._metric_map = {m.name: m for m in self.metrics}
        self._dim_map = {d.name: d for d in self.dimensions}
        return self

    def model_post_init(self, __context: Any) -> None:
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
    dimension_filters: Dict[str, Any] = Field(default_factory=dict)
    hierarchy_filters: Dict[str, Any] = Field(default_factory=dict)
    
    # Immutable metadata for the run
    run_id: str
    max_drill_depth: int = 3
    temporal_grain: Literal["daily", "weekly", "monthly", "quarterly", "yearly", "unknown"] = "unknown"
    temporal_grain_confidence: float = 0.0
    detected_anchor: Optional[str] = None
    period_end_column: Optional[str] = None
    time_frequency: Optional[str] = None

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
