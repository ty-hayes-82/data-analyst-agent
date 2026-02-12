# Phase Logging Integration Guide

This guide shows how to integrate phase-based logging into your P&L Analyst workflow.

## Table of Contents

1. [Quick Start](#quick-start)
2. [Manual Integration](#manual-integration)
3. [Decorator Integration](#decorator-integration)
4. [Agent-Level Integration](#agent-level-integration)
5. [Configuration](#configuration)
6. [Output Files](#output-files)
7. [Examples](#examples)

## Quick Start

### 1. Enable Phase Logging in Environment

Add to your `.env` file:

```bash
# Phase Logging Configuration
PHASE_LOGGING_ENABLED=true
PHASE_LOG_LEVEL=INFO
PHASE_LOG_DIRECTORY=logs
```

### 2. Initialize Phase Logger in Main Agent

Update `pl_analyst_agent/agent.py`:

```python
from .utils.phase_logger import PhaseLogger

# In your root agent or session initialization
phase_logger = PhaseLogger(cost_center="067")
ctx.session.state["phase_logger"] = phase_logger
```

### 3. Log Each Phase

The logger automatically tracks 6 phases matching your README:

- **Phase 1**: Data Ingestion & Validation
- **Phase 2**: Category Aggregation & Prioritization
- **Phase 3**: GL Drill-Down
- **Phase 4**: Parallel Analysis
- **Phase 5**: Synthesis & Structuring
- **Phase 6**: Alert Scoring & Persistence

## Manual Integration

### Phase 1: Data Ingestion & Validation

Update `sub_agents/ingest_validator_agent/agent.py`:

```python
from pl_analyst_agent.utils.phase_logger import PhaseLogger

async def _run_async_impl(self, ctx):
    # Get or create phase logger
    phase_logger = ctx.session.state.get("phase_logger")
    if not phase_logger:
        cost_center = ctx.session.state.get("current_cost_center")
        phase_logger = PhaseLogger(cost_center=cost_center)
        ctx.session.state["phase_logger"] = phase_logger
    
    # Start Phase 1
    phase_logger.start_phase(
        "Phase 1: Data Ingestion & Validation",
        description="Fetches P&L data, ops metrics, and validates data quality",
        input_data={
            "cost_center": cost_center,
            "date_ranges": ctx.session.state.get("date_ranges", {})
        }
    )
    
    try:
        # Your existing data ingestion code
        result = await self.ingest_and_validate(ctx)
        
        # Log metrics
        phase_logger.log_metric("records_fetched", len(result.get("time_series", [])))
        phase_logger.log_metric("data_quality_score", result.get("quality_score", 0))
        phase_logger.log_metric("missing_periods", len(result.get("quality_flags", {}).get("missing_periods", [])))
        
        # End Phase 1
        phase_logger.end_phase(
            "Phase 1: Data Ingestion & Validation",
            output_data={
                "status": result.get("status"),
                "record_count": len(result.get("time_series", [])),
                "quality_flags": result.get("quality_flags", {})
            },
            status="completed"
        )
        
        return result
    
    except Exception as e:
        phase_logger.log_error(f"Data ingestion failed: {str(e)}", e)
        phase_logger.end_phase("Phase 1: Data Ingestion & Validation", status="failed")
        raise
```

### Phase 2: Category Aggregation & Prioritization

Update `sub_agents/data_analysis/category_analyzer_agent/agent.py`:

```python
async def _run_async_impl(self, ctx):
    phase_logger = ctx.session.state.get("phase_logger")
    
    phase_logger.start_phase(
        "Phase 2: Category Aggregation & Prioritization",
        description="Aggregates GLs into categories and identifies top variance drivers",
        input_data={
            "gl_count": len(ctx.session.state.get("time_series", []))
        }
    )
    
    try:
        # Your category analysis code
        result = await self.analyze_categories(ctx)
        
        # Log metrics
        phase_logger.log_metric("categories_identified", len(result.get("categories", [])))
        phase_logger.log_metric("material_categories", result.get("material_count", 0))
        phase_logger.log_metric("total_variance_dollars", result.get("total_variance", 0))
        
        phase_logger.end_phase(
            "Phase 2: Category Aggregation & Prioritization",
            output_data={
                "top_categories": result.get("top_categories", [])[:5],
                "coverage_pct": result.get("coverage_pct", 0)
            },
            status="completed"
        )
        
        return result
    
    except Exception as e:
        phase_logger.log_error(f"Category analysis failed: {str(e)}", e)
        phase_logger.end_phase("Phase 2: Category Aggregation & Prioritization", status="failed")
        raise
```

### Phase 3: GL Drill-Down

Update `sub_agents/data_analysis/gl_drilldown_agent/agent.py`:

```python
async def _run_async_impl(self, ctx):
    phase_logger = ctx.session.state.get("phase_logger")
    
    phase_logger.start_phase(
        "Phase 3: GL Drill-Down",
        description="Analyzes individual GLs within top categories for root causes",
        input_data={
            "top_categories": ctx.session.state.get("top_categories", [])
        }
    )
    
    try:
        result = await self.drill_down_gls(ctx)
        
        # Log metrics
        phase_logger.log_metric("gls_analyzed", len(result.get("gl_details", [])))
        phase_logger.log_metric("root_causes_classified", len(result.get("root_causes", [])))
        phase_logger.log_metric("one_time_events", result.get("one_time_count", 0))
        
        phase_logger.end_phase(
            "Phase 3: GL Drill-Down",
            output_data={
                "gl_count": len(result.get("gl_details", [])),
                "root_cause_distribution": result.get("root_cause_summary", {})
            },
            status="completed"
        )
        
        return result
    
    except Exception as e:
        phase_logger.log_error(f"GL drill-down failed: {str(e)}", e)
        phase_logger.end_phase("Phase 3: GL Drill-Down", status="failed")
        raise
```

### Phase 4: Parallel Analysis

Update `agent.py` (parallel analysis coordinator):

```python
async def run_parallel_analysis(ctx):
    phase_logger = ctx.session.state.get("phase_logger")
    
    phase_logger.start_phase(
        "Phase 4: Parallel Analysis",
        description="Runs 6 analysis agents concurrently (Statistical, Seasonal, Ratio, Anomaly, Forecasting, Visualization)",
        input_data={
            "agents_count": 6,
            "data_ready": ctx.session.state.get("data_validated", False)
        }
    )
    
    start_time = time.time()
    
    try:
        # Run parallel agents
        result = await parallel_analysis_agent.run_async(ctx)
        
        # Log metrics
        phase_logger.log_metric("agents_executed", 6)
        phase_logger.log_metric("total_analysis_time", time.time() - start_time)
        
        # Check for agent failures
        failed = []
        for agent_name in ["statistical", "seasonal", "ratio", "anomaly", "forecasting", "visualization"]:
            if f"{agent_name}_result" not in ctx.session.state:
                failed.append(agent_name)
        
        if failed:
            phase_logger.log_warning(f"Some agents failed: {failed}")
        phase_logger.log_metric("failed_agents", len(failed))
        
        phase_logger.end_phase(
            "Phase 4: Parallel Analysis",
            output_data={
                "completed_agents": 6 - len(failed),
                "failed_agents": failed
            },
            status="completed" if len(failed) < 3 else "partial"
        )
        
        return result
    
    except Exception as e:
        phase_logger.log_error(f"Parallel analysis failed: {str(e)}", e)
        phase_logger.end_phase("Phase 4: Parallel Analysis", status="failed")
        raise
```

### Phase 5: Synthesis & Structuring

Update `sub_agents/synthesis_agent/agent.py`:

```python
async def _run_async_impl(self, ctx):
    phase_logger = ctx.session.state.get("phase_logger")
    
    phase_logger.start_phase(
        "Phase 5: Synthesis & Structuring",
        description="Generates 3-level output (Executive Summary, Category Analysis, GL Drill-Down)",
        input_data={
            "analysis_results_available": len([k for k in ctx.session.state.keys() if k.endswith("_result")])
        }
    )
    
    try:
        result = await self.synthesize(ctx)
        
        # Log metrics
        phase_logger.log_metric("executive_bullets_count", len(result.get("executive_summary", {}).get("bullets", [])))
        phase_logger.log_metric("categories_in_summary", len(result.get("category_analysis", [])))
        phase_logger.log_metric("gls_in_drilldown", len(result.get("gl_drilldown", [])))
        
        phase_logger.end_phase(
            "Phase 5: Synthesis & Structuring",
            output_data={
                "levels_generated": 3,
                "executive_summary_length": len(str(result.get("executive_summary", {})))
            },
            status="completed"
        )
        
        return result
    
    except Exception as e:
        phase_logger.log_error(f"Synthesis failed: {str(e)}", e)
        phase_logger.end_phase("Phase 5: Synthesis & Structuring", status="failed")
        raise
```

### Phase 6: Alert Scoring & Persistence

Update `sub_agents/persist_insights_agent.py`:

```python
async def _run_async_impl(self, ctx):
    phase_logger = ctx.session.state.get("phase_logger")
    
    phase_logger.start_phase(
        "Phase 6: Alert Scoring & Persistence",
        description="Scores alerts by priority and saves results to JSON files",
        input_data={
            "cost_center": ctx.session.state.get("current_cost_center"),
            "synthesis_complete": "synthesis_result" in ctx.session.state
        }
    )
    
    try:
        # Score alerts
        alerts = await self.score_alerts(ctx)
        
        # Persist results
        output_files = await self.persist_results(ctx)
        
        # Log metrics
        phase_logger.log_metric("alerts_extracted", len(alerts))
        phase_logger.log_metric("high_priority_alerts", len([a for a in alerts if a.get("priority") == "high"]))
        phase_logger.log_metric("output_files_written", len(output_files))
        
        phase_logger.end_phase(
            "Phase 6: Alert Scoring & Persistence",
            output_data={
                "alerts_scored": len(alerts),
                "files_saved": output_files
            },
            status="completed"
        )
        
        # Save complete phase summary
        phase_logger.save_phase_summary()
        
        return {"alerts": alerts, "files": output_files}
    
    except Exception as e:
        phase_logger.log_error(f"Alert scoring/persistence failed: {str(e)}", e)
        phase_logger.end_phase("Phase 6: Alert Scoring & Persistence", status="failed")
        raise
```

## Decorator Integration

For cleaner code, use the `@phase_logged` decorator:

```python
from pl_analyst_agent.utils.phase_logger import phase_logged

@phase_logged("Phase 1: Data Ingestion & Validation", 
              "Fetches P&L data, ops metrics, and validates data quality")
async def _run_async_impl(self, ctx):
    # Your code here - phase logging is automatic
    result = await self.ingest_and_validate(ctx)
    
    # You can still log custom metrics
    phase_logger = ctx.session.state.get("phase_logger")
    phase_logger.log_metric("records_fetched", len(result.get("time_series", [])))
    
    return result
```

## Configuration

### Edit `config/phase_logging.yaml`

```yaml
# Enable/disable specific phases
phases:
  data_ingestion:
    enabled: true
    log_metrics:
      - records_fetched
      - data_quality_score
  
  # ... other phases
```

### Environment Variables

```bash
# Override in .env
PHASE_LOGGING_ENABLED=true
PHASE_LOG_LEVEL=DEBUG  # DEBUG, INFO, WARNING, ERROR
PHASE_LOG_DIRECTORY=logs
```

## Output Files

Phase logging generates these files in `logs/`:

### 1. Per-Cost-Center Log Files

```
logs/
├── cost_center_067_20250127_143022.log   # Detailed phase-by-phase log
├── cost_center_067_20250127_143022.json  # Structured JSON log
└── phase_summary_cc067_20250127_143157.json  # Complete summary
```

### 2. Phase Summary JSON Structure

```json
{
  "cost_center": "067",
  "session_start": "2025-01-27T14:30:22",
  "session_end": "2025-01-27T14:31:57",
  "total_duration_seconds": 95.3,
  "phases": {
    "phase_1_data_ingestion_validation": {
      "name": "Phase 1: Data Ingestion & Validation",
      "description": "Fetches P&L data, ops metrics, and validates data quality",
      "start_time": 1706364622.123,
      "end_time": 1706364642.456,
      "duration_seconds": 20.333,
      "status": "completed",
      "input_summary": {
        "cost_center": "067",
        "date_ranges": {...}
      },
      "output_summary": {
        "record_count": 285,
        "quality_score": 0.95
      },
      "metrics": {
        "records_fetched": 285,
        "data_quality_score": 0.95,
        "missing_periods": 2
      },
      "errors": [],
      "warnings": ["2 periods missing data"]
    },
    // ... other phases
  },
  "summary_statistics": {
    "total_phases": 6,
    "phases_completed": 6,
    "phases_failed": 0,
    "phases_skipped": 0,
    "total_duration_seconds": 95.3,
    "total_errors": 0,
    "total_warnings": 3,
    "success_rate": 1.0
  }
}
```

## Examples

### Example 1: Basic Phase Logging

```python
from pl_analyst_agent.utils.phase_logger import PhaseLogger

# Initialize
phase_logger = PhaseLogger(cost_center="067")

# Start phase
phase_logger.start_phase("Phase 1: Data Ingestion & Validation")

# Do work
data = fetch_data()

# Log metrics
phase_logger.log_metric("records_fetched", len(data))

# End phase
phase_logger.end_phase("Phase 1: Data Ingestion & Validation")

# Save summary
phase_logger.save_phase_summary()
```

### Example 2: Error Handling

```python
try:
    phase_logger.start_phase("Phase 2: Category Analysis")
    result = analyze_categories()
    phase_logger.end_phase("Phase 2: Category Analysis", status="completed")
except ValueError as e:
    phase_logger.log_error("Invalid data format", e)
    phase_logger.end_phase("Phase 2: Category Analysis", status="failed")
```

### Example 3: Conditional Warnings

```python
phase_logger.start_phase("Phase 3: GL Drill-Down")

for gl in gls_to_analyze:
    if gl.variance < threshold:
        phase_logger.log_warning(f"GL {gl.number} below materiality threshold")

phase_logger.end_phase("Phase 3: GL Drill-Down")
```

## Viewing Logs

### Console Output

```
2025-01-27 14:30:22 | pl_analyst.067 | INFO | ================================================================================
2025-01-27 14:30:22 | pl_analyst.067 | INFO | STARTING: Phase 1: Data Ingestion & Validation
2025-01-27 14:30:22 | pl_analyst.067 | INFO | Description: Fetches P&L data, ops metrics, and validates data quality
2025-01-27 14:30:22 | pl_analyst.067 | INFO | ================================================================================
2025-01-27 14:30:42 | pl_analyst.067 | INFO | Metric [phase_1_data_ingestion_validation]: records_fetched = 285
2025-01-27 14:30:42 | pl_analyst.067 | INFO | ================================================================================
2025-01-27 14:30:42 | pl_analyst.067 | INFO | COMPLETED: Phase 1: Data Ingestion & Validation [COMPLETED]
2025-01-27 14:30:42 | pl_analyst.067 | INFO | Duration: 20.33s
2025-01-27 14:30:42 | pl_analyst.067 | INFO | ================================================================================
```

### Read Log Files

```python
import json

# Read phase summary
with open("logs/phase_summary_cc067_20250127_143157.json") as f:
    summary = json.load(f)

print(f"Total duration: {summary['total_duration_seconds']}s")
print(f"Success rate: {summary['summary_statistics']['success_rate'] * 100}%")

# List all phases
for phase_name, phase_info in summary['phases'].items():
    print(f"{phase_info['name']}: {phase_info['duration_seconds']}s - {phase_info['status']}")
```

## Performance Analysis

Use logged metrics to optimize your pipeline:

```python
# Find slowest phases
for phase_name, phase in summary['phases'].items():
    if phase['duration_seconds'] > 30:
        print(f"SLOW: {phase['name']} took {phase['duration_seconds']}s")

# Identify error patterns
for phase_name, phase in summary['phases'].items():
    if phase['errors']:
        print(f"ERRORS in {phase['name']}: {len(phase['errors'])}")
```

## Best Practices

1. **Initialize early**: Create `PhaseLogger` at the start of your session
2. **Be specific**: Use descriptive phase names matching your README
3. **Log metrics**: Track key performance indicators for each phase
4. **Handle errors**: Always wrap phase execution in try/except
5. **Save summaries**: Call `save_phase_summary()` at the end
6. **Review logs**: Regularly check logs for performance bottlenecks
7. **Sanitize data**: Never log PII or sensitive information

## Troubleshooting

### Logs not appearing?

Check that:
- `PHASE_LOGGING_ENABLED=true` in `.env`
- `logs/` directory exists and is writable
- Phase logger is initialized before first phase

### Missing metrics?

Ensure you're calling `log_metric()` within an active phase:
```python
phase_logger.start_phase("Phase X")  # Must call first
phase_logger.log_metric("my_metric", value)  # Then log metrics
```

### Phase summary empty?

Make sure to:
1. Start each phase with `start_phase()`
2. End each phase with `end_phase()`
3. Save with `save_phase_summary()` at the end

## Additional Resources

- See `config/phase_logging.yaml` for all configuration options
- See `utils/phase_logger.py` for implementation details
- See README.md for phase descriptions and workflow

