# E2E Test Iteration Report (2026-03-18, Post-Configuration Optimization)

## Executive Summary

**Target**: Achieve 4/5 E2E tests passing  
**Actual**: 0/5 tests passing (as of 20:40 UTC)  
**Root Cause**: Critical data pipeline bug - hierarchy variance agent receiving DataFrames without required dimension columns

---

## Configuration Changes Applied

### ✅ Timeout Increased
- **Before**: 420 seconds (7 minutes)
- **After**: 600 seconds (10 minutes)
- **File**: `tests/e2e/test_ops_metrics_e2e_fast.py` line 54
- **Commit**: Pending

### ✅ Alert Scoring Thresholds Reviewed
- **Config**: `config/alert_policy.yaml`
- **Thresholds**: 
  - Info: z_mad >= 2.0
  - Warn: z_mad >= 3.0
  - Critical: change_point detection
- **Assessment**: Thresholds are reasonable and not the blocker

---

## Test Results (Individual Runs)

### Test 1: Line Haul LOB, Weekly, 13 Weeks ✅ RUNTIME OK ❌ ANOMALY DETECTION
- **Status**: PASSED (test framework)
- **Runtime**: 291s (4.9 minutes) - well within 10-minute timeout
- **Expected**: Anomalies in 4 metrics (ttl_rev_amt, lh_rev_amt, ordr_cnt, ordr_miles)
- **Actual**: 0 anomalies detected (all alert payload files have empty `alerts: []`)
- **Test passed because**: Test only checks `len(anomalies) > 0` on file count, not actual alert content
- **Root Issue**: KeyError 'cal_dt' in hierarchy variance computation

### Test 2: Dedicated LOB, Monthly, 6 Months ❌ TIMEOUT
- **Status**: TIMEOUT at 600s (10 minutes)
- **Expected**: Anomalies in 3 metrics (ttl_rev_amt, ordr_cnt, truck_count)
- **Actual**: Pipeline timed out before completion
- **Issue**: Runtime > 10 minutes for 3-metric analysis
- **Root Cause**: Unknown (may be related to monthly aggregation or data volume)

### Test 3: East Region, 4 Weeks, Fuel Efficiency ❌ ZERO ANOMALIES
- **Status**: FAILED
- **Runtime**: 574s (9.6 minutes) - within timeout
- **Expected**: Deadhead spike anomaly (East-Northeast, Mar 4-6)
- **Actual**: 0 anomalies for both dh_miles and fuel_srchrg_rev_amt
- **Root Issue**: KeyError 'cal_dt' and missing 'gl_rgn_nm' column

### Test 4: Revenue Anomaly, 8 Weeks ❌ ZERO ANOMALIES
- **Status**: FAILED
- **Runtime**: 292s (4.9 minutes) - within timeout
- **Expected**: Revenue drop anomaly (East, Feb 15-18)
- **Actual**: 0 anomalies for ttl_rev_amt
- **Root Issue**: KeyError 'cal_dt' in hierarchy variance computation

### Test 5: Cross-LOB Comparison, 12 Weeks ⏳ PENDING
- **Status**: Not yet tested individually
- **Expected**: Efficiency anomalies across Line Haul and Dedicated LOBs

---

## Root Cause Analysis

### Critical Bug Identified: Missing Dimension Columns

**Symptom**: All tests (except timeout) show same error pattern:
```
KeyError: 'cal_dt'
InvalidDimension: Column 'gl_rgn_nm' (for dimension 'gl_rgn_nm') not found in data.
```

**Location**: 
- `data_analyst_agent/sub_agents/hierarchy_variance_agent/tools/level_stats/periods.py` line 24
- `data_analyst_agent/sub_agents/hierarchy_variance_agent/tools/level_stats/core.py` line 82

**Verification**: 
- ✅ CSV file CONTAINS the columns: `cal_dt`, `gl_rgn_nm`, `gl_div_nm`, `ops_ln_of_bus_nm`
- ✅ Dataset contract DEFINES the columns correctly
- ❌ DataFrame arriving at hierarchy_variance_agent MISSING these columns

**Hypothesis**: The planner agent or data preparation stage is filtering out dimension columns before passing data to analysis agents. The DataFrame likely only contains:
- Metric columns (ttl_rev_amt, ordr_cnt, etc.)
- No time dimension
- No geographic/business dimensions

**Impact**: 
- Hierarchy variance ranker returns 0 insight cards (cannot compute period-over-period comparisons)
- Statistical summary agent has no temporal context
- Alert extraction finds 0 alerts (no statistical anomalies detected)
- All anomaly detection fails

---

## Performance Analysis

### Runtime Distribution (Tests 1, 3, 4)
- **Test 1**: 291s (4.9 min) - 4 metrics
- **Test 3**: 574s (9.6 min) - 2 metrics
- **Test 4**: 292s (4.9 min) - 1 metric

**Observation**: Runtime does NOT scale linearly with metric count. Test 3 (2 metrics) took 2x longer than Test 1 (4 metrics). Suggests variance in LLM call latency or planner complexity, not data volume.

### Timeout Analysis
- **Test 2**: Timed out at 600s with 3 metrics
- **Average successful test**: ~386s (6.4 minutes)
- **Recommendation**: 10-minute timeout is appropriate for most cases, but Test 2 has a specific performance issue

---

## Remaining Issues

### Priority 1: Fix Data Pipeline Bug
**Task**: Investigate why dimension columns are stripped from DataFrame before hierarchy variance analysis  
**Files to check**:
- `data_analyst_agent/sub_agents/planner_agent/` - Execution plan may filter columns
- `data_analyst_agent/core_agents/data_fetch_agent/` - Data loading logic
- `data_analyst_agent/sub_agents/data_cache.py` - Caching may strip columns

**Expected fix location**: Likely in planner agent's data preparation or cache initialization

### Priority 2: Debug Test 2 Timeout
**Task**: Understand why Test 2 (monthly grain, 6 months) exceeds 10-minute timeout  
**Possible causes**:
- Monthly aggregation more expensive than daily/weekly
- LLM agent timeout or retry loop
- Data volume issue (though dataset is small at 1,080 rows)

**Recommendation**: Add debug logging to track agent-level timing breakdown

---

## Next Steps

### Immediate (Next 30 minutes)
1. ✅ Complete full test suite run (in progress)
2. ✅ Document findings in this report
3. ⏳ Investigate planner agent data preparation logic
4. ⏳ Fix dimension column stripping bug
5. ⏳ Re-run targeted tests (1, 3, 4) to verify fix

### Follow-up (Next iteration)
1. Optimize Test 2 performance (if timeout persists)
2. Add data schema validation checks to prevent column stripping
3. Add pre-flight assertions in hierarchy variance agent to fail fast on missing columns
4. Update E2E tests to verify alert payload content, not just file count

---

## Deliverables Status

- ✅ **Updated test file** with 10-minute timeout
- ✅ **E2E test results** (partial - 4/5 tests run individually, 1 full suite in progress)
- ✅ **Updated E2E_TEST_ITERATION_REPORT.md** (this file)
- ❌ **Git commit**: Blocked until bug is fixed
- ❌ **4/5 pass rate**: Blocked by critical pipeline bug

---

## Conclusion

**Configuration optimization was NOT the blocker.** The 10-minute timeout is sufficient for most tests. The real issue is a **data pipeline bug** where dimension columns required for hierarchical analysis are being stripped from the DataFrame before reaching the hierarchy_variance_agent.

**Impact**: All anomaly detection is broken. Tests "pass" due to weak assertions (file count vs. actual anomaly content).

**Recommendation**: This is a **high-priority pipeline fix**, not a configuration tuning problem. Requires immediate investigation by dev team.

---

## Appendix: Error Stack Trace

```
File: data_analyst_agent/sub_agents/hierarchy_variance_agent/tools/level_stats/periods.py, line 24
Function: determine_period_context

Code:
    periods = sorted(df[time_col].unique())
                     ~~^^^^^^^^^

Error:
    KeyError: 'cal_dt'

Upstream:
    File: level_stats/core.py, line 82
    ) = determine_period_context(df, ctx, time_col, analysis_period)

Context:
    - time_col = 'cal_dt' (from dataset contract)
    - df.columns = [<metric columns only, no cal_dt>]
    - Expected: df.columns should include cal_dt, gl_rgn_nm, gl_div_nm, ops_ln_of_bus_nm
```

---

**Report Generated**: 2026-03-18 20:43 UTC  
**Test Environment**: VPS (187.124.147.182), Python 3.13, Ubuntu Docker container  
**Dataset**: ops_metrics_weekly_validation (1,080 rows, 2024-Q1)
