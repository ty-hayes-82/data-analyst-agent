# P&L Analyst Data Sources

This directory contains validation and testing scripts for the P&L Analyst Agent's data sources.

## Overview

The P&L Analyst Agent relies on three primary data sources:
1. **Tableau P&L Data** (6.3M+ transactions) - Account research dataset
2. **Tableau Ops Metrics** (37M+ records) - Operational metrics dataset  
3. **Tableau Order Details** - Order-level dispatch and revenue data

All data is accessed via remote A2A agents running on `http://localhost:8001`.

## Data Source Architecture

```
P&L Analyst Agent
    ↓
Remote A2A Server (http://localhost:8001)
    ├── tableau_account_research_ds_agent
    ├── tableau_ops_metrics_ds_agent
    └── tableau_order_dispatch_revenue_ds_agent
         ↓
SQL Server Database
    ├── Tableau Hyper Extract: Account Research
    ├── Tableau Hyper Extract: Ops Metrics
    └── Tableau Hyper Extract: Order Dispatch Revenue
```

## Validation Scripts

### `test_tableau_connection.py`
Tests connectivity to all three A2A Tableau agents.

**Usage:**
```bash
python data/test_tableau_connection.py
```

**What it checks:**
- A2A server is running
- All three agents are responding
- Agent metadata is correct

### `test_database_connection.py`
Validates SQL Server database connectivity directly (bypassing A2A).

**Usage:**
```bash
python data/test_database_connection.py
```

**Requirements:**
- `database_config.yaml` must be configured
- ODBC Driver 17 for SQL Server installed

**What it checks:**
- Database credentials are valid
- Connection string is correct
- Basic query execution works

### `validate_data_sources.py`
End-to-end validation of all data sources with sample queries.

**Usage:**
```bash
python data/validate_data_sources.py
```

**What it tests:**
- Fetches sample P&L data (last 30 days)
- Fetches sample ops metrics
- Fetches sample order details
- Validates data schemas
- Reports row counts and date ranges

## Prerequisites

### A2A Server
The A2A server must be running before using the agent or validation scripts:

```bash
python scripts/start_a2a_server.py
```

This starts all three Tableau agents on port 8001.

### Database Configuration
Create `database_config.yaml` in the project root:

```yaml
driver: "{ODBC Driver 17 for SQL Server}"
server: "your-server.database.windows.net"
database: "your-database"
username: "your-username"
password: "your-password"
```

### Service Account
Place your Google Cloud service account JSON in the project root as `service-account.json`.

## Data Schemas

### P&L Data (Account Research)
- `GL_ACCOUNT`: General ledger account number
- `COST_CENTER`: Cost center identifier
- `AMOUNT`: Transaction amount
- `TRANSACTION_DATE`: Date of transaction
- `DESCRIPTION`: Transaction description

### Ops Metrics
- `COST_CENTER`: Cost center identifier
- `METRIC_DATE`: Date of metric
- `MILES`: Total miles
- `STOPS`: Total stops
- `PACKAGES`: Total packages delivered
- `HOURS`: Total labor hours

### Order Details
- `ORDER_ID`: Unique order identifier
- `COST_CENTER`: Cost center identifier
- `ORDER_DATE`: Date order was placed
- `REVENUE`: Revenue amount
- `SHIPPER_ID`: Shipper identifier
- `MILES`: Miles driven for order

## Troubleshooting

### A2A Server Not Running
```
Error: Connection refused to localhost:8001
```

**Solution:** Start the A2A server:
```bash
python scripts/start_a2a_server.py
```

### Database Connection Failed
```
Error: Login failed for user
```

**Solution:** Verify credentials in `database_config.yaml`

### Missing Service Account
```
Error: Could not load credentials
```

**Solution:** Ensure `service-account.json` exists in project root

### ODBC Driver Not Found
```
Error: [IM002] Data source name not found
```

**Solution:** Install ODBC Driver 17 for SQL Server:
- Windows: https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server
- Linux: https://learn.microsoft.com/en-us/sql/connect/odbc/linux-mac/installing-the-microsoft-odbc-driver-for-sql-server

## Data Refresh Schedule

The Tableau extracts are refreshed according to the following schedule:
- **P&L Data**: Daily at 2:00 AM UTC
- **Ops Metrics**: Daily at 3:00 AM UTC
- **Order Details**: Hourly

## Security Notes

⚠️ **Never commit these files:**
- `database_config.yaml` - Contains database credentials
- `service-account.json` - Contains GCP credentials
- Any output files with actual data

## Support

For data access issues:
1. Check A2A server logs: `logs/a2a_server.log`
2. Verify database connectivity
3. Review agent configuration in `config/`

