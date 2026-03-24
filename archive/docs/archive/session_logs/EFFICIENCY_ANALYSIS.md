# Executive Brief Performance Analysis
**Date:** 2026-03-12 19:05 UTC  
**Run:** outputs/trade_data/global/all/20260312_185705

## Timing Breakdown

### Full Pipeline (2 metrics: trade_value_usd, volume_units)
- **Total pipeline:** ~150s
- **report_synthesis_agent:** 19.41s (per metric)
- **executive_brief_agent:** 130.67s (cross-metric synthesis)

### Executive Brief Agent Breakdown (130.67s)
1. **Network brief generation:** ~20-30s
   - Single LLM call to Gemini
   - Digest: 4,117 characters
   - Output: 2.2KB markdown, 2.7KB JSON
   - Max retries: 3
   
2. **Scoped brief generation:** ~90-100s
   - 3 entity briefs (Midwest, Northeast, South)
   - Concurrency limit: 2 (semaphore)
   - Each brief: ~30s with retries
   - Max retries per scoped brief: 2
   - Output: 3 scoped markdown + JSON files

## Prompt Size Analysis
- **executive_brief.md:** 18,785 bytes (18.8KB)
  - Comprehensive instructions
  - JSON schema examples
  - Style guidelines
  - Section contract enforcement
  
- **report_synthesis.md:** 1,817 bytes (1.8KB)
  - Much more concise
  - Clear tool contract

## Optimization Opportunities

### 1. Increase Scoped Brief Concurrency ⚡
**Current:** `_scope_concurrency_limit() = 2`  
**Proposed:** `_scope_concurrency_limit() = 3`  
**Impact:** ~30s savings (all 3 briefs run in parallel vs 2+1 sequence)

**Rationale:**
- Max scoped briefs is capped at 3 by default
- Current semaphore of 2 means: Brief 1&2 run || Brief 3 waits
- Increasing to 3 means: All 3 run in parallel
- No risk of API throttling with just 3 concurrent requests

**Implementation:**
```python
# In agent.py ExecutiveBriefConfig
@staticmethod
def scope_concurrency_limit() -> int:
    return max(1, _parse_positive_int_env("EXECUTIVE_BRIEF_SCOPE_CONCURRENCY", 3))  # Changed from 2
```

### 2. Tighten Executive Brief Prompt 📝
**Current size:** 18.8KB  
**Opportunity:** Reduce by ~20% without quality loss

**Candidates for removal/consolidation:**
- Duplicate style guidelines (mentioned in multiple sections)
- Verbose JSON schema examples (schema itself is enforced programmatically)
- Redundant section title warnings (already validated in code)

**Estimated impact:** ~5-10% token reduction → ~2-4s per brief

### 3. Reduce Scoped Brief Retries (Optional) ⚙️
**Current:** max_scoped_retries = 2  
**Consideration:** Reduce to 1 for low-priority scoped briefs

**Trade-off:** Quality vs speed. Scoped briefs already use structured fallback gracefully.

## Recommendation

**Primary optimization:** Increase `EXECUTIVE_BRIEF_SCOPE_CONCURRENCY` from 2 to 3.
- **Implementation:** One-line env var default change
- **Impact:** ~30s reduction (130s → 100s for executive brief agent)
- **Risk:** None (3 concurrent Gemini requests is well within limits)
- **ROI:** High (23% speed improvement for zero cost)

**Secondary optimization:** Prompt tightening
- **Implementation:** Editorial pass on executive_brief.md
- **Impact:** ~2-4s per brief (7 LLM calls: 1 network + 3 scoped + retries)
- **Risk:** Low (preserve core instructions, remove redundancy)
- **ROI:** Medium (requires careful editing to maintain quality)

## Current Performance vs Baseline
- **Baseline mentioned in goals:** narrative_agent 17s, report_synthesis 36s
- **Current run:** report_synthesis 19.41s (already optimized from 36s!)
- **Executive brief:** 130.67s (new bottleneck identified)

## Action Items
1. ✅ Document findings (this file)
2. 🔍 Propose env var change for scope concurrency
3. 🔍 Create prompt optimization ticket for future iteration
4. ✅ Commit analysis to dev branch
