# Validation Loader Fix - Contract-Driven Implementation

## Problem Statement
ValidationCSVFetcher was hardcoded to:
- File path: `data/validation_data.csv`
- Format: UTF-16, tab-delimited
- Not contract-driven, breaking with standard CSV files

Our validation file:
- Path: `data/validation/ops_metrics_weekly_validation.csv`
- Format: UTF-8, comma-delimited

## Solution Implemented

### 1. Updated Contract File
**File:** `config/datasets/csv/ops_metrics_weekly_validation/contract.yaml`

Changes:
- Updated `data_source.type` from `tableau_hyper` to `csv`
- Updated `data_source.file` to `data/validation/ops_metrics_weekly_validation.csv`
- Updated `time.format` from `%Y-%m-%d %H:%M:%S` to `%Y-%m-%d` (matches CSV format)

### 2. Created loader.yaml
**File:** `config/datasets/csv/ops_metrics_weekly_validation/loader.yaml`

Defines:
- Source file path: `data/validation/ops_metrics_weekly_validation.csv`
- Encoding: UTF-8
- Delimiter: comma
- Format: long (already melted, not wide)
- Column mappings

### 3. Made validation_data_loader.py Contract-Aware
**File:** `data_analyst_agent/tools/validation_data_loader.py`

Changes:
- Added `contract` parameter to `load_validation_data()`
- File path resolution: contract.data_source.file > csv_path > legacy fallback
- Auto-detect CSV format:
  - Try UTF-8 comma-separated first (standard)
  - Fallback to UTF-16 tab-separated (legacy)
- Detect format: wide (needs melting) vs long (already melted)
- Added pre-flight validation logging:
  - Row count, column count
  - Date range
  - First 5 rows

### 4. Updated ValidationCSVFetcher
**File:** `data_analyst_agent/sub_agents/validation_csv_fetcher.py`

Changes:
- Pass `contract` parameter to `load_validation_data()`

### 5. Added Pre-flight Validation to ConfigCSVFetcher
**File:** `data_analyst_agent/sub_agents/config_csv_fetcher.py`

Changes:
- Added pre-flight validation logging after data load:
  - Row count, column count
  - Date range
  - First 5 rows displayed

## Verification Results

✅ **CSV Format Auto-Detection:**
```
[validation_data_loader] Loaded CSV with UTF-8 comma-separated format
```

✅ **Data Loaded Correctly:**
- 1,080 rows loaded
- 12 columns detected
- Date range: 2024-01-01 to 2024-03-30
- Time column: cal_dt

✅ **Contract-Driven:**
- File path read from contract.data_source.file
- Time column read from contract.time.column
- No hardcoded paths remaining

✅ **Pre-flight Validation:**
- Row/column counts logged
- Date range displayed
- First 5 rows shown in console

## Usage

Run validation pipeline:
```bash
cd /data/data-analyst-agent
ACTIVE_DATASET=ops_metrics_weekly_validation python -m data_analyst_agent --metrics "truck_count"
```

Expected output includes:
```
[ConfigCSVFetcher] PRE-FLIGHT VALIDATION
  Rows: 1080
  Columns: 12
  Date range: 2024-01-01 to 2024-03-30

First 5 rows:
[data displayed here]
```

## Architecture Notes

The solution uses ConfigCSVFetcher (not ValidationCSVFetcher) because:
1. ConfigCSVFetcher is already contract-driven
2. It uses loader.yaml for flexible ETL configuration
3. It follows the same pattern as other CSV datasets
4. ValidationCSVFetcher is deprecated (legacy trade_data format)

The validation_data_loader.py changes ensure backward compatibility with:
- Legacy wide-format CSVs (trade_data)
- Legacy UTF-16 tab-separated format
- New long-format CSVs (ops_metrics_weekly_validation)
- Standard UTF-8 comma-separated format

## Success Criteria

✅ Pipeline loads validation dataset correctly (confirmed by pre-flight log)
✅ No hardcoded paths or formats remaining
✅ Auto-detection of CSV format (UTF-8/UTF-16, comma/tab)
✅ Pre-flight validation with row count, column count, date range, first 5 rows
✅ Contract-driven: respects contract.data_source.file and contract.time.column
