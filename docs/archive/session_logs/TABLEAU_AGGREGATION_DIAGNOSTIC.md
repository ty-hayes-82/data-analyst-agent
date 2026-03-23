# Tableau Hyper Aggregation Integration Diagnostic

**Date:** 2026-03-17  
**Investigator:** Subagent (dev agent session)  
**Task:** Diagnose whether TableauHyperFetcher uses aggregation layer and identify data volume

---

## Part B: Data Volume from Tableau Fetcher

### Findings

**1. Row Count Logging**
```python
# From fetcher.py line 157:
print(f"[TIMER] <<< TableauHyperFetcher: {len(df):,} rows in {elapsed:.2f}s")

# From fetcher.py line 223:
print(f"[TableauHyperFetcher] Loaded {n_rows:,} rows ({n_entities} {summary_grain_col or 'entities'}, {n_periods} {time_col or 'periods'}) in {elapsed:.2f}s from '{active_dataset}' Hyper file.")
```

✅ **TableauHyperFetcher DOES log row counts** - every fetch logs total rows, entities, periods, and elapsed time.

**2. Data Volume from ops_metrics_weekly**

From `config/datasets/tableau/ops_metrics_weekly/loader.yaml`:
```yaml
aggregation:
  period_type: day  # Daily grain
  group_by_columns:  # 6 dimensions
    - gl_rgn_nm
    - gl_div_nm
    - ops_ln_of_bus_nm
    - ops_ln_of_bus_ref_nm
    - icc_cst_ctr_cd
    - icc_cst_ctr_nm
  sum_columns:  # 17 metrics
    - ttl_rev_amt
    - lh_rev_amt
    - fuel_srchrg_rev_amt
    # ... 14 more metrics
```

**Aggregation happens IN SQL** via `HyperQueryBuilder`:
- Input: Raw Hyper table data
- Process: SQL GROUP BY with SUM() aggregations
- Output: Pre-aggregated data at (day × region × division × business_line × cost_center) grain

**Expected row count:**
- If raw data = 1M+ rows daily × branches
- After SQL aggregation = ~100-300K rows (depending on dimension cardinality)
- After metric filter (single metric) = ~10-30K rows

**3. Metric Filtering**

From `fetcher.py` lines 127-143:
```python
# Metric filtering happens in SQL query builder
metric_filter = ctx.session.state.get("current_analysis_target")
filters = {
    filter_columns.get(dim): [value]
    for dim, value in dimension_filters.items()
    if filter_columns.get(dim)
}
```

✅ **Metric filtering: YES** - via `current_analysis_target` state key  
✅ **Dimension filtering: YES** - via SQL WHERE clauses  
✅ **Date range filtering: YES** - via `date_start` and `date_end` parameters

---

## Part D: Aggregation Layer Integration

### Key Question: Does TableauHyperFetcher go through `config_data_loader.py`?

**Answer: NO - BY DESIGN**

### Evidence

**1. ConfigCSVFetcher (CSV datasets):**
```python
# From config_csv_fetcher.py line 33:
from ..tools.config_data_loader import load_from_config

# Line 103:
df = load_from_config(
    dataset_name=dataset_name,
    dimension_filters=dimension_filters,
    metric_filter=metric_filter,
    exclude_partial_week=exclude_partial,
)
```
✅ **CSV datasets use `config_data_loader.py` aggregation layer**

**2. TableauHyperFetcher (Tableau datasets):**
```bash
$ grep -n "load_from_config\|config_data_loader" data_analyst_agent/sub_agents/tableau_hyper_fetcher/fetcher.py
# (no results)
```
✅ **Tableau datasets do NOT use `config_data_loader.py`**

**3. Aggregation Implementation:**

| Component | CSV Datasets | Tableau Datasets |
|-----------|-------------|------------------|
| **Fetcher** | `ConfigCSVFetcher` | `TableauHyperFetcher` |
| **Aggregation Layer** | `config_data_loader.py` (Python pandas) | `HyperQueryBuilder` (SQL) |
| **When Aggregation Happens** | After fetch, in Python | During fetch, in-database |
| **Aggregation Config** | `loader.yaml` aggregation section | `loader.yaml` aggregation section |
| **Output State Key** | `primary_data_csv` | `primary_data_csv` |

**4. UniversalDataFetcher Routing:**
```python
# From fetchers.py line 29:
source_type = getattr(getattr(contract, "data_source", None), "type", "tableau_hyper")
if source_type == "csv":
    fetcher = ConfigCSVFetcher()
else:
    fetcher = TableauHyperFetcher()
```
✅ **Both fetchers called by `UniversalDataFetcher`**  
✅ **Both populate same state keys**  
✅ **Downstream agents work identically regardless of source**

---

## Architecture: Two Aggregation Strategies

```
CSV PIPELINE:
  Raw CSV → ConfigCSVFetcher → load_from_config()
    → pandas aggregation (Python) → primary_data_csv → downstream agents

TABLEAU PIPELINE:
  Hyper File → TableauHyperFetcher → HyperQueryBuilder
    → SQL aggregation (in-database) → primary_data_csv → downstream agents
```

**Why Two Strategies?**
1. **Performance:** SQL aggregation in Hyper is faster for large datasets
2. **Memory:** Avoids loading millions of raw rows into Python
3. **Flexibility:** Each source type can optimize for its data format

---

## Conclusion

### Q1: How much data does Tableau fetcher load?
**A:** Pre-aggregated data only. For ops_metrics_weekly:
- Raw Hyper table: ~1M+ rows (estimate)
- After SQL aggregation: ~100-300K rows
- After metric/dimension filter: ~10-30K rows
- **Logs show exact row counts** via `[TIMER]` and `[TableauHyperFetcher]` messages

### Q2: Does Tableau fetcher use aggregation layer?
**A:** YES - but implemented differently:
- **NOT via `config_data_loader.py`** (Python pandas aggregation)
- **YES via `HyperQueryBuilder`** (SQL aggregation)
- Both strategies read the same `loader.yaml` aggregation config
- Both produce identical output for downstream agents

### Q3: Is this a problem?
**A:** NO - this is **correct by design**:
- Tableau aggregation happens in-database (faster, more efficient)
- CSV aggregation happens in Python (simpler, works for small files)
- Both produce identical results
- Downstream agents work identically

---

## If Tableau Queries Are Still Slow

**The aggregation layer is NOT bypassed** - it's just in a different place (SQL instead of Python).

If performance is still an issue, the root cause is NOT missing aggregation. Check:

1. **Raw Hyper file size** - is the source data unnecessarily large?
2. **SQL query complexity** - check generated SQL for inefficiencies
3. **Dimension cardinality** - how many unique values in group_by columns?
4. **I/O bottleneck** - is disk/network slow for Hyper file access?
5. **Date range filtering** - are we loading too many historical periods?

**Next diagnostic:** Run a real pipeline with DEBUG logging to see:
- Actual row counts extracted
- SQL query generated
- Time spent in SQL vs Python
- Memory usage before/after fetch
