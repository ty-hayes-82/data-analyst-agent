# Quick Start - Running with ADK

This quick start guide shows how to run the P&L Analyst Agent using Google ADK.

## Prerequisites

- Python 3.10+
- Google Cloud project with Vertex AI API enabled
- Service account JSON key file
- `.env` file configured (see `.env.example`)

## Installation

```bash
# Navigate to project directory
cd C:\Streamlit\development\pl_analyst

# Activate virtual environment (if using one)
.venv\Scripts\activate

# Verify dependencies are installed
pip install -r requirements.txt
```

## Running the Agent

### Method 1: Using run_agent.py (Recommended)

**CSV Test Mode** (no external dependencies required):

```bash
# Interactive mode
python run_agent.py --test

# Single query
python run_agent.py --test --query "Analyze cost center 067 for revenue variances"

# From input file
python run_agent.py --test --input input.json
```

**Live Mode** (requires A2A server running on port 8001):

```bash
# Interactive mode
python run_agent.py

# Single query
python run_agent.py --query "Analyze cost center 067"
```

### Method 2: Direct Python Import

```python
import sys
sys.path.insert(0, 'C:\\Streamlit\\development')

# Enable test mode
import os
os.environ["PL_ANALYST_TEST_MODE"] = "true"

# Import and run
from pl_analyst.pl_analyst_agent.agent import root_agent
from google.adk.sessions.in_memory_session_service import InMemorySessionService

session_service = InMemorySessionService()
session = await session_service.create_session(app_name="pl_analyst", user_id="test_user")

# Run query
result = await root_agent.run_async(session, "Analyze cost center 067")
```

## Validation

Before running analysis, validate your setup:

```bash
# Validate project structure and configuration
python scripts\validate_adk_config.py

# Check agent health
python scripts\check_agent_health.py --skip-a2a

# Run test suite
pytest -m csv_mode
```

**Expected Output:**
```
================================================================================
ADK Configuration Validator - P&L Analyst Agent
================================================================================

Checking Agent Folder Structure... [OK] OK
Checking Root Agent Export... [OK] OK
Checking Environment Configuration... [OK] OK
Checking CSV Test Data... [OK] OK
Checking Dependencies... [OK] OK
Checking Sub-Agents... [OK] OK
Checking Config Files... [OK] OK
Checking ADK CLI Availability... [OK] OK

================================================================================
[OK] All 8 checks passed!

[INFO]
Your project is ready to run with ADK CLI:
  $ adk run pl_analyst_agent
================================================================================
```

## Example Session

```bash
$ python run_agent.py --test
[INFO] Running in TEST_MODE with CSV data
[INFO] Created session: abc123...

================================================================================
P&L Analyst Agent - Interactive Mode
================================================================================
App: pl_analyst
User: default_user
Session: abc123...
Mode: TEST (using CSV data)

Type your query or 'exit' to quit
================================================================================

[user]: Analyze cost center 067 for revenue variances

[pl_analyst_agent]: I'll analyze cost center 067's revenue variances...

[RequestAnalyzer]: Analyzing request intent...
[CostCenterExtractor]: Extracted cost center: 067
[testing_data_agent]: Loading data from CSV...
[DataValidationAgent]: Validating and enriching data...
[DataAnalystAgent]: Performing hierarchical drill-down analysis...
  Level 2: Analyzing 5 categories...
  Level 3: Drilling into top 3 categories...
  Level 4: Analyzing 12 GL accounts...
[ReportSynthesisAgent]: Generating 3-level report framework...
[OutputPersistenceAgent]: Saving results to outputs/cost_center_067.json

[pl_analyst_agent]: Analysis complete. Key findings:

Executive Summary:
- Revenue decreased $427K (-15.2%) YoY in Dec 2024
- Primary driver: Linehaul Revenue down $385K (90% of total variance)
- Partially offset by increased Accessorial Revenue (+$42K)
- Volume decline of 12% combined with 3% rate erosion
- Recommend: Review lane pricing and investigate customer attrition

Analysis saved to: outputs/cost_center_067.json
Alerts saved to: outputs/alerts_payload_cc067.json

[user]: exit

[INFO] Exiting...
```

## Output Files

After running analysis, check:

1. **outputs/cost_center_067.json** - Full analysis results with 3-level framework
2. **outputs/alerts_payload_cc067.json** - Scored alerts with recommendations
3. **logs/phase_log_*.log** - Detailed execution logs

## Next Steps

1. **Review outputs:** Check JSON files for detailed analysis
2. **Run pytest:** `pytest -m csv_mode` to validate components
3. **Read full guide:** See [ADK_CLI_GUIDE.md](ADK_CLI_GUIDE.md) for advanced usage
4. **Optimization:** Review [OPTIMIZATION_REPORT.md](OPTIMIZATION_REPORT.md) for performance tuning

## Troubleshooting

### Issue: "No module named 'pl_analyst'"

**Solution:** Use `run_agent.py` which handles PYTHONPATH automatically:
```bash
python run_agent.py --test
```

### Issue: A2A agents timeout

**Solution:** Switch to CSV test mode:
```bash
set PL_ANALYST_TEST_MODE=true
python run_agent.py --test
```

### Issue: pmdarima warning

**Impact:** Non-critical (ARIMA forecasting skipped)

**Optional fix:**
```bash
pip uninstall numpy pmdarima
pip install numpy==1.26.4 pmdarima
```

## Documentation

- **ADK_CLI_GUIDE.md** - Complete ADK CLI integration guide
- **OPTIMIZATION_REPORT.md** - Agent optimization and validation report
- **TESTING_GUIDE.md** - Comprehensive testing documentation
- **README.md** - Full project documentation

## Support

For issues:
1. Run validation: `python scripts\check_agent_health.py --verbose`
2. Check logs in `logs/` directory
3. Review troubleshooting section in ADK_CLI_GUIDE.md
