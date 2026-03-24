# Performance Profile — Data Analyst Agent

Last profiled: 2026-03-12 21:49 UTC  
Dataset: trade_data (258K rows, 2 metrics: trade_value_usd, volume_units)  
Run ID: 20260312_214745

## Pipeline Timing (2 Metrics, 3-Level Hierarchy)

### Overall Pipeline
- **Total Duration:** ~90 seconds (both metrics in parallel)

### Per-Metric Breakdown

#### trade_value_usd
- **analysis_context_initializer:** 0.46s
- **planner_agent:** 0.00s (rule-based, no LLM)
- **statistical_insights_agent:** 2.57s
- **hierarchical_analysis_agent:** 2.76s (3 drill levels)
- **narrative_agent:** 15.08s ⚠️ (LLM call)
- **alert_scoring_coordinator:** 0.12s
- **report_synthesis_agent:** 20.16s ⚠️ (LLM call)
- **output_persistence_agent:** 0.34s

#### volume_units
- **analysis_context_initializer:** 0.46s
- **planner_agent:** 0.00s (rule-based, no LLM)
- **statistical_insights_agent:** 2.31s
- **hierarchical_analysis_agent:** 2.34s (1 drill level, stopped early)
- **narrative_agent:** 17.52s ⚠️ (LLM call)
- **alert_scoring_coordinator:** 0.21s
- **report_synthesis_agent:** 3.90s (fast-path, no LLM)
- **output_persistence_agent:** 0.49s

#### Cross-Metric
- **executive_brief_agent:** 65.90s 🔴 (SLOWEST — LLM call + scoped briefs)

## Bottlenecks

### 1. ExecutiveBriefAgent (65.90s)
- **What:** Cross-metric synthesis + scoped regional briefs (Midwest, Northeast, South)
- **Why Slow:** 
  - Generates 4 briefs total (1 network + 3 scoped)
  - Each brief requires Gemini LLM call with schema validation
  - Prompt includes full digest from all metrics
- **Optimization Opportunities:**
  - Reduce max scoped briefs (currently 3, env: EXECUTIVE_BRIEF_MAX_SCOPED_BRIEFS)
  - Tighten prompt size (currently ~14KB input cache)
  - Consider parallel scoped brief generation
  - Cache digest summaries between briefs

### 2. NarrativeAgent (~16-17s avg)
- **What:** Converts insight cards to natural language narrative
- **Why Slow:** LLM call to Gemini with full insight card payload
- **Optimization Opportunities:**
  - Reduce prompt size (check config/prompts/narrative_agent.md)
  - Pre-filter low-priority cards before LLM call
  - Consider fast-path for metrics with <5 cards

### 3. ReportSynthesisAgent (3.90s - 20.16s)
- **What:** Combines narrative + hierarchical + statistical results
- **Why Variable:** 
  - Fast-path (3.90s) when no hierarchical drill-down
  - Slow-path (20.16s) when full LLM synthesis required
- **Optimization Opportunities:**
  - Already has fast-path logic — working well
  - Ensure hierarchical payload detection is accurate

## Token Usage Estimates (Gemini)

### Per Metric
- **narrative_agent:** ~2-3K input tokens
- **report_synthesis_agent:** ~5-10K input tokens (full), ~2K (fast-path)

### Cross-Metric
- **executive_brief_agent:** ~10-15K input tokens per brief × 4 briefs = 40-60K tokens total

## Test Suite Performance

- **Total Tests:** 298 passed, 6 skipped
- **Duration:** 35.29s
- **Slowest Test:** 3.40s (test_end_to_end_bookshop_pipeline)
- **Test Coverage:** Unit (fast), Integration (moderate), E2E (slow)

## Recommendations

### Short-Term (Quick Wins)
1. Set `EXECUTIVE_BRIEF_MAX_SCOPED_BRIEFS=1` to reduce brief generation from 4→2 (saves ~30-40s)
2. Audit prompt size in config/prompts/executive_brief.md — remove redundant warnings

### Medium-Term (Engineering)
1. Parallelize scoped brief generation in ExecutiveBriefAgent
2. Add prompt caching for repeated sections (dataset context, section titles)
3. Pre-filter insight cards by materiality before passing to NarrativeAgent

### Long-Term (Architecture)
1. Consider incremental brief updates (only regenerate changed metrics)
2. Explore smaller/faster models for narrative_agent (fallback from Gemini Flash to lighter model)
3. Add distributed execution for multi-metric analysis (currently sequential ParallelAgent)

## Measurement Commands

```bash
# Full pipeline with timing
cd /data/data-analyst-agent
ACTIVE_DATASET=trade_data python -m data_analyst_agent --dataset trade_data --metrics "trade_value_usd,volume_units" 2>&1 | grep "TIMER"

# Extract timings from logs
cd /data/data-analyst-agent
grep "TIMER" outputs/trade_data/global/all/LATEST_RUN/logs/execution.log

# Test suite timing
python -m pytest tests/ --tb=short -q --durations=10
```

## Profiling Goals

### Current (Baseline)
- **Pipeline:** ~90s (2 metrics)
- **Executive Brief:** 65.90s

### Target (Optimized)
- **Pipeline:** <60s (2 metrics)
- **Executive Brief:** <30s

### Stretch (Aggressive)
- **Pipeline:** <30s (2 metrics)
- **Executive Brief:** <15s
