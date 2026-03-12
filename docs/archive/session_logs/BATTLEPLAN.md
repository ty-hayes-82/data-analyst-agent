# BATTLEPLAN — Data Analyst Agent

Date: 2026-03-09 (UTC)
Branch: dev

## 1) Remaining failures + root cause

### Current pytest status
- **All green:** `252 passed, 205 skipped` (full `tests/` suite)
- **E2E:** `10 passed, 10 skipped` (skips are expected due to missing `data/validation_data.csv` + A2A server)

### Last failure we fixed (so it doesn’t regress)
- `tests/unit/test_026_ratio_aggregation_robustness.py::test_statistical_summary_robust_ratio_detection`
  - **Root cause:** `compute_statistical_summary.py` imported `resolve_data_and_columns` as a *function* at import time. Tests patch `data_analyst_agent.sub_agents.data_cache.resolve_data_and_columns`, but that patch **does not affect** already-imported local function references.
  - **Fix:** pass `data_cache.resolve_data_and_columns` (module attribute) into `prepare_state(...)` so patching works.

## 2) Every file >200 lines that needs splitting (priority order)

Priority heuristic: (1) pipeline-critical / imported everywhere, (2) biggest files, (3) tools that are slow to reason about, (4) agents.

> **Target:** everything <200L.

### P0 — biggest + pipeline-critical
1. 796 `data_analyst_agent/sub_agents/report_synthesis_agent/tools/generate_markdown_report.py`
2. 763 `data_analyst_agent/sub_agents/hierarchical_analysis_agent/agent.py`
3. 605 `data_analyst_agent/sub_agents/statistical_insights_agent/tools/compute_cross_dimension_analysis.py`
4. 551 `data_analyst_agent/sub_agents/hierarchy_variance_agent/tools/compute_level_statistics.py`
5. 546 `data_analyst_agent/utils/phase_logger.py`
6. 509 `data_analyst_agent/sub_agents/report_synthesis_agent/agent.py`
7. 482 `data_analyst_agent/sub_agents/executive_brief_agent/agent.py`
8. 478 `data_analyst_agent/sub_agents/executive_brief_agent/scope_utils.py`
9. 452 `data_analyst_agent/sub_agents/data_cache.py`
10. 432 `data_analyst_agent/agent.py`

### P1 — large tools/infra
11. 426 `data_analyst_agent/sub_agents/executive_brief_agent/pdf_renderer.py`
12. 416 `data_analyst_agent/sub_agents/alert_scoring_agent/tools/contract_rate_tools.py`
13. 397 `data_analyst_agent/sub_agents/output_persistence_agent/agent.py`
14. 381 `data_analyst_agent/sub_agents/statistical_insights_agent/tools/compute_derived_metrics.py`
15. 377 `data_analyst_agent/sub_agents/hierarchy_variance_agent/tools/format_insight_cards.py`
16. 376 `data_analyst_agent/sub_agents/tableau_hyper_fetcher/fetcher.py`
17. 372 `data_analyst_agent/sub_agents/alert_scoring_agent/tools/extract_alerts_from_analysis.py`
18. 371 `data_analyst_agent/sub_agents/statistical_insights_agent/tools/compute_concentration_analysis.py`
19. 321 `data_analyst_agent/core_agents/loaders.py`

### P2 — still must split (complete list)
20. 313 `data_analyst_agent/sub_agents/statistical_insights_agent/tools/stat_summary/core_metrics.py`
21. 299 `data_analyst_agent/sub_agents/tableau_hyper_fetcher/hyper_connection.py`
22. 298 `data_analyst_agent/sub_agents/alert_scoring_agent/agent.py`
23. 295 `data_analyst_agent/sub_agents/statistical_insights_agent/tools/compute_outlier_impact.py`
24. 286 `data_analyst_agent/semantic/models.py`
25. 283 `data_analyst_agent/sub_agents/testing_data_agent/agent.py`
26. 278 `data_analyst_agent/sub_agents/tableau_hyper_fetcher/query_builder.py`
27. 265 `data_analyst_agent/semantic/profiler.py`
28. 263 `data_analyst_agent/config.py`
29. 260 `data_analyst_agent/sub_agents/alert_scoring_agent/tools/_llm_extract_alerts_from_text.py`
30. 257 `data_analyst_agent/sub_agents/statistical_insights_agent/tools/card_builder_modules/portfolio_cards.py`
31. 251 `data_analyst_agent/sub_agents/statistical_insights_agent/tools/card_builder_modules/variance_cards.py`
32. 242 `data_analyst_agent/sub_agents/statistical_insights_agent/tools/compute_variance_decomposition.py`
33. 242 `data_analyst_agent/sub_agents/executive_brief_agent/html_renderer.py`
34. 241 `data_analyst_agent/tools/validation_data_loader.py`
35. 238 `data_analyst_agent/sub_agents/alert_scoring_agent/tools/apply_suppression.py`
36. 234 `data_analyst_agent/semantic/tests/test_profiler.py`
37. 230 `data_analyst_agent/sub_agents/statistical_insights_agent/agent.py`
38. 230 `data_analyst_agent/__main__.py`
39. 225 `data_analyst_agent/sub_agents/statistical_insights_agent/tools/stat_summary/advanced_analysis.py`
40. 223 `data_analyst_agent/sub_agents/hierarchical_analysis_agent/hierarchy_ranker_wrapper.py`
41. 222 `data_analyst_agent/sub_agents/statistical_insights_agent/tools/compute_new_lost_same_store.py`
42. 222 `data_analyst_agent/root_agent/test_mode_agents.py`
43. 221 `data_analyst_agent/sub_agents/validation_csv_fetcher.py`
44. 220 `data_analyst_agent/sub_agents/alert_scoring_agent/tools/get_period_aggregates_by_dimension.py`
45. 219 `data_analyst_agent/tools/config_data_loader.py`
46. 218 `data_analyst_agent/sub_agents/statistical_insights_agent/tools/compute_cross_metric_correlation.py`
47. 210 `data_analyst_agent/sub_agents/statistical_insights_agent/tools/generate_insight_cards.py`
48. 209 `data_analyst_agent/sub_agents/statistical_insights_agent/tools/compute_lagged_correlation.py`
49. 206 `data_analyst_agent/sub_agents/hierarchy_variance_agent/agent.py`
50. 204 `data_analyst_agent/sub_agents/hierarchy_variance_agent/tools/compute_mix_shift_analysis.py`
51. 202 `data_analyst_agent/sub_agents/narrative_agent/agent.py`
52. 201 `data_analyst_agent/sub_agents/statistical_insights_agent/tools/compute_seasonal_decomposition.py`

## 3) Missing E2E tests (full pipeline coverage)

We have good coverage for **trade_data** validation datapoints and a basic **full workflow** smoke test, but we do **not** yet have a single E2E that asserts the full *trade* pipeline end-to-end with strong, deterministic assertions.

### Gaps to close
1. **Trade pipeline E2E:** Data loading → hierarchy variance → anomaly detection → seasonal patterns → report generation (single test).
2. **Hierarchy variance on trade_data:** we validate ranking math separately, but not the actual `HierarchyVarianceAgent` integration for trade.
3. **Report generation assertions on trade_data:** confirm the synthesized markdown includes:
   - Executive brief
   - Variance section
   - Anomalies section
   - Seasonality section
   - Recommended actions
4. **Negative-path E2E:** missing columns / empty dataset → structured error payload (no stacktrace) with stable keys.

## 4) Dev agent task list (fix failures first, then refactor)

1. **(Guardrail) Keep tests green:** run `./.venv/bin/python -m pytest tests/ -q` before/after each refactor chunk.
2. **Split report synthesis markdown generator (796L)** into modules (section builders + formatting utils). Keep public API stable.
3. **Split hierarchical_analysis_agent/agent.py (763L)** into:
   - orchestration
   - ranking
   - explanations
   - IO/state plumbing
4. **Split compute_cross_dimension_analysis (605L)** into focused files (pair selection, stats, formatting).
5. **Split compute_level_statistics (551L)** into: data prep, ratio handling, variance calcs, driver selection.
6. **Split phase_logger (546L)** (or re-home to `utils/logging/` + keep shim).
7. **Split data_cache (452L)** (cache storage vs resolve logic vs persistence). Preserve existing import paths with shims.
8. Continue down the >200L list until all are <200L.

## 5) Tester agent task list (expand E2E coverage)

1. Add `tests/e2e/test_trade_full_pipeline_e2e.py`:
   - Set `ACTIVE_DATASET=trade_data`
   - Run the *full pipeline* (same entrypoint used by `test_full_workflow.py`)
   - Assert:
     - hierarchy variance output present (non-empty drivers)
     - anomaly detection output present (at least one anomaly for fixture C)
     - seasonality output present and matches existing validation datapoint (amplitude)
     - report markdown contains required section headers
2. Add a **snapshot-style assertion**: parse the markdown and assert key sections + at least N bullet points (avoid brittle exact text).
3. Add an E2E for **error handling**: intentionally pass a broken fixture missing a required column and assert structured error.

## 6) Make iteration faster (what’s wasting time + shortcuts)

- **Biggest waste:** refactors that break import patching / implicit wiring. Shortcut: favor module imports (`import x`) over `from x import y` when tests patch attributes.
- **Run focused tests first:**
  - Unit: `./.venv/bin/python -m pytest tests/unit/test_026_ratio_aggregation_robustness.py -q`
  - Then full: `./.venv/bin/python -m pytest tests/ -q`
- **Cache heavy fixtures in E2E:** load trade fixture once (`@lru_cache`) and copy for mutation.
- **Prefer “shim files” during splits:** keep old import paths re-exporting new modules to avoid cascading breakage.
- **Parallelize work:** dev refactors monoliths while tester adds E2Es; keep PR-sized commits.
