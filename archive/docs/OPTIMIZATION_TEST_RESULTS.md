# Optimization Test Results

## Test: Reduce EXECUTIVE_BRIEF_MAX_SCOPED_BRIEFS

**Date:** 2026-03-12 22:10 UTC  
**Change:** Set `EXECUTIVE_BRIEF_MAX_SCOPED_BRIEFS=1` (down from default 3)  
**Goal:** Reduce scoped briefs from 3 → 1, saving ~30-40s

---

## Results

### Baseline (No Optimization)
- **ExecutiveBriefAgent Duration:** 65.90s
- **Briefs Generated:** 4 (1 network + 3 scoped: Midwest, Northeast, South)
- **Validation Failures:** 0
- **Total Pipeline:** ~90s

### Optimized Run (EXECUTIVE_BRIEF_MAX_SCOPED_BRIEFS=1)
- **ExecutiveBriefAgent Duration:** 95.78s ⚠️ SLOWER
- **Briefs Generated:** 2 (1 network + 1 scoped: Midwest) ✅
- **Validation Failures:** 1 (retry on first attempt)
- **Total Pipeline:** ~95s

---

## Analysis

### ✅ What Worked
- Scoped brief reduction worked as designed: only 1 scoped brief generated (Midwest)
- Logs confirm: "Level 1 truncated to 1 entity(ies) due to EXECUTIVE_BRIEF_MAX_SCOPED_BRIEFS=1"
- Brief output reduced from 4 → 2 files ✅

### ⚠️ Unexpected Overhead
**Validation Retry:**
```
[BRIEF] Attempt 1/3 failed: Structured brief failed validation: 
Key Findings insight 'Systemic Uniform Growth Pattern' contains only 2 numeric values (minimum: 3). 
Include more specific amounts, percentages, baselines, or statistical values. 
Retrying in 5.0s...
```

**Impact:** Added ~20-30s overhead (retry delay + second LLM call)

### Root Cause
The validation rule requires **minimum 3 numeric values** per Key Finding insight. The insight "Systemic Uniform Growth Pattern" only included 2 values:
- Perfect correlation (r=1.0) ← 1 numeric value
- Week ending 2025-12-31 ← date (not counted)

This is a **prompt quality issue**, not an optimization failure.

---

## Corrected Performance Estimate

Assuming no validation retry:
- **Network brief:** ~20-25s (1 LLM call)
- **Scoped brief (1):** ~15-20s (1 LLM call)
- **Total Expected (Optimized):** ~35-45s

**Savings vs Baseline:** ~20-25s (from 65.90s → 40-45s estimated)

---

## Recommendations

### 1. Fix Validation Rule (Short-Term)
**Option A:** Relax numeric value requirement from 3 → 2
```python
# In validation logic
MIN_NUMERIC_VALUES = 2  # was 3
```

**Option B:** Improve prompt to consistently generate 3+ values
- Add examples with 3+ numeric values
- Add explicit instruction: "Include at least 3 quantitative values per insight"

### 2. Reduce Retry Delay (Quick Win)
Current: 5.0s delay between retries  
Proposed: 2.0s delay (validation is deterministic, no rate limit concern)

### 3. Re-Test After Fix
Once validation is stable (no retries), re-run optimization test to measure true impact.

---

## Expected Final Performance (After Fixes)

| Component | Baseline | Optimized | Savings |
|-----------|----------|-----------|---------|
| ExecutiveBriefAgent | 65.90s | ~40s | ~25s |
| **Total Pipeline** | **~90s** | **~65s** | **~25s** |

---

## Next Steps

1. ✅ Document finding (this file)
2. 🔲 Fix validation rule or improve prompt
3. 🔲 Re-test optimization with stable validation
4. 🔲 Measure actual savings
5. 🔲 Consider parallel scoped brief generation (additional ~10-15s savings)

---

## Files Modified in Test
- `outputs/trade_data/global/all/20260312_220557/` (test output)
- `outputs/trade_data/global/all/20260312_220557/brief*` (2 files vs baseline 4)
