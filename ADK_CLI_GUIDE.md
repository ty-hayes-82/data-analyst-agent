# ADK CLI Guide - P&L Analyst Agent

## Table of Contents

1. [Overview](#overview)
2. [Project Structure & Compatibility](#project-structure--compatibility)
3. [Running the Agent](#running-the-agent)
4. [Configuration](#configuration)
5. [Test Mode (CSV Data)](#test-mode-csv-data)
6. [Live Mode (A2A Agents)](#live-mode-a2a-agents)
7. [Validation Scripts](#validation-scripts)
8. [Troubleshooting](#troubleshooting)
9. [Performance Optimization](#performance-optimization)

---

## Overview

This P&L Analyst Agent is built on Google's Agent Development Kit (ADK) and can be run programmatically using the custom `run_agent.py` script or integrated into larger applications.

**Key Points:**
- The agent uses **programmatic Python construction** rather than declarative YAML configs
- ADK CLI `adk run` can work with the current structure, but `run_agent.py` is recommended
- Project requires proper `PYTHONPATH` setup due to package structure

---

## Project Structure & Compatibility

### Package Structure

```
C:\Streamlit\development\pl_analyst\
├── pl_analyst_agent/           # Main agent package
│   ├── __init__.py
│   ├── agent.py               # root_agent export (main entry point)
│   ├── prompt.py
│   ├── config.py
│   ├── auth_config.py
│   ├── sub_agents/            # 9 specialized sub-agents
│   │   ├── 01_data_validation_agent/
│   │   ├── 02_statistical_insights_agent/
│   │   ├── 03_hierarchy_variance_ranker_agent/
│   │   ├── 04_report_synthesis_agent/
│   │   ├── 05_alert_scoring_agent/
│   │   ├── 06_output_persistence_agent/
│   │   ├── 07_seasonal_baseline_agent/
│   │   ├── data_analyst_agent/
│   │   └── testing_data_agent/
│   ├── tools/
│   └── utils/
├── config/                    # Configuration YAML files
├── data/                      # Test data
├── scripts/                   # Validation & utility scripts
├── __init__.py               # Package root (creates pl_analyst package)
├── run_agent.py              # Recommended run script
└── .env                      # Environment configuration
```

### ADK CLI Compatibility

The project structure is compatible with ADK CLI because:

1. **Agent Entry Point**: `pl_analyst_agent/agent.py` exports `root_agent` (SequentialAgent)
2. **Package Structure**: Follows ADK loader pattern (a) - `{agent_name}/agent.py`
3. **Import Structure**: Uses `pl_analyst` as package root

**Note:** The directory `pl_analyst` acts as the package root, so imports use:
```python
from pl_analyst.pl_analyst_agent.agent import root_agent
from pl_analyst.config.model_loader import get_agent_model
```

---

## Running the Agent

### Method 1: Using run_agent.py (Recommended)

The `run_agent.py` script handles PYTHONPATH setup automatically:

```bash
# Interactive mode with CSV test data
python run_agent.py --test

# Interactive mode with live A2A agents
python run_agent.py

# Single query non-interactive
python run_agent.py --test --query "Analyze cost center 067 for revenue variances"

# From input JSON file
python run_agent.py --test --input input.json
```

**Options:**
- `--test` - Run in CSV test mode (no A2A agents required)
- `--query "..."` - Run single query non-interactively
- `--input file.json` - Run from input JSON file
- `--save-session` - Save session on exit
- `--session-id ID` - Resume existing session
- `--user-id USER` - Set user ID (default: default_user)
- `--app-name NAME` - Set app name (default: pl_analyst)

### Method 2: Direct Python Import

```python
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, 'C:\\Streamlit\\development')

# Set test mode if needed
import os
os.environ["PL_ANALYST_TEST_MODE"] = "true"

# Import agent
from pl_analyst.pl_analyst_agent.agent import root_agent

# Create session and run
from google.adk.sessions.in_memory_session_service import InMemorySessionService
session_service = InMemorySessionService()
session = await session_service.create_session(app_name="pl_analyst", user_id="test_user")

# Run query
result = await root_agent.run_async(session, "Analyze cost center 067")
```

### Method 3: ADK CLI (if available)

If ADK CLI is installed:

```bash
# From parent directory with PYTHONPATH
cd C:\Streamlit\development
set PYTHONPATH=C:\Streamlit\development
set PL_ANALYST_TEST_MODE=true
adk run pl_analyst/pl_analyst_agent
```

**Note:** This may require additional configuration depending on ADK CLI version.

---

## Configuration

### Environment Variables (.env)

Required variables:

```bash
# Google Cloud Configuration
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_CLOUD_LOCATION=us-central1
GOOGLE_APPLICATION_CREDENTIALS=./service-account.json

# Model Configuration
ROOT_AGENT_MODEL=gemini-2.5-pro
MODEL_TEMPERATURE=0.0

# A2A Server (for live mode)
A2A_BASE_URL=http://localhost:8001
A2A_SERVER_PORT=8001

# Test Mode
PL_ANALYST_TEST_MODE=false  # Set to "true" for CSV test mode

# Rate Limiting
GOOGLE_GENAI_RPM_LIMIT=30

# Logging
PHASE_LOGGING_ENABLED=true
PHASE_LOG_LEVEL=INFO
```

### Agent Model Tiers

Models are configured in `config/agent_models.yaml`:

```yaml
model_tiers:
  ultra: "gemini-2.0-flash-lite"      # Ultra-fast, simple operations
  fast: "gemini-2.5-flash-lite"       # Fast, efficient
  standard: "gemini-2.5-flash"        # Balanced, general use
  advanced: "gemini-2.5-pro"          # Complex reasoning

agents:
  data_validation_agent: {tier: ultra}
  statistical_insights_agent: {tier: fast}
  data_analyst_agent: {tier: standard}
  report_synthesis_agent: {tier: standard}
  # ... 30+ agent configurations
```

**Optimization Guidelines:**
- **Ultra**: Simple data transformations, parsing, validation
- **Fast**: Statistical computations, aggregations, ranking
- **Standard**: Business logic, analysis orchestration, synthesis
- **Advanced**: Complex reasoning, multi-step planning (use sparingly)

---

## Test Mode (CSV Data)

Test mode uses local CSV data instead of A2A agents, ideal for:
- CI/CD pipelines
- Development without external dependencies
- Quick validation
- Demos and testing

### Setup

1. **Set environment variable:**
   ```bash
   set PL_ANALYST_TEST_MODE=true
   ```

2. **Ensure CSV test data exists:**
   ```
   C:\Streamlit\development\pl_analyst\data\PL-067-REVENUE-ONLY.csv
   ```

3. **Run agent:**
   ```bash
   python run_agent.py --test
   ```

### Example Test Query

```
Analyze cost center 067 for revenue variances
```

**Expected Workflow:**
1. RequestAnalyzer - Analyzes query intent
2. CostCenterExtractor - Extracts "067"
3. testing_data_agent - Loads data from CSV
4. DataValidationAgent - Validates and enriches data
5. DataAnalystAgent - Performs hierarchical drill-down
6. ReportSynthesisAgent - Generates 3-level report
7. OutputPersistenceAgent - Saves to `outputs/cost_center_067.json`

**Performance (CSV Mode):**
- Data loading: ~2-3s (from CSV)
- Analysis: ~30-45s (hierarchical drill-down)
- Total: ~35-50s per cost center

---

## Live Mode (A2A Agents)

Live mode connects to Tableau A2A agents for real data.

### Prerequisites

1. **A2A Server running on port 8001**
2. **Three Tableau A2A agents configured:**
   - `tableau_account_research_ds_agent` (P&L data)
   - `tableau_ops_metrics_ds_agent` (operational metrics)
   - `tableau_order_dispatch_revenue_ds_agent` (order details)

### Setup

1. **Ensure A2A server is running:**
   ```bash
   # Check A2A agents are accessible
   curl http://localhost:8001/a2a/tableau_account_research_ds_agent/.well-known/agent.json
   ```

2. **Set environment:**
   ```bash
   set PL_ANALYST_TEST_MODE=false
   set A2A_BASE_URL=http://localhost:8001
   ```

3. **Run agent:**
   ```bash
   python run_agent.py
   ```

### Example Live Query

```
Analyze cost center 067 for contract billing violations in the last 3 months
```

**Expected Workflow:**
1. RequestAnalyzer - Identifies "contract validation" request type
2. CostCenterExtractor - Extracts "067"
3. DateInitializer - Calculates date ranges (24mo P&L, 3mo orders)
4. **Parallel Data Fetch** (3 A2A agents in parallel):
   - tableau_account_research_ds_agent (P&L data, 24 months)
   - tableau_ops_metrics_ds_agent (ops metrics, 24 months)
   - tableau_order_dispatch_revenue_ds_agent (order details, 3 months)
5. DataValidationAgent - Validates and enriches all data
6. DataAnalystAgent - Hierarchical drill-down with contract analysis
7. ReportSynthesisAgent - 3-level framework report
8. OutputPersistenceAgent - Saves JSON outputs

**Performance (Live Mode):**
- Data fetch: ~15-20s (rate-limited A2A calls)
- Analysis: ~30-45s (hierarchical drill-down)
- Total: ~50-70s per cost center

---

## Validation Scripts

### 1. validate_adk_config.py

Validates project structure and configuration:

```bash
python scripts\validate_adk_config.py
python scripts\validate_adk_config.py --verbose
```

**Checks:**
- ✓ Agent folder structure
- ✓ Root agent export
- ✓ Environment configuration
- ✓ CSV test data
- ✓ Dependencies installed
- ✓ Sub-agents configured
- ✓ Config files valid
- ✓ ADK CLI availability

### 2. check_agent_health.py

Performs health checks on all agents:

```bash
python scripts\check_agent_health.py
python scripts\check_agent_health.py --skip-a2a
python scripts\check_agent_health.py --verbose
```

**Checks:**
- ✓ Root agent imports correctly
- ✓ All 9 sub-agents load
- ✓ Model tier assignments valid
- ✓ A2A agent connectivity (if not skipped)
- ✓ Configuration files valid

---

## Troubleshooting

### Issue: "No module named 'pl_analyst'"

**Cause:** PYTHONPATH not set correctly

**Solution:**
```bash
# Use run_agent.py which handles this automatically
python run_agent.py --test

# OR set PYTHONPATH manually
cd C:\Streamlit\development
set PYTHONPATH=C:\Streamlit\development
python -m pl_analyst.pl_analyst_agent.agent
```

### Issue: "pmdarima not available" warning

**Cause:** Numpy version incompatibility

**Impact:** ARIMA forecasting will be skipped (non-critical)

**Solution:** (Optional)
```bash
pip uninstall pmdarima numpy
pip install numpy==1.26.4
pip install pmdarima
```

### Issue: A2A agents timeout

**Cause:** A2A server not running or agents not configured

**Solution:**
```bash
# Switch to test mode
set PL_ANALYST_TEST_MODE=true
python run_agent.py --test

# OR check A2A server status
python scripts\check_agent_health.py --skip-a2a
```

### Issue: "UnicodeEncodeError" in validation scripts

**Cause:** Windows console encoding (cp1252) doesn't support Unicode checkmarks

**Status:** Fixed in validation scripts (using ASCII [OK]/[ERROR] instead)

**Verify:**
```bash
python scripts\validate_adk_config.py
```

---

## Performance Optimization

### Model Tier Optimization

Current tier distribution (from `agent_models.yaml`):

| Tier | Model | Agent Count | Use Case |
|------|-------|-------------|----------|
| **Ultra** | gemini-2.0-flash-lite | 4 | Data validation, persistence, iteration |
| **Fast** | gemini-2.5-flash-lite | 12 | Statistics, ranking, forecasting, Jira ops |
| **Standard** | gemini-2.5-flash | 18 | Analysis, synthesis, orchestration |
| **Advanced** | gemini-2.5-pro | 0 | (Not currently used) |

**Recommendations:**

1. **Consider downgrading to "fast":**
   - `request_analyzer` - Simple intent classification
   - `cost_center_extractor` - Regex-based extraction

2. **Consider upgrading to "advanced":**
   - `data_analyst_agent` - Complex hierarchical reasoning
   - Only if budget allows and quality issues observed

3. **Parallel execution:**
   - Data fetch agents run in parallel (3 concurrent)
   - Analysis agents can run in parallel (6 concurrent)
   - Monitor rate limits (GOOGLE_GENAI_RPM_LIMIT=30)

### Performance Metrics

**Target Latency (per cost center):**
- CSV Test Mode: 35-50s
- Live Mode: 50-70s

**Breakdown:**
```
Request Processing:     5-10s  (LLM extraction)
Data Fetching:         15-20s  (A2A agents, rate limited)
Data Validation:        5-10s  (enrichment + joins)
Hierarchical Analysis: 30-45s  (Level 2→3→4 drill-down)
Synthesis:              5-10s  (3-level report)
Alert Scoring:          5-10s  (multi-factor scoring)
Total:                 65-100s
```

### Optimization Strategies

1. **Caching:**
   - Cache GL account hierarchy lookups
   - Cache cost center to customer mappings
   - Cache seasonal baseline calculations

2. **Batch Processing:**
   - Process multiple cost centers in single session
   - Reuse common data (e.g., same date ranges)

3. **Rate Limit Management:**
   - Increase RPM limit if quota allows
   - Implement request queuing for bursts
   - Use exponential backoff (already configured)

4. **Model Selection:**
   - Profile agent execution times
   - Downgrade non-critical paths to "fast"
   - Reserve "standard" for synthesis and orchestration

---

## Next Steps

1. **Run validation:**
   ```bash
   python scripts\validate_adk_config.py
   python scripts\check_agent_health.py --skip-a2a
   ```

2. **Test in CSV mode:**
   ```bash
   python run_agent.py --test --query "Analyze cost center 067"
   ```

3. **Review outputs:**
   ```
   outputs/cost_center_067.json
   outputs/alerts_payload_cc067.json
   logs/phase_log_*.log
   ```

4. **Run pytest suite:**
   ```bash
   pytest -m csv_mode
   pytest --cov=pl_analyst_agent --cov-report=html
   ```

5. **Deploy to production:**
   ```bash
   python deployment/deploy_with_tracing.py --create \
     --project_id=your-project-id \
     --location=us-central1 \
     --bucket=your-storage-bucket
   ```

---

## Additional Resources

- **Main README:** `README.md`
- **Agent Architecture:** `AGENT_ARCHITECTURE_SUMMARY.md`
- **Testing Guide:** `TESTING_GUIDE.md`
- **Deployment Guide:** `DEPLOYMENT.md`
- **Quick Reference:** `QUICK_REFERENCE.md`
- **Phase Logging:** `PHASE_LOGGING_GUIDE.md`
- **Test Mode:** `TEST_MODE_README.md`

---

## Support

For issues or questions:
1. Check troubleshooting section above
2. Review agent logs in `logs/` directory
3. Run health checks: `python scripts\check_agent_health.py --verbose`
4. Check configuration: `python scripts\validate_adk_config.py --verbose`

---

**Last Updated:** 2025-11-20
**ADK Version:** 1.16.0+ (source install from C:\Streamlit\adk-python)
**Python Version:** 3.10+
