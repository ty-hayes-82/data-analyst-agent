# Pipeline Bug-Fix Sprint Plan

**Created:** 2026-03-23
**Baseline run:** `ops_metrics_ds --start-date 2025-12-07 --end-date 2026-03-14 --dimension lob_ref --dimension-value "Line Haul" --metrics "ttl_rev_xf_sr_amt,truck_count_avg,rev_trk_day,total_miles_rpt,miles_trk_wk,deadhead_pct,lrpm,trpm,avg_loh"`

Each sprint is a single bug fix followed by a full re-run of the baseline command above. The sprint is not complete until the fix is verified in the logs **and** no regressions are introduced in other metrics.

---

## Sprint 1 -- NaN / Infinity in Alert Payloads

**Status:** Done (code + `test_extract_alerts_sanitizes_nan_and_inf`; re-run baseline to confirm outputs)
**File:** `data_analyst_agent/sub_agents/alert_scoring_agent/tools/extract_alerts_from_analysis.py`

### Problem
Ratio metrics (`rev_trk_day`, `miles_trk_wk`, `lrpm`, `trpm`) produce `NaN` and `Infinity` values in alert payloads. These propagate into rendered markdown reports as `+$infB z=nan p=nan` in the Anomalies section and into Recommended Actions (e.g. "observed value +$infB for Lrpm").

### Root Cause
Lines 168-182: when an anomaly's `avg` is 0 or the upstream `value` is already NaN, the arithmetic produces NaN/Infinity with no guard:

```python
variance_amount = abs(value - avg)
variance_pct = abs((variance_amount / avg * 100)) if avg != 0 else 0
# ...
"item_total": round(_item_avgs.get(item_name, 0), 2),
"cv": abs(std / avg) if avg != 0 else 0,
```

The `_item_avgs` dict can also contain Infinity when a driver's `avg` is near-zero multiplied by `count`.

### Fix
Add a `_safe_float()` helper that replaces `NaN`, `Infinity`, and `-Infinity` with `0.0` (or `None`). Apply it to every numeric field written into an alert dict: `variance_amount`, `variance_pct`, `item_total`, `cv`, `z_score`, and any value passed to `round()`.

### Verification
1. Re-run the baseline command.
2. `grep -r "NaN\|Infinity\|inf" outputs/.../alerts/` should return zero hits.
3. Rendered `.md` files must not contain `nan`, `inf`, or `$infB`.
4. Existing unit tests pass (`pytest tests/unit/`).

---

## Sprint 2 -- Temporal Grain Mislabeled as "Daily"

**Status:** Done (`loaders.py` median-gap override; `level_stats/core.py` + `refresh_analysis_context_temporal_grain`; re-run baseline for logs)
**Files:**
- `data_analyst_agent/semantic/models.py` (or wherever `TemporalGrain` detection lives)
- `data_analyst_agent/sub_agents/hierarchy_variance_agent/tools/level_stats/core.py` (auto-switch logic)

### Problem
`[TemporalGrain] detected=daily source=contract_frequency confidence=1.00 periods=14 (contract=daily)` but the actual data has 7-day gaps. `LevelStats` auto-switches comparison to WoW, but the **label** stays "daily" throughout the pipeline.

### Downstream Impact
- Reports say "the day ending 2026-03-14" instead of "the week ending..."
- Period labels use "DoD" instead of "WoW"
- Recommended actions say "Monitor next day" instead of "Monitor next week"
- LLM synthesis prompts include incorrect temporal context, producing "vs prior day"

### Fix
When `LevelStats` detects a median gap of 7 days but the contract says "daily", the temporal grain stored in session state should be corrected to "weekly". The auto-switch in `core.py` already knows the truth (`median gap: 7d`); it should also update `ctx.temporal_grain` (or the session state equivalent) so all downstream consumers get the corrected label.

### Verification
1. Re-run the baseline command.
2. Log output should show `detected=weekly` (or at least not `daily` when median gap is 7d).
3. All `.md` reports should say "week ending" not "day ending".
4. Recommended actions should say "Monitor next week" not "Monitor next day".
5. LLM synthesis output should reference "WoW" not "vs prior day".

---

## Sprint 3 -- Scoped Brief Failure Crashes Executive Brief Agent

**Status:** Done (`return_exceptions=True`, per-entity try/return None)
**File:** `data_analyst_agent/sub_agents/executive_brief_agent/agent.py`

### Problem
When one scoped brief (Albuquerque) fails LLM validation after retries, the `ValueError` propagates through `asyncio.gather(*tasks)` and crashes the entire `executive_brief_agent`. The network-level brief and other scoped briefs (East, Atlanta) that already succeeded are lost.

### Root Cause
Line 1753: `results = await asyncio.gather(*tasks)` does not use `return_exceptions=True`. A single task failure aborts the entire gather.

### Fix
1. Change to `asyncio.gather(*tasks, return_exceptions=True)`.
2. In the results loop, check if each result is an `Exception`. If so, log the error and skip that entity's scoped brief instead of crashing.
3. The agent should still yield a successful event with whatever briefs were generated.

### Verification
1. Re-run the baseline command.
2. The executive brief agent should complete without the traceback.
3. The network brief and successful scoped briefs should be saved to disk.
4. Failed scoped briefs should be logged as warnings, not fatal errors.
5. The overall pipeline exit code should be 0.

---

## Sprint 4 -- Report Synthesis LLM Truncation / Silent Fallback

**Status:** Done (default `max_tool_calls=4`, `max_output_tokens=4096`, richer fallback log)
**File:** `data_analyst_agent/sub_agents/report_synthesis_agent/agent.py`

### Problem
Multiple metrics trigger `[REPORT_SYNTHESIS] Fallback triggered (missing LLM output); calling generate_markdown_report directly.` The LLM response is truncated mid-JSON, causing the agent to silently fall back to template-based generation. An earlier run also showed `[REPORT_SYNTHESIS] Reached max tool calls (1), stopping.`

### Root Cause
The report synthesis agent wraps the LLM call inside a tool-call workflow. When the LLM response exceeds the token budget or the agent reaches `max_tool_calls=1`, the structured output is incomplete. The fallback is silent -- no warning about *why* it triggered.

### Fix
1. Increase `max_tool_calls` if applicable, or restructure so the LLM output goes directly to the tool without an intermediate step.
2. When fallback triggers, log the reason (token truncation vs. tool-call limit vs. parse failure) and the size of the partial response.
3. Consider truncating the input payload to stay within token limits (the `TOTAL payload` sizes range from 10K-18K chars, which may be pushing Gemini's structured output limits).

### Verification
1. Re-run the baseline command.
2. Count fallback triggers: should be fewer than before (ideally zero).
3. When fallback does trigger, the log should explain why.
4. Report quality for metrics that previously fell back should improve.

---

## Sprint 5 -- Corporate Entity Noise in Anomalies

**Status:** Done (share-of-total filter default 0.1%; optional `ALERT_MATERIALITY_MIN_VARIANCE_ABS`, default 0)
**File:** `data_analyst_agent/sub_agents/alert_scoring_agent/tools/extract_alerts_from_analysis.py`

### Problem
"Corporate" is a vestigial dimension value with near-zero activity. It generates anomalies with extreme percentages (1270%, 1328%) on negligible absolute amounts ($3.05, $0.93), crowding out real signals in alert lists and anomaly sections.

### Fix
Add a materiality filter during alert extraction. Options:
- **Share-of-total filter:** skip anomalies where `item_total / grand_total < 0.001` (0.1%).
- **Minimum absolute value filter:** skip anomalies where `abs(variance_amount) < materiality_floor` (e.g. $100 for dollar metrics, configurable).
- **Both:** apply share-of-total first, then absolute floor as a safety net.

### Verification
1. Re-run the baseline command.
2. "Corporate" should not appear in any alert payload or anomaly section.
3. Legitimate anomalies (e.g. West deadhead_pct) should still surface.
4. Alert counts should decrease for metrics like `ttl_rev_xf_sr_amt` and `avg_loh`.

---

## Sprint 6 -- Alert Severity Score Inconsistency

**Status:** Done (`compute_severity` + `score_alerts` finite guards; re-check on baseline)
**File:** `data_analyst_agent/sub_agents/alert_scoring_agent/` (scoring logic)

### Problem
For ratio metrics: `severity=1.000, high=0, medium=0, low=10`. A max severity of 1.0 (the ceiling) with all-low alerts is contradictory. This is likely caused by NaN values corrupting the severity aggregation (NaN comparisons in `max()` can produce unexpected results).

### Root Cause
NaN values from Sprint 1 flow into the severity scoring math. After Sprint 1 is fixed, this may self-resolve. If not, the scoring aggregation needs explicit NaN handling.

### Fix
1. Re-check after Sprint 1 is done -- the NaN fix may resolve this.
2. If it persists, add NaN guards in the severity aggregation function.
3. The overall severity score should be the max of individual alert severities, not a sum or corrupted value.

### Verification
1. Re-run the baseline command.
2. `severity` should be proportional to the highest-severity alert in the set.
3. If all alerts are "low", severity should be well below 1.0.

---

## Sprint 7 -- Dollar Sign on Ratio Metrics

**Status:** Not started
**File:** `data_analyst_agent/sub_agents/report_synthesis_agent/tools/report_markdown/formatting.py`

### Problem
LRPM and TRPM variance tables show `$-0` and `+$0`. These metrics are ratios (revenue per mile), not dollar amounts. The variance is ~$0.03, which rounds to `$0` and looks meaningless.

### Fix
1. In `resolve_unit()` or `_format_amount_short()`, detect ratio metrics (either from contract metadata or by checking if the value is small and the metric name suggests a rate).
2. For ratio metrics, show more decimal places (e.g. `-0.03` or `-$0.03`) instead of rounding to `$0`.
3. Alternatively, expose `presentation_unit` from the contract and format accordingly (e.g. "$/mile").

### Verification
1. Re-run the baseline command.
2. LRPM/TRPM variance tables should show meaningful values (e.g. `-$0.03` or `-0.03 $/mi`), not `$-0`.
3. Dollar-denominated metrics (ttl_rev_xf_sr_amt, total_miles_rpt) should be unaffected.

---

## Sprint 8 -- Scoped Brief Entity Selection

**Status:** Done (`_discover_level_entities` ranked by cross-metric |variance $| then |variance %|)
**File:** `data_analyst_agent/sub_agents/executive_brief_agent/agent.py`

### Problem
When truncating Level 2 to `EXECUTIVE_BRIEF_MAX_SCOPED_BRIEFS`, the system picked Albuquerque and Atlanta instead of the top variance drivers (Manteno at -57.2%, Gary at +54.7%, Phoenix at -8.1%).

### Fix
Rank candidate entities by absolute variance impact (sum of `|variance_dollar|` or max `|variance_pct|` across all metrics) before applying the truncation limit. The entities with the largest cross-metric impact should get scoped briefs.

### Verification
1. Re-run the baseline command.
2. Scoped briefs should target Manteno, Gary, and/or Phoenix (not Albuquerque).
3. The selected entities should match the top drivers in the executive summary narrative.
4. The truncation log message should show the selected entities and their scores.

---

## Regression Test Protocol

After **each** sprint, run the full baseline command and verify:

1. Pipeline exits with code 0 (no unhandled exceptions).
2. All 9 metric `.md` reports are generated.
3. Executive brief (`brief.md`) is generated.
4. `pytest tests/unit/` passes with no new failures.
5. No new `NaN`, `Infinity`, or traceback appears in the logs.
6. The specific sprint's verification checklist passes.
