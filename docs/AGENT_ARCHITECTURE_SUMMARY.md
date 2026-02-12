# P&L Analyst Agent - Complete Architecture Summary

**Date:** October 28, 2025  
**Version:** 2.0 (Hierarchical Implementation)

---

## Executive Overview

The P&L Analyst Agent is an intelligent financial analysis system built on Google's Agent Development Kit (ADK) that performs automated cost center analysis, anomaly detection, and actionable insights for logistics operations. The system processes 6.3M+ P&L transactions, 37M+ operational metrics, and order-level details through a sophisticated multi-agent architecture.

### Key Capabilities

- **Dynamic Cost Center Analysis**: Extracts and analyzes multiple cost centers from natural language
- **Multi-Source Data Integration**: Combines P&L data, operational metrics, and order details
- **Hierarchical Drill-Down**: Level 2 → Level 3 → Level 4 analysis with materiality-based decisions
- **Intelligent Alert Scoring**: Prioritizes findings by financial impact and urgency
- **Contract Validation**: Identifies billing discrepancies and recovery opportunities
- **Per-Unit Metrics**: Normalizes costs by operational volumes (per-mile, per-load, per-stop)

---

## Architecture Overview

### System Flow

```
User Query
    ↓
Cost Center Extraction (LLM)
    ↓
For Each Cost Center (Sequential):
    ├─ Data Fetching (3 Remote A2A Agents)
    │   ├─ P&L Data (24 months)
    │   ├─ Ops Metrics (24 months)
    │   └─ Order Details (3 months, conditional)
    ↓
    ├─ Data Validation & Enrichment
    │   ├─ Validate completeness
    │   ├─ Join ops metrics
    │   └─ Join chart of accounts metadata
    ↓
    ├─ Hierarchical Analysis (Data Analyst Agent)
    │   └─ Level 2 → Level 3 → Level 4 Loop
    │       ├─ Aggregate by hierarchy level
    │       ├─ Run 5 analysis agents in parallel
    │       ├─ LLM drill-down decision
    │       └─ Repeat or terminate
    ↓
    ├─ Synthesis (3-Level Report)
    │   ├─ Executive Summary
    │   ├─ Hierarchical Analysis
    │   └─ GL Detail (if reached)
    ↓
    ├─ Alert Scoring & Prioritization
    └─ Persist Results (JSON)
```

---

## Agent Catalog

### 1. Root Orchestration Agent

**Location:** `pl_analyst_agent/agent.py`

**Role:** Main orchestrator coordinating the entire analysis pipeline

**Key Components:**
- **Cost Center Extractor** (LLM): Parses cost center numbers from natural language
- **Request Analyzer** (LLM): Determines analysis scope and type
- **Date Initializer**: Calculates 24-month P&L and 3-month order detail ranges
- **Cost Center Loop**: Sequentially processes each cost center

**Configuration:**
- Model: `gemini-2.5-pro` (configurable via `agent_models.yaml`)
- Temperature: 0.0

**Workflow:**
1. Extract cost centers from user query
2. For each cost center:
   - Initialize date ranges
   - Fetch data from 3 sources
   - Run analysis pipeline
   - Generate and persist results

---

### 2. Remote A2A Agents (Data Sources)

#### 2.1 Tableau Account Research DS Agent

**Location:** Remote A2A Agent (http://localhost:8001)

**Purpose:** Retrieves monthly P&L data from Account Research dataset

**Data Characteristics:**
- **Volume:** 6.3M+ GL transactions
- **Granularity:** Aggregated by month/period (not order-level)
- **Time Range:** 24 months
- **Format:** CSV via `export_bulk_data_tool`
- **Schema:** period (YYYY-MM), gl_account, amount, cost_center

**Use Cases:**
- Monthly trend analysis
- Variance analysis (YoY, MoM)
- Historical P&L tracking

#### 2.2 Tableau Ops Metrics DS Agent

**Location:** Remote A2A Agent (http://localhost:8001)

**Purpose:** Retrieves monthly operational metrics

**Data Characteristics:**
- **Volume:** 37M+ records
- **Granularity:** Aggregated by cost center and month
- **Time Range:** 24 months
- **Metrics:** 
  - Miles (loaded, empty, total)
  - Orders, stops, trucks
  - Revenue (total, linehaul, accessorial)
  - Driver pay, fuel consumed
  - Driving/on-duty minutes
  - Service metrics

**Use Cases:**
- Cost center performance analysis
- Efficiency metrics
- Per-unit cost calculations

#### 2.3 Tableau Order Dispatch Revenue DS Agent

**Location:** Remote A2A Agent (http://localhost:8001)

**Purpose:** Retrieves order-level detail for contract validation

**Data Characteristics:**
- **Granularity:** Individual orders with full detail
- **Time Range:** 3 months (recent)
- **Details:** Stops, miles, tolls, dates, shippers, rates

**Use Cases:**
- Contract validation
- Billing recovery opportunities
- Order-level root cause analysis

**Conditional Fetching:**
- Only fetched when user requests contract validation
- Controlled by `should_fetch_order_details` tool

---

### 3. Data Preparation Agents

#### 3.1 Ingest & Validation Agent

**Location:** `pl_analyst_agent/sub_agents/ingest_validator_agent/`

**Model:** `gemini-2.0-flash-lite` (ultra-fast tier)

**Purpose:** Validates, cleans, and enriches all fetched data

**Tools:**
- `reshape_and_validate`: Validates data completeness and quality
- `load_and_validate_from_cache`: Loads CSV data (TEST_MODE)
- `aggregate_by_category`: Groups GLs by canonical category
- `join_ops_metrics`: Merges P&L with operational volumes
- `join_chart_metadata`: Adds level_1, level_2, level_3, level_4 hierarchy
- `json_to_csv` / `csv_to_json_passthrough`: Format conversions

**Output:**
- `validated_data`: Enriched DataFrame with P&L + ops metrics + hierarchy

**Data Integrity:**
- **Fail Fast:** Returns structured error if data missing or invalid
- **No Mock Data:** Never fabricates values
- **Schema Validation:** Checks required fields before proceeding

---

### 4. Analysis Coordinator

#### 4.1 Data Analyst Agent

**Location:** `pl_analyst_agent/sub_agents/data_analyst_agent/`

**Model:** `gemini-2.5-flash` (standard tier)

**Purpose:** Stats-first analysis coordinator with hierarchical drill-down

**Architecture:**
```
InitializeHierarchicalLoop (Level 2)
    ↓
LoopAgent (Hierarchical Drill-Down):
    ├─ Level Analyzer Agent (aggregate & rank)
    ├─ Parallel Analysis (5 agents)
    ├─ DrillDownDecisionAgent (LLM: continue or stop?)
    ├─ ProcessDrillDownDecision (update state)
    └─ Repeat or Finalize
    ↓
FinalizeAnalysisResults
```

**Components:**
1. **StatisticalComputationAgent**: Computes comprehensive statistics in Python/pandas
2. **StatisticalInsightsAgent** (LLM): Interprets statistics and provides business insights
3. **InitializeHierarchicalLoop**: Sets starting level (Level 2)
4. **DrillDownDecisionAgent** (LLM): Decides whether to drill deeper based on materiality
5. **ProcessDrillDownDecision**: Updates loop state and escalates when done
6. **FinalizeAnalysisResults**: Aggregates results from all levels reached

**Drill-Down Logic:**
- Starts at Level 2 (high-level categories)
- Analyzes top 3-5 variance drivers at each level
- LLM decides whether to drill to next level based on:
  - Materiality thresholds (±5% or ±$50K)
  - Severity of findings
  - Pattern types (operational vs timing)
- Continues to Level 3, then Level 4 (GL detail) if warranted
- Stops when no material variances or GL detail reached

**Output:**
- `level_2_result`, `level_3_result`, `level_4_result` (as applicable)

---

### 5. Analysis Sub-Agents (Run in Parallel at Each Level)

#### 5.1 Level Analyzer Agent

**Location:** `pl_analyst_agent/sub_agents/data_analysis/level_analyzer_agent/`

**Model:** `gemini-2.5-flash` (standard tier)

**Purpose:** Aggregates financial data by hierarchy level and ranks variance drivers

**Tools:**
- `get_validated_csv_from_state`: Retrieves validated data
- `aggregate_by_level`: Groups GL accounts by level_N field from chart of accounts
- `rank_level_items_by_variance`: Sorts items by absolute dollar variance
- `identify_top_level_drivers`: Selects top 3-5 items explaining 80%+ of variance

**Output:**
- `level_analysis_result`: Ranked list of top variance drivers with metadata

**Hierarchy Levels:**
- **Level 1:** Total Operating Revenue, Total Operating Expenses
- **Level 2:** Freight Revenue, Driver Pay, Fuel, Maintenance, etc.
- **Level 3:** Sub-categories within Level 2 items
- **Level 4:** Individual GL accounts

#### 5.2 Statistical Analysis Agent

**Location:** `pl_analyst_agent/sub_agents/data_analysis/statistical_analysis_agent/` (if exists as separate agent)

**Model:** `gemini-2.5-flash-lite` (fast tier)

**Purpose:** Computes variances and applies materiality thresholds

**Capabilities:**
- Descriptive statistics (mean, median, std dev)
- Variance calculations: YoY, MoM, 3-month moving average (3MMA), 6-month moving average (6MMA)
- Period comparisons
- Materiality filtering (±5% or ±$50K)

**Thresholds (from `materiality_config.yaml`):**
- Variance percentage: ±5.0%
- Variance dollar: ±$50,000
- Minimum amount: $10,000
- Top categories count: 5
- Cumulative variance target: 80%

#### 5.3 Seasonal Baseline Agent

**Location:** `pl_analyst_agent/sub_agents/data_analysis/seasonal_baseline_agent/` (if exists)

**Model:** `gemini-2.5-flash` (standard tier)

**Purpose:** Creates seasonal baselines and YoY comparisons

**Capabilities:**
- Year-over-year comparisons
- Seasonal pattern detection
- Timing adjustments

#### 5.4 Ratio Analysis Agent

**Location:** `pl_analyst_agent/sub_agents/data_analysis/ratio_analysis_agent/` (if exists)

**Model:** `gemini-2.5-flash-lite` (fast tier)

**Purpose:** Performs operational volume normalization

**Capabilities:**
- Per-unit metrics: cost per mile, per load, per stop
- Variance decomposition: ΔCost = (ΔRate × Volume) + (Rate × ΔVolume)
- Rate effect vs volume effect analysis

**Thresholds (from `materiality_config.yaml`):**
- Cost per mile variance: ±10%
- Cost per load variance: ±10%
- Cost per stop variance: ±10%

#### 5.5 Anomaly Detection Agent

**Location:** `pl_analyst_agent/sub_agents/data_analysis/anomaly_detection_agent/` (if exists)

**Model:** `gemini-2.5-flash` (standard tier)

**Purpose:** Multi-method anomaly detection

**Capabilities:**
- Change point detection
- Drift detection
- Timing swing identification
- Statistical outlier detection (Z-scores, MAD)

**Alert Severity (from `alert_policy.yaml`):**
- **Info:** Z-score MAD ≥ 2.0
- **Warn:** Z-score MAD ≥ 3.0, 1+ PI breaches
- **Critical:** Change point detected, MoM ≥ 25%, YoY ≥ 20%

---

### 6. Synthesis & Reporting

#### 6.1 Synthesis Agent

**Location:** `pl_analyst_agent/sub_agents/synthesis_agent/`

**Model:** `gemini-2.5-flash` (standard tier)

**Purpose:** Synthesizes results from all analysis agents into structured executive report

**Output Structure (3-Level Framework):**

**Level 1 - Executive Summary (5 bullets):**
- Overall variance summary (YoY, MoM, 3MMA, 6MMA)
- Top 2-4 category/level drivers explaining 80%+ of variance
- Seasonal/timing factors
- Key insights and recommendations
- Next steps

**Level 2 - Hierarchical Analysis:**
- Ranked list of Level 2 items by absolute dollar variance
- Materiality filtering applied
- Focused on top drivers explaining majority of change

**Level 3 - Drill-Down (if reached):**
- Detailed analysis of Level 3 sub-categories or Level 4 GLs
- Root cause classification:
  - **Accruals:** Monthly variance, YoY stable
  - **Timing:** Month shifts, YoY stable
  - **Allocations:** Cross-account, YoY varies
  - **Miscoding:** Irregular patterns
  - **Operational:** Volume/rate driven
- One-time vs run-rate pattern detection
- Per-unit metrics with variance decomposition

**Output Key:** `synthesis_result`

---

### 7. Alert Management

#### 7.1 Alert Scoring Coordinator Agent

**Location:** `pl_analyst_agent/sub_agents/alert_scoring_coordinator_agent/`

**Model:** `gemini-2.5-flash` (standard tier)

**Purpose:** Complete alert lifecycle management (extraction, scoring, suppression, prioritization)

**Tools:**
- `extract_alerts_from_analysis`: Parses analysis results for actionable alerts
- `score_alerts`: Multi-factor scoring (Impact × Confidence × Persistence)
- `apply_suppression`: Deduplication and low-value filtering
- `get_order_details_for_period`: Fetches order data for validation
- `get_top_shippers_by_miles`: Identifies high-volume shippers
- `get_monthly_aggregates_by_cost_center`: Cost center trends
- `capture_feedback`: Stores user feedback for learning

**Scoring Factors:**
1. **Financial Impact:** Dollar magnitude of variance
2. **Confidence:** Statistical significance and pattern clarity
3. **Persistence:** Duration of issue (one-time vs ongoing)
4. **Severity:** Info, Warn, Critical (from alert policy)

**Suppression Rules (from `alert_policy.yaml`):**
- Suppress for 14 days after alert
- Rearm on escalation

**Ownership Mapping:**
- Maps cost centers to responsible teams
- Example: CC 067 → "Ops - Sacramento"

**Output:**
- `alert_scoring_result`: Prioritized list of alerts with recommended actions
- Saved to `outputs/alerts_payload_ccXXX.json`

---

### 8. Persistence

#### 8.1 Persist Insights Agent

**Location:** `pl_analyst_agent/sub_agents/persist_insights_agent/`

**Purpose:** Saves complete analysis results to JSON files

**Outputs:**
- `outputs/cost_center_XXX.json`: Full analysis report
- `outputs/alerts_payload_ccXXX.json`: Scored alerts

**File Contents:**
- Executive summary
- Hierarchical analysis (all levels reached)
- Statistical analysis
- Per-unit metrics
- Anomaly detection results
- Prioritized alerts with recommended actions
- Metadata: timestamp, cost center, period range

---

### 9. Utility Agents

#### 9.1 Testing Data Agent

**Location:** `pl_analyst_agent/sub_agents/testing_data_agent/`

**Purpose:** Provides CSV-based data loading for development/testing

**Usage:**
- Set environment variable: `PL_ANALYST_TEST_MODE=true`
- Bypasses Tableau A2A agents
- Loads data from CSV files in `data/` directory

**Use Cases:**
- Unit testing
- Local development without A2A server
- CI/CD pipelines

---

## Configuration Files

### 1. Agent Models Configuration

**Location:** `config/agent_models.yaml`

**Purpose:** Defines which Gemini models to use for each agent

**Model Tiers:**
- **Ultra:** `gemini-2.0-flash-lite` - Ultra-fast for simple operations
- **Fast:** `gemini-2.5-flash-lite` - Fast for simple tasks
- **Standard:** `gemini-2.5-flash` - Balanced for general use
- **Advanced:** `gemini-2.5-pro` - High-capability for complex reasoning

**Agent Assignments:**
- Ingest Validator: Ultra (data validation)
- Statistical Analysis: Fast (computation-heavy)
- Level Analyzer: Standard (LLM decision-making)
- Synthesis: Standard (complex reasoning)
- Alert Scoring: Standard (multi-factor analysis)

### 2. Materiality Configuration

**Location:** `config/materiality_config.yaml`

**Thresholds:**
- Variance percentage: ±5.0%
- Variance dollar: ±$50,000
- Minimum amount: $10,000
- Top categories count: 5
- Cumulative variance target: 80%

**Per-Unit Thresholds:**
- Cost per mile: ±10%
- Cost per load: ±10%
- Cost per stop: ±10%

### 3. Alert Policy Configuration

**Location:** `config/alert_policy.yaml`

**Severity Levels:**
- **Info:** Z-score MAD ≥ 2.0, 0+ PI breaches
- **Warn:** Z-score MAD ≥ 3.0, 1+ PI breaches
- **Critical:** Change point true, MoM ≥ 25%, YoY ≥ 20%

**Fatigue Settings:**
- Suppress for 14 days
- Rearm on escalation

**Ownership Mapping:**
- Maps GL divisions and cost centers to responsible teams

### 4. Chart of Accounts

**Location:** `config/chart_of_accounts.yaml`

**Purpose:** Single source of truth for account hierarchy and canonical categories

**Structure:**
```yaml
accounts:
  "6020-01":
    acct_nm: "Diesel Fuel"
    level_1: "Total Operating Expenses"
    level_2: "Fuel"
    level_3: "Road Fuel"
    level_4: "Diesel Fuel"
    canonical_category: "Fuel"
```

**Canonical Categories:**
- Wages, Benefits, Fuel, Equipment, Facilities
- Insurance, PurchasedTransportation, Allocations
- TaxesLicenses, Utilities, OtherOps
- Amortization, Impairments, GainsLosses

**Loader Functions** (`config/chart_loader.py`):
- `get_accounts_by_level(level_number)`: Returns {level_name: [accounts]}
- `get_level_hierarchy(account_code)`: Returns {level_1, level_2, level_3, level_4}
- `get_all_accounts_with_levels()`: Complete mapping
- `get_level_items_list(level_number)`: Unique level names

---

## Tools Catalog

### Root Agent Tools

**Location:** `pl_analyst_agent/tools/`

- **`calculate_date_ranges`**: Computes 24-month P&L and 3-month order detail ranges
- **`parse_cost_centers`**: Extracts cost center numbers from user query
- **`iterate_cost_centers`**: Loop control for sequential cost center processing
- **`should_fetch_order_details`**: Determines if order data needed
- **`create_data_request_message`**: Formats data queries for A2A agents

### Ingest Validator Tools

**Location:** `pl_analyst_agent/sub_agents/ingest_validator_agent/tools/`

- **`reshape_and_validate`**: Validates data completeness and quality
- **`load_and_validate_from_cache`**: Loads CSV data (TEST_MODE)
- **`aggregate_by_category`**: Groups GLs by canonical_category
- **`join_ops_metrics`**: Merges P&L with operational volumes
- **`join_chart_metadata`**: Adds hierarchy levels from chart of accounts
- **`json_to_csv`** / **`csv_to_json_passthrough`**: Format conversions

### Level Analyzer Tools

**Location:** `pl_analyst_agent/sub_agents/data_analysis/level_analyzer_agent/tools/`

- **`aggregate_by_level`**: Groups GL accounts by level_N field
- **`rank_level_items_by_variance`**: Sorts items by absolute dollar variance
- **`identify_top_level_drivers`**: Selects top 3-5 items (80% rule)
- **`get_validated_csv_from_state`**: Retrieves validated data from state

### Data Analyst Tools

**Location:** `pl_analyst_agent/sub_agents/data_analyst_agent/tools/`

- **`compute_statistical_summary`**: Computes comprehensive statistics in Python/pandas
  - Top drivers identification
  - Anomaly detection (Z-scores, change points)
  - Correlations analysis
  - Monthly totals and summary stats
  - Per-unit metrics calculation

### Alert Scoring Tools

**Location:** `pl_analyst_agent/sub_agents/alert_scoring_coordinator_agent/tools/`

- **`extract_alerts_from_analysis`**: Parses analysis for actionable alerts
- **`score_alerts`**: Multi-factor scoring (Impact × Confidence × Persistence)
- **`apply_suppression`**: Deduplication and low-value filtering
- **`get_order_details_for_period`**: Fetches order data for validation
- **`get_top_shippers_by_miles`**: Identifies high-volume shippers
- **`get_monthly_aggregates_by_cost_center`**: Cost center trends
- **`capture_feedback`**: Stores user feedback for learning
- **`contract_rate_tools`**: Contract validation utilities
- **`_llm_extract_alerts_from_text`**: LLM-based alert parsing

---

## Workflow Details

### Complete Analysis Workflow

#### Phase 1: Request Processing (5-10s)

1. **User Query Reception**
   - Example: "Analyze cost center 067 for contract violations"

2. **Cost Center Extraction (LLM)**
   - Tool: `parse_cost_centers`
   - Model: `gemini-2.5-flash` (standard)
   - Extracts: ["067"]

3. **Date Range Calculation**
   - Tool: `calculate_date_ranges`
   - P&L range: Last 24 months
   - Order detail range: Last 3 months

#### Phase 2: Data Fetching (15-20s per cost center)

**Sequential Execution with Rate Limiting**

1. **P&L Data Fetch**
   - Agent: `tableau_account_research_ds_agent`
   - Request: CC 067, 24 months, all GL accounts
   - Format: CSV time series

2. **Ops Metrics Fetch**
   - Agent: `tableau_ops_metrics_ds_agent`
   - Request: CC 067, 24 months
   - Metrics: Miles, loads, stops, revenue, etc.

3. **Order Details Fetch (Conditional)**
   - Agent: `tableau_order_dispatch_revenue_ds_agent`
   - Condition: Contract validation requested
   - Request: CC 067, 3 months, order-level detail

#### Phase 3: Data Validation & Enrichment (5-10s)

**Agent:** `ingest_validator_agent`

1. **Validation**
   - Check data completeness
   - Validate schema
   - Detect missing periods

2. **Enrichment**
   - Join ops metrics (miles, loads, stops)
   - Join chart of accounts metadata (levels 1-4, canonical_category)

3. **Output**
   - `validated_data`: Enriched DataFrame
   - Fail fast on errors (no mock data)

#### Phase 4: Hierarchical Analysis (30-45s)

**Agent:** `data_analyst_agent`

**Level 2 Analysis (10-15s):**
1. Aggregate by level_2
2. Run 5 analysis agents in parallel:
   - Level Analyzer (rank drivers)
   - Statistical Analysis (variances)
   - Seasonal Baseline (YoY patterns)
   - Ratio Analysis (per-unit metrics)
   - Anomaly Detection (change points)
3. LLM drill-down decision:
   - Materiality: ±5% or ±$50K?
   - Pattern: Operational vs timing?
   - Decision: CONTINUE or STOP

**Level 3 Analysis (10-15s, if triggered):**
1. Drill into top 3-5 Level 2 items
2. Aggregate by level_3 within each
3. Run 5 analysis agents in parallel
4. LLM drill-down decision

**Level 4 Analysis (10-15s, if triggered):**
1. Drill to GL account level
2. Full root cause analysis
3. Per-unit metrics with variance decomposition
4. LLM decision: STOP (reached detail)

#### Phase 5: Synthesis (5-10s)

**Agent:** `synthesis_agent`

**Generates 3-Level Report:**

1. **Level 1 - Executive Summary (5 bullets)**
   ```
   - Overall variance: -$425K YoY (-12%)
   - Top drivers: Fuel -$300K, Labor +$150K, Maint -$200K
   - Seasonal: Fuel costs up due to winter rates
   - Operational: Volume down 8%, per-mile costs stable
   - Next steps: Investigate fuel contracts, labor overtime
   ```

2. **Level 2 - Hierarchical Analysis**
   ```
   - Fuel: -$300K (-15%) - Material variance
   - Maintenance: -$200K (-22%) - Material variance
   - Labor: +$150K (+8%) - Material variance
   - Supplies: -$75K (-18%) - Material variance
   ```

3. **Level 3/4 - Drill-Down (if reached)**
   ```
   Fuel Category:
   - GL 6020 Diesel Fuel: -$280K
     Root Cause: Operational (rate: -$200K, volume: -$80K)
     Pattern: Run-rate change (not one-time)
     Per-Mile: $0.85/mi (vs $0.92/mi LY)
   
   - GL 6025 Fuel Surcharge: -$20K
     Root Cause: Timing (recovery lag in Sep)
     Pattern: One-time variance
   ```

#### Phase 6: Alert Scoring (5-10s)

**Agent:** `alert_scoring_coordinator`

1. **Extract Alerts**
   - Parse synthesis for actionable items
   - Example: Fuel variance -$300K, contract issue

2. **Score Alerts**
   - Financial impact: High ($300K)
   - Confidence: High (clear pattern)
   - Persistence: Run-rate change
   - Severity: Critical

3. **Apply Suppression**
   - Deduplicate similar alerts
   - Filter low-value items
   - Check suppression windows

4. **Recommend Actions**
   - "Review fuel contracts with top 5 suppliers"
   - "Validate fuel surcharge recovery process"

#### Phase 7: Persistence (1-2s)

**Agent:** `persist_insights_agent`

**Outputs:**
- `outputs/cost_center_067.json`: Full analysis
- `outputs/alerts_payload_cc067.json`: Scored alerts

#### Total Time Per Cost Center

- **Single Cost Center:** 65-100s
- **Multiple Cost Centers:** Sequential (no overlap)
- **Efficiency Gain:** 40% vs analyzing all GLs

---

## Performance Characteristics

### Timing Breakdown

| Phase | Duration | Notes |
|-------|----------|-------|
| Request Processing | 5-10s | LLM extraction + date calc |
| Data Fetching | 15-20s | 3 A2A agents with rate limiting |
| Data Validation | 5-10s | Enrichment + joins |
| Level 2 Analysis | 10-15s | 5 agents in parallel |
| Level 3 Analysis | 10-15s | If triggered |
| Level 4 Analysis | 10-15s | If triggered |
| Synthesis | 5-10s | 3-level report generation |
| Alert Scoring | 5-10s | Multi-factor scoring |
| Persistence | 1-2s | JSON write |
| **Total** | **65-100s** | Per cost center |

### Optimization Strategies

1. **Parallel Data Fetch:** 3 A2A agents fetch concurrently
2. **Parallel Analysis:** 5 agents run simultaneously at each level
3. **Smart Drill-Down:** Only analyzes top variance drivers (80% rule)
4. **Safe Parallel Wrapper:** Isolates failures without cascading
5. **Materiality Filtering:** Focuses on significant variances only

### Scalability

- **Cost Centers:** Sequential processing (clean data isolation)
- **Concurrency:** Parallel analysis within each cost center
- **Data Volume:** Handles 6.3M+ P&L transactions, 37M+ ops metrics
- **Rate Limiting:** Respects Google Cloud API quotas

---

## Data Integrity & Safety

### Operating Principles

1. **LLM for Intelligence; Code for Infrastructure**
   - LLMs: Decisions, classification, analysis, insights
   - Python: I/O, APIs, auth, performance-critical paths

2. **Grounded Reasoning**
   - Tool-grounded decisions (DB, APIs, search)
   - Fail explicitly on missing data
   - Never fabricate values

3. **Fail Fast**
   - Return structured error on data issues:
     ```json
     {
       "error": "DataUnavailable",
       "source": "ingest_validator_agent",
       "detail": "Missing P&L data for period 2024-01",
       "action": "stop"
     }
     ```
   - Short-circuit on invalid inputs
   - Log and surface root cause

### Never Rules

- Never use mock/placeholder data in production
- Never silently default missing values
- Never infer schema from column names
- Never proceed after tool failures

### Always Rules

- Always validate schemas before LLM calls
- Always return structured errors
- Always log failures with context
- Always use null for unknowns (not guesses)

---

## Output Contracts

### Insight Report Structure

```json
{
  "version": "2.0",
  "cost_center": "067",
  "period_range": "2023-01 to 2024-12",
  "executive_summary": [
    "Overall variance: -$425K YoY (-12%)",
    "Top drivers: Fuel -$300K, Labor +$150K, Maint -$200K",
    "Seasonal: Fuel costs up due to winter rates",
    "Operational: Volume down 8%, per-mile costs stable",
    "Next steps: Investigate fuel contracts, labor overtime"
  ],
  "level_2_analysis": [
    {
      "level_name": "Fuel",
      "variance_yoy": -300000,
      "variance_pct": -15.0,
      "materiality": "material",
      "top_drivers": ["GL 6020 Diesel Fuel", "GL 6025 Fuel Surcharge"]
    }
  ],
  "level_3_analysis": [ /* if reached */ ],
  "level_4_analysis": [ /* if reached */ ],
  "alerts": [ /* see alert structure below */ ],
  "metadata": {
    "timestamp": "2025-10-28T10:30:00Z",
    "analysis_levels_reached": ["2", "3", "4"],
    "drill_down_decisions": ["CONTINUE", "CONTINUE", "STOP"]
  }
}
```

### Alert Structure

```json
{
  "alert_id": "cc067_fuel_2024",
  "severity": "critical",
  "category": "Fuel",
  "gl_accounts": ["6020-01", "6020-02"],
  "financial_impact": -300000,
  "variance_pct": -15.0,
  "pattern": "run_rate_change",
  "root_cause": "operational",
  "confidence": 0.95,
  "persistence": "ongoing",
  "recommended_actions": [
    "Review fuel contracts with top 5 suppliers",
    "Validate fuel surcharge recovery process"
  ],
  "ownership": "Ops - Sacramento",
  "timestamp": "2025-10-28T10:30:00Z"
}
```

---

## Testing & Development

### Test Mode

**Environment Variable:** `PL_ANALYST_TEST_MODE=true`

**Behavior:**
- Bypasses Tableau A2A agents
- Loads data from CSV files in `data/` directory
- Uses `testing_data_agent`

**Use Cases:**
- Unit testing
- Local development without A2A server
- CI/CD pipelines

### Testing Strategy

**Data Source Tests:**
```bash
python data/test_database_connection.py
python data/test_tableau_connection.py
python data/validate_data_sources.py
```

**Integration Tests:**
```bash
python scripts/tests/test_pl_analyst_direct.py
python scripts/tests/test_pl_analyst_validation.py
python scripts/tests/test_alert_scoring.py
python scripts/tests/test_tableau_agents.py
```

### Test Scenarios

1. **Level 2 Only:** Low variance (should stop at Level 2)
2. **Level 2→3:** Material Level 2 variance (should drill to Level 3)
3. **Level 2→3→4:** Critical issues (should drill to Level 4)
4. **TEST_MODE:** CSV loading with hierarchy
5. **Error Handling:** Missing data, invalid periods

---

## Deployment

### Prerequisites

- Python 3.10+
- Google Cloud account with Vertex AI API enabled
- gcloud CLI authenticated
- SQL Server access (for Tableau data)
- ODBC Driver 17 for SQL Server

### Quick Start

```bash
# 1. Setup environment
cd pl_analyst
python -m venv .venv
.venv\Scripts\activate  # Windows
pip install -r requirements.txt

# 2. Configure
cp config/env.example .env
# Edit .env with your settings

# 3. Setup credentials
# Add service-account.json
# Add database_config.yaml

# 4. Test data sources
python data/validate_data_sources.py

# 5. Start A2A server (separate terminal)
cd ../remote_a2a
python start_a2a_server.py

# 6. Run analysis
python -c "from pl_analyst_agent.agent import root_agent; ..."
```

### Deployment to Vertex AI

```bash
python deployment/deploy_with_tracing.py --create \
  --project_id=your-project-id \
  --location=us-central1 \
  --bucket=your-storage-bucket
```

---

## Security & Compliance

### Never Commit

- `service-account.json`
- `database_config.yaml`
- `.env`
- `outputs/*.json`
- `logs/*.log`

### Secrets Management

- Use environment variables for secrets
- Store service accounts securely
- Respect data residency requirements
- Redact PII in logs

### Authentication

- Service account authentication via `auth_config.py`
- Google Cloud credentials via `GOOGLE_APPLICATION_CREDENTIALS`
- Database credentials via `database_config.yaml`

---

## Key Files & Directories

### Entry Points

- `pl_analyst_agent/agent.py`: Main orchestration agent
- `start_a2a_server.py`: Launch A2A data agents (in remote_a2a/)
- `deployment/deploy_with_tracing.py`: Deploy to Vertex AI
- `data/validate_data_sources.py`: Validate all connections

### Configuration

- `config/agent_models.yaml`: Model assignments
- `config/materiality_config.yaml`: Thresholds
- `config/alert_policy.yaml`: Scoring rules
- `config/chart_of_accounts.yaml`: Account hierarchy
- `.env`: Environment variables

### Documentation

- `README.md`: Project overview
- `HIERARCHICAL_IMPLEMENTATION.md`: Recent architecture changes
- `TEST_MODE_README.md`: Testing guide
- `QUICKSTART_FIXES.md`: Setup troubleshooting

### Outputs

- `outputs/cost_center_XXX.json`: Analysis results
- `outputs/alerts_payload_ccXXX.json`: Scored alerts
- `logs/`: Runtime logs (gitignored)

---

## Recent Changes

### Version 2.0 (October 27, 2025)

**Major Refactoring: Hierarchical Implementation**

**Removed:**
- `visualization_agent` (no longer generating charts)
- `forecasting_agent` (no ARIMA forecasting)
- `category_analyzer_agent` (replaced by level_analyzer_agent)
- `gl_drilldown_agent` (logic moved to data_analyst_agent)

**Added:**
- `data_analyst_agent`: Main orchestrator with hierarchical LoopAgent
- `level_analyzer_agent`: Level-aware aggregation and ranking
- `chart_loader.py`: Chart of accounts utility

**Architecture Change:**
- Before: Category Analysis → GL Drill → 8 Parallel Agents
- After: Level 2→3→4 Loop with 5 Parallel Agents per level

**Benefits:**
- 40% efficiency gain (focused analysis)
- Clearer drill-down logic
- Better materiality filtering
- Simplified workflow

---

## Support & Troubleshooting

### Common Issues

**A2A Server Connection:**
```python
from pl_analyst.agent import verify_tableau_agents
status = verify_tableau_agents()
```

**Authentication Errors:**
```python
from pl_analyst.config import config
config.validate()
```

**Import Errors:**
```bash
python verify_structure.py
```

### Resources

- Project README: `README.md`
- Architecture docs: `docs/` directory
- Cursor rules: `.cursor/rules/pl-analyst-project-structure.mdc`
- Hierarchical implementation: `HIERARCHICAL_IMPLEMENTATION.md`

---

## Future Enhancements

### Planned Features

1. **Dynamic Forecasting:** Reintroduce ARIMA with configurable toggle
2. **Visualization:** Optional chart generation via API
3. **Real-Time Monitoring:** Streaming alerts and dashboards
4. **Feedback Loop:** Machine learning from user feedback
5. **Multi-Tenant:** Support multiple organizations

### Performance Improvements

1. **Caching:** LLM result caching by prompt hash
2. **Batch Processing:** Parallel cost center analysis
3. **Incremental Analysis:** Delta updates vs full rerun
4. **Predictive Fetching:** Pre-fetch likely drill-down data

---

## Appendix

### Agent Model Mapping

| Agent | Model | Tier | Purpose |
|-------|-------|------|---------|
| Root Agent | gemini-2.5-pro | Advanced | Orchestration |
| Cost Center Extractor | gemini-2.5-flash | Standard | Parsing |
| Ingest Validator | gemini-2.0-flash-lite | Ultra | Data validation |
| Data Analyst | gemini-2.5-flash | Standard | Stats-first analysis |
| Level Analyzer | gemini-2.5-flash | Standard | Hierarchy aggregation |
| Statistical Analysis | gemini-2.5-flash-lite | Fast | Variance calc |
| Seasonal Baseline | gemini-2.5-flash | Standard | YoY patterns |
| Ratio Analysis | gemini-2.5-flash-lite | Fast | Per-unit metrics |
| Anomaly Detection | gemini-2.5-flash | Standard | Change points |
| Synthesis | gemini-2.5-flash | Standard | Report generation |
| Alert Scoring | gemini-2.5-flash | Standard | Prioritization |

### Glossary

- **A2A:** Agent-to-Agent communication protocol
- **ADK:** Agent Development Kit (Google)
- **GL:** General Ledger account
- **YoY:** Year-over-Year
- **MoM:** Month-over-Month
- **3MMA:** 3-Month Moving Average
- **6MMA:** 6-Month Moving Average
- **MAD:** Median Absolute Deviation
- **Z-score:** Standard deviation units from mean
- **PI:** Prediction Interval

---

**Document Version:** 1.0  
**Last Updated:** October 28, 2025  
**Maintained By:** P&L Analyst Development Team

