# Revenue Sign Flip Update

## Overview
Updated the Data Validation Agent to automatically flip revenue signs for proper P&L presentation.

## Changes Made

### 1. New Tool: `flip_revenue_signs.py`
Created a new tool that identifies revenue accounts and flips their signs:

**Revenue Account Identification:**
- Account numbers starting with "3" (e.g., 3100-00, 3115-00, 3200-00)
- Accounts with `level_1 = "Total Operating Revenue"`
- Accounts with `canonical_category = "Revenue"`

**Functionality:**
- Multiplies revenue account amounts by -1
- Adds `sign_flipped` column to track which records were modified
- Logs the count of flipped records for transparency
- Returns CSV data with flipped signs

### 2. Updated `agent.py`
- Added `flip_revenue_signs` to the list of available tools
- Imported the new tool from the tools module

### 3. Updated `prompt.py`
- Modified **PRODUCTION MODE WORKFLOW** to include revenue sign flipping:
  1. Check session state for pl_data_json
  2. Call reshape_and_validate
  3. Call json_to_csv
  4. **Call flip_revenue_signs (NEW - REQUIRED)**
  5. Call join_chart_metadata
  6. Output final JSON

- Added tool description: "REQUIRED - Flips signs for revenue accounts (3xxx accounts) for proper P&L presentation"

### 4. Updated `load_from_global_cache.py`
- Integrated automatic revenue sign flipping in TEST MODE
- Imports `_is_revenue_account` helper function
- Flips revenue signs before returning JSON
- Adds quality flags:
  - `revenue_signs_flipped: True`
  - `records_sign_flipped: <count>`

### 5. Fixed Missing Helper Functions
Added missing helper functions to existing tools:

**`reshape_and_validate.py`:**
- `_reshape_row()` - Reshapes wide-format rows to time series
- `_filter_invalid_periods()` - Filters periods with month > 12 or < 1
- `_validate_series()` - Validates for gaps and back-dated postings
- Added missing imports: `Dict, List, Tuple, datetime`

**`load_and_validate_from_cache.py`:**
- `_validate_series()` - Validates time series data
- Added missing imports: `pandas, datetime, pathlib`
- Added HAS_PANDAS flag and cache path constants

## Workflow Impact

### TEST MODE (using testing_data_agent)
```
load_from_global_cache() 
  ↓
Revenue signs automatically flipped
  ↓
Complete JSON with time_series + quality_flags
```

### PRODUCTION MODE (using tableau agents)
```
reshape_and_validate() 
  ↓
json_to_csv()
  ↓
flip_revenue_signs() ← NEW REQUIRED STEP
  ↓
join_chart_metadata()
  ↓
Final JSON output
```

## Revenue Account Examples
Accounts that will have signs flipped:
- 3100-00: Operating Revenue
- 3100-01: Operating Revenue - Singles
- 3100-02: Operating Revenue - Mentors
- 3115-00: Load/Unload
- 3116-00: Tolls Accessorial Revenue
- 3120-00: Stop-Offs
- 3130-00: Trailer Detention Revenue
- 3131-00: Power Detention Revenue
- 3135-xx: Various Accessorial Revenue accounts
- 3200-xx: Fuel Surcharge Revenue

## Quality Flags
The updated agent now includes revenue sign flip tracking in quality flags:

```json
{
  "quality_flags": {
    "revenue_signs_flipped": true,
    "records_sign_flipped": 45,
    "total_records": 150,
    ...
  }
}
```

## Backwards Compatibility
- Existing workflows continue to function
- Revenue sign flipping is now automatic in both TEST and PRODUCTION modes
- No changes required to calling code
- Data structure remains the same (adds optional `sign_flipped` column)

## Testing Recommendations
1. Test with revenue-heavy cost centers (verify positive revenues show correctly)
2. Test with expense-heavy cost centers (verify no changes to expense signs)
3. Verify quality flags show correct counts
4. Check both TEST MODE and PRODUCTION MODE workflows
5. Confirm downstream agents handle data correctly

## Notes
- Revenue accounts in GL systems are often stored as negative values
- For P&L presentation, revenue should display as positive
- This update ensures consistent, correct revenue sign presentation
- The `sign_flipped` column provides audit trail of transformations

