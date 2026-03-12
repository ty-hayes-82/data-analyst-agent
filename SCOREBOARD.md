# Data Analyst Agent — Test Results Scoreboard

## Latest Run: 2026-03-12 21:12 UTC

### Test Suite Results
- **Total Tests**: 298 passed, 6 skipped, 1 warning
- **Duration**: 37.98s
- **Baseline**: 236 tests → **+62 tests** (26% growth)
- **E2E Tests**: 5/5 pass
- **Unit Tests**: 293/293 pass

### Pipeline Execution Results
- **Auto-extraction**: ✅ VERIFIED — Contract-driven metric selection works
- **Single-metric mode**: ✅ VERIFIED — ENV var override works
- **Output directories**: ✅ VERIFIED — Timestamped run dirs created
- **Full pipeline completion**: ⚠️ **REGRESSION** — Both runs terminated with SIGTERM

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
1. **SIGTERM during pipeline execution** — Both multi-metric and single-metric runs terminated before completion. Narrative generation appears to be the hang point.

### Next Actions
1. Investigate SIGTERM source (timeout? OOM? external kill?)
2. Add timeout guards to narrative agent
3. Test with shorter dataset or single dimension
4. Check system resource limits

---

## Historical Baseline (2026-03-10)
- Tests: 236 pass
- E2E: 5/5 pass
- Metrics analyzed: 2/2 complete end-to-end
