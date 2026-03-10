# Data Analyst Agent

An intelligent, contract-driven time-series analysis system built on Google's **Agent Development Kit (ADK)**. Upload any CSV dataset, auto-detect its structure, configure the analysis focus, and get executive-quality insights — anomaly detection, trend analysis, variance drill-downs, and actionable recommendations.

## Overview

The Data Analyst Agent automates complex time-series analysis across any domain: financial P&L, COVID epidemiology, climate data, population demographics, trade flows, and more. It uses a recursive drill-down framework to navigate hierarchies, identify variance drivers, and produce human-centric executive briefs.

## Key Features

- **Contract-Driven Analysis** — Zero-code dataset onboarding via YAML contracts defining metrics, hierarchies, and business rules
- **Auto-Detect Contract Builder** — Upload a CSV and auto-detect time columns, metrics, dimensions, and hierarchies with human-in-the-loop confirmation
- **Analysis Focus Modes** — Choose from weekly/monthly trends, anomaly detection, revenue gap analysis, seasonal patterns, YoY comparison, forecasting, or outlier investigation
- **Custom Analysis Direction** — Free-text instructions to guide the AI (e.g., "Find billing anomalies where volume stayed flat but revenue dropped")
- **Multi-Dataset Support** — 13 pre-configured datasets including 4 public datasets ready to analyze
- **Web UI** — Browser-based interface for dataset selection, run management, live monitoring, and results viewing
- **Executive Briefing** — Auto-generated briefs with actionable insights (Markdown, PDF)
- **Recursive Drill-Down** — Level-agnostic hierarchy analysis (Region → State → County, Country → Category → Sub-category, etc.)
- **Parallel Analysis** — Statistical, seasonal, anomaly, and cross-dimension analysis agents run in parallel

## Quick Start

### 1. Installation

```bash
git clone https://github.com/ty-hayes-82/data-analyst-agent.git
cd data-analyst-agent

python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

pip install -r requirements.txt
```

### 2. Configuration

Create a `.env` file:

```bash
GOOGLE_API_KEY=your_google_api_key_here
```

### 3. Start the Web UI

```bash
uvicorn web.app:app --host 0.0.0.0 --port 8080
```

Open `http://localhost:8080` in your browser.

### 4. Run Your First Analysis

1. Go to the **New Analysis** tab
2. Select a dataset (e.g., "COVID-19 US County-Level Cases & Deaths")
3. Choose your metrics and hierarchy
4. Select an **Analysis Focus** (e.g., Anomaly Detection)
5. Click **Run Analysis**
6. Watch progress in the **Monitor** tab
7. View results in the **Results** tab — the executive brief loads automatically

## Included Public Datasets

These datasets are ready to analyze out of the box:

| Dataset | Rows | Metrics | Hierarchies | Source |
|---------|------|---------|-------------|--------|
| **COVID-19 US Counties** | 100K | cases, deaths | State → County | NY Times |
| **Global CO2 Emissions** | 50K | co2, coal, oil, gas, per_capita, population, gdp | Country | Our World in Data |
| **World Bank Population** | 17K | population | Country | World Bank |
| **Global Temperature** | 3.8K | temperature_anomaly | Source (GCAG/GISTEMP) | Berkeley Earth |
| **Synthetic Trade Data** | 258K | trade_value_usd, volume_units | Region → State → Port, HS2 → HS4 | Generated (with 6 embedded anomaly scenarios) |

## Adding Your Own Dataset

### Option A: Web UI (Recommended)

1. Click the **+ Add Dataset** tab
2. Drag and drop your CSV file
3. Review the auto-detected contract: time column, metrics, dimensions, hierarchies
4. Adjust confidence scores, toggle fields on/off, change types
5. Click **Confirm & Save** — your dataset is immediately available for analysis

### Option B: Manual Contract

Create `config/datasets/csv/<your_dataset>/contract.yaml`:

```yaml
name: "My Dataset"
version: "1.0.0"
display_name: "My Custom Analysis"
description: "Description of your dataset"

data_source:
  type: "csv"
  file: "path/to/your/data.csv"

time:
  column: "date"          # Your date/time column name
  frequency: "monthly"    # daily, weekly, monthly, quarterly, yearly
  format: "%Y-%m-%d"      # strftime format
  range_months: 24        # How many months of history

metrics:
  - name: "revenue"
    column: "revenue"     # Actual CSV column name
    type: "additive"      # additive, ratio, or non_additive
    format: "currency"    # currency, integer, float, percentage
    description: "Monthly revenue in USD"

dimensions:
  - name: "region"
    column: "region"
    role: "primary"       # primary, secondary, or time
    description: "Geographic region"

hierarchies:
  - name: "geographic"
    description: "Region → State drill-down"
    children: ["region", "state"]
    level_names:
      0: "Total"
      1: "Region"
      2: "State"

materiality:
  variance_pct: 8.0       # Minimum % change to flag
  variance_absolute: 1000  # Minimum absolute change to flag
```

Also create `config/datasets/csv/<your_dataset>/loader.yaml`:

```yaml
type: csv
file: "path/to/your/data.csv"
encoding: utf-8
date_columns: ["date"]
numeric_columns: ["revenue"]
```

## Analysis Focus Modes

When starting a run, select one or more focus modes to guide the analysis:

| Focus Mode | What It Does |
|-----------|-------------|
| **Recent Weekly Trends** | Focuses on last 4-8 weeks, week-over-week changes |
| **Recent Monthly Trends** | Focuses on last 3-6 months, month-over-month changes |
| **Anomaly Detection** | Scans for statistical outliers, unusual spikes/drops |
| **Revenue Gap Analysis** | Finds potential missed billing, volume-without-revenue gaps |
| **Seasonal Patterns** | Identifies recurring cycles, holiday effects |
| **Year-over-Year Comparison** | Compares current vs same period last year |
| **Trend Forecasting** | Projects trends forward, identifies inflection points |
| **Outlier Investigation** | Deep-dives into top outliers, traces root causes |

You can also type a **custom analysis direction** for specific questions.

## CLI Usage

Run analysis directly from the command line:

```bash
# Analyze all metrics for the trade dataset
python -m data_analyst_agent.agent "Analyze trade_value_usd and volume_units"

# With environment overrides
export ACTIVE_DATASET=trade_data
export DATA_ANALYST_METRICS=trade_value_usd,volume_units
export DATA_ANALYST_HIERARCHY=geographic
export DATA_ANALYST_MAX_DRILL_DEPTH=3
export DATA_ANALYST_FOCUS=anomaly_detection,yoy_comparison
export DATA_ANALYST_CUSTOM_FOCUS="Find the top 3 drivers of the Q4 trade decline"
python -m data_analyst_agent.agent "Analyze trade metrics"
```

## Output Files

Each run generates a unique directory under `outputs/` containing:

| File | Description |
|------|-------------|
| `brief.md` | Executive summary with actionable insights |
| `brief.pdf` | PDF version for leadership |
| `metric_{name}.json` | Structured statistical results per metric |
| `metric_{name}.md` | Individual narrative report per metric |
| `alerts/alerts_payload_{name}.json` | Alert payloads for detected anomalies |
| `logs/execution.log` | Full trace of agent decisions |
| `run_metadata.json` | Run configuration and timing |

## Project Structure

```
data-analyst-agent/
├── config/datasets/csv/       # Dataset contracts and loaders
├── data/public/               # Public CSV datasets (included)
├── data/synthetic/            # Generated test data with ground truth
├── data_analyst_agent/        # Core pipeline
│   ├── agent.py               # Root pipeline orchestrator
│   ├── core_agents/           # CLI injector, data fetchers, loaders
│   └── sub_agents/            # Specialized analysis agents
│       ├── executive_brief_agent/
│       ├── hierarchical_analysis_agent/
│       ├── narrative_agent/
│       ├── statistical_insights_agent/
│       ├── alert_scoring_agent/
│       ├── report_synthesis_agent/
│       └── planner_agent/
├── web/                       # FastAPI web UI
│   ├── app.py                 # API endpoints
│   ├── contract_detector.py   # Auto-detect CSV structure
│   ├── contract_loader.py     # Load dataset contracts
│   ├── run_manager.py         # Pipeline run management
│   └── static/                # Frontend (HTML/CSS/JS)
├── tests/                     # Unit, integration, and E2E tests
├── outputs/                   # Analysis results (per-run directories)
└── requirements.txt
```

## Running Tests

```bash
python -m pytest --tb=short -q           # Full suite
python -m pytest tests/unit/ -q          # Unit tests only
python -m pytest tests/e2e/ -q           # End-to-end tests
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/datasets` | List all available datasets |
| `GET` | `/api/datasets/{id}/contract` | Get dataset contract details |
| `POST` | `/api/datasets/detect` | Upload CSV and auto-detect structure |
| `POST` | `/api/datasets/confirm` | Save confirmed contract |
| `POST` | `/api/runs` | Start a new analysis run |
| `GET` | `/api/runs` | List all runs |
| `GET` | `/api/runs/{id}` | Get run status |
| `GET` | `/api/runs/{id}/log` | Get live run log |
| `GET` | `/api/runs/{id}/outputs` | List output files |
| `GET` | `/api/runs/{id}/files/{name}` | Get specific output file |

## License

Apache License 2.0
