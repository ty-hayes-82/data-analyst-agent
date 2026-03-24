# Remaining Fixes — Phased Sprint Plan

**Created:** 2026-03-23  
**Depends on:** Prior work in [BUGFIX_SPRINT_PLAN.md](BUGFIX_SPRINT_PLAN.md) (implementation largely done; some items need **post-fix verification** or **follow-up**).

## How to use this doc

- One **sprint = one focused change** (or one verification pass with no code change).
- After each sprint: run the **baseline command**, then complete that sprint’s **Verification** checklist.
- Do not start the next sprint until the current one is green (no new regressions).

## Baseline command (PowerShell)

```powershell
Set-Location c:\GITLAB\data-analyst-agent
$env:SKIP_EXECUTIVE_BRIEF_LLM = "false"
python -m data_analyst_agent `
  --dataset ops_metrics_ds `
  --start-date 2025-12-07 `
  --end-date 2026-03-14 `
  --dimension lob_ref `
  --dimension-value "Line Haul" `
  --metrics "ttl_rev_xf_sr_amt,truck_count_avg,rev_trk_day,total_miles_rpt,miles_trk_wk,deadhead_pct,lrpm,trpm,avg_loh"
```

Note the new output directory printed at startup (timestamped path under `outputs/ops_metrics_ds/lob_ref/Line_Haul/`).

## Development Progress (2026-03-23)

- Fresh baseline reruns completed with exit code `0`; latest verified run: `outputs/ops_metrics_ds/lob_ref/Line_Haul/20260323_115554`.
- Targeted regression tests currently green:
  - `tests/unit/test_alert_scoring_tools.py`
  - `tests/unit/test_008_alert_scoring_pipeline.py`
  - `tests/unit/test_report_synthesis_fast_path.py`
  - `tests/unit/test_executive_brief_fallback.py`
  - `tests/unit/test_report_synthesis_tools.py`
  - `tests/smoke/test_report_markdown_smoke.py`
- New guardrail coverage added:
  - `test_markdown_report_anomalies_skip_blocklisted_items`
  - `test_markdown_report_anomalies_prefer_payload_over_raw_stats`
  - `test_extract_alerts_honors_contract_low_activity_values`
  - `test_executive_brief_partial_digest_quality_continues_llm`
- Sprint status is tracked below with latest verification evidence.

---

## Sprint R0 — Post-regression verification (formatting / reports)

**Status:** Complete  
**Code:** `data_analyst_agent/sub_agents/report_synthesis_agent/tools/report_markdown/formatting.py` — `format_value` must call `is_revenue_per_mile_metric` (no stale `_metric_is_revenue_per_mile_rate` reference).

### Problem

A `NameError` inside markdown formatting caused LLM tool invocations of `generate_markdown_report` to fail; persisted JSON/MD showed `# Error Generating Report...`. Executive brief skipped the LLM because digests looked like error state.

### Fix

None if already fixed in tree; otherwise ensure the correct function name is used and run tests.

### Verification

1. [x] Run baseline command; exit code `0` (`20260323_115554`).
2. [x] Open any `metric_<name>.md` under the new run folder — none starts with `# Error Generating Report`.
3. [x] `outputs/.../.cache/digest.json` spot-check — no error-stub summaries detected.
4. [x] `brief.md` — not the “all reports empty or error-state” placeholder.
5. [x] `Select-String -Path "outputs\...\alerts\*.json" -Pattern "NaN|Infinity|inf" -SimpleMatch` equivalent scan — no matches.
6. [x] `pytest tests/unit/test_alert_scoring_tools.py tests/unit/test_008_alert_scoring_pipeline.py` — pass (targeted set currently green).

**Sprint complete when:** R0 checklist passes on a fresh timestamped output folder.

---

## Sprint R1 — Report synthesis: LLM path yields markdown (not only fallback)

**Status:** In progress (implementation landed; partially verified)  
**Primary files:**  
`data_analyst_agent/sub_agents/report_synthesis_agent/agent.py`  
`data_analyst_agent/sub_agents/report_synthesis_agent/tools/generate_markdown_report.py`

### Problem

Logs showed `Fallback triggered: reason=missing LLM output` with `last_llm_text_chars=0`, `generate_markdown_tool_calls=0/4`, `events=1` for several metrics — the wrapped agent often ends before populating `report_markdown`, so users rely on deterministic fallback even when the LLM path is enabled.

### Goal

Either (pick one direction per implementation):

- **A)** Make the LLM reliably emit a `generate_markdown_report` tool call and session state update, **or**  
- **B)** Intentionally **fast-path** to `generate_markdown_report` when hierarchy signal is weak (already partially present) and **reduce misleading “fallback” noise** in logs.

### Fix ideas (choose in implementation)

- Inspect `wrapped_agent.run_async` event stream: why only one event and no tool response.  
- Adjust `GenerateContentConfig` (modalities, tool config) if the model never invokes the tool.  
- If LLM path is optional by design, gate it behind env and log `Fast-path` vs `Fallback` distinctly.

### Implemented

- Added `REPORT_SYNTHESIS_EXECUTION_MODE` (`auto|llm|direct`) to make execution intent explicit.
- Kept existing direct-tool fast-path behavior and clarified fallback diagnostics.
- Changed misleading log wording for missing LLM output from `Fallback triggered` to `Direct-render recovery`.

### Verification

1. Baseline run; for **at least half** of the nine metrics, logs should show either:  
   - `generate_markdown_tool_calls >= 1`, **or**  
   - an explicit fast-path line (not `missing LLM output`) if you adopt option B.  
2. [x] No increase in `# Error Generating Report` in outputs (`20260323_115554`).  
3. Compare report quality vs prior all-fallback run (spot-check LRPM/TRPM variance table formatting).

**Latest evidence:** `Direct-render recovery` diagnostics observed in latest run logs; wording no longer uses misleading `Fallback triggered` for missing LLM output.

---

## Sprint R2 — Corporate / vestigial dimension noise in alerts

**Status:** Complete  
**Primary file:** `data_analyst_agent/sub_agents/alert_scoring_agent/tools/extract_alerts_from_analysis.py`

### Problem

Share-of-total materiality (`ALERT_MATERIALITY_SHARE_MAX`, default `0.001`) does **not** filter entities like `Corporate` when `item_total / grand_total` is still large enough (e.g. ~29% on `avg_loh` run) but the anomaly is operationally meaningless (huge `%`, tiny business relevance).

### Fix options

- **Dimension blocklist** (env-driven), e.g. `ALERT_SKIP_ITEM_NAMES=Corporate` or YAML in contract.  
- **Combined rule:** e.g. skip if `abs(variance_pct) > X` **and** `abs(variance_amount) < Y` **and** optional name match.  
- **Contract metadata:** `low_activity_dimension_values` on the primary geo dimension.

### Implemented

- Added dynamic runtime share-of-total suppression using statistical payload:
  - Prefer `enhanced_top_drivers[].share_of_total`
  - Fallback to computed share from `top_drivers[].avg`
- Retained optional env and contract suppression hooks for explicit overrides.
- Added ratio-metric guardrail for extreme pct + tiny absolute deltas.
- Added unit test: immaterial `Corporate`-like row is skipped while material control row remains.
- Extended suppression to volatility/changepoint alert generation paths.
- Added dataset contract low-activity metadata:
  - `config/datasets/tableau/ops_metrics_ds/contract.yaml` now includes `low_activity_dimension_values: [Corporate]`.
- Report markdown anomalies now prefer alert payload anomalies (when present) and avoid reintroducing suppressed raw-stat anomalies.

### Verification

1. [x] Baseline run (`20260323_115554`): `Corporate` absent from `alerts/*.json` and from `metric_avg_loh.md`.  
2. [x] Legitimate driver still present when material (`alerts_payload_deadhead_pct.json` includes `West`).  
3. [x] Unit coverage:
   - `test_extract_alerts_skips_immaterial_item_by_runtime_share`
   - `test_extract_alerts_honors_contract_low_activity_values`
   - `test_markdown_report_anomalies_skip_blocklisted_items`
   - `test_markdown_report_anomalies_prefer_payload_over_raw_stats`

---

## Sprint R3 — Executive brief: digest quality guardrails

**Status:** Complete  
**Primary file:** `data_analyst_agent/sub_agents/executive_brief_agent/agent.py` (digest assembly / “empty or error-state” detection)

### Problem

Brief agent treats metric summaries as unusable when they match error/empty heuristics; after R0 this should be rare, but the detection logic may be **too strict** (false negatives) or **too loose** (LLM on garbage).

### Fix ideas

- Tighten “error state” detection to match only real failure patterns (e.g. `# Error Generating Report`, stub guard).  
- Log **which** metric(s) failed the check and why (metric id + reason code).  
- Optional: allow brief with partial metrics (network + N scoped) when some summaries are bad.

### Implemented

- Added strict metric-level reason coding for unusable markdown (`empty_report`, `report_generation_error`, `stub_content`, etc.).
- Replaced broad `"Error"` string heuristic with explicit pattern checks to avoid false negatives.
- Added per-metric digest-quality logging and partial-digest continuation path.
- Baseline run produced non-placeholder `brief.md` on healthy data.

### Verification

1. [x] After R0 green: baseline with `SKIP_EXECUTIVE_BRIEF_LLM=false` produces a non-placeholder `brief.md` (`20260323_115554`).  
2. [x] Added dev test for one intentionally broken metric payload:
   - `test_executive_brief_partial_digest_quality_continues_llm`
   - Verifies clear partial-quality log and continued LLM path (not all-metrics skip).

---

## Sprint R4 — Observability & regression pack (optional hardening)

**Status:** Complete

### Scope

- Single **smoke script** or `pytest` marker that: runs a **minimal** subset (1–2 metrics + `--skip-executive-brief-llm` if available) and asserts no error summary in MD.  
- Document env vars: `ALERT_MATERIALITY_*`, `REPORT_SYNTHESIS_MAX_TOOL_CALLS`, etc., in `.env.example` with one line each.

### Implemented

- Added `smoke` pytest marker in `pytest.ini`.
- Added `tests/smoke/test_report_markdown_smoke.py` to verify no `# Error Generating Report` for a minimal subset.
- Expanded `.env.example` docs for report synthesis and alert materiality controls.

### Verification

- [x] Local smoke: `pytest tests/smoke/test_report_markdown_smoke.py` passes in a few minutes.  
- [x] This doc contains the baseline command and latest verification evidence.

---

## Regression protocol (every sprint)

1. Pipeline exits `0`.  
2. Nine `metric_*.md` files exist under the run directory.  
3. `brief.md` present (content quality per sprint goals).  
4. `pytest tests/unit/` — no new failures (full suite if your workspace has fixtures; otherwise the subset in R0).  
5. No `traceback` / unhandled exception in console log for the run.  
6. Sprint-specific checklist above passes.

## Remaining Items (next execution order)

1. (Optional) Tighten R1 observability so explicit fast-path lines are emitted per metric for easier `>= half metrics` counting in logs.  
2. If desired, run full `pytest tests/unit/` suite for a broader non-targeted confidence pass.

---

## Completed elsewhere (do not duplicate as new sprints)

Tracked in [BUGFIX_SPRINT_PLAN.md](BUGFIX_SPRINT_PLAN.md): NaN/inf sanitization, temporal grain override, scoped brief `gather` resilience, report synthesis fallback **logging** and token/tool defaults, materiality share filter (first pass), severity finite guards, LRPM/TRPM formatting intent, scoped entity ranking by variance impact.

If any of those regress, **fix forward in the same file** or add a one-line “Regression” sprint under R0.
