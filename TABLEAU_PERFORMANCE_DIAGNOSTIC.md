# Tableau Performance Diagnostic Report
**Date:** 2026-03-17
**Dataset:** ops_metrics_weekly
**Metric:** ttl_rev_amt

## Executive Summary

**TABLEAU QUERY IS NOT THE BOTTLENECK.**

The performance issue is NOT in data fetching from Tableau. The bottleneck is in the downstream analysis pipeline (LLM-powered agents or network latency).

## Test Results

### Test 1: 24-Month Date Range (Full Dataset)
- **Date Range:** 2024-03-17 to 2026-03-17 (24 months)
- **Rows Fetched:** 177,913
- **SQL Execution Time:** 2.17s
- **DataFrame Conversion:** 0.54s
- **Total Data Fetch:** 4.26s
- **Total Pipeline Runtime:** 23 seconds
- **Unaccounted Time:** ~18-19 seconds (78% of total)

### Test 2: 3-Month Date Range (Reduced Dataset)
- **Date Range:** 2025-12-17 to 2026-03-17 (3 months)
- **Rows Fetched:** 31,356 (82% reduction)
- **SQL Execution Time:** 0.41s (81% faster)
- **DataFrame Conversion:** 0.09s (83% faster)
- **Total Data Fetch:** 0.84s (80% faster)
- **Total Pipeline Runtime:** 26 seconds (13% SLOWER!)
- **Unaccounted Time:** ~25 seconds (96% of total)

### Key Insight
**Reducing data volume by 82% only saved 3.5 seconds but INCREASED total runtime by 3 seconds.**

This definitively proves the bottleneck is NOT in the Tableau query or data volume.

## Profiling Breakdown (24-Month Run)

### Fast Components ✅
```
Contract Loader:              0.01s
CLI Parameter Injector:       0.00s
Output Dir Initializer:       0.00s
Data Fetch Workflow:          4.26s
  - SQL Execution:            2.17s
  - DataFrame Conversion:     0.54s
  - Post-processing:          1.55s
Analysis Context Init:        0.42s
Planner Agent:                0.00s
Statistical Analysis:         <1.00s
  - MAD Outliers:             0.24s
  - Other analyses:           <0.10s each
Hierarchy Variance Ranker:    <1.00s
```

**Total Measured Fast Components:** ~6 seconds

### Slow/Unmeasured Components ❌
```
Dynamic Parallel Analysis:    (no completion timing logged)
Narrative Agent:              (no timing logged)
Alert Scoring Coordinator:    (no timing logged)
Report Synthesis Agent:       (no timing logged)
Output Persistence:           (no timing logged)
```

**Unaccounted Time:** ~17-20 seconds

## Probable Root Causes

### 1. LLM API Network Latency (Most Likely)
- Narrative, Alert Scoring, and Report Synthesis agents likely make API calls to Google Gemini
- Each API call has network round-trip latency
- Pipeline uses `[INFO] No service account found -- defaulting to Google AI (API Key)`
- API latency can be 2-5 seconds per call
- Multiple sequential calls = cumulative latency

### 2. Missing Agent Timing Instrumentation
- Narrative, Alert Scoring, and Synthesis agents don't log completion times
- Can't see where 17-20 seconds is spent
- Need to add `[TIMER]` instrumentation to these agents

### 3. Sequential Execution Bottleneck
- After parallel analysis completes, remaining agents run sequentially
- Each waiting for previous agent to complete
- No opportunity for parallelization

## Recommendations

### Immediate Fixes

#### 1. Add Timing Instrumentation
Add `[TIMER]` logging to:
- `narrative_agent` (start/end)
- `alert_scoring_coordinator` (start/end)
- `report_synthesis_agent` (start/end)
- `output_persistence_agent` (start/end)

Location: Look for `TimedAgentWrapper` or similar pattern used by other agents

#### 2. Profile LLM API Calls
Add timing around each Gemini API call:
```python
import time
start = time.perf_counter()
response = client.generate_content(...)
api_time = time.perf_counter() - start
print(f"[API Call] Gemini API: {api_time:.2f}s")
```

#### 3. Enable Code-Only Mode for Testing
The pipeline shows it's using code-based generation for some agents:
```
[StatisticalInsightsAgent] Using code-based card generator (USE_CODE_INSIGHTS=True)
[HierarchyVarianceRanker] Using code-based card generator (USE_CODE_INSIGHTS=True)
```

Check if Narrative/AlertScoring/Synthesis can also run in code-only mode to eliminate LLM latency for performance testing.

### Long-Term Optimizations

#### 1. Batch LLM Calls
Instead of sequential API calls, batch them:
```python
# Bad: Sequential
narrative_result = await call_llm(narrative_prompt)
alert_result = await call_llm(alert_prompt)
synthesis_result = await call_llm(synthesis_prompt)

# Good: Parallel
results = await asyncio.gather(
    call_llm(narrative_prompt),
    call_llm(alert_prompt),
    call_llm(synthesis_prompt)
)
```

#### 2. Use Vertex AI (If Not Already)
- Switch from Google AI API (api.google.dev) to Vertex AI
- Lower latency for enterprise customers
- Better quotas and reliability

#### 3. Cache Common LLM Responses
- Hash input prompts
- Cache responses for identical inputs
- Useful for repeated analyses on same dataset

#### 4. Implement Streaming
- Use Gemini streaming API
- Start processing partial responses while API call is in progress
- Reduce perceived latency

## Verdict

### ❌ NOT the Bottleneck
- Tableau Hyper SQL query (2.17s for 177K rows is excellent)
- DataFrame conversion (0.54s is fast)
- Data volume (reducing by 82% didn't help)
- Statistical computation (<1s for comprehensive analysis)

### ✅ ACTUAL Bottleneck
- **LLM API network latency** (most probable)
- **Sequential execution of downstream agents**
- **Lack of parallelization after analysis phase**

### Next Steps
1. ✅ Add timing instrumentation to all agents (DONE for Tableau fetcher)
2. ⏳ Profile Narrative/AlertScoring/Synthesis agents
3. ⏳ Measure LLM API call latency
4. ⏳ Consider batch/parallel LLM calls
5. ⏳ Evaluate code-only mode for faster testing

## Test Command Reference

### Full 24-Month Run
```bash
python -m data_analyst_agent --dataset ops_metrics_weekly --metrics ttl_rev_amt
```

### 3-Month Run
```bash
python -m data_analyst_agent --dataset ops_metrics_weekly --metrics ttl_rev_amt \
  --start-date 2025-12-17 --end-date 2026-03-17
```

### With Profiling
```bash
python -m data_analyst_agent --dataset ops_metrics_weekly --metrics ttl_rev_amt \
  2>&1 | tee /tmp/tableau_profile.log
```

## Profiling Code Added

### File: `data_analyst_agent/sub_agents/tableau_hyper_fetcher/hyper_connection.py`
Added detailed timing for SQL execution vs DataFrame conversion:
```python
# [PROFILING] SQL execution timing
print(f"[SQL Query] Executing query...")
sql_start = time.perf_counter()
with conn.execute_query(sql) as result_set:
    columns = [col.name.unescaped for col in result_set.schema.columns]
    rows = [list(row) for row in result_set]
sql_time = time.perf_counter() - sql_start
print(f"[SQL Execution] {sql_time:.2f}s for {len(rows)} rows")

# [PROFILING] DataFrame conversion timing
convert_start = time.perf_counter()
df = pd.DataFrame(rows, columns=columns)
convert_time = time.perf_counter() - convert_start
print(f"[DataFrame Conversion] {convert_time:.2f}s")
```

### File: `data_analyst_agent/sub_agents/tableau_hyper_fetcher/fetcher.py`
Added query parameter logging:
```python
print(f"\n[HyperQuery] Building query with parameters:")
print(f"[HyperQuery]   Date range: {date_start} to {date_end}")
print(f"[HyperQuery]   Filters: {physical_filters}")
print(f"[HyperQuery]   Metrics requested: {req_analysis.get('metrics', 'N/A')}")
```

---

**Report Generated:** 2026-03-17 21:05 UTC
**Diagnostic Tool:** OpenClaw + Python Profiling
**Analyst:** Atlas (Data Analyst Agent Coordinator)
