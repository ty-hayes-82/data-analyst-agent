# P&L Analyst - Workflow Diagrams

## High-Level System Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                          USER QUERY                              │
│           "Analyze cost center 067 for contract violations"      │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                  ROOT ORCHESTRATION AGENT                        │
│                  (pl_analyst_agent/agent.py)                     │
│                                                                   │
│  Tools: parse_cost_centers, calculate_date_ranges                │
│  Output: ["067"], date_ranges                                    │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
        ┌────────────────────────────────────────┐
        │  FOR EACH COST CENTER (Sequential)      │
        └────────────────┬───────────────────────┘
                         │
        ┌────────────────┴────────────────┐
        │    PHASE 1: DATA FETCHING       │
        │         (15-20s)                │
        └────────────────┬────────────────┘
                         │
        ┌────────────────┴────────────────┬────────────────┬────────────────┐
        ▼                                 ▼                                 ▼
┌────────────────┐            ┌────────────────┐            ┌────────────────┐
│  Tableau P&L   │            │  Tableau Ops   │            │  Tableau Order │
│    A2A Agent   │            │  Metrics A2A   │            │  Dispatch A2A  │
│                │            │     Agent      │            │     Agent      │
│  24mo P&L data │            │ 24mo ops data  │            │ 3mo order data │
│  6.3M+ records │            │ 37M+ records   │            │  (conditional) │
└────────┬───────┘            └────────┬───────┘            └────────┬───────┘
         │                             │                             │
         └─────────────────────────────┼─────────────────────────────┘
                                       │
                                       ▼
        ┌──────────────────────────────────────────────────┐
        │    PHASE 2: DATA VALIDATION & ENRICHMENT         │
        │         (ingest_validator_agent)                 │
        │                 (5-10s)                          │
        │                                                  │
        │  Tools:                                          │
        │  - reshape_and_validate                          │
        │  - join_ops_metrics                              │
        │  - join_chart_metadata                           │
        │                                                  │
        │  Output: validated_data (enriched DataFrame)     │
        └────────────────────────┬─────────────────────────┘
                                 │
                                 ▼
        ┌──────────────────────────────────────────────────┐
        │    PHASE 3: HIERARCHICAL ANALYSIS                │
        │         (data_analyst_agent)                     │
        │              (30-45s)                            │
        └────────────────────────┬─────────────────────────┘
                                 │
                                 ▼
        ┌──────────────────────────────────────────────────┐
        │              LEVEL 2 ANALYSIS                    │
        │               (10-15s)                           │
        │                                                  │
        │  Step 1: Level Analyzer Agent                   │
        │    - Aggregate by level_2                       │
        │    - Rank by variance                           │
        │    - Identify top 3-5 drivers                   │
        │                                                  │
        │  Step 2: Parallel Analysis (5 agents):          │
        │    ┌─────────────────────────────────────┐      │
        │    │ 1. Statistical Analysis Agent       │      │
        │    │ 2. Seasonal Baseline Agent          │      │
        │    │ 3. Ratio Analysis Agent             │      │
        │    │ 4. Anomaly Detection Agent          │      │
        │    │ 5. Level Analyzer Agent             │      │
        │    └─────────────────────────────────────┘      │
        │                                                  │
        │  Step 3: LLM Drill-Down Decision                │
        │    - Materiality: ±5% or ±$50K?                 │
        │    - Pattern: Operational vs timing?            │
        │    - Decision: CONTINUE or STOP?                │
        └────────────────────────┬─────────────────────────┘
                                 │
                 ┌───────────────┴───────────────┐
                 │   LLM Decision: CONTINUE?     │
                 └───────────┬───────────────────┘
                             │
                    ┌────────┴────────┐
                    │ YES             │ NO
                    ▼                 ▼
        ┌───────────────────┐  ┌──────────────┐
        │  LEVEL 3 ANALYSIS │  │  FINALIZE    │
        │     (10-15s)      │  │  RESULTS     │
        └─────────┬─────────┘  └──────┬───────┘
                  │                   │
          ┌───────┴───────┐           │
          │ LLM Decision: │           │
          │  CONTINUE?    │           │
          └───────┬───────┘           │
                  │                   │
         ┌────────┴────────┐          │
         │ YES             │ NO       │
         ▼                 ▼          │
┌────────────────┐  ┌──────────────┐ │
│ LEVEL 4        │  │  FINALIZE    │ │
│ ANALYSIS       │  │  RESULTS     │ │
│   (10-15s)     │  └──────┬───────┘ │
└────────┬───────┘         │         │
         │                 │         │
         └─────────────────┴─────────┘
                           │
                           ▼
        ┌──────────────────────────────────────────────────┐
        │    PHASE 4: SYNTHESIS                            │
        │         (synthesis_agent)                        │
        │              (5-10s)                             │
        │                                                  │
        │  Generate 3-Level Report:                        │
        │  - Level 1: Executive Summary (5 bullets)        │
        │  - Level 2: Hierarchical Analysis                │
        │  - Level 3/4: Drill-Down (if reached)            │
        │                                                  │
        │  Output: synthesis_result                        │
        └────────────────────────┬─────────────────────────┘
                                 │
                                 ▼
        ┌──────────────────────────────────────────────────┐
        │    PHASE 5: ALERT SCORING                        │
        │         (alert_scoring_coordinator)              │
        │              (5-10s)                             │
        │                                                  │
        │  Steps:                                          │
        │  1. Extract alerts from analysis                 │
        │  2. Score by Impact × Confidence × Persistence   │
        │  3. Apply suppression rules                      │
        │  4. Generate recommended actions                 │
        │                                                  │
        │  Output: alert_scoring_result                    │
        └────────────────────────┬─────────────────────────┘
                                 │
                                 ▼
        ┌──────────────────────────────────────────────────┐
        │    PHASE 6: PERSISTENCE                          │
        │         (persist_insights_agent)                 │
        │              (1-2s)                              │
        │                                                  │
        │  Outputs:                                        │
        │  - outputs/cost_center_067.json                  │
        │  - outputs/alerts_payload_cc067.json             │
        └──────────────────────────────────────────────────┘

        ┌────────────────────────────────────────┐
        │  REPEAT FOR NEXT COST CENTER           │
        └────────────────────────────────────────┘
```

---

## Hierarchical Drill-Down Detail

```
┌──────────────────────────────────────────────────────────────┐
│              DATA ANALYST AGENT LOOP                         │
└────────────────────────┬─────────────────────────────────────┘
                         │
                         ▼
        ┌────────────────────────────────────┐
        │  Initialize: Level = 2             │
        │  State: current_level = 2          │
        └────────────────┬───────────────────┘
                         │
                         ▼
        ┌────────────────────────────────────────────────────┐
        │               LOOP ITERATION                       │
        │                                                    │
        │  ┌──────────────────────────────────────────────┐ │
        │  │  Step 1: Level Analyzer Agent                │ │
        │  │  - Get validated_data from state             │ │
        │  │  - Aggregate by level_N                      │ │
        │  │  - Rank items by absolute $ variance         │ │
        │  │  - Identify top 3-5 (80% rule)               │ │
        │  │  - Store: level_N_drivers                    │ │
        │  └──────────────────────────────────────────────┘ │
        │                         │                          │
        │                         ▼                          │
        │  ┌──────────────────────────────────────────────┐ │
        │  │  Step 2: Parallel Analysis                   │ │
        │  │                                              │ │
        │  │  ┌───────────────┐  ┌───────────────┐      │ │
        │  │  │ Statistical   │  │   Seasonal    │      │ │
        │  │  │   Analysis    │  │   Baseline    │      │ │
        │  │  └───────────────┘  └───────────────┘      │ │
        │  │                                              │ │
        │  │  ┌───────────────┐  ┌───────────────┐      │ │
        │  │  │     Ratio     │  │    Anomaly    │      │ │
        │  │  │   Analysis    │  │   Detection   │      │ │
        │  │  └───────────────┘  └───────────────┘      │ │
        │  │                                              │ │
        │  │  ┌───────────────┐                          │ │
        │  │  │     Level     │                          │ │
        │  │  │   Analyzer    │                          │ │
        │  │  └───────────────┘                          │ │
        │  │                                              │ │
        │  │  Store results: level_N_analysis             │ │
        │  └──────────────────────────────────────────────┘ │
        │                         │                          │
        │                         ▼                          │
        │  ┌──────────────────────────────────────────────┐ │
        │  │  Step 3: Drill-Down Decision Agent (LLM)    │ │
        │  │                                              │ │
        │  │  Inputs:                                     │ │
        │  │  - level_N_analysis                          │ │
        │  │  - level_N_drivers                           │ │
        │  │  - materiality_thresholds                    │ │
        │  │                                              │ │
        │  │  LLM Analyzes:                               │ │
        │  │  - Variance materiality (±5% or ±$50K?)     │ │
        │  │  - Pattern type (operational vs timing?)     │ │
        │  │  - Anomaly severity (critical issues?)       │ │
        │  │  - Current level (4 = GL detail, stop)       │ │
        │  │                                              │ │
        │  │  Decision Output:                            │ │
        │  │  - action: "CONTINUE" or "STOP"              │ │
        │  │  - reasoning: "Material variance in Fuel..." │ │
        │  └──────────────────────────────────────────────┘ │
        │                         │                          │
        │                         ▼                          │
        │  ┌──────────────────────────────────────────────┐ │
        │  │  Step 4: Process Decision                    │ │
        │  │                                              │ │
        │  │  If CONTINUE and level < 4:                  │ │
        │  │    - current_level += 1                      │ │
        │  │    - continue_loop = true                    │ │
        │  │                                              │ │
        │  │  If STOP or level == 4:                      │ │
        │  │    - continue_loop = false                   │ │
        │  │    - escalate to finalize                    │ │
        │  └──────────────────────────────────────────────┘ │
        │                                                    │
        └────────────────────────┬───────────────────────────┘
                                 │
                 ┌───────────────┴────────────────┐
                 │   continue_loop == true?       │
                 └───────────┬────────────────────┘
                             │
                    ┌────────┴────────┐
                    │ YES             │ NO
                    ▼                 ▼
            ┌───────────────┐  ┌──────────────────┐
            │  LOOP AGAIN   │  │  FINALIZE        │
            │  (next level) │  │  - Aggregate all │
            └───────────────┘  │    level results │
                               │  - Return report │
                               └──────────────────┘
```

---

## Alert Scoring Workflow

```
┌──────────────────────────────────────────────────────────────┐
│              ALERT SCORING COORDINATOR                       │
└────────────────────────┬─────────────────────────────────────┘
                         │
                         ▼
        ┌────────────────────────────────────────────────┐
        │  Step 1: Extract Alerts                        │
        │  (extract_alerts_from_analysis tool)           │
        │                                                │
        │  Parse synthesis_result for:                   │
        │  - Material variances                          │
        │  - Anomalies detected                          │
        │  - Contract violations                         │
        │  - Operational issues                          │
        │                                                │
        │  Output: raw_alerts[]                          │
        └────────────────────┬───────────────────────────┘
                             │
                             ▼
        ┌────────────────────────────────────────────────┐
        │  Step 2: Enrich Alerts                         │
        │  (conditional data fetching)                   │
        │                                                │
        │  For each alert:                               │
        │  - get_order_details_for_period()              │
        │  - get_top_shippers_by_miles()                 │
        │  - get_monthly_aggregates_by_cost_center()     │
        │                                                │
        │  Add context: volumes, trends, contracts       │
        └────────────────────┬───────────────────────────┘
                             │
                             ▼
        ┌────────────────────────────────────────────────┐
        │  Step 3: Score Alerts                          │
        │  (score_alerts tool)                           │
        │                                                │
        │  For each alert, calculate:                    │
        │                                                │
        │  Financial Impact Score:                       │
        │    - abs(variance_dollar) / threshold          │
        │    - Weight: 40%                               │
        │                                                │
        │  Confidence Score:                             │
        │    - Pattern clarity                           │
        │    - Statistical significance (Z-score)        │
        │    - Data completeness                         │
        │    - Weight: 30%                               │
        │                                                │
        │  Persistence Score:                            │
        │    - One-time (0.3) vs Run-rate (1.0)          │
        │    - Trend direction (improving/worsening)     │
        │    - Weight: 30%                               │
        │                                                │
        │  Total Score = (Impact × 0.4) +                │
        │                (Confidence × 0.3) +            │
        │                (Persistence × 0.3)             │
        │                                                │
        │  Severity:                                     │
        │    - Info: Score < 0.5                         │
        │    - Warn: Score 0.5-0.75                      │
        │    - Critical: Score > 0.75                    │
        └────────────────────┬───────────────────────────┘
                             │
                             ▼
        ┌────────────────────────────────────────────────┐
        │  Step 4: Apply Suppression                     │
        │  (apply_suppression tool)                      │
        │                                                │
        │  Rules:                                        │
        │  - Deduplicate similar alerts                  │
        │  - Check suppression windows (14 days)         │
        │  - Filter low-value items (score < 0.3)        │
        │  - Rearm on escalation                         │
        │                                                │
        │  Reference: alert_policy.yaml                  │
        └────────────────────┬───────────────────────────┘
                             │
                             ▼
        ┌────────────────────────────────────────────────┐
        │  Step 5: Generate Recommendations              │
        │  (LLM-based)                                   │
        │                                                │
        │  For each alert:                               │
        │  - Identify root cause                         │
        │  - Suggest specific actions                    │
        │  - Assign ownership                            │
        │  - Set priority                                │
        │                                                │
        │  Example:                                      │
        │    "Review fuel contracts with top 5           │
        │     suppliers by volume. Expected recovery:    │
        │     $300K annually."                           │
        └────────────────────┬───────────────────────────┘
                             │
                             ▼
        ┌────────────────────────────────────────────────┐
        │  Step 6: Sort & Prioritize                     │
        │                                                │
        │  Sort alerts by:                               │
        │  1. Severity (Critical → Warn → Info)          │
        │  2. Total Score (descending)                   │
        │  3. Financial Impact (descending)              │
        │                                                │
        │  Output: alert_scoring_result                  │
        └────────────────────┬───────────────────────────┘
                             │
                             ▼
                  ┌──────────────────────┐
                  │  Return Prioritized  │
                  │  Alert List          │
                  └──────────────────────┘
```

---

## Data Validation & Enrichment Flow

```
┌──────────────────────────────────────────────────────────────┐
│           INGEST & VALIDATION AGENT                          │
└────────────────────────┬─────────────────────────────────────┘
                         │
                         ▼
        ┌────────────────────────────────────────────────┐
        │  Step 1: Reshape & Validate                    │
        │  (reshape_and_validate tool)                   │
        │                                                │
        │  Checks:                                       │
        │  - Data not empty                              │
        │  - Required columns present:                   │
        │    * period, gl_account, amount, cost_center   │
        │  - Date format valid (YYYY-MM)                 │
        │  - Numeric columns are numeric                 │
        │  - No all-null columns                         │
        │                                                │
        │  If fails:                                     │
        │    Return error JSON (DataUnavailable)         │
        │    Stop processing                             │
        │                                                │
        │  If succeeds:                                  │
        │    Store: financial_data_pl                    │
        └────────────────────┬───────────────────────────┘
                             │
                             ▼
        ┌────────────────────────────────────────────────┐
        │  Step 2: Join Ops Metrics                      │
        │  (join_ops_metrics tool)                       │
        │                                                │
        │  Join financial_data_pl with ops_metrics on:   │
        │    - cost_center                               │
        │    - period                                    │
        │                                                │
        │  Add columns:                                  │
        │  - miles_total, miles_loaded, miles_empty      │
        │  - orders_count, stops_count                   │
        │  - revenue_total, revenue_linehaul             │
        │  - driver_pay, fuel_consumed                   │
        │  - driving_minutes, on_duty_minutes            │
        │  - truck_count                                 │
        │                                                │
        │  Result: Enriched DataFrame with per-unit      │
        │          calculation capability                │
        └────────────────────┬───────────────────────────┘
                             │
                             ▼
        ┌────────────────────────────────────────────────┐
        │  Step 3: Join Chart Metadata                   │
        │  (join_chart_metadata tool)                    │
        │                                                │
        │  Load chart_of_accounts.yaml                   │
        │                                                │
        │  Join on: gl_account                           │
        │                                                │
        │  Add columns:                                  │
        │  - acct_nm (account name)                      │
        │  - level_1 (Total Operating Revenue/Expenses)  │
        │  - level_2 (Fuel, Labor, etc.)                 │
        │  - level_3 (Sub-categories)                    │
        │  - level_4 (GL detail)                         │
        │  - canonical_category (Fuel, Wages, etc.)      │
        │                                                │
        │  Result: Fully enriched DataFrame ready for    │
        │          hierarchical analysis                 │
        └────────────────────┬───────────────────────────┘
                             │
                             ▼
        ┌────────────────────────────────────────────────┐
        │  Step 4: Validate Enrichment                   │
        │                                                │
        │  Checks:                                       │
        │  - Level columns present                       │
        │  - No critical missing values                  │
        │  - Data ranges valid                           │
        │                                                │
        │  Store: validated_data                         │
        └────────────────────┬───────────────────────────┘
                             │
                             ▼
                  ┌──────────────────────┐
                  │  Return Success      │
                  │  validated_data      │
                  └──────────────────────┘
```

---

## Safe Parallel Execution Pattern

```
┌──────────────────────────────────────────────────────────────┐
│           SAFE PARALLEL WRAPPER                              │
│           (prevents cascading failures)                      │
└────────────────────────┬─────────────────────────────────────┘
                         │
                         ▼
        ┌────────────────────────────────────────────────┐
        │  Launch N Agents Concurrently                  │
        │                                                │
        │  For each agent:                               │
        │    - Wrap in try-catch                         │
        │    - Collect all events                        │
        │    - Log individual failures                   │
        │    - Continue with others                      │
        └────────────────────┬───────────────────────────┘
                             │
         ┌───────────────────┼───────────────────┐
         │                   │                   │
         ▼                   ▼                   ▼
┌────────────────┐  ┌────────────────┐  ┌────────────────┐
│   Agent 1      │  │   Agent 2      │  │   Agent 3      │
│                │  │                │  │                │
│  Try:          │  │  Try:          │  │  Try:          │
│    Run agent   │  │    Run agent   │  │    Run agent   │
│    Collect OK  │  │    ERROR!      │  │    Collect OK  │
│                │  │                │  │                │
│  Return:       │  │  Catch:        │  │  Return:       │
│    [events]    │  │    Log error   │  │    [events]    │
│                │  │    Return []   │  │                │
└────────┬───────┘  └────────┬───────┘  └────────┬───────┘
         │                   │                   │
         └───────────────────┼───────────────────┘
                             │
                             ▼
        ┌────────────────────────────────────────────────┐
        │  Aggregate Results                             │
        │                                                │
        │  - Agent 1: Success (15 events)                │
        │  - Agent 2: Failed (0 events)                  │
        │  - Agent 3: Success (12 events)                │
        │                                                │
        │  Total: 2/3 successful, 27 events              │
        │                                                │
        │  Continue with partial results                 │
        └────────────────────┬───────────────────────────┘
                             │
                             ▼
                  ┌──────────────────────┐
                  │  Yield All Events    │
                  │  (from successful    │
                  │   agents only)       │
                  └──────────────────────┘
```

---

## Cost Center Loop Pattern

```
User Query: "Analyze cost centers 067, 088, 095"
     ↓
Parse: ["067", "088", "095"]
     ↓
     ┌───────────────────────────────┐
     │  FOR EACH cost_center:        │
     └──────────┬────────────────────┘
                │
     ┌──────────▼──────────────────────────┐
     │  COST CENTER 067                    │
     │  ├─ Fetch data (067)                │
     │  ├─ Validate & enrich               │
     │  ├─ Hierarchical analysis           │
     │  ├─ Synthesis                       │
     │  ├─ Alert scoring                   │
     │  └─ Persist:                        │
     │      - cost_center_067.json         │
     │      - alerts_payload_cc067.json    │
     └──────────┬──────────────────────────┘
                │ (complete before next)
                │
     ┌──────────▼──────────────────────────┐
     │  COST CENTER 088                    │
     │  ├─ Fetch data (088)                │
     │  ├─ Validate & enrich               │
     │  ├─ Hierarchical analysis           │
     │  ├─ Synthesis                       │
     │  ├─ Alert scoring                   │
     │  └─ Persist:                        │
     │      - cost_center_088.json         │
     │      - alerts_payload_cc088.json    │
     └──────────┬──────────────────────────┘
                │ (complete before next)
                │
     ┌──────────▼──────────────────────────┐
     │  COST CENTER 095                    │
     │  ├─ Fetch data (095)                │
     │  ├─ Validate & enrich               │
     │  ├─ Hierarchical analysis           │
     │  ├─ Synthesis                       │
     │  ├─ Alert scoring                   │
     │  └─ Persist:                        │
     │      - cost_center_095.json         │
     │      - alerts_payload_cc095.json    │
     └─────────────────────────────────────┘
                │
                ▼
            ALL DONE
```

**Why Sequential?**
- Clean data isolation per cost center
- Predictable resource usage
- Easier debugging and error handling
- Clear progress tracking

---

**Document Version:** 1.0  
**Last Updated:** October 28, 2025

