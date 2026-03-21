# Iterative E2E Testing - Ops Metrics Weekly TDSX

## Scenario 1: Single Metric - Total Revenue

### Iteration 1: Baseline

**Test Parameters:**
- Metric: ttl_rev_amt
- Focus: trend_analysis (implicit)
- Filter: None (all regions)
- Scope: Last 24 months (2024-03-17 to 2026-03-17)
- Runtime: ~274s (4.6 minutes)
- Output: `/data/data-analyst-agent/outputs/ops_metrics_weekly/global/all/20260317_212558/`

**Executive Brief Quality Score: 5/10**

---

### Strengths:
1. **Good concrete numbers** - Specific revenue figures ($1,479,888.93, $1,192,436.12), percentages (29.77%, 23.98%), and slopes (-$1.31M, -$1.02M)
2. **Regional breakdown** - Clear identification of East, West, and Central regions with their contributions
3. **Statistical context** - Mentions p-values (0.33), correlation coefficient (r=0.993), and z-scores
4. **Forward outlook** - Provides scenario planning with specific ranges ($4.5M-$5.0M, $5.5M baseline, $4.2M worst case)
5. **Anomaly detection** - Identifies Corporate region anomalies with dates and magnitudes

### Weaknesses:

#### 1. **Confusing Time Period Context** ❌
**Issue:** Brief says "for the day ending March 12, 2026" but shows "3-month trend declines" and "slope over last 3 months." This is contradictory - is it analyzing a single day or 3 months?

**Example from brief:**
> "East region revenue reached $1,479,888.93 on March 12, 2026, but continues a sharp 3-month downward trajectory with a slope of -$1.31M"

**Root cause:** The analysis period is unclear. The contract says `range_months: 24`, the date initializer set 2024-03-17 to 2026-03-17, but the brief focuses on "the day ending 2026-03-12". Is $1.31M a daily slope or total 3-month change?

#### 2. **Missing Context: What is "Baseline"?** ❌
**Issue:** Brief says "slope of -$1.31M compared to the rolling 7-day average" but never explains what the baseline comparison is or why it matters.

**Example from brief:**
> "compared to the rolling 7-day average, it shows a 3-month revenue slope of -$1.02M"

**Question:** Is this a daily rate? A cumulative change? Why is rolling 7-day average the right baseline?

#### 3. **Unclear Scope of Request** ⚠️
**Issue:** The test asked for "last 3 months" but the pipeline analyzed 24 months of data. The brief doesn't clarify what time range was actually analyzed.

**Gap:** Brief should state upfront: "Analysis period: 2024-03-17 to 2026-03-12 (24 months)" but instead says "the day ending March 12, 2026"

#### 4. **No Drill-Down Despite Available Hierarchy** ❌ **CRITICAL BUG**
**Issue:** Contract has `max_drill_depth: 3` and dimensions like `gl_rgn_nm`, `gl_div_nm`, `ops_ln_of_bus_nm`, but the analysis stopped at Level 0.

**Log evidence:**
```
[ConfigOverride] max_drill_depth=3 (from env)
...
[DrillDownDecisionFunction] Level 0: action=STOP — Reached max drill depth (0).
```

**Root cause:** In `initialization.py`, the code sets `max_depth = len(hierarchy.children)` which is 0 because the contract YAML uses `levels:` but the HierarchyNode model expects `children:`. When `min(0, 3)` is computed, it results in 0, blocking all drill-down.

**Impact:** HIGH - Prevents hierarchical analysis entirely, missing division and business line insights.

#### 5. **Vague Root Cause Explanations** ❌
**Issue:** All findings cite "volume fluctuations" or "macroeconomic drivers" without any supporting evidence or specific drivers.

**Example:**
> "High volatility in regional demand" - What specific metrics show this volatility? Order count? Miles? Fuel surcharge?

**Gap:** Contract has 8 different metrics available (lh_rev_amt, fuel_srchrg_rev_amt, acsrl_rev_amt, ordr_cnt, etc.) but the analysis doesn't break down which component metrics are driving the revenue changes.

#### 6. **Actionable Recommendations Missing** ⚠️
**Issue:** The "Recommended Actions" section has 5 items, but most are generic "review" or "monitor" statements without specific next steps.

**Example:**
> "monitor East trend over last 3 days (slope -$1.3M per day) as an early signal... Escalate if the trend persists 2 more days"

**Better:** "East region revenue dropped from $X to $Y in last 3 days. Investigate West division order count (down Z%) and fuel surcharge revenue (down W%). Contact regional sales manager for March booking pipeline."

#### 7. **Statistical Jargon Without Explanation** ⚠️
**Issue:** Brief mentions "p-value of 0.33 indicates this is an early-stage signal" but doesn't explain what that means for a business user.

**Better:** "p-value of 0.33 means there's a 33% chance this is random variation rather than a real trend - monitor for 2 more weeks before taking action"

---

### Code Issues Identified:

1. **❌ CRITICAL: Hierarchy Loading Bug - max_drill_depth = 0**
   - File: `data_analyst_agent/sub_agents/hierarchical_analysis_agent/initialization.py` (lines 28-41)
   - Issue: `len(hierarchy.children) = 0` because contract YAML uses `levels:` but model expects `children:`
   - Impact: Blocks ALL hierarchical drill-down
   - Fix: Prioritize `analysis_ctx.max_drill_depth` over broken `len(hierarchy.children)`

2. **Time Period Ambiguity**
   - File: `data_analyst_agent/sub_agents/executive_brief_agent.py`
   - Issue: Brief says "the day ending 2026-03-12" but analysis covers 24 months
   - Fix: Clarify in template whether we're analyzing a single day, a trend over time, or comparing periods

3. **Baseline Comparison Unclear**
   - File: `data_analyst_agent/sub_agents/statistical_insights_agent.py`
   - Issue: "rolling 7-day average" baseline is mentioned but not explained
   - Fix: Add baseline explanation to insight cards and brief template

4. **Missing Component Metric Breakdown**
   - File: `data_analyst_agent/sub_agents/statistical_insights_agent.py`
   - Issue: Revenue is a composite metric (line haul + fuel surcharge + accessorial) but components aren't analyzed
   - Fix: When analyzing additive metrics with components defined in contract, automatically include component variance analysis

---

### Fix #1 IMPLEMENTED: Prioritize analysis_ctx.max_drill_depth

**File:** `data_analyst_agent/sub_agents/hierarchical_analysis_agent/initialization.py`

**Change:**
```python
# OLD CODE (lines 28-41):
        start_level = 0
        max_depth = 5
        hierarchy_name = None

        if analysis_ctx and analysis_ctx.contract:
            if analysis_ctx.contract.hierarchies:
                hierarchy = analysis_ctx.contract.hierarchies[0]
                max_depth = len(hierarchy.children)  # ← THIS IS 0!
                hierarchy_name = hierarchy.name

            if getattr(analysis_ctx, "max_drill_depth", None):
                max_depth = min(max_depth, analysis_ctx.max_drill_depth)  # ← min(0, 3) = 0!

# NEW CODE:
        start_level = 0
        max_depth = 5
        hierarchy_name = None

        # Priority: analysis_ctx.max_drill_depth > hierarchy length > default (5)
        if analysis_ctx:
            # Use explicit max_drill_depth from AnalysisContext if available
            if getattr(analysis_ctx, "max_drill_depth", None) is not None:
                max_depth = analysis_ctx.max_drill_depth
            
            # Get hierarchy metadata
            if analysis_ctx.contract and analysis_ctx.contract.hierarchies:
                hierarchy = analysis_ctx.contract.hierarchies[0]
                hierarchy_name = hierarchy.name
                
                # Only use hierarchy length as a cap if it's non-zero and no explicit max_drill_depth was set
                if len(hierarchy.children) > 0 and getattr(analysis_ctx, "max_drill_depth", None) is None:
                    max_depth = len(hierarchy.children)
```

**Reason:** The contract specifies `max_drill_depth: 3` and the environment sets it to 3, but the broken `len(hierarchy.children) = 0` was overriding it. Now we respect the explicit max_drill_depth setting from AnalysisContext.

**Expected Impact:** Enable hierarchical drill-down to Level 1 (divisions) and Level 2 (business lines).

---

### Iteration 2: With Hierarchy Fix

**Running now...**

---

**Runtime:** ~274 seconds (4.6 minutes)
**Status:** ✅ Pipeline completed successfully
**Issues:** 7 weaknesses identified, Fix #1 implemented
