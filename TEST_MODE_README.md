# P&L Analyst - Testing with CSV Data

## Overview

The P&L Analyst now supports **TEST MODE** which allows you to run the full analysis pipeline using CSV data instead of requiring the Tableau A2A agents to be running.

This is useful for:
- Development and testing without infrastructure dependencies
- Rapid iteration on analysis logic
- Debugging specific scenarios with known data
- Demo and training purposes

## Quick Start

### 1. Enable Test Mode

Set the environment variable:

```bash
# Windows PowerShell
$env:PL_ANALYST_TEST_MODE = "true"

# Linux/Mac
export PL_ANALYST_TEST_MODE=true
```

### 2. Run the Test Script

```bash
python test_with_csv.py
```

### 3. Or Use in Your Own Code

```python
import os
os.environ["PL_ANALYST_TEST_MODE"] = "true"

from pl_analyst.pl_analyst_agent.agent import root_agent
# ... use root_agent as normal
```

## Data Format

The testing data agent expects CSV data in the following format (matching PL-067.csv):

```csv
DIV,LOB,GL_CC,Account Nbr,level_1,level_2,level_3,level_4,CTDESC,2024 - 07,2024 - 08,...
107,17,67,3100-00,Total Operating Revenue,...,Operating Revenue,"-645,527","-781,132",...
```

### Key Columns:
- `GL_CC`: Cost center (e.g., "67")
- `Account Nbr`: GL account number (e.g., "3100-00")
- `CTDESC`: Account description
- `level_1, level_2, level_3, level_4`: Account hierarchy
- Period columns: Format "YYYY - MM" (e.g., "2024 - 07")

## What Works in Test Mode

✅ **Full Analysis Pipeline:**
- Cost center extraction
- Date range calculation
- P&L data loading from CSV
- Data validation and cleaning
- Category aggregation
- Statistical analysis (MoM, YoY, 3MMA, 6MMA)
- Variance calculations
- Materiality flagging
- Ratio analysis
- Anomaly detection
- Forecasting
- Synthesis and executive summary
- Alert scoring

✅ **3-Level Drill-Down:**
- Level 1: High-level summary with baselines
- Level 2: Category analysis (top drivers)
- Level 3: GL-level drill-down

## Limitations in Test Mode

⚠️ **Not Yet Implemented:**
- Operational metrics (miles, loads, stops) - CSV doesn't include this
- Order-level details - Not in PL-067.csv
- Per-unit analysis (per mile, per load, per stop) - Requires ops metrics

These features work in production mode with the full Tableau A2A agents.

## Switching Between Modes

### Test Mode (CSV Data)
```python
os.environ["PL_ANALYST_TEST_MODE"] = "true"
```

### Production Mode (Tableau A2A)
```python
os.environ["PL_ANALYST_TEST_MODE"] = "false"
# or unset the variable
```

## Adding Test Data

To test with different cost centers:

1. Export P&L data in the same format as PL-067.csv
2. Save to `data/PL-XXX.csv` (where XXX is the cost center)
3. Update the CSV path in testing_data_agent if needed

## File Structure

```
pl_analyst/
├── data/
│   └── PL-067.csv                          # Test data
├── pl_analyst_agent/
│   ├── agent.py                            # Main agent (with TEST_MODE support)
│   └── sub_agents/
│       ├── testing_data_agent/             # CSV data loader
│       │   ├── agent.py                    # TestingDataAgent
│       │   └── __init__.py
│       └── ...
└── test_with_csv.py                        # Test script
```

## Troubleshooting

### CSV File Not Found
```
Error: CSV file not found: data/PL-067.csv
```
**Solution:** Ensure `data/PL-067.csv` exists in the project root.

### Cost Center Mismatch
```
[TestingDataAgent] Data loaded successfully:
  Total rows: 0
```
**Solution:** The CSV's `GL_CC` column must match the requested cost center.

### Date Range Issues
```
  Period range: NaT to NaT
```
**Solution:** Check that period columns in CSV match format "YYYY - MM".

## Next Steps

After testing with CSV data:

1. **Validate Results:** Review outputs in `outputs/` directory
2. **Switch to Production:** Disable TEST_MODE and connect to Tableau A2A agents
3. **Add Ops Metrics:** Extend testing_data_agent to include mock operational metrics
4. **Create More Test Cases:** Add additional CSV files for different scenarios

## Support

For issues or questions:
- Check the main README.md
- Review agent.py for TEST_MODE implementation
- Inspect testing_data_agent/agent.py for CSV loading logic

