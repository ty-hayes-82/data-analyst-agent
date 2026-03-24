# Scenario 1: Single Metric - Total Revenue (COMPLETE)

## Test Metadata
- **Metric:** ttl_rev_amt
- **Focus:** Trend analysis (implicit)
- **Filter:** None (all regions)
- **Scope:** Last 24 months (2024-03-17 to 2026-03-17)
- **Iterations:** 2 completed

---

## Iteration 1: Baseline (max_drill_depth Bug)

**Output:** `/data/data-analyst-agent/outputs/ops_metrics_weekly/global/all/20260317_212558/`
**Runtime:** 274s (4.6 minutes)
**Quality Score:** 5/10

### Critical Bug Discovered
**Issue:** max_drill_depth set to 0 instead of 3, preventing hierarchical drill-down
**Root Cause:** `len(hierarchy.children) = 0` because contract YAML uses `levels:` but HierarchyNode model expects `children:`
**Impact:** Analysis stopped at Level 0 (total), never drilled into regional divisions or business lines

### Brief Quality Analysis
**Strengths:**
- ✅ Concrete numbers ($1.48M, 29.77%, -$1.31M slope)
- ✅ Regional breakdown (East, West, Central)
- ✅ Statistical context (p-values, correlation r=0.993)
- ✅ Forward outlook with scenarios ($4.5M-$5.0M range)
- ✅ Anomaly detection (Corporate region)

**Weaknesses:**
- ❌ **Time period confusion** - Says "the day ending March 12" but shows "3-month trends"
- ❌ **Baseline unexplained** - "rolling 7-day average" mentioned without context
- ❌ **No drill-down** - Stopped at total level due to bug
- ❌ **Vague root causes** - Generic "volume fluctuations" without supporting evidence
- ⚠️ **Weak recommendations** - Generic "monitor" statements instead of specific actions
- ⚠️ **Statistical jargon** - p-value not explained for business users

---

## Iteration 2: With Hierarchy Fix

**Output:** `/data/data-analyst-agent/outputs/ops_metrics_weekly/global/all/20260317_213502/`
**Runtime:** 283s (4.7 minutes)
**Quality Score:** 6/10 (+1 improvement)

### Fix Applied
**File:** `data_analyst_agent/sub_agents/hierarchical_analysis_agent/initialization.py`
**Change:** Prioritize `analysis_ctx.max_drill_depth` over broken `len(hierarchy.children)`
**Result:** max_drill_depth now correctly set to 3

### Observed Behavior
```
[InitializeHierarchicalLoop] Starting hierarchical analysis at Level 0
  Metric: ttl_rev_amt
  Hierarchy: geographic
  Max Drill Depth: 3  ← FIXED! Was 0 in Iteration 1
```

**However:** Drill-down still stopped at Level 0 with reasoning:
> "No high-impact findings at level 0. Drill-down not warranted."

**Implication:** The fix worked structurally, but the drill-down decision logic chose not to drill due to no material variance at Level 0.

### Brief Quality Analysis
**Strengths:**
- ✅ Same concrete numbers as Iteration 1
- ✅ Slightly improved wording ("rolling 90-day average" vs "rolling 7-day average")
- ✅ Better dimension labeling ("gl_rgn_nm dimension")
- ✅ Clearer portfolio context ("53.8% of total share")

**Weaknesses:**
- ❌ **Still no drill-down** - Different reason (no material findings) but same result
- ❌ **Time period still confusing** - "the day ending" vs "3-month trend"
- ❌ **Baseline still unexplained** - Now says "rolling 90-day average" but still no context
- ❌ **Root causes still vague** - Still generic "volume-driven headwinds"
- ⚠️ **Forward outlook changed** - Now says "$3.2M-$3.5M" instead of "$4.5M-$5.0M" (inconsistent)

---

## Iteration Comparison

| Dimension | Iteration 1 | Iteration 2 | Change |
|-----------|------------|------------|--------|
| **Quality Score** | 5/10 | 6/10 | +1 |
| **max_drill_depth** | 0 (broken) | 3 (fixed) | ✅ Fixed |
| **Actual drill-down** | Level 0 only | Level 0 only | ⚠️ No change |
| **Baseline reference** | "rolling 7-day avg" | "rolling 90-day avg" | ⚠️ Inconsistent |
| **Forward outlook** | $4.5M-$5.0M | $3.2M-$3.5M | ⚠️ Different |
| **Dimension labeling** | Implicit | Explicit (gl_rgn_nm) | ✅ Improved |
| **Portfolio context** | By region | "53.8% share" | ✅ Better |
| **Runtime** | 274s | 283s | +9s (3% slower) |

---

## Key Learnings

### 1. **Hierarchy Loading Schema Mismatch**
**Problem:** Contract YAML uses `levels:` list, but HierarchyNode model expects `children:` list
**Result:** `len(hierarchy.children)` returns 0, breaking drill-down logic
**Fix Applied:** Prioritize explicit `max_drill_depth` from AnalysisContext
**Future Fix Needed:** Add validator to HierarchyNode that transforms `levels` → `children`

### 2. **Drill-Down Decision Logic is Conservative**
**Observation:** Even with max_drill_depth=3, the system chose not to drill because Level 0 had no "high-impact findings"
**Implication:** The system requires variance above materiality thresholds to trigger drill-down
**Question:** Should drill-down be automatic for hierarchical datasets, or should it remain variance-driven?

### 3. **Baseline Reference Inconsistency**
**Issue:** Iteration 1 said "rolling 7-day average", Iteration 2 said "rolling 90-day average"
**Root Cause:** Likely LLM variation in narrative synthesis, not a data change
**Fix Needed:** Standardize baseline references in prompt templates

### 4. **Time Period Ambiguity Persists**
**Issue:** Brief title says "for the day ending 2026-03-12" but body discusses "3-month trends"
**Root Cause:** Template confusion between single-period reports and trend analysis
**Fix Needed:** Clarify in template: "Analysis of trend ending [date]" vs "Analysis of period [date]"

### 5. **Forward Outlook Variance**
**Issue:** Iteration 1 projected $4.5M-$5.0M, Iteration 2 projected $3.2M-$3.5M
**Root Cause:** LLM-generated scenarios based on statistical summary, not deterministic
**Impact:** Users may be confused by different projections from same data
**Fix Needed:** Either remove LLM-generated scenarios or make them deterministic code-based

---

## Remaining Issues for Iteration 3

### High Priority
1. **Force drill-down for testing** - Override decision logic to test Level 1 and Level 2 analysis
2. **Fix time period wording** - Change "for the day ending" to "trend analysis ending"
3. **Standardize baseline reference** - Lock in "rolling 90-day average" in template
4. **Deterministic forward outlook** - Replace LLM scenarios with code-based projections

### Medium Priority
5. **Explain root causes with data** - When claiming "volume fluctuations", cite ordr_cnt or ordr_miles
6. **Improve recommendations** - Provide specific next steps, not generic "monitor"
7. **Simplify statistical language** - Add business-friendly explanations for p-values

### Low Priority (Future)
8. **Fix HierarchyNode schema** - Add `levels:` field support
9. **Component metric breakdown** - Auto-analyze lh_rev_amt, fuel_srchrg_rev_amt, acsrl_rev_amt when analyzing ttl_rev_amt

---

## Next Steps

**For Iteration 3:**
1. ✅ Hierarchy fix implemented
2. 🔧 Override drill-down decision to force Level 1 analysis
3. 🔧 Update brief template to clarify time period
4. 🔧 Lock baseline reference to "90-day rolling average"
5. 📊 Run pipeline and compare results

**Expected Improvement:**
- Target score: 8/10
- Must have: Actual Level 1 drill-down results
- Must have: Clearer time period context
- Nice to have: Data-driven root cause explanations

---

## Code Changes Made

### ✅ Fix #1: Prioritize analysis_ctx.max_drill_depth
**File:** `data_analyst_agent/sub_agents/hierarchical_analysis_agent/initialization.py`
**Lines:** 28-44
**Status:** Committed ✅

**Before:**
```python
max_depth = 5
if analysis_ctx and analysis_ctx.contract:
    if analysis_ctx.contract.hierarchies:
        hierarchy = analysis_ctx.contract.hierarchies[0]
        max_depth = len(hierarchy.children)  # ← Returns 0!
        hierarchy_name = hierarchy.name
    if getattr(analysis_ctx, "max_drill_depth", None):
        max_depth = min(max_depth, analysis_ctx.max_drill_depth)  # ← min(0, 3) = 0!
```

**After:**
```python
max_depth = 5
# Priority: analysis_ctx.max_drill_depth > hierarchy length > default (5)
if analysis_ctx:
    # Use explicit max_drill_depth from AnalysisContext if available
    if getattr(analysis_ctx, "max_drill_depth", None) is not None:
        max_depth = analysis_ctx.max_drill_depth  # ← Now uses 3!
    
    # Get hierarchy metadata
    if analysis_ctx.contract and analysis_ctx.contract.hierarchies:
        hierarchy = analysis_ctx.contract.hierarchies[0]
        hierarchy_name = hierarchy.name
        
        # Only use hierarchy length as a cap if it's non-zero and no explicit max_drill_depth was set
        if len(hierarchy.children) > 0 and getattr(analysis_ctx, "max_drill_depth", None) is None:
            max_depth = len(hierarchy.children)
```

---

## Session Complete
**Status:** Scenario 1 Iteration 1-2 complete, ready for Iteration 3 with additional fixes
**Time Invested:** ~10 minutes runtime + analysis
**Value Delivered:** Critical bug discovered and fixed, drill-down now structurally enabled
