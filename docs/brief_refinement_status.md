# CEO Brief Refinement — Status Update
**Date:** 2026-03-27
**Branch:** `refactor/deterministic-metric-desc`
**Dataset:** Ops Metrics DS (Tableau), Line Haul, Week ending 3/14/2026

---

## BQS Score Progression

| Phase | T0 (Data Accuracy) | T1 (Structure) | T2 (LLM Critic) | BQS Total | Key Change |
|---|---|---|---|---|---|
| Starting point | 1.0-1.8 / 15 | 37-40 / 40 | 44-46 / 45 | 81-83 | Baseline with CSV datasets |
| + Ground truth scoring | 2.8 | 40 | 46 | 88.8 | Added T0 tier to evaluate.py |
| + Network totals in digest | 3.6 | 40 | 46 | 89.6 | Prepended KEY METRICS to digest |
| + KPI signals in Pass 0 | 7.3 | 40 | 46 | 93.3 | Derived KPIs as first-class signal cards |
| + KPI re-injection after Pass 1 | 7.8 | 40 | 46 | 92.8 | Bypass Flash Lite dropping KPIs |
| + Deterministic metric_description | 9.5 | 40 | 37.7 | 87.2 | Removed Flash Lite hallucination |
| + Fixed 0.0 garbage KPI values | 8.4 | 40 | 44.3 | 92.7 | Return None not 0 for missing metrics |
| + Deterministic KPI table in markdown | 12.2 | 39.3 | 41.0 | 92.5 | Python-rendered table, no LLM |
| + Fixed KPI formulas (Driving Hrs, Turnover) | 13.3 | 40 | 41.0 | **94.3** | Contract formula corrections |
| + Core 9 KPIs only | 12.1 | 37.3 | 42.7 | 92.1 | Hidden secondary KPIs |
| **Current best** | **13.3** | **40.0** | **44.3** | **94.3** | — |

---

## Current Architecture

### 3-Step Hybrid Brief Pipeline
1. **Pass 0 (Code):** SignalRanker extracts ~30 signals from hierarchy cards, statistical insights, cross-metric analysis, temporal benchmarks, concentration risk, price-volume decomposition, and derived KPI signals
2. **Pass 1 (Flash Lite):** Curates top 12 signals, assigns `one_line_why`, `category`, `clean_name`, `dimension`. `metric_description` is now computed deterministically in Python (not by Flash Lite) to prevent hallucination
3. **Pass 2 (Pro):** Synthesizes final CEO brief from curated signals + KPI block. Output is structured JSON (bottom_line, what_moved, trend_status, where_it_came_from, why_it_matters, next_week_outlook, leadership_focus)

### Deterministic Elements (no LLM involvement)
- **KPI Table:** Rendered in Python from contract derived_kpis, injected after bottom_line in the markdown
- **metric_description:** Computed from verified signal fields (`current_value`, `prior_value`, `var_pct`)
- **KPI signals:** Derived KPIs injected as high-priority (0.8) Pass 0 signals, re-injected after Pass 1 if dropped

### Core 9 KPIs (shown in brief table)
| KPI | Contract Name | Pipeline Value | Dashboard Value | Match |
|---|---|---|---|---|
| Total Revenue xFSR | ttl_rev_xf_sr_amt | $23,233,591 | $23,233,591 | Exact |
| Truck Count | truck_count_avg | 6,119 | 6,119 | Exact |
| Rev/Trk/Day | rev_trk_day | $759 | $759 | Exact |
| Total Miles | total_miles_rpt | 9,961,464 | 9,961,464 | Exact |
| Miles/Trk/Wk | miles_trk_wk | 1,628 | 1,628 | Exact |
| Deadhead % | deadhead_pct | 15.5% | 15.5% | Exact |
| LRPM | lrpm | $2.76 | $2.760 | Exact |
| TRPM | trpm | $2.33 | $2.332 | Exact |
| Avg LOH | avg_loh | 370 | 370 | Exact |

### Secondary KPIs (hidden from brief, available for analysis)
Seated Truck Count, Rev/Trk/Wk, Rev/Seated Trk/Day, Loaded Miles/Trk/Wk, Fuel RPM, Driving Hrs/Active Driver/Day, On-Duty Hrs/Driver/Day, Turnover %, CPMM, DOT CPMM

---

## Key Technical Decisions

1. **`period_days` magic token:** Contract derived_kpis use `divide_by: period_days` or `multiply: period_days` instead of hardcoded `7`. KPI calculator resolves at runtime (7 for weekly, 28-31 for monthly).

2. **Supplemented current_totals:** Agent.py reads ALL contract base metrics from the loaded DataFrame (not just the 4-6 analyzed metrics) so derived KPIs that reference non-analyzed columns can compute correctly.

3. **`brief_hidden: true`:** Contract field that keeps a KPI available for chaining/computation but hides it from the deterministic table and KPI signals.

4. **Flash Lite no longer generates metric_description:** Removed from schema entirely. Deterministic `_build_deterministic_metric_description()` in brief_utils.py computes it from verified signal fields.

5. **Ground truth files are gitignored:** `config/datasets/**/ground_truth_*.json` — validation data stays local only, never pushed to GitHub.

---

## Remaining Gaps to 100

### T0: 1.7 pts remaining (13.3 / 15)
- **Network: 9/9** — all core KPIs found in brief
- **Regional: ~2/3** — one region's values sometimes not matched
- **Fix:** Ground truth corrected (Avg LOH=370, Miles/Trk/Wk=1628). Next run should hit 14-15.

### T1: 0-2.7 pts remaining (37.3-40.0 / 40)
- **contract_compliance: 1.3/4** — scorer checks raw metric names but brief uses display names
- **Fix:** Updated scorer to also match `display_name` from metric JSON. Should restore to 4/4.

### T2: 1-4 pts remaining (41-44.3 / 45)
- **completeness: 5.3/9** — biggest gap. Brief doesn't cover all digest content.
- **causal_depth: 8.7/9** — near max
- **consistency_bonus: 0/1** — 3 critic runs disagree by >2 pts
- **Fix:** Strengthened Pass 2 grounding (4+ what_moved bullets, 3+ trends, 3+ leadership items, display names, region references). Should push completeness to 7-8.

---

## Files Modified (this branch)

| File | Changes |
|---|---|
| `data_analyst_agent/brief_utils.py` | Deterministic metric_description builder, KPI signal extraction, display name replacement in Pass 2, regional breakdown, strengthened grounding |
| `data_analyst_agent/sub_agents/executive_brief_agent/hybrid_brief_pipeline.py` | Removed Flash Lite hallucination cleanup, KPI re-injection, deterministic KPI table rendering, `kpi_rows` passthrough |
| `data_analyst_agent/sub_agents/executive_brief_agent/brief_format.py` | Deterministic KPI table in markdown after bottom_line |
| `data_analyst_agent/sub_agents/executive_brief_agent/kpi_calculator.py` | `period_days` token, `brief_hidden` filtering, None-not-0 for missing metrics, no cents for large currency |
| `data_analyst_agent/sub_agents/executive_brief_agent/agent.py` | Supplemented current_totals from DataFrame, contract passthrough, KPI rows in session state |
| `config/datasets/tableau/ops_metrics_ds/contract.yaml` | 20+ new base metrics, 15+ derived KPIs, `brief_hidden` flags, formula corrections |
| `config/datasets/tableau/ops_metrics_ds/loader.yaml` | 25+ new sum_columns from Hyper extract |
| `autoresearch/evaluate.py` | T0 scoring (key_metrics, 2-decimal matching), T1 display name compliance |
| `autoresearch/datasets.py` | Ops Metrics DS with --lob "Line Haul" filter |

---

## Next Steps

1. **Run iteration with latest fixes** — ground truth corrected, T1 compliance fixed. Expect BQS 95-97.
2. **Merge to dev** once BQS stabilizes above 95.
3. **Expand to other datasets** — re-enable CSV eval datasets (Global Superstore, Iowa Liquor) and Tolls Expense to verify the pipeline works across different data types.
4. **Autoresearch at scale** — run 50 iterations on the merged code to optimize T2 completeness through prompt mutations.
5. **Regional scoped briefs** — each region gets its own deterministic KPI table at generation time.
6. **Monthly validation** — test with monthly period_type to verify `period_days` token works (28 for Feb, 31 for March).
