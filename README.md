# P&L Analyst Agent

An intelligent financial analysis agent that provides automated cost center analysis, anomaly detection, and actionable insights for logistics operations.

## Overview

The P&L Analyst Agent is a sophisticated AI-powered system built on Google's Agent Development Kit (ADK) that analyzes Profit & Loss data, operational metrics, and order details to identify cost anomalies, contract violations, and business opportunities.

## 📊 Features

### Core Capabilities

- **💰 Dynamic Cost Center Analysis**: Automatically extracts and analyzes multiple cost centers from natural language requests
- **🔄 Multi-Source Data Integration**: Combines P&L data (6.3M+ transactions), operational metrics (37M+ records), and order-level details  
- **📊 3-Level Drill-Down Framework**: Executive summary → Category analysis → GL-level details with root cause classification
- **⚡ Intelligent Analysis Pipeline**: Category prioritization followed by targeted GL analysis for top variance drivers
- **📏 Materiality-Based Filtering**: Focuses on variances exceeding ±5% or ±$50K thresholds
- **🎯 Smart Alert Scoring**: Prioritizes findings by financial impact and urgency
- **✅ Contract Validation**: Identifies billing discrepancies and recovery opportunities
- **📈 Forecasting & Anomaly Detection**: Statistical models for trend analysis and outlier detection
- **🔢 Operational Volume Normalization**: Per-mile, per-load, per-stop metrics with rate vs volume decomposition
- **📝 Phase-Based Logging**: Comprehensive logging for each analysis phase with metrics, performance tracking, and JSON summaries

### Data Coverage

- **Time Range**: 24 months of P&L data, 3 months of order details
- **Data Sources**: 3 Tableau extracts via A2A agents (6.3M+ P&L transactions, 37M+ ops metrics)
- **Analysis Types**: Category aggregation, materiality filtering, statistical, seasonal, ratio, anomaly, forecasting, visualization
- **Output Formats**: JSON with 3-level structured output (executive summary, category drivers, GL drill-down)

## Architecture

```
Request → Cost Center Extraction → Loop (per cost center):
  ├─ Data Fetch (P&L, Ops Metrics, Order Details)
  ├─ Data Validation & Join (with ops metrics)
  ├─ Category Aggregation (group GLs by canonical_category)
  ├─ Category Analysis (identify top 3-5 variance drivers)
  ├─ GL Drill-Down (analyze top categories only)
  ├─ Parallel Analysis (6 agents on selected GLs with per-unit metrics)
  ├─ Enhanced Synthesis (3-level framework output)
  ├─ Alert Scoring (prioritize by financial impact)
  └─ Persist Results (JSON output)
```

### 3-Level Drill-Down Framework

**Level 1 - Executive Summary** (5 bullets):
- High-level variance overview (YoY, MoM, 3MMA, 6MMA)
- Top 2-4 category drivers explaining 80%+ of variance
- Seasonal/timing factors
- Key insights and next steps

**Level 2 - Category Analysis**:
- Ranked list of categories by absolute dollar variance
- Materiality filtering (±5% or ±$50K thresholds)
- Focus on top categories driving majority of change

**Level 3 - GL Drill-Down**:
- Detailed analysis of individual GLs within top categories
- Root cause classification (Accruals, Timing, Allocations, Miscoding, Operational)
- One-time vs run-rate detection
- Per-unit metrics (per mile, per load, per stop)
- Variance decomposition (rate effect vs volume effect)

### Detailed Workflow

```
┌─────────────────────────────────────────────────────────────────┐
│                   User Query: "Analyze CC 067"                   │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 1: Data Ingestion & Validation                           │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ • Extract cost center (067) from natural language          │ │
│  │ • Fetch P&L data from Tableau A2A agent                    │ │
│  │ • Fetch Ops Metrics from Tableau A2A agent                 │ │
│  │ • Validate data completeness & quality                     │ │
│  │ • Join P&L amounts with operational volumes                │ │
│  │   (miles, loads, stops by GL and period)                   │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                   │
│  Agent: Ingest & Validation Agent                                │
│  Output: Validated DataFrame with P&L + Ops Metrics              │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 2: Category Aggregation & Prioritization                 │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ • Group GLs by canonical_category                          │ │
│  │ • Calculate YoY, MoM variances by category                 │ │
│  │ • Apply materiality thresholds (±5% or ±$50K)              │ │
│  │ • Rank categories by absolute dollar variance              │ │
│  │ • Identify top 3-5 categories explaining 80%+ variance     │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                   │
│  Agent: Category Analyzer Agent                                  │
│  Output: Ranked list of top variance drivers                     │
│          ["Fuel", "Labor", "Maintenance"]                        │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 3: GL Drill-Down (Top Categories Only)                   │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ For each top category:                                     │ │
│  │ • Extract individual GLs within category                   │ │
│  │ • Classify root cause:                                     │ │
│  │   - Accruals (monthly variance, YoY stable)                │ │
│  │   - Timing (month shifts, YoY stable)                      │ │
│  │   - Allocations (cross-account, YoY varies)                │ │
│  │   - Miscoding (irregular patterns)                         │ │
│  │   - Operational (volume/rate driven)                       │ │
│  │ • Detect one-time spikes vs run-rate changes               │ │
│  │ • Flag GLs for detailed analysis                           │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                   │
│  Agent: GL Drill-Down Agent                                      │
│  Output: GL-level insights with root cause classification        │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 4: Parallel Analysis (Selected GLs)                      │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ Run 6 agents concurrently on selected GLs:                │ │
│  │                                                            │ │
│  │ [Statistical]  [Seasonal]  [Ratio]                        │ │
│  │    ↓              ↓          ↓                            │ │
│  │ • YoY, MoM     • YoY comp   • Per-mile                    │ │
│  │ • 3MMA, 6MMA   • Seasonal   • Per-load                    │ │
│  │ • Descriptive  • Patterns   • Per-stop                    │ │
│  │                             • Rate vs Vol                 │ │
│  │                                                            │ │
│  │ [Anomaly]    [Forecast]   [Visualization]                 │ │
│  │    ↓            ↓             ↓                           │ │
│  │ • Changepoint  • ARIMA      • Line charts                 │ │
│  │ • Drift        • Baseline   • Trend viz                   │ │
│  │ • Timing       • Future     • Executive                   │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                   │
│  Agents: Statistical, Seasonal, Ratio, Anomaly,                  │
│          Forecasting, Visualization                              │
│  Output: 6 comprehensive analysis reports                        │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 5: Synthesis & Structuring                               │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ Generate 3-Level Output:                                   │ │
│  │                                                            │ │
│  │ Level 1 - Executive Summary (5 bullets)                   │ │
│  │ • Overall variance: -$425K YoY (-12%)                      │ │
│  │ • Top drivers: Fuel -$300K, Labor +$150K, Maint -$200K    │ │
│  │ • Seasonal: Fuel costs up due to winter rates             │ │
│  │ • Operational: Volume down 8%, per-mile costs stable      │ │
│  │ • Next steps: Investigate fuel contracts, labor overtime  │ │
│  │                                                            │ │
│  │ Level 2 - Category Analysis (Ranked by $ Variance)        │ │
│  │ • Fuel: -$300K (-15%) - Material variance                 │ │
│  │ • Maintenance: -$200K (-22%) - Material variance           │ │
│  │ • Labor: +$150K (+8%) - Material variance                 │ │
│  │ • Supplies: -$75K (-18%) - Material variance              │ │
│  │ • (Other categories below threshold)                      │ │
│  │                                                            │ │
│  │ Level 3 - GL Drill-Down (Top Categories)                  │ │
│  │ Fuel Category:                                            │ │
│  │ • GL 6020 Diesel Fuel: -$280K                             │ │
│  │   Root Cause: Operational (rate effect: -$200K,           │ │
│  │                volume effect: -$80K)                      │ │
│  │   Pattern: Run-rate change (not one-time)                 │ │
│  │   Per-Mile: $0.85/mi (vs $0.92/mi LY)                    │ │
│  │                                                            │ │
│  │ • GL 6025 Fuel Surcharge Recovery: -$20K                  │ │
│  │   Root Cause: Timing (recovery lag in Sep)                │ │
│  │   Pattern: One-time variance                              │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                   │
│  Agent: Synthesis Agent                                          │
│  Output: Structured 3-level JSON report                          │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 6: Alert Scoring & Persistence                           │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ • Extract actionable alerts from analysis                  │ │
│  │ • Score by financial impact ($$$) + urgency                │ │
│  │ • Apply suppression (dedupe, low-value filter)             │ │
│  │ • Generate recommended actions                             │ │
│  │ • Save to outputs/cost_center_067.json                     │ │
│  │ • Save alerts to outputs/alerts_payload_cc067.json         │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                   │
│  Agents: Alert Scoring Coordinator, Persist Insights            │
│  Output: JSON files in outputs/ directory                        │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
                        ┌───────────────┐
                        │  USER REVIEW  │
                        └───────────────┘
```

### Agent Interaction Map

```
┌──────────────────────────────────────────────────────────────────┐
│                      ROOT ORCHESTRATION AGENT                     │
│                      (pl_analyst_agent/agent.py)                  │
└────────────────┬────────────────────────────────┬─────────────────┘
                 │                                │
                 ▼                                ▼
    ┌────────────────────────┐      ┌────────────────────────┐
    │  Cost Center Extractor │      │   Date Range Calculator │
    │  (LLM-based parsing)   │      │   (Tool-based logic)    │
    └────────────┬───────────┘      └────────────┬───────────┘
                 │                                │
                 └──────────────┬─────────────────┘
                                ▼
                ┌───────────────────────────────┐
                │  Data Ingestion Orchestrator   │
                └───────────┬───────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│ Tableau P&L  │   │ Tableau Ops  │   │  Database    │
│  A2A Agent   │   │  A2A Agent   │   │   (Orders)   │
└──────┬───────┘   └──────┬───────┘   └──────┬───────┘
       │                  │                  │
       └──────────────────┼──────────────────┘
                          ▼
              ┌─────────────────────────┐
              │ Ingest & Validation Agent│
              │ • Validate completeness  │
              │ • Join P&L + Ops Metrics │
              │ • Quality checks         │
              └───────────┬──────────────┘
                          │
                          ▼
              ┌─────────────────────────┐
              │  Category Analyzer Agent │
              │ • Aggregate to category  │
              │ • Rank by $ variance     │
              │ • Identify top 3-5       │
              │ • Apply materiality      │
              └───────────┬──────────────┘
                          │
                          ▼
              ┌─────────────────────────┐
              │   GL Drill-Down Agent    │
              │ • Get GLs in top cats   │
              │ • Classify root causes  │
              │ • One-time vs run-rate  │
              └───────────┬──────────────┘
                          │
                          ▼
          ┌───────────────────────────────────┐
          │  Parallel Analysis Coordinator     │
          └───────┬───────────────────────────┘
                  │
     ┌────────────┼────────────┬─────────┬──────────┬───────────┐
     ▼            ▼            ▼         ▼          ▼           ▼
┌─────────┐ ┌─────────┐ ┌─────────┐ ┌────────┐ ┌─────────┐ ┌──────┐
│Statistical│ │Seasonal │ │  Ratio  │ │Anomaly │ │Forecast │ │ Viz  │
│ Analysis │ │Baseline │ │Analysis │ │Detection│ │        │ │      │
└────┬────┘ └────┬────┘ └────┬────┘ └───┬────┘ └────┬────┘ └──┬───┘
     │           │           │          │           │          │
     └───────────┴───────────┴──────────┴───────────┴──────────┘
                              │
                              ▼
                   ┌──────────────────────┐
                   │   Synthesis Agent     │
                   │ • Generate Level 1-3  │
                   │ • Executive summary   │
                   │ • Category analysis   │
                   │ • GL drill-down       │
                   └──────────┬────────────┘
                              │
                              ▼
                   ┌──────────────────────┐
                   │ Alert Scoring         │
                   │ Coordinator Agent     │
                   │ • Extract alerts      │
                   │ • Score by impact     │
                   │ • Apply suppression   │
                   └──────────┬────────────┘
                              │
                              ▼
                   ┌──────────────────────┐
                   │  Persist Insights     │
                   │  Agent                │
                   │ • Save JSON output    │
                   │ • Save alerts         │
                   └───────────────────────┘
```

### Analysis Agents

The system employs 8 specialized analysis agents organized in a sequential workflow:

**Phase 1: Data Preparation**
1. **Ingest & Validation Agent**: Validates data completeness, joins P&L with operational metrics

**Phase 2: Category Prioritization**
2. **Category Analyzer Agent**: Aggregates GLs by canonical_category, ranks by absolute dollar variance, identifies top 3-5 drivers explaining 80%+ of total variance

**Phase 3: GL Deep Dive**
3. **GL Drill-Down Agent**: Analyzes individual GLs within top categories, classifies root causes, detects one-time vs run-rate patterns

**Phase 4: Parallel Analysis (Top Categories Only)**
4. **Statistical Analysis Agent**: Descriptive stats, variances (YoY, MoM, 3MMA, 6MMA), period comparisons, materiality thresholds (±5% or ±$50K)
5. **Seasonal Baseline Agent**: YoY comparisons and seasonal patterns
6. **Ratio Analysis Agent**: Per-unit metrics (per mile, per load, per stop) with rate vs volume decomposition
7. **Anomaly Detection Agent**: Change points, drift detection, timing swings
8. **Forecasting Agent**: Baseline and future forecasts using ARIMA
9. **Visualization Agent**: Executive-ready charts and graphs

**Phase 5: Synthesis & Scoring**
10. **Synthesis Agent**: Generates 3-level output (executive summary, category analysis, GL drill-down)
11. **Alert Scoring Coordinator**: Prioritizes findings by financial impact
12. **Persist Insights Agent**: Saves JSON output to outputs/ directory

## Prerequisites

- Python 3.10 or higher
- Google Cloud account with Vertex AI API enabled
- gcloud CLI installed and authenticated
- SQL Server access for Tableau data sources
- ODBC Driver 17 for SQL Server

## Quick Start

### 1. Installation

```bash
# Navigate to project directory
cd pl_analyst

# Create virtual environment
python -m venv .venv
.venv\Scripts\activate  # Windows
source .venv/bin/activate  # Linux/Mac

# Install dependencies
pip install -r requirements.txt
```

### 2. Configuration

```bash
# Copy environment template
cp .env.template .env

# Edit .env with your settings
# Required: GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_STORAGE_BUCKET
# Optional: ROOT_AGENT_MODEL, A2A_BASE_URL
```

Create `service-account.json` in the project root:

```json
{
  "type": "service_account",
  "project_id": "your-project-id",
  "private_key_id": "...",
  "private_key": "...",
  "client_email": "...",
  "client_id": "...",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token"
}
```

Create `database_config.yaml`:

```yaml
driver: "{ODBC Driver 17 for SQL Server}"
server: "your-server.database.windows.net"
database: "your-database"
username: "your-username"
password: "your-password"
```

### 3. Validate Data Sources

```bash
# Test database connectivity
python data/test_database_connection.py

# Start A2A server (in separate terminal)
python scripts/start_a2a_server.py

# Test A2A agents
python data/test_tableau_connection.py

# Validate all data sources end-to-end
python data/validate_data_sources.py
```

### 4. Deploy to Google Cloud

```bash
# Deploy the agent to Vertex AI
python deployment/deploy_with_tracing.py --create \
  --project_id=your-project-id \
  --location=us-central1 \
  --bucket=your-storage-bucket
```

### 5. Test the Agent

```python
from pl_analyst_agent.agent import root_agent
from google.adk.sessions import InMemorySessionStore

# Create session
session_store = InMemorySessionStore()
session = session_store.create_session(app_name="pl_analyst")

# Run analysis
user_query = "Analyze cost center 067 for contract violations"
result = await root_agent.run_async(session, user_query)

# Results saved to outputs/cost_center_067.json
```

## Project Structure

```
pl_analyst/
├── pl_analyst_agent/           # Main agent package
│   ├── agent.py               # Root agent orchestration
│   ├── config.py              # Configuration management
│   ├── prompt.py              # System prompts
│   ├── auth_config.py         # Authentication setup
│   │
│   ├── sub_agents/            # Analysis agents
│   │   ├── orchestration/     # Workflow control
│   │   ├── ingest_validator_agent/
│   │   ├── data_analysis/     # 8 analysis agents
│   │   │   ├── category_analyzer_agent/
│   │   │   ├── gl_drilldown_agent/
│   │   │   ├── statistical_analysis_agent/
│   │   │   ├── seasonal_baseline_agent/
│   │   │   ├── ratio_analysis_agent/
│   │   │   ├── anomaly_detection_agent/
│   │   │   ├── forecasting_agent/
│   │   │   └── visualization_agent/
│   │   ├── synthesis_agent/
│   │   ├── alert_scoring_coordinator_agent/
│   │   └── persist_insights_agent/
│   │
│   ├── tools/                 # Utility functions
│   └── utils/                 # Helper utilities
│
├── config/                     # Configuration files
│   ├── agent_models.yaml      # Model configurations
│   ├── alert_policy.yaml      # Alert scoring rules
│   ├── tier_thresholds.yaml   # Financial thresholds
│   ├── materiality_config.yaml # Materiality thresholds and top-N settings
│   └── .env.example           # Environment template
│
├── deployment/                 # Deployment scripts
│   └── deploy_with_tracing.py # Vertex AI deployment
│
├── data/                       # Data validation scripts
│   ├── README.md              # Data source documentation
│   ├── test_tableau_connection.py
│   ├── test_database_connection.py
│   └── validate_data_sources.py
│
├── ../remote_a2a/              # Remote A2A agents (at development root)
│   ├── tableau_account_research_ds_agent/
│   ├── tableau_ops_metrics_ds_agent/
│   └── tableau_order_dispatch_revenue_ds_agent/
│
├── scripts/                    # Helper scripts
│   ├── start_a2a_server.py   # Launch A2A server
│   └── [test scripts...]
│
├── pyproject.toml             # Poetry configuration
├── requirements.txt           # pip dependencies
├── .env.template              # Environment template
├── .gitignore                 # Git ignore rules
└── README.md                  # This file
```

## 🛠️ Available Tools

The agent includes comprehensive analysis tools organized by function:

### Data Fetching Tools
- `calculate_date_ranges` - Compute analysis periods dynamically
- `parse_cost_centers` - Extract cost centers from requests
- `create_data_request_message` - Format data queries
- `aggregate_by_category` - Group GLs into categories using canonical_category metadata
- `join_ops_metrics` - Merge P&L amounts with operational volumes (miles, loads, stops)

### Analysis Tools (8 Agents)
1. **Category Analyzer** - Prioritize variance drivers by category
   - `rank_categories_by_variance` - Sort by absolute dollar variance
   - `identify_top_drivers` - Find top N categories explaining 80%+ of change
2. **GL Drill-Down** - Deep-dive into top categories
   - `get_gls_in_category` - Filter GLs by category
   - `classify_root_cause` - Categorize as Accruals, Timing, Allocations, Miscoding, or Operational
   - `detect_one_time_vs_runrate` - Distinguish spikes from patterns
3. **Statistical Analysis** - Descriptive stats and materiality filtering
   - `calculate_variances` - YoY, MoM, 3MMA, 6MMA with materiality thresholds (±5% or ±$50K)
   - `apply_materiality_thresholds` - Flag material variances
4. **Seasonal Baseline** - YoY comparisons and seasonal patterns
5. **Ratio Analysis** - Operational volume normalization
   - `analyze_ratios` - Per-mile, per-load, per-stop metrics
   - Variance decomposition: ΔCost = (ΔRate × Volume) + (Rate × ΔVolume)
6. **Anomaly Detection** - Change points, drift detection, timing swings
7. **Forecasting** - Baseline and future forecasts using ARIMA
8. **Visualization** - Executive-ready line charts

### Alert & Scoring Tools
- `extract_alerts_from_analysis` - Parse analysis for actionable alerts
- `score_alerts` - Prioritize by financial impact
- `apply_suppression` - Filter duplicate/low-value alerts
- `capture_feedback` - Store user feedback for learning

### Synthesis Tools
- `generate_executive_summary` - Create 5-bullet Level 1 executive summary with top category drivers and key insights

## Key Entry Points

- **pl_analyst_agent/agent.py**: Main application agent and workflow orchestration
- **scripts/start_a2a_server.py**: Launch all A2A data agents  
- **deployment/deploy_with_tracing.py**: Deploy to Vertex AI
- **data/validate_data_sources.py**: Validate all data connections

## Testing

### Data Source Tests

```bash
# Test database connectivity
python data/test_database_connection.py

# Test A2A agent connectivity
python data/test_tableau_connection.py

# Validate all data sources end-to-end
python data/validate_data_sources.py
```

### Integration Tests

```bash
# Full agent tests
python scripts/tests/test_pl_analyst_direct.py
python scripts/tests/test_pl_analyst_validation.py

# Component tests
python scripts/tests/test_alert_scoring.py
python scripts/tests/test_tableau_agents.py
```

## Configuration

### Environment Variables

Create `.env` file (copy from `.env.template`):

```bash
# Google Cloud Configuration
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_CLOUD_LOCATION=us-central1
GOOGLE_CLOUD_STORAGE_BUCKET=your-bucket-name

# Model Configuration
ROOT_AGENT_MODEL=gemini-2.5-pro
MODEL_TEMPERATURE=0.0

# A2A Server Configuration
A2A_BASE_URL=http://localhost:8001

# Rate Limiting (for parallel execution)
GOOGLE_GENAI_RPM_LIMIT=5
GOOGLE_GENAI_RETRY_DELAY=3
```

### Model Configuration

Edit `config/agent_models.yaml` to customize models for each agent:

```yaml
default_model: "gemini-2.5-pro"
agents:
  cost_center_extractor: "gemini-2.0-flash-exp"
  request_analyzer: "gemini-2.5-pro"
  synthesis_agent: "gemini-2.5-pro"
```

## Output Files

Analysis results are saved to `outputs/`:

```
outputs/
├── cost_center_067.json          # Full analysis results
├── alerts_payload_cc067.json     # Scored alerts with actions
└── [other cost centers...]
```

Each file contains:
- Executive summary (Level 1: 5-bullet overview with top category drivers)
- Category analysis (Level 2: Ranked categories with materiality filtering)
- GL drill-down (Level 3: Root cause analysis for top categories)
- Statistical analysis with 3MMA and 6MMA variances
- Per-unit metrics (per mile, per load, per stop)
- Anomaly detection results
- Forecasts and trends
- Prioritized alerts with recommended actions

## Development

### Adding a New Sub-Agent

1. Create directory: `sub_agents/my_agent/`
2. Add files: `agent.py`, `prompt.py`, `tools/`, `__init__.py`
3. Import in main `agent.py`
4. Add to appropriate workflow pipeline

### Adding a New Tool

1. Create: `tools/my_tool.py`
2. Export in `tools/__init__.py`
3. Import where needed

### Adding a New Script

1. Categorize: test, utility, data_processing, or deployment
2. Create in appropriate `scripts/` subdirectory
3. Document usage in script header

## Troubleshooting

### A2A Server Connection Issues

Verify agents are running:

```python
from pl_analyst.agent import verify_tableau_agents
status = verify_tableau_agents()
print(status)
```

### Authentication Errors

Check service account file exists and environment is set:

```python
from pl_analyst.config import config
config.validate()
```

### Import Errors

Verify project structure:

```bash
python verify_structure.py
```

## Documentation

- **[QUICKSTART.md](docs/QUICKSTART.md)**: Fast setup and first analysis
- **[ARCHITECTURE.md](docs/ARCHITECTURE.md)**: Detailed system design
- **[DEPLOYMENT.md](docs/DEPLOYMENT.md)**: Production deployment guide
- **[TESTING.md](docs/TESTING.md)**: Testing strategy and guidelines

## Performance

- **Data Fetch**: ~15-20s per cost center (3 data sources with rate limiting)
- **Category Analysis**: ~5-10s (aggregate and rank categories)
- **GL Drill-Down**: ~10-15s (analyze top 3-5 categories)
- **Parallel Analysis**: ~30-45s (6 agents on selected GLs with per-unit metrics)
- **Synthesis & Scoring**: ~5-10s (3-level output generation and alert scoring)
- **Total**: ~65-100s per cost center
- **Processing**: Sequential by cost center for clean data isolation
- **Efficiency**: Focused analysis on top variance drivers (not all GLs) reduces compute time by ~40%

## Security Notes

⚠️ **Never commit these files:**
- `service-account.json`
- `database_config.yaml`
- `.env`
- Files in `outputs/` or `logs/`

See `.gitignore` for complete list.

## License

Copyright 2025 Google LLC

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

## Support

For issues, questions, or contributions:
- Review documentation in `docs/`
- Check `.cursorrules` for project guidelines
- See `REFACTORING_SUMMARY.md` for recent changes

