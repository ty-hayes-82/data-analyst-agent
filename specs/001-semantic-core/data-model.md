# Data Model: Semantic Core (Wave 1)

**Feature**: `001-semantic-core` | **Date**: 2025-02-12

This document defines the Pydantic models that constitute the Semantic Layer. All models use Pydantic v2 with strict validation.

---

## 1. DatasetContract (Top-Level)

The central configuration schema. One YAML file = one `DatasetContract`.

```python
class DatasetContract(BaseModel):
    """Complete semantic description of a dataset."""
    model_config = ConfigDict(extra="forbid")

    name: str                          # e.g., "P&L Financial Data"
    version: str                       # Semver, e.g., "1.0.0"
    description: str = ""

    time: TimeConfig                   # Time axis definition
    grain: GrainConfig                 # Row uniqueness definition
    metrics: list[MetricDefinition]    # Fact columns (things you measure)
    dimensions: list[DimensionDefinition]  # Categorical columns (things you slice by)
    hierarchies: list[HierarchyDefinition] = []  # Parent-child drill paths
    materiality: MaterialityConfig = MaterialityConfig()  # Thresholds
    policies: PolicyConfig = PolicyConfig()  # Business rules, alerts, ownership
    analysis: AnalysisConfig = AnalysisConfig()  # Analysis behavior tuning
```

---

## 2. TimeConfig

```python
class TimeFrequency(str, Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"

class TimeConfig(BaseModel):
    """Defines the time axis of the dataset."""
    column: str                        # Column name in the DataFrame, e.g., "period"
    frequency: TimeFrequency           # Granularity of time data
    format: str = ""                   # Optional strftime format, e.g., "%Y-%m"
    timezone: str = "UTC"              # IANA timezone
    range_months: int = 24             # Default lookback window for analysis
    order_detail_months: int = 3       # Lookback for order-level detail (if applicable)
```

---

## 3. GrainConfig

```python
class GrainConfig(BaseModel):
    """Defines the unique identifier for a row."""
    columns: list[str]                 # e.g., ["period", "cost_center", "gl_account"]
    description: str = ""              # Human-readable, e.g., "Monthly GL by cost center"
```

---

## 4. MetricDefinition

```python
class MetricType(str, Enum):
    ADDITIVE = "additive"              # Can be summed (e.g., Revenue, Miles)
    NON_ADDITIVE = "non_additive"      # Cannot be summed (e.g., Margin %, Cost/Mile)

class MetricFormat(str, Enum):
    CURRENCY = "currency"
    PERCENT = "percent"
    INTEGER = "integer"
    DECIMAL = "decimal"

class OptimizationDirection(str, Enum):
    MAXIMIZE = "maximize"              # Higher is better (Revenue)
    MINIMIZE = "minimize"              # Lower is better (Cost, Latency)

class MetricDefinition(BaseModel):
    """A measurable fact column in the dataset."""
    name: str                          # Semantic name, e.g., "Revenue"
    column: str                        # DataFrame column name, e.g., "amount"
    type: MetricType                   # Additive or Non-Additive
    format: MetricFormat = MetricFormat.DECIMAL
    optimization: OptimizationDirection | None = None  # null = no preference
    sign_flip: bool = False            # If True, negate values (e.g., revenue in expense-positive ledger)
    tags: list[str] = []               # Freeform tags, e.g., ["revenue", "primary"]
    description: str = ""
```

---

## 5. DimensionDefinition

```python
class DimensionRole(str, Enum):
    PRIMARY = "primary"                # Main slicing dimension (e.g., gl_account)
    SECONDARY = "secondary"            # Grouping dimension (e.g., canonical_category)
    FILTER = "filter"                  # Selection dimension (e.g., cost_center)
    DETAIL = "detail"                  # Informational only (e.g., account_name)

class DimensionDefinition(BaseModel):
    """A categorical column used for slicing and grouping."""
    name: str                          # Semantic name, e.g., "gl_account"
    column: str                        # DataFrame column name
    role: DimensionRole                # How this dimension is used
    tags: list[str] = []               # Freeform tags, e.g., ["revenue_indicator"]
    description: str = ""
```

---

## 6. HierarchyDefinition

```python
class HierarchyDefinition(BaseModel):
    """An ordered parent-child drill path across dimensions."""
    name: str                          # e.g., "account_hierarchy"
    levels: list[str]                  # Ordered dimension names: ["level_1", "level_2", "level_3", "level_4"]
    description: str = ""
```

**Usage**: `context.hierarchy_path("account_hierarchy")` returns `["level_1", "level_2", "level_3", "level_4"]`. `context.hierarchy_children("level_1")` returns `["level_2"]`.

---

## 7. MaterialityConfig

```python
class MaterialityConfig(BaseModel):
    """Thresholds for filtering significant variances."""
    variance_pct: float = 5.0          # +/- percentage threshold
    variance_dollar: float = 50000.0   # +/- absolute dollar threshold
    top_categories_count: int = 5      # Max categories to drill into
    cumulative_variance_pct: float = 80.0  # Explain this % of total variance
    min_amount: float = 10000.0        # Minimum dollar amount to consider material
    per_unit_thresholds: dict[str, float] = {}  # e.g., {"cost_per_mile_pct": 10.0}
    use_empirical: bool = False        # Use data-derived thresholds if available
```

---

## 8. PolicyConfig

```python
class SeverityThresholds(BaseModel):
    """Thresholds for alert severity classification."""
    info: dict[str, float] = {"point_z_mad_min": 2.0}
    warn: dict[str, float] = {"point_z_mad_min": 3.0, "pi_breaches_min": 1}
    critical: dict[str, Any] = {"change_point": True, "mom_pct_min": 25, "yoy_pct_min": 20}

class KnownPattern(BaseModel):
    """A documented recurring pattern to suppress or contextualize."""
    name: str
    pattern_type: str                  # "seasonal", "operational", "timing", "policy", "one_time"
    description: str
    affected_metrics: list[str] = []   # Metric names from the contract
    affected_dimensions: dict[str, list[str]] = {}  # e.g., {"cost_center": ["067"]}
    months: list[int] = []             # Applicable months (1-12)
    suppress_alerts: bool = False
    documented_by: str = ""
    documented_date: str = ""

class SuppressionRule(BaseModel):
    """A rule to suppress alerts below a severity threshold."""
    name: str
    description: str
    affected_metrics: list[str] = []
    affected_dimensions: dict[str, list[str]] = {}
    periods: list[int] = []            # Period numbers or months
    suppress_severity_below: float = 0.5
    reason: str = ""
    active: bool = True

class OwnershipMapping(BaseModel):
    """Maps dimension values to responsible parties."""
    dimension: str                     # e.g., "cost_center"
    value: str                         # e.g., "067"
    owner: str                         # e.g., "Ops - Sacramento"

class PolicyConfig(BaseModel):
    """Business rules, alerts, and domain intelligence."""
    severity: SeverityThresholds = SeverityThresholds()
    windows: list[int] = [3, 6, 12, 24]  # Analysis windows in months
    fatigue_suppress_days: int = 14
    fatigue_rearm_on_escalation: bool = True
    known_patterns: list[KnownPattern] = []
    suppression_rules: list[SuppressionRule] = []
    ownership: list[OwnershipMapping] = []
    root_cause_types: list[str] = [
        "accruals", "timing", "allocations", "miscoding",
        "operational", "rate_change", "volume_mix", "one_time"
    ]
```

---

## 9. AnalysisConfig

```python
class AnalysisConfig(BaseModel):
    """Controls analysis behavior per contract."""
    max_drill_depth: int = 5           # Max recursive hierarchy depth (Wave 2)
    enable_driver_decomposition: bool = True  # Price-Volume-Mix analysis (Wave 2)
    enable_stl_decomposition: bool = True     # STL time-series (Wave 2)
    enable_forecasting: bool = True           # ARIMA forecasting
    z_score_threshold: float = 2.0            # Anomaly detection threshold
    correlation_threshold: float = 0.7        # Cross-metric correlation threshold
```

---

## 10. AnalysisContext (Runtime, Not Persisted)

```python
@dataclass(frozen=True)
class AnalysisContext:
    """Immutable runtime object wrapping a DataFrame with semantic accessors."""
    contract: DatasetContract
    df: pd.DataFrame                    # Not serialized
    _metric_map: dict[str, str]         # name -> column, built at construction
    _dimension_map: dict[str, str]      # name -> column, built at construction

    # --- Accessors ---
    def metric(self, name: str) -> str:
        """Return DataFrame column name for a metric by semantic name."""

    def dimension(self, name: str) -> str:
        """Return DataFrame column name for a dimension by semantic name."""

    def metric_by_tag(self, tag: str) -> list[str]:
        """Return column names for all metrics with a given tag."""

    def dimension_by_role(self, role: DimensionRole) -> list[str]:
        """Return column names for all dimensions with a given role."""

    @property
    def time_column(self) -> str:
        """Return the time axis column name."""

    @property
    def grain_columns(self) -> list[str]:
        """Return the grain column names."""

    @property
    def materiality(self) -> MaterialityConfig:
        """Return the materiality config."""

    @property
    def policies(self) -> PolicyConfig:
        """Return the policy config."""

    def hierarchy_path(self, name: str) -> list[str]:
        """Return ordered list of dimension columns for a named hierarchy."""

    def hierarchy_children(self, level: str) -> list[str]:
        """Return the next level(s) below a given hierarchy level."""
```

**Construction**: `AnalysisContext(contract, df)` validates that every column referenced in the contract exists in `df.columns`. Raises `SchemaColumnMismatchError` listing all missing columns.

---

## 11. QualityReport (DataQualityGate Output)

```python
class QualityStatus(str, Enum):
    GO = "go"
    NO_GO = "no_go"
    WARNING = "warning"

class ViolationType(str, Enum):
    TIME_CONTINUITY = "time_continuity"
    GRAIN_UNIQUENESS = "grain_uniqueness"
    ADDITIVITY = "additivity"
    NULL_THRESHOLD = "null_threshold"
    COLUMN_EXISTENCE = "column_existence"

class Violation(BaseModel):
    """A single data quality check failure."""
    type: ViolationType
    severity: str = "error"            # "error" or "warning"
    message: str
    details: dict[str, Any] = {}       # e.g., {"missing_periods": ["2025-03"]}

class CheckResult(BaseModel):
    """Result of a single quality check."""
    name: str                          # e.g., "TimeContinuityCheck"
    passed: bool
    duration_ms: float
    record_count: int = 0
    violations: list[Violation] = []

class QualityReport(BaseModel):
    """Complete output of the DataQualityGate."""
    status: QualityStatus
    contract_name: str
    contract_version: str
    checked_at: datetime
    total_records: int
    total_duration_ms: float
    checks: list[CheckResult]
    violations: list[Violation]        # Flattened from all checks
```

---

## 12. Example Contract YAML: P&L (Migrated)

```yaml
name: "P&L Financial Data"
version: "1.0.0"
description: "Logistics P&L with operational metrics"

time:
  column: "period"
  frequency: "monthly"
  format: "%Y-%m"
  timezone: "America/Chicago"
  range_months: 24
  order_detail_months: 3

grain:
  columns: ["period", "cost_center", "gl_account"]
  description: "Monthly GL by cost center"

metrics:
  - name: "amount"
    column: "amount"
    type: "additive"
    format: "currency"
    optimization: "minimize"
    tags: ["primary"]

  - name: "miles"
    column: "total_miles"
    type: "additive"
    format: "integer"
    optimization: "maximize"
    tags: ["operational", "denominator"]

  - name: "loads"
    column: "orders"
    type: "additive"
    format: "integer"
    tags: ["operational", "denominator"]

  - name: "stops"
    column: "stops"
    type: "additive"
    format: "integer"
    tags: ["operational", "denominator"]

  - name: "cost_per_mile"
    column: "amount_per_mile"
    type: "non_additive"
    format: "currency"
    optimization: "minimize"
    tags: ["derived", "per_unit"]

dimensions:
  - name: "gl_account"
    column: "gl_account"
    role: "primary"
    tags: ["revenue_prefix:3"]

  - name: "canonical_category"
    column: "canonical_category"
    role: "secondary"

  - name: "cost_center"
    column: "gl_cst_ctr_cd"
    role: "filter"

  - name: "account_name"
    column: "acct_nm"
    role: "detail"

  - name: "level_1"
    column: "level_1"
    role: "detail"

  - name: "level_2"
    column: "level_2"
    role: "detail"

  - name: "level_3"
    column: "level_3"
    role: "detail"

  - name: "level_4"
    column: "level_4"
    role: "detail"

hierarchies:
  - name: "account_hierarchy"
    levels: ["level_1", "level_2", "level_3", "level_4"]
    description: "Chart of accounts rollup"

materiality:
  variance_pct: 5.0
  variance_dollar: 50000
  top_categories_count: 5
  cumulative_variance_pct: 80
  min_amount: 10000
  per_unit_thresholds:
    cost_per_mile_pct: 10.0
    cost_per_load_pct: 10.0
    cost_per_stop_pct: 10.0
  use_empirical: false

analysis:
  max_drill_depth: 4
  enable_driver_decomposition: true
  enable_stl_decomposition: true
  enable_forecasting: true
  z_score_threshold: 2.0
  correlation_threshold: 0.7

policies:
  severity:
    info:
      point_z_mad_min: 2.0
    warn:
      point_z_mad_min: 3.0
      pi_breaches_min: 1
    critical:
      change_point: true
      mom_pct_min: 25
      yoy_pct_min: 20
  windows: [3, 6, 12, 24]
  fatigue_suppress_days: 14
  fatigue_rearm_on_escalation: true
  root_cause_types:
    - accruals
    - timing
    - allocations
    - miscoding
    - operational
    - rate_change
    - volume_mix
    - one_time
  known_patterns:
    - name: "067_freight_revenue_q4_spike"
      pattern_type: "seasonal"
      description: "Q4 freight revenue typically up 10-15% due to holiday volume"
      affected_metrics: ["amount"]
      affected_dimensions:
        cost_center: ["067"]
        gl_account: ["3100-00", "3100-01", "3100-03"]
      months: [10, 11, 12]
      suppress_alerts: true
      documented_by: "Finance BP"
  suppression_rules:
    - name: "067_period_14_accruals"
      description: "Period 14 accruals cause timing variances"
      affected_dimensions:
        cost_center: ["067"]
        gl_account: ["4100-*", "4200-*"]
      periods: [14]
      suppress_severity_below: 0.6
      reason: "Known timing - accrual reversals in P14"
      active: true
  ownership:
    - dimension: "gl_account"
      value: "div_cd:107"
      owner: "Finance BP - West"
    - dimension: "cost_center"
      value: "067"
      owner: "Ops - Sacramento"
```
