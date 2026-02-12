# Test Setup Guide for test_with_csv.py

## Overview

The `test_with_csv.py` script tests the P&L Analyst using CSV data instead of live Tableau connections. However, it still requires Google Cloud authentication because the analysis agents use Google's Gemini models for intelligent analysis.

## Quick Setup (Recommended)

### Option 1: Using Google AI API Key (Easiest)

1. **Get a Free API Key**:
   - Visit: https://aistudio.google.com/apikey
   - Sign in with your Google account
   - Click "Create API Key"
   - Copy the key

2. **Set Environment Variable**:
   ```powershell
   # PowerShell
   $env:GOOGLE_API_KEY = "your-api-key-here"
   
   # Or for persistence (PowerShell):
   [System.Environment]::SetEnvironmentVariable('GOOGLE_API_KEY', 'your-api-key-here', 'User')
   ```

3. **Run the Test**:
   ```powershell
   cd pl_analyst
   python test_with_csv.py
   ```

### Option 2: Using Google Cloud Service Account (Production)

1. **Get Service Account**:
   - Go to: https://console.cloud.google.com/
   - Navigate to IAM & Admin > Service Accounts
   - Create service account with Vertex AI user role
   - Download JSON key file

2. **Place Service Account File**:
   ```powershell
   # Option A: Place in parent directory
   copy path\to\service-account.json C:\Streamlit\service-account.json
   
   # Option B: Set environment variable
   $env:GOOGLE_APPLICATION_CREDENTIALS = "C:\path\to\service-account.json"
   ```

3. **Run the Test**:
   ```powershell
   cd pl_analyst
   python test_with_csv.py
   ```

### Option 3: Using Application Default Credentials (gcloud CLI)

1. **Install gcloud CLI**:
   - Download from: https://cloud.google.com/sdk/docs/install

2. **Authenticate**:
   ```powershell
   gcloud auth application-default login
   ```

3. **Run the Test**:
   ```powershell
   cd pl_analyst
   python test_with_csv.py
   ```

## Troubleshooting

### "DefaultCredentialsError: Your default credentials were not found"

This means no authentication method is configured. Choose one of the options above.

### "API Key not valid"

- Make sure you copied the entire key
- Check if the API key has been enabled for the Gemini API
- Visit Google AI Studio to verify the key is active

### "Permission Denied" with Service Account

- Ensure the service account has "Vertex AI User" role
- Check that the project ID matches your GCP project
- Verify the service account JSON file is valid

### CSV File Not Found

The test requires `data/PL-067-REVENUE-ONLY.csv` to exist. Check that:
- The file exists at `pl_analyst/data/PL-067-REVENUE-ONLY.csv`
- The file has the correct format with period columns

## What Gets Tested

The test script validates:

1. **Data Loading**: CSV data is loaded correctly
2. **Data Validation**: Data cleaning and validation works
3. **Statistical Analysis**: 6 parallel analysis agents run successfully
4. **Report Synthesis**: Results are combined into executive summary
5. **Alert Scoring**: Alerts are extracted and scored
6. **Output Persistence**: Results are saved to JSON files

## Expected Output

When successful, you should see:

```
================================================================================
P&L ANALYST - TEST MODE (CSV DATA)
================================================================================

Cost Center: 067 (Revenue Accounts Only)
Analysis: 3-Level Drill-Down Framework
  - Level 1: High-level summary with baselines (YoY, MoM, 3MMA, 6MMA)
  - Level 2: Category analysis (top 3-5 drivers explaining 80%+ variance)
  - Level 3: GL drill-down with root cause classification

================================================================================
STARTING ANALYSIS...
================================================================================

[TestingDataAgent] P&L Data loaded:
  Total rows: XXX
  Unique accounts: XX
  Unique periods: XX

[Analysis agents running...]

================================================================================
ANALYSIS COMPLETE
================================================================================

Generated files:
  Analysis outputs: cost_center_067.json
  Alert payloads: alerts_payload_cc067.json
```

## Next Steps

After successful test:

1. Review generated files in `outputs/` directory
2. Check logs in `logs/` directory (if phase logging enabled)
3. Adjust analysis parameters in `config/agent_models.yaml` if needed
4. Run additional tests with different cost centers (requires CSV data)

## Need Help?

- Check `docs/QUICKSTART.md` for general setup
- Check `docs/START_HERE.md` for development guide
- Review `docs/AGENT_ARCHITECTURE_SUMMARY.md` for architecture details


