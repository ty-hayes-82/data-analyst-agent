# Dev Iterate Findings — 2026-03-13 05:35 UTC

## Test Status
✅ **291 tests passing** (baseline was 236 - improved!)
✅ **Full pipeline completes** with both metrics
✅ **Executive brief generates properly** (brief.json, brief.md)

## Objective 1: QUALITY — Executive Brief Output

### Finding: Executive Brief Agent WORKS CORRECTLY ✅
- `CrossMetricExecutiveBriefAgent` produces properly structured JSON
- Uses `response_mime_type="application/json"` with `response_schema`
- Output format is correct:
  ```json
  {
    "header": {"title": "...", "summary": "..."},
    "body": {"sections": [
      {"title": "Executive Summary", "content": "...", "insights": []},
      {"title": "Key Findings", "content": "...", "insights": [...]},
      {"title": "Forward Outlook", "content": "...", "insights": []}
    ]}
  }
  ```
- File: `outputs/.../brief.json` (3.3KB), `brief.md` (2.7KB)
- **No action needed for executive brief** ✅

### Issue: Per-Metric Report Synthesis Falls Back to Generic Output ⚠️
**Location**: `data_analyst_agent/sub_agents/report_synthesis_agent/agent.py`

**Problem**: 
- LLM calls `generate_markdown_report` tool but simplifies the `hierarchical_results` payload
- Input (correct): Full JSON with `level_0`, `level_1`, `level_2` dicts containing insight_cards
- Tool call (wrong): Human-readable summary string:
  ```
  'hierarchical_results': 'Level 0 (Total): +$97,224,511.66 (+3.0%) variance.\nLevel 1 (Region): ...'
  ```
- Result: Tool fails to parse, outputs generic fallback:
  ```
  > Error: Hierarchical analysis payload could not be parsed
  ```

**Root Cause**:
- The injection message includes correct JSON structure in `REPORT_SYNTHESIS_INPUT_JSON`
- But the LLM agent "helpfully" summarizes it instead of passing through verbatim
- The instruction doesn't explicitly require JSON structure preservation

**Potential Solutions**:
1. **Strengthen tool contract** in prompt: "Pass the EXACT JSON structure from hierarchical_analysis, do NOT summarize"
2. **Expand fast-path logic**: Bypass LLM entirely for deterministic scenarios
3. **Add validation layer**: Reject tool calls that don't match expected schema

---

## Objective 2: FLEXIBILITY — Contract-Driven Pipeline

### Current State:
- ✅ No hardcoded metric names found (`trade_value_usd`, `volume_units`)
- ✅ No hardcoded dimension values in semantic layer
- ⚠️ Need to audit:
  - Hierarchy level assumptions (e.g., "state", "region" labels)
  - Time grain logic (weekly/monthly assumptions)
  - Alert scoring thresholds
  - Narrative generation dimension references

### Next Steps:
1. Search for hardcoded strings in `sub_agents/` and `semantic/`
2. Verify all entity labels come from `contract.hierarchies[].level_names`
3. Check if dimension names are pulled from `contract.dimensions[].name`

---

## Objective 3: EFFICIENCY — Pipeline Performance

### Current Timings (per metric):
- **narrative_agent**: 14.96s (generates insight cards)
- **report_synthesis_agent**: 14.96-20.04s (calls LLM + tool)
- **executive_brief_agent**: 288.61s (2 metrics + 3 scoped briefs + PDF)

### Observations:
1. **Narrative agent**: 
   - Reduced `max_output_tokens` from 4096 → 2048 (already done)
   - Prompt size: 1,775 chars instruction + 6,751 chars payload
   - Could pre-filter insight cards to reduce context

2. **Report synthesis agent**:
   - Pre-summarization available via `REPORT_SYNTHESIS_PRE_SUMMARIZE=true`
   - Already truncates components to max chars
   - Issue: LLM call adds 15s+ when fast-path could handle it in <1s

3. **Executive brief agent**:
   - Most time spent on: network brief + 3 scoped briefs + PDF generation
   - Each scoped brief = separate LLM call
   - Could reduce `EXECUTIVE_BRIEF_MAX_SCOPED_BRIEFS` from 3 → 2

### Recommendations:
- ✅ Token reduction already applied (2048 tokens)
- 🔄 Enable fast-path for report_synthesis when possible
- 🔄 Consider reducing scoped brief count for faster runs
- 🔄 Profile LLM thinking config impact

---

## Objective 4: CLEANUP — Remove Dead Config

### Findings:
- ✅ `fix_validation.py` NOT FOUND in repo root (already removed)
- ⚠️ `config/datasets/tableau/ops_metrics_weekly/` exists but:
  - Tests skip it: "ops_metrics contract.yaml not found"
  - Not actively used in current dataset roster
  - **Decision needed**: Keep for future use or remove?

### Structure:
```
config/datasets/
├── csv/
│   └── trade_data/         # ACTIVE
└── tableau/
    └── ops_metrics_weekly/  # UNUSED (skipped in tests)
```

### Recommendation:
- If ops_metrics is planned for future use → keep
- If abandoned → remove to reduce clutter
- Current impact: minimal (tests skip it gracefully)

---

## Summary of Actions Needed

### HIGH PRIORITY:
1. **Fix report_synthesis tool calling**: Update prompt to preserve hierarchical_results JSON structure
2. **Audit hardcoded references**: Ensure all entity/dimension labels come from contract

### MEDIUM PRIORITY:
3. **Enable report_synthesis fast-path**: Reduce LLM calls for deterministic scenarios
4. **Review ops_metrics dataset**: Remove if abandoned, document if planned

### LOW PRIORITY:
5. **Profile thinking config**: Measure impact of thinking tokens on speed
6. **Reduce scoped brief count**: Consider 2 instead of 3 for faster runs

---

## Test Results:
```bash
cd /data/data-analyst-agent && python -m pytest tests/ --tb=short -q
# Result: 291 passed, 13 skipped, 1 warning in 36.43s
```

## Pipeline Run:
```bash
ACTIVE_DATASET=trade_data python -m data_analyst_agent --metrics "trade_value_usd,volume_units"
# Result: SUCCESS
# Outputs:
#   - metric_trade_value_usd.md (5.8KB) - has parsing error
#   - metric_volume_units.md (4.0KB) - has parsing error
#   - brief.md (2.7KB) - ✅ properly structured
#   - brief.json (3.3KB) - ✅ properly structured
#   - 3 scoped briefs (Midwest, Northeast, South)
#   - brief.pdf (2.4KB)
```
