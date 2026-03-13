# Pipeline Profiling Guide

## Current Performance Baseline (as of 2026-03-13)

Based on user reports:
- **narrative_agent**: ~17s (LLM-based narrative generation)
- **report_synthesis_agent**: ~36s (LLM-based report synthesis)

These are the two slowest agents in the pipeline.

## Running the Profiler

```bash
# Profile full pipeline
./scripts/profile_pipeline.sh trade_data "trade_value_usd,volume_units"

# Output saved to /tmp/pipeline_profile.log
```

## Optimization Strategies

### 1. Prompt Length Reduction
**Target**: narrative_agent, report_synthesis_agent

**Actions**:
- [ ] Measure current prompt token counts
- [ ] Remove redundant context from system instructions
- [ ] Move static reference content to external docs (load on-demand)
- [ ] Use pointer-based context (reference digest line numbers instead of full content)

**Expected impact**: 20-30% reduction in LLM latency

### 2. Token Usage Analysis
**Target**: All LLM agents

**Actions**:
- [ ] Log input/output token counts for each LLM call
- [ ] Identify verbose prompts (>4K tokens)
- [ ] Evaluate if shorter prompts maintain quality (A/B test)

**Tools**:
```python
# Add to LlmAgent config
generate_content_config=types.GenerateContentConfig(
    temperature=0.2,
    max_output_tokens=2000,  # Current setting
    # Add response_logprobs=True to track token usage
)
```

### 3. Parallel Execution Review
**Target**: narrative_agent, statistical_insights_agent

**Current state**: 
- HierarchyVarianceAgent, StatisticalInsightsAgent, SeasonalBaselineAgent run in parallel (DynamicParallelAnalysisAgent)
- narrative_agent runs sequentially after parallel block

**Potential optimization**:
- [ ] Evaluate if narrative_agent can start with partial insights (stream-based approach)
- [ ] Check if report_synthesis can begin before all narratives complete

### 4. Caching Intermediate Results
**Target**: Repeated LLM calls with similar context

**Actions**:
- [ ] Identify redundant digest content across metrics
- [ ] Cache common analysis patterns (e.g., seasonality detection)
- [ ] Implement prompt prefix caching (if Gemini API supports)

### 5. Model Selection
**Target**: narrative_agent, report_synthesis_agent

**Current models**: Check config/model_config.yaml

**Actions**:
- [ ] Test if gemini-2.5-flash maintains quality (faster, cheaper)
- [ ] Evaluate gemini-2.0-flash for non-critical synthesis steps
- [ ] Benchmark latency vs quality tradeoff

## Measurement Process

1. **Baseline run** (before optimization):
   ```bash
   ./scripts/profile_pipeline.sh > baseline_timing.txt
   ```

2. **Apply optimization**

3. **Profile again**:
   ```bash
   ./scripts/profile_pipeline.sh > optimized_timing.txt
   ```

4. **Compare**:
   ```bash
   diff baseline_timing.txt optimized_timing.txt
   ```

5. **Quality check**:
   - Run E2E validation tests
   - Compare executive brief output quality
   - Verify numeric density and insight depth

## Next Steps

Priority order (highest impact first):

1. **Prompt audit** (narrative_agent, report_synthesis_agent)
   - Remove redundant instructions
   - Consolidate context blocks
   - Target: <3K tokens per prompt

2. **Token usage logging**
   - Add instrumentation to track actual token counts
   - Identify outliers (>10K token prompts)

3. **Parallel execution**
   - Evaluate if report_synthesis can overlap with narrative generation
   - Consider streaming partial results

4. **Model downgrade testing**
   - Test gemini-2.5-flash for synthesis (vs current model)
   - Measure latency gain vs quality loss

## Success Metrics

- [ ] narrative_agent: <12s (30% reduction from 17s)
- [ ] report_synthesis_agent: <25s (30% reduction from 36s)
- [ ] Overall pipeline: <90s end-to-end (target for interactive use)
- [ ] Quality maintained: E2E tests pass, numeric density ≥15 values per brief
