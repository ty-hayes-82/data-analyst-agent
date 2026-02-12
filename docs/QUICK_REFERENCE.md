# P&L Analyst - Quick Reference Guide

## Agent Directory

### Root Level Agents

| Agent Name | Location | Model Tier | Purpose | Key Tools |
|------------|----------|------------|---------|-----------|
| **Root Orchestration Agent** | `pl_analyst_agent/agent.py` | Advanced (2.5-pro) | Main workflow coordinator | `parse_cost_centers`, `calculate_date_ranges`, `should_fetch_order_details` |
| **Cost Center Extractor** | `pl_analyst_agent/agent.py` | Standard (2.5-flash) | Extracts cost center numbers from query | LLM-based parsing |
| **Request Analyzer** | `pl_analyst_agent/agent.py` | Standard (2.5-flash) | Analyzes user request scope | LLM-based analysis |

### Remote A2A Data Agents

| Agent Name | Port | Data Type | Volume | Time Range |
|------------|------|-----------|--------|------------|
| **tableau_account_research_ds_agent** | 8001 | P&L monthly aggregates | 6.3M+ transactions | 24 months |
| **tableau_ops_metrics_ds_agent** | 8001 | Operational metrics | 37M+ records | 24 months |
| **tableau_order_dispatch_revenue_ds_agent** | 8001 | Order-level detail | Variable | 3 months (conditional) |

### Core Processing Agents

| Agent Name | Location | Model Tier | Purpose | Output Key |
|------------|----------|------------|---------|------------|
| **Ingest Validator Agent** | `sub_agents/ingest_validator_agent/` | Ultra (2.0-flash-lite) | Data validation & enrichment | `validated_data` |
| **Data Analyst Agent** | `sub_agents/data_analyst_agent/` | Standard (2.5-flash) | Stats-first hierarchical analysis | `level_N_result` |
| **Level Analyzer Agent** | `sub_agents/data_analysis/level_analyzer_agent/` | Standard (2.5-flash) | Hierarchy aggregation & ranking | `level_analysis_result` |
| **Synthesis Agent** | `sub_agents/synthesis_agent/` | Standard (2.5-flash) | 3-level report generation | `synthesis_result` |
| **Alert Scoring Coordinator** | `sub_agents/alert_scoring_coordinator_agent/` | Standard (2.5-flash) | Alert lifecycle management | `alert_scoring_result` |
| **Persist Insights Agent** | `sub_agents/persist_insights_agent/` | N/A | JSON file persistence | File outputs |

### Analysis Sub-Agents (Run in Parallel)

| Agent Name | Model Tier | Focus Area | Key Outputs |
|------------|------------|------------|-------------|
| **Statistical Analysis Agent** | Fast (2.5-flash-lite) | Variances, materiality | YoY, MoM, 3MMA, 6MMA |
| **Seasonal Baseline Agent** | Standard (2.5-flash) | Seasonal patterns | YoY comparisons |
| **Ratio Analysis Agent** | Fast (2.5-flash-lite) | Per-unit metrics | Cost per mile/load/stop |
| **Anomaly Detection Agent** | Standard (2.5-flash) | Outliers & change points | Z-scores, MAD, drift |

### Utility Agents

| Agent Name | Location | Purpose |
|------------|----------|---------|
| **Testing Data Agent** | `sub_agents/testing_data_agent/` | CSV-based testing (TEST_MODE) |
| **Safe Parallel Wrapper** | `utils/safe_parallel_wrapper.py` | Fault-tolerant parallel execution |

---

## Tool Inventory

### Root Agent Tools
**Location:** `pl_analyst_agent/tools/`

| Tool | Purpose | Returns |
|------|---------|---------|
| `calculate_date_ranges` | Computes analysis periods | Dict with P&L (24mo) and order (3mo) ranges |
| `parse_cost_centers` | Extracts cost centers from query | List of cost center strings |
| `iterate_cost_centers` | Loop control | Next cost center or completion |
| `should_fetch_order_details` | Determines order data need | Boolean |
| `create_data_request_message` | Formats A2A queries | Formatted request string |

### Ingest Validator Tools
**Location:** `sub_agents/ingest_validator_agent/tools/`

| Tool | Purpose | Input | Output |
|------|---------|-------|--------|
| `reshape_and_validate` | Data quality checks | Raw data | Validated DataFrame |
| `load_and_validate_from_cache` | TEST_MODE CSV loader | File path | DataFrame |
| `aggregate_by_category` | Category grouping | DataFrame | Aggregated by canonical_category |
| `join_ops_metrics` | Merge operational data | financial_data_pl + ops_metrics | Enriched DataFrame |
| `join_chart_metadata` | Add hierarchy levels | DataFrame + chart_of_accounts | DataFrame with level_1-4 |
| `json_to_csv` / `csv_to_json_passthrough` | Format conversion | Data | Converted format |

### Level Analyzer Tools
**Location:** `sub_agents/data_analysis/level_analyzer_agent/tools/`

| Tool | Purpose | Input | Output |
|------|---------|-------|--------|
| `aggregate_by_level` | Group by hierarchy level | DataFrame, level_number | Aggregated by level_N |
| `rank_level_items_by_variance` | Sort by variance | Aggregated data | Ranked list |
| `identify_top_level_drivers` | Select top 3-5 items | Ranked data | Top drivers (80% rule) |
| `get_validated_csv_from_state` | Retrieve data | State | validated_data |

### Data Analyst Tools
**Location:** `sub_agents/data_analyst_agent/tools/`

| Tool | Purpose | Outputs |
|------|---------|---------|
| `compute_statistical_summary` | Comprehensive stats in Python/pandas | Top drivers, anomalies, correlations, monthly totals, per-unit metrics |

### Alert Scoring Tools
**Location:** `sub_agents/alert_scoring_coordinator_agent/tools/`

| Tool | Purpose | Input | Output |
|------|---------|-------|--------|
| `extract_alerts_from_analysis` | Parse analysis for alerts | synthesis_result | List of raw alerts |
| `score_alerts` | Multi-factor scoring | Raw alerts | Scored alerts |
| `apply_suppression` | Deduplication & filtering | Scored alerts | Suppressed list |
| `get_order_details_for_period` | Order data fetch | Period, cost center | Order DataFrame |
| `get_top_shippers_by_miles` | High-volume shippers | Cost center | Shipper list |
| `get_monthly_aggregates_by_cost_center` | Cost center trends | Cost center | Monthly aggregates |
| `capture_feedback` | User feedback storage | Alert ID, feedback | Confirmation |
| `contract_rate_tools` | Contract validation | Order data | Validation results |

---

## Configuration Quick Reference

### Environment Variables (.env)

```bash
# Google Cloud
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_CLOUD_LOCATION=us-central1
GOOGLE_CLOUD_STORAGE_BUCKET=your-bucket-name

# Models
ROOT_AGENT_MODEL=gemini-2.5-pro
MODEL_TEMPERATURE=0.0

# A2A Server
A2A_BASE_URL=http://localhost:8001

# Rate Limiting
GOOGLE_GENAI_RPM_LIMIT=5
GOOGLE_GENAI_RETRY_DELAY=3

# Testing
PL_ANALYST_TEST_MODE=false
```

### Materiality Thresholds (materiality_config.yaml)

| Threshold | Value | Purpose |
|-----------|-------|---------|
| `variance_pct` | ±5.0% | Percentage threshold |
| `variance_dollar` | ±$50,000 | Absolute dollar threshold |
| `top_categories_count` | 5 | Number of categories to analyze |
| `cumulative_variance_pct` | 80% | Variance explanation target |
| `min_amount` | $10,000 | Minimum to consider material |
| `cost_per_mile_pct` | ±10% | Per-mile variance threshold |
| `cost_per_load_pct` | ±10% | Per-load variance threshold |
| `cost_per_stop_pct` | ±10% | Per-stop variance threshold |

### Alert Severity (alert_policy.yaml)

| Severity | Conditions | Actions |
|----------|------------|---------|
| **Info** | Z-score MAD ≥ 2.0, PI breaches ≥ 0 | Monitor |
| **Warn** | Z-score MAD ≥ 3.0, PI breaches ≥ 1 | Investigate |
| **Critical** | Change point true, MoM ≥ 25%, YoY ≥ 20% | Immediate action |

**Fatigue Settings:**
- Suppress for: 14 days
- Rearm on escalation: true

### Model Tiers (agent_models.yaml)

| Tier | Model | Use Cases |
|------|-------|-----------|
| **Ultra** | `gemini-2.0-flash-lite` | Simple operations, data validation |
| **Fast** | `gemini-2.5-flash-lite` | Simple tasks, computation-heavy |
| **Standard** | `gemini-2.5-flash` | General use, LLM decisions |
| **Advanced** | `gemini-2.5-pro` | Complex reasoning, orchestration |

---

## Performance Benchmarks

### Timing by Phase

| Phase | Average | Range | Notes |
|-------|---------|-------|-------|
| Request Processing | 7s | 5-10s | LLM extraction + calculations |
| Data Fetching | 17s | 15-20s | 3 A2A agents (rate limited) |
| Data Validation | 7s | 5-10s | Enrichment + joins |
| Level 2 Analysis | 12s | 10-15s | 5 agents in parallel |
| Level 3 Analysis | 12s | 10-15s | If triggered |
| Level 4 Analysis | 12s | 10-15s | If triggered |
| Synthesis | 7s | 5-10s | 3-level report |
| Alert Scoring | 7s | 5-10s | Multi-factor scoring |
| Persistence | 1.5s | 1-2s | JSON write |
| **Total (L2 only)** | **59s** | **48-67s** | No drill-down |
| **Total (L2→L3)** | **71s** | **58-82s** | One drill-down |
| **Total (L2→L3→L4)** | **83s** | **68-97s** | Full drill-down |

### Data Volume Characteristics

| Data Source | Records | Time Range | Fetch Time | Format |
|-------------|---------|------------|------------|--------|
| P&L Data | 6.3M+ | 24 months | 6-8s | CSV |
| Ops Metrics | 37M+ | 24 months | 7-9s | CSV |
| Order Details | Variable | 3 months | 2-3s | CSV |

---

## Command Reference

### Setup & Installation

```bash
# Create environment
cd pl_analyst
python -m venv .venv
.venv\Scripts\activate  # Windows
source .venv/bin/activate  # Linux/Mac

# Install dependencies
pip install -r requirements.txt

# Copy environment template
cp config/env.example .env

# Edit configuration
# - Add service-account.json
# - Edit database_config.yaml
# - Configure .env
```

### Testing & Validation

```bash
# Test database connection
python data/test_database_connection.py

# Test A2A agents
python data/test_tableau_connection.py

# Validate all data sources
python data/validate_data_sources.py

# Run integration tests
python scripts/tests/test_pl_analyst_direct.py
python scripts/tests/test_alert_scoring.py
```

### Running A2A Server

```bash
# Navigate to remote_a2a directory
cd ../remote_a2a

# Start A2A server
python start_a2a_server.py

# Verify agents are running
curl http://localhost:8001/a2a/tableau_account_research_ds_agent/.well-known/a2a-agent.json
```

### Deployment

```bash
# Deploy to Vertex AI
python deployment/deploy_with_tracing.py --create \
  --project_id=your-project-id \
  --location=us-central1 \
  --bucket=your-storage-bucket

# Update existing deployment
python deployment/deploy_with_tracing.py --update \
  --project_id=your-project-id
```

### Test Mode

```bash
# Enable TEST_MODE
export PL_ANALYST_TEST_MODE=true  # Linux/Mac
$env:PL_ANALYST_TEST_MODE="true"  # Windows PowerShell

# Run with CSV data
python test_with_csv.py
```

---

## API Usage Examples

### Basic Analysis

```python
from pl_analyst_agent.agent import root_agent
from google.adk.sessions import InMemorySessionStore

# Create session
session_store = InMemorySessionStore()
session = session_store.create_session(app_name="pl_analyst")

# Run analysis
user_query = "Analyze cost center 067 for contract violations"
result = await root_agent.run_async(session, user_query)

# Results saved to:
# - outputs/cost_center_067.json
# - outputs/alerts_payload_cc067.json
```

### Multiple Cost Centers

```python
user_query = "Analyze cost centers 067, 088, and 095"
result = await root_agent.run_async(session, user_query)

# Sequential processing (clean isolation)
# Outputs:
# - outputs/cost_center_067.json
# - outputs/cost_center_088.json
# - outputs/cost_center_095.json
```

### Test Mode with CSV

```python
import os
os.environ["PL_ANALYST_TEST_MODE"] = "true"

# Uses data/test_pl_data.csv instead of A2A agents
result = await root_agent.run_async(session, "Analyze cost center 067")
```

---

## Output File Structure

### Cost Center Analysis (cost_center_XXX.json)

```json
{
  "version": "2.0",
  "cost_center": "067",
  "period_range": "2023-01 to 2024-12",
  "timestamp": "2025-10-28T10:30:00Z",
  
  "executive_summary": [
    "Overall variance: -$425K YoY (-12%)",
    "Top drivers: Fuel -$300K, Labor +$150K",
    "..."
  ],
  
  "level_2_analysis": [{
    "level_name": "Fuel",
    "variance_yoy": -300000,
    "variance_pct": -15.0,
    "materiality": "material",
    "top_drivers": ["GL 6020", "GL 6025"]
  }],
  
  "level_3_analysis": [/* if reached */],
  "level_4_analysis": [/* if reached */],
  
  "statistical_summary": {
    "top_drivers": [/* ... */],
    "anomalies": [/* ... */],
    "correlations": {/* ... */}
  },
  
  "metadata": {
    "analysis_levels_reached": ["2", "3", "4"],
    "drill_down_decisions": ["CONTINUE", "CONTINUE", "STOP"]
  }
}
```

### Alert Payload (alerts_payload_ccXXX.json)

```json
{
  "cost_center": "067",
  "timestamp": "2025-10-28T10:30:00Z",
  "alerts": [
    {
      "alert_id": "cc067_fuel_2024",
      "severity": "critical",
      "score": 0.85,
      "category": "Fuel",
      "gl_accounts": ["6020-01"],
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
      "ownership": "Ops - Sacramento"
    }
  ]
}
```

---

## Troubleshooting Quick Fixes

### Issue: A2A Server Not Responding

```bash
# Check if server is running
curl http://localhost:8001/health

# Restart server
cd ../remote_a2a
python start_a2a_server.py
```

### Issue: Authentication Errors

```bash
# Verify service account
ls -la service-account.json

# Set environment variable
export GOOGLE_APPLICATION_CREDENTIALS="$(pwd)/service-account.json"

# Test authentication
gcloud auth application-default login
```

### Issue: Import Errors

```bash
# Verify virtual environment is activated
which python  # Should show .venv path

# Reinstall dependencies
pip install -r requirements.txt

# Check Python version
python --version  # Should be 3.10+
```

### Issue: Missing Data

```python
# Validate data sources
from pl_analyst_agent.agent import verify_tableau_agents
status = verify_tableau_agents()
print(status)

# Check database config
from pl_analyst_agent.config import config
config.validate()
```

### Issue: Slow Performance

1. **Check rate limiting:** Increase `GOOGLE_GENAI_RPM_LIMIT` in .env
2. **Reduce analysis depth:** Set materiality thresholds higher
3. **Use faster models:** Switch agents to "fast" tier in agent_models.yaml
4. **Enable caching:** (Future enhancement)

---

## File Locations Quick Map

| File Type | Location | Example |
|-----------|----------|---------|
| Main Agent | `pl_analyst_agent/agent.py` | Root orchestrator |
| Sub-Agents | `pl_analyst_agent/sub_agents/*/agent.py` | Data analyst, synthesis, etc. |
| Tools | `pl_analyst_agent/*/tools/*.py` | Individual tool functions |
| Config | `config/*.yaml` | Models, thresholds, policies |
| Outputs | `outputs/*.json` | Analysis results, alerts |
| Logs | `logs/*.log` | Runtime logs |
| Tests | `scripts/tests/*.py` | Integration tests |
| Deployment | `deployment/*.py` | Vertex AI deployment |
| Data | `data/*.csv` | Test data (TEST_MODE) |
| Docs | `docs/*.md` | Documentation |

---

## Security Checklist

### Never Commit
- [ ] `service-account.json`
- [ ] `database_config.yaml`
- [ ] `.env`
- [ ] `outputs/*.json`
- [ ] `logs/*.log`
- [ ] `__pycache__/`
- [ ] `temp_*` directories

### Always
- [ ] Use `.example` templates for sensitive configs
- [ ] Store secrets in environment variables
- [ ] Redact PII in logs
- [ ] Respect data residency requirements
- [ ] Use service account authentication

---

## Key Contacts & Resources

### Documentation
- **Architecture Summary:** `docs/AGENT_ARCHITECTURE_SUMMARY.md`
- **Workflow Diagrams:** `docs/WORKFLOW_DIAGRAM.md`
- **Quick Reference:** `docs/QUICK_REFERENCE.md` (this file)
- **Main README:** `README.md`
- **Hierarchical Implementation:** `HIERARCHICAL_IMPLEMENTATION.md`

### Project Structure Rules
- **Workspace Rules:** `.cursor/rules/pl-analyst-project-structure.mdc`
- **Remote A2A Rules:** `.cursor/rules/remote-a2a-project-structure.mdc`

### Entry Points
- **Main Agent:** `pl_analyst_agent/agent.py`
- **A2A Server:** `../remote_a2a/start_a2a_server.py`
- **Deployment:** `deployment/deploy_with_tracing.py`
- **Validation:** `data/validate_data_sources.py`

---

**Document Version:** 1.0  
**Last Updated:** October 28, 2025  
**Quick Reference Guide**

