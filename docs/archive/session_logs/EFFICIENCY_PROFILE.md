# Efficiency Profile - March 12, 2026

## Baseline Performance (trade_data, 2 metrics)
- **Total pipeline**: ~131s
- **report_synthesis_agent**: 17.29s (trade_value_usd), 6.25s (volume_units fast-path)
- **executive_brief_agent**: 130.74s total
  - Network brief: ~30-40s
  - 2 scoped briefs: ~40-50s each
  - 1 failed brief (Midwest): 10s (2 retry attempts)

## Bottleneck Analysis
1. **Executive Brief Agent (130s)**
   - Primary driver: LLM generation time (Gemini 2.5 Flash)
   - Scoped briefs run in parallel (semaphore=2) but still sequential for LLM calls
   - Retry logic adds 5s delay per attempt
   - Network brief: 4,117 char digest → ~30s LLM time
   - Scoped briefs: smaller digests but same model overhead

2. **Report Synthesis Agent (6-17s)**
   - Fast-path (6s): Rule-based execution plans bypass LLM
   - Full LLM path (17s): Pre-summarization + narrative generation
   - Gemini 503 errors during testing (high demand)

## Optimization Opportunities
1. **Executive Brief**
   - ✅ Reduced scoped brief validation from 3 to 2 numeric values (fewer retries)
   - Potential: Cache contract metadata block (currently regenerated per brief)
   - Potential: Reduce max_scoped_briefs from 3 to 2 (save ~40s per run)
   - Potential: Use lower-tier model for scoped briefs (Gemini 1.5 Flash vs 2.5 Flash)

2. **Report Synthesis**
   - ✅ Fast-path already implemented for rule-based plans
   - Potential: Pre-summarization could use even smaller model for compression

3. **Narrative Agent** (not directly measured in this run)
   - Runs within target_analysis_pipeline per metric
   - Historical timing: ~17s per metric (from user notes)

## Recommended Changes
1. **IMMEDIATE** (already done): Relax scoped brief validation to reduce retries
2. **LOW-HANGING**: Set EXECUTIVE_BRIEF_MAX_SCOPED_BRIEFS=2 to save ~40s
3. **FUTURE**: Implement model tiering (Flash 2.5 for network, Flash 1.5 for scoped)
4. **FUTURE**: Cache contract metadata blocks across briefs

## Contract-Driven Status
- ✅ Core pipeline is contract-driven (no hardcoded metrics/dimensions)
- ✅ Executive brief uses contract metadata for all references
- ⚠️ Minor hardcode in validation_data_loader.py (Region/Terminal - dataset-specific)
- ⚠️ Minor hardcode in ratio_metrics.py ("terminal" check - only activates when column exists)

Both hardcodes are validation-data-specific and don't affect general pipeline.
