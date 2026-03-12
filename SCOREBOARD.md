# Data Analyst Agent — Test Results Scoreboard

## Latest Run: 2026-03-12 21:55 UTC (Cron E2E Test)

### Test Suite Results
- **Total Tests**: 298 passed, 6 skipped, 1 warning
- **Duration**: 33.63s
- **Baseline**: 236 tests → **+62 tests** (26% growth)
- **E2E Tests**: 5/5 pass
- **Unit Tests**: 293/293 pass

### Pipeline Execution Results
- **Auto-extraction**: ⚠️ **INCOMPLETE** — Pipeline started successfully, auto-extracted 2 metrics from contract, but terminated during narrative generation (SIGTERM)
- **Single-metric mode**: ⚠️ **INCOMPLETE** — ENV var override recognized, pipeline started successfully, but terminated during execution (SIGTERM)
- **Output directories**: ✅ VERIFIED — Timestamped run dirs created (20260312_215647, 20260312_220000)
- **Directory structure**: ✅ VERIFIED — alerts/, debug/, logs/ subdirs created, metric JSON/MD files present for completed metrics
- **Full pipeline completion**: ❌ **REGRESSION** — Both runs terminated with SIGTERM ~2min after start, likely cron timeout

### Test Coverage by Category
- Contract loading: ✅ All pass
- Statistical insights: ✅ All pass
- Hierarchical analysis: ✅ All pass
- Alert scoring: ✅ All pass
- Report synthesis: ✅ All pass
- Data validation: ✅ All pass
- Integration tests: ✅ All pass

### Performance
- Fastest test: <0.01s
- Slowest test: 7.48s (e2e full pipeline)
- Average E2E duration: ~2s

### Critical Issues
1. **SIGTERM during pipeline execution** — Both multi-metric and single-metric runs terminated ~2min after start, before narrative generation completed. Likely **cron timeout** (180s limit).
2. **Narrative agent duration** — LLM call taking 15.26s for trade_value_usd narrative (from logs). Combined with data fetch + analysis, exceeds cron timeout.

### Next Actions
1. **Increase cron timeout to 5min** for E2E tests
2. Investigate narrative agent performance — 15s LLM call is slow
3. Add pipeline timeout guards with graceful shutdown
4. Consider splitting E2E test into: (a) test suite only, (b) pipeline E2E with longer timeout

---

## Historical Baseline (2026-03-10)
- Tests: 236 pass
- E2E: 5/5 pass
- Metrics analyzed: 2/2 complete end-to-end
