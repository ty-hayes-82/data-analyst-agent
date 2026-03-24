# Analysis Focus System

## Overview

The Analysis Focus System allows users to shape analysis behavior through focus directives passed via environment variables. Focus modes adjust how the pipeline prioritizes findings, filters data, and frames narratives.

## Environment Variables

### `DATA_ANALYST_FOCUS`
Comma-separated list of focus modes. Valid modes:

- **`recent_weekly_trends`** - Focus on last 8 weeks, emphasize week-over-week changes
- **`recent_monthly_trends`** - Focus on last 6 months, emphasize month-over-month changes
- **`anomaly_detection`** - Lower anomaly detection threshold (z-score 2.0 vs 3.0), scan more aggressively
- **`revenue_gap_analysis`** - Prioritize variance decomposition and gap identification
- **`seasonal_patterns`** - Highlight seasonal decomposition findings
- **`yoy_comparison`** - Emphasize year-over-year comparisons
- **`forecasting`** - Prioritize trend forecasting and projection
- **`outlier_investigation`** - Focus on outlier detection and investigation

**Example:**
```bash
export DATA_ANALYST_FOCUS="recent_monthly_trends,anomaly_detection"
```

### `DATA_ANALYST_CUSTOM_FOCUS`
Free-text custom focus instruction (max 500 chars, sanitized).

**Example:**
```bash
export DATA_ANALYST_CUSTOM_FOCUS="Find revenue gaps in Retail LOB"
```

## Pipeline Integration

### 1. CLIParameterInjector (`data_analyst_agent/core_agents/cli.py`)

**Responsibilities:**
- Read `DATA_ANALYST_FOCUS` and `DATA_ANALYST_CUSTOM_FOCUS` from environment
- Parse comma-separated focus list into normalized strings
- Validate focus modes against `VALID_FOCUS_MODES` set
- Warn about unknown modes and filter them out
- Sanitize custom focus text (remove control chars, truncate to 500 chars)
- Inject into session state as `analysis_focus` (list) and `custom_focus` (string)

**Session State Keys:**
- `analysis_focus`: `list[str]` - Normalized, validated focus modes
- `custom_focus`: `str` - Sanitized custom focus text

### 2. Planner Agent (`data_analyst_agent/sub_agents/planner_agent/`)

**Behavior:**
- Uses `focus_search_text()` to combine focus modes and custom text into a searchable blob
- Passes focus blob to `refine_plan()` for keyword-based agent selection
- LLM-based planner (when `USE_CODE_INSIGHTS=false`) uses `augment_instruction()` to append focus directives to prompt

**Integration:**
```python
from data_analyst_agent.utils.focus_directives import (
    get_focus_modes,
    get_custom_focus,
    focus_search_text,
    augment_instruction,
)

focus_modes = get_focus_modes(ctx.session.state)
custom_focus = get_custom_focus(ctx.session.state)
focus_blob = focus_search_text(ctx.session.state)
```

### 3. Statistical Tools (`data_analyst_agent/sub_agents/statistical_insights_agent/tools/`)

#### `compute_anomaly_indicators.py`
**Behavior:**
- Default anomaly threshold: z-score >= 3.0
- When `"anomaly_detection"` in focus modes: lowers threshold to 2.0
- Prints diagnostic message when focus mode triggers threshold adjustment

**Code:**
```python
from ....utils.focus_directives import get_focus_modes
focus_modes = get_focus_modes(ctx.session.state if ctx and hasattr(ctx, 'session') else None)
threshold = 3.0  # default
if "anomaly_detection" in focus_modes:
    threshold = 2.0  # more aggressive
    print(f"[AnomalyIndicators] Focus mode 'anomaly_detection' active: lowering threshold to {threshold}")
```

#### `compute_period_over_period_changes.py`
**Behavior:**
- Default: analyze all available periods
- When `"recent_weekly_trends"` in focus modes: filters to last 8 periods
- When `"recent_monthly_trends"` in focus modes: filters to last 6 periods

**Code:**
```python
from ....utils.focus_directives import get_focus_modes
focus_modes = get_focus_modes(ctx.session.state if ctx and hasattr(ctx, 'session') else None)
if "recent_weekly_trends" in focus_modes and len(agg) > 8:
    agg = agg.tail(8)  # last 8 weeks
    print("[PeriodOverPeriod] Focus mode 'recent_weekly_trends': filtering to last 8 periods")
elif "recent_monthly_trends" in focus_modes and len(agg) > 6:
    agg = agg.tail(6)  # last 6 months
    print("[PeriodOverPeriod] Focus mode 'recent_monthly_trends': filtering to last 6 periods")
```

### 4. Narrative Agent (`data_analyst_agent/sub_agents/narrative_agent/`)

**Behavior:**
- Uses `focus_lines()` to extract formatted focus directive lines
- Uses `augment_instruction()` to append focus directives to LLM prompt
- Frames findings in terms of selected focus when generating insight cards

**Integration:**
```python
from ...utils.focus_directives import augment_instruction, focus_lines

focus_lines_list = focus_lines(ctx.session.state)
instr = augment_instruction(NARRATIVE_AGENT_INSTRUCTION, ctx.session.state)
```

**Prompt Injection Format:**
```
FOCUS_DIRECTIVES:
Focus modes to prioritize: recent_weekly_trends, anomaly_detection
Custom directive: Find revenue gaps in Retail LOB
```

### 5. Report Synthesis Agent (`data_analyst_agent/sub_agents/report_synthesis_agent/`)

**Behavior:**
- Uses `build_focus_payload()` to create structured focus payload
- Includes focus in report payload passed to `generate_markdown_report` tool
- Prompt updated to prioritize focus-relevant findings in "The Big Story" section

**Integration:**
```python
from ...utils.focus_directives import focus_payload as build_focus_payload

focus_payload = build_focus_payload(state)
report_payload = {
    "dataset_context": contract_context,
    "focus": focus_payload,  # {"modes": [...], "custom_directive": "..."}
    "temporal_context": temporal_context,
    "components": {...},
}
```

**Prompt Guardrails (Updated):**
```markdown
6. **FOCUS DIRECTIVES**: If the payload includes `focus` directives (modes or custom instructions), 
   prioritize those findings in "The Big Story" and lead with insights matching the focus. For example:
   - `recent_weekly_trends` → emphasize last 8 weeks in opening paragraph
   - `anomaly_detection` → lead with detected anomalies if present
   - `seasonal_patterns` → highlight seasonality in the executive summary
   - Custom focus text → incorporate as a filter for which insights to emphasize
```

## Utility Functions (`data_analyst_agent/utils/focus_directives.py`)

### Core Functions
- **`get_focus_modes(state)`** - Extract `analysis_focus` list from state
- **`get_custom_focus(state)`** - Extract `custom_focus` text from state
- **`focus_search_text(state)`** - Combine focus modes + custom text into searchable blob
- **`focus_lines(state)`** - Format focus as list of lines for prompts
- **`focus_block(state)`** - Format focus as a block with header
- **`augment_instruction(base, state)`** - Append focus block to prompt
- **`focus_payload(state)`** - Create structured focus payload for JSON

### Example Usage
```python
from data_analyst_agent.utils.focus_directives import (
    get_focus_modes,
    get_custom_focus,
    augment_instruction,
)

# Read focus from state
focus_modes = get_focus_modes(ctx.session.state)  # ["recent_weekly_trends", "anomaly_detection"]
custom = get_custom_focus(ctx.session.state)      # "Find revenue gaps"

# Check if specific mode is active
if "anomaly_detection" in focus_modes:
    threshold = 2.0

# Augment LLM prompt with focus directives
augmented_prompt = augment_instruction(base_instruction, ctx.session.state)
```

## Testing

Run focus system tests:
```bash
cd /data/data-analyst-agent
python -m pytest tests/unit/test_focus_integration.py -v
```

**Test Coverage:**
- Focus mode parsing from env vars
- Unknown mode validation and filtering
- Custom focus sanitization
- Focus payload construction
- Integration with planner, narrative, and report synthesis agents
- Statistical tool threshold/filtering adjustments

## Examples

### Example 1: Recent Weekly Trends
```bash
export DATA_ANALYST_FOCUS="recent_weekly_trends"
export DATA_ANALYST_METRICS="revenue,orders"
python -m data_analyst_agent
```
**Effect:**
- Period-over-period analysis filters to last 8 periods
- Executive brief emphasizes week-over-week changes
- Narrative leads with recent trends

### Example 2: Anomaly Detection
```bash
export DATA_ANALYST_FOCUS="anomaly_detection"
export DATA_ANALYST_METRICS="revenue"
python -m data_analyst_agent
```
**Effect:**
- Anomaly detection threshold lowered from 3.0 to 2.0 z-score
- More anomalies flagged in statistical summary
- Narrative and executive brief lead with anomaly findings

### Example 3: Custom Focus
```bash
export DATA_ANALYST_FOCUS="recent_monthly_trends"
export DATA_ANALYST_CUSTOM_FOCUS="Find revenue gaps between Retail and Wholesale LOBs"
python -m data_analyst_agent
```
**Effect:**
- Period filtering: last 6 months
- Planner keywords match "revenue gaps" and "Retail" / "Wholesale"
- Narrative frames findings around LOB comparison
- Executive brief highlights revenue gap insights

### Example 4: Multiple Focus Modes
```bash
export DATA_ANALYST_FOCUS="recent_monthly_trends,anomaly_detection,seasonal_patterns"
python -m data_analyst_agent
```
**Effect:**
- Period filtering: last 6 months
- Anomaly threshold: 2.0
- Planner keywords match "seasonal"
- Narrative synthesizes recent trends + anomalies + seasonality
- Executive brief balances all three focus areas

## Future Enhancements

### Potential Additions
1. **YoY Computation Support** - Add year-over-year comparison when `yoy_comparison` is in focus
2. **Forecasting Integration** - Trigger forecasting tools when `forecasting` is in focus
3. **Revenue Gap Decomposition** - Add specialized gap analysis when `revenue_gap_analysis` is in focus
4. **Focus Priority Scoring** - Weight insight cards by alignment with focus directives
5. **Focus-Aware Thresholds** - Adjust materiality thresholds based on focus modes
6. **Focus History Tracking** - Log focus directives in output metadata for reproducibility

### Architecture Considerations
- Keep focus logic lightweight and deterministic
- Avoid overloading focus modes with too much behavior
- Balance user control with sensible defaults
- Maintain backward compatibility (empty focus = default behavior)
- Document focus mode semantics clearly in web UI

## Troubleshooting

### Issue: Focus modes not affecting output
**Diagnosis:**
1. Check that env vars are set: `echo $DATA_ANALYST_FOCUS`
2. Check CLIParameterInjector output: `grep "CLIParameterInjector" output.log`
3. Check statistical tool logs: `grep "Focus mode" output.log`

**Solution:**
- Ensure focus modes are spelled correctly (lowercase, underscores)
- Verify focus modes are in `VALID_FOCUS_MODES` set

### Issue: Unknown focus mode warning
**Diagnosis:**
```
[CLIParameterInjector] WARNING: Unknown focus modes: ['invalid_mode']
```

**Solution:**
- Check spelling: `recent_weekly_trends` not `recent-weekly-trends`
- Use only modes from valid set (see Environment Variables section)

### Issue: Custom focus not appearing in report
**Diagnosis:**
- Check sanitization: control chars removed, truncated to 500 chars
- Check report synthesis prompt injection

**Solution:**
- Keep custom focus under 500 chars
- Avoid newlines/tabs (auto-converted to spaces)
- Check `focus_payload` in report synthesis debug logs

## References

- **CLIParameterInjector:** `data_analyst_agent/core_agents/cli.py`
- **Focus Utilities:** `data_analyst_agent/utils/focus_directives.py`
- **Planner Agent:** `data_analyst_agent/sub_agents/planner_agent/agent.py`
- **Anomaly Tool:** `data_analyst_agent/sub_agents/statistical_insights_agent/tools/compute_anomaly_indicators.py`
- **Period-over-Period Tool:** `data_analyst_agent/sub_agents/statistical_insights_agent/tools/compute_period_over_period_changes.py`
- **Narrative Agent:** `data_analyst_agent/sub_agents/narrative_agent/agent.py`
- **Report Synthesis:** `data_analyst_agent/sub_agents/report_synthesis_agent/agent.py`
- **Tests:** `tests/unit/test_focus_integration.py`
