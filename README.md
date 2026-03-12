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

## CLI Usage

Run analysis directly from the command line for automation and scripting.

### Basic Command

```bash
python -m data_analyst_agent --dataset <dataset_name> --metrics "metric1,metric2"
```

### Available Options

```
--dataset NAME              Dataset folder name (e.g., us_airfare, covid_us_counties)
--metrics M1,M2             Comma-separated metric names (required)
--dimension DIM             Primary dimension (e.g., region, state)
--dimension-value VAL       Filter by dimension value (e.g., Central, California)
--start-date YYYY-MM-DD     Override analysis start date
--end-date YYYY-MM-DD       Override analysis end date
--interactive               Interactive mode with guided menus
```

### Examples

**1. Basic Single-Metric Analysis**
```bash
python -m data_analyst_agent \
    --dataset covid_us_counties \
    --metrics cases
```

**2. Multi-Metric Analysis**
```bash
python -m data_analyst_agent \
    --dataset us_airfare \
    --metrics "avg_fare,passengers"
```

**3. With Analysis Focus (Anomaly Detection)**
```bash
DATA_ANALYST_FOCUS=anomaly_detection \
python -m data_analyst_agent \
    --dataset us_airfare \
    --metrics avg_fare
```

**4. Recent Monthly Trends**
```bash
DATA_ANALYST_FOCUS=recent_monthly_trends \
python -m data_analyst_agent \
    --dataset covid_us_counties \
    --metrics "cases,deaths"
```

**5. Multi-Focus with Custom Instructions**
```bash
DATA_ANALYST_FOCUS=anomaly_detection,yoy_comparison \
DATA_ANALYST_CUSTOM_FOCUS="Focus on Q4 performance and identify seasonal holiday patterns" \
python -m data_analyst_agent \
    --dataset us_airfare \
    --metrics avg_fare
```

**6. Dimension Filter (Analyze Specific Region)**
```bash
python -m data_analyst_agent \
    --dataset trade_data \
    --metrics trade_value_usd \
    --dimension region \
    --dimension-value Midwest
```

**7. Interactive Mode (Guided Menus)**
```bash
python -m data_analyst_agent --interactive
```

### Analysis Focus Modes

Set via `DATA_ANALYST_FOCUS` environment variable (comma-separated):

- `recent_weekly_trends` - Focus on last 8 weeks
- `recent_monthly_trends` - Focus on last 6 months  
- `anomaly_detection` - Identify outliers and unusual patterns
- `revenue_gap_analysis` - Find volume vs. value mismatches
- `seasonal_patterns` - Detect cyclical behavior
- `yoy_comparison` - Year-over-year comparisons
- `forecasting` - Forward projections
- `outlier_investigation` - Deep-dive on extreme values

### Output Location

Results are saved to:
```
outputs/<dataset>/<dimension>/<value>/<timestamp>/
  ├── brief.md          # Executive summary (Markdown)
  ├── brief.pdf         # Executive summary (PDF)
  ├── brief.json        # Structured insights (JSON)
  ├── metric_*.json     # Detailed metric analysis
  └── run_metadata.json # Run configuration
```

## Web UI Usage

The web interface provides a complete visual workflow for dataset management and analysis.

### Starting the Web Server

**Development Mode (with auto-reload):**
```bash
cd /data/data-analyst-agent
uvicorn web.app:app --reload --host 0.0.0.0 --port 8080
```

**Production Mode:**
```bash
uvicorn web.app:app --host 0.0.0.0 --port 8080 --workers 4
```

**Background Mode (Linux/Mac):**
```bash
nohup uvicorn web.app:app --host 0.0.0.0 --port 8080 > web.log 2>&1 &
```

### Web UI Tabs

**1. New Analysis**
- Select dataset from dropdown
- Choose metrics (single or multiple)
- Select analysis focus mode (or multiple)
- Add custom analysis instructions (optional)
- Configure hierarchy and drill depth
- Click "Run Analysis" to start

**2. Monitor**
- View all active and recent runs
- See real-time progress logs (updates every 2 seconds)
- Check run status (Running, Completed, Failed)
- Track execution time
- Cancel running analyses

**3. Results**
- Browse all completed analyses
- Filter by dataset, date, status
- Preview executive briefs in-browser (Markdown rendering)
- Download outputs:
  - `brief.md` - Markdown summary
  - `brief.pdf` - PDF for leadership
  - `brief.json` - Structured JSON
  - `metric_*.json` - Detailed analysis per metric
- View run metadata (configuration, timing, focus)

**4. Add Dataset**
- Upload CSV file (drag-and-drop)
- Auto-detect structure:
  - Time columns (date/week/month/quarter)
  - Numeric metrics
  - Categorical dimensions
  - Hierarchical relationships
- Review detected contract
- Adjust confidence thresholds
- Toggle fields on/off
- Save and use immediately

### API Integration

The web UI is built on a REST API that you can call directly:

**Start an Analysis:**
```bash
curl -X POST http://localhost:8080/api/runs \
  -H "Content-Type: application/json" \
  -d '{
    "dataset_id": "us_airfare",
    "metrics": ["avg_fare"],
    "focus": ["anomaly_detection"],
    "custom_focus": "Focus on Q4 routes"
  }'
```

**Check Run Status:**
```bash
curl http://localhost:8080/api/runs/{run_id}
```

**Get Live Logs:**
```bash
curl http://localhost:8080/api/runs/{run_id}/log
```

**Download Brief:**
```bash
curl http://localhost:8080/api/runs/{run_id}/files/brief.md > brief.md
```

**Health Check:**
```bash
curl http://localhost:8080/health
# Returns: {"status": "healthy", "service": "data-analyst-agent-web", "version": "1.0.0"}
```

### Configuration

Environment variables for the web server (add to `.env`):

```bash
# Server
WEB_SERVER_PORT=8080           # Default port

# CORS (for browser-based frontends)
CORS_ALLOWED_ORIGINS=http://localhost:3000,https://yourdomain.com

# Performance
EXECUTIVE_BRIEF_MAX_SCOPED_BRIEFS=3    # Limit entity-level briefs
EXECUTIVE_BRIEF_SCOPE_CONCURRENCY=3    # Parallel brief generation

# Logging
LOG_LEVEL=INFO                         # DEBUG, INFO, WARNING, ERROR
PHASE_LOGGING_ENABLED=true            # Enable phase-based logging
```

### Troubleshooting

**Port already in use:**
```bash
# Find process using port 8080
lsof -i :8080
# Kill it
kill -9 <PID>
# Or use a different port
uvicorn web.app:app --port 8081
```

**Import errors:**
```bash
# Ensure you're in the project root
cd /data/data-analyst-agent
# Activate venv
source .venv/bin/activate
# Verify installation
pip list | grep google-adk
```

**Slow performance:**
- Reduce `EXECUTIVE_BRIEF_MAX_SCOPED_BRIEFS` to 2
- Increase `EXECUTIVE_BRIEF_SCOPE_CONCURRENCY` to 4
- Use `REPORT_SYNTHESIS_FORCE_DIRECT_TOOL=true` for faster synthesis

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


## Performance Controls

| Env Var | Default | Description |
|---------|---------|-------------|
| `EXECUTIVE_BRIEF_MAX_SCOPED_BRIEFS` | `3` | Caps how many scoped briefs (Level 1/2 entities) the executive brief agent will spawn per run. Tune down when profiling or when metric fan-out overwhelms the LLM budget. |
| `EXECUTIVE_BRIEF_SCOPE_CONCURRENCY` | `2` | Limits the asyncio semaphore that guards scoped brief fan-out to avoid saturating the GenAI backend. Set higher on beefier nodes or lower when profiling latency. |
| `REPORT_SYNTHESIS_FORCE_DIRECT_TOOL` | `false` | Forces the synthesis stage to skip the LLM and call `generate_markdown_report` directly. Useful for deterministic tests or when profiling tool latency. The agent now also auto-enables this fast-path whenever no hierarchical payload is available. |

When `REPORT_SYNTHESIS_FORCE_DIRECT_TOOL` is unset, the agent automatically detects missing hierarchical payloads and uses the deterministic Markdown tool. This prevents 300-second timeouts when upstream stages skip drill-downs.

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
