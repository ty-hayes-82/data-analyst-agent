# Data Analyst Agent — Agent Garden Listing

## Overview

**P&L Variance Data Analyst** is a Google ADK-based multi-agent system that automates financial variance analysis with hierarchical drill-down capabilities.

Perfect for finance teams, business analysts, and operations managers who need to:
- Quickly understand what's driving P&L variances
- Identify top performance issues across regions/products/cost centers
- Get natural language explanations of complex financial patterns
- Generate executive-ready reports with one query

## Key Features

### 🎯 Contract-Driven Analysis
- Define your data structure once in YAML
- Agent automatically adapts to your dimensions and metrics
- No code changes needed for new datasets

### 🔀 Parallel Deep Analysis
- Runs 3+ specialized analysis agents concurrently
- Hierarchy variance ranking (what's driving changes?)
- Statistical insights (trends, outliers, seasonality)
- Seasonal baseline comparison

### 📊 Multi-Dimensional Drill-Down
- Analyze by region, product, cost center, or any dimension
- Automatic top-down ranking of variance drivers
- Identifies most impactful entities at each level

### 🤖 LLM-Powered Narratives
- Natural language explanations of findings
- Semantic insight cards for each key finding
- Alert scoring and prioritization
- Executive brief synthesis

### 📄 Professional Outputs
- PDF executive briefs with bookmarks
- Markdown source for editing
- Structured JSON for integration
- GCS-hosted, shareable URLs

## Quick Start

### 1. Invoke the Agent

```bash
gcloud ai agents invoke data-analyst-agent \
  --region=us-central1 \
  --input='{
    "request": "Analyze gross margin by region",
    "dataset_name": "trade_data"
  }'
```

### 2. Retrieve Results

```json
{
  "status": "success",
  "analysis_id": "a1b2c3d4-5678-90ab-cdef-1234567890ab",
  "outputs": {
    "executive_brief_pdf": "gs://project-outputs/executive_briefs/2024-03-12_gross_margin_region.pdf",
    "executive_brief_md": "gs://project-outputs/executive_briefs/2024-03-12_gross_margin_region.md",
    "analysis_json": "gs://project-outputs/analysis/2024-03-12_gross_margin_region.json"
  },
  "summary": {
    "top_variance_driver": "West Region (-15.2%)",
    "total_variance_amount": -2450000,
    "alert_count": 3,
    "insight_cards": [...]
  },
  "metrics": {
    "duration_seconds": 45,
    "llm_calls": 12,
    "total_tokens": 25000
  }
}
```

### 3. Download PDF

```bash
gsutil cp gs://project-outputs/executive_briefs/2024-03-12_gross_margin_region.pdf ./
```

## Use Cases

### Financial Planning & Analysis (FP&A)
- Monthly variance reviews
- Budget vs. actual analysis
- Forecast accuracy assessment
- KPI tracking and alerting

### Operations Management
- Cost center performance monitoring
- Efficiency trend analysis
- Anomaly detection in operational metrics

### Business Intelligence
- Sales performance deep-dives
- Market segment analysis
- Product profitability reviews

### Executive Reporting
- Board-ready summaries
- Quarterly business reviews
- Strategic decision support

## Sample Queries

```
"Show me top 5 cost centers with largest budget overruns"
"Analyze revenue trends by product category for Q4"
"What's driving the variance in gross margin this month?"
"Compare West region performance to East region"
"Identify outliers in operating expenses by department"
```

## Supported Data Sources

- **Tableau Hyper** files (via A2A agents)
- **CSV** files (direct pandas loading)
- **SQL databases** (via ODBC connectors)

## Configuration

### Dataset Contract (YAML)

Define your data structure once:

```yaml
dataset_name: trade_data
display_name: "Trade Network P&L"

dimensions:
  - name: region
    display_name: "Region"
    hierarchy_level: 1
  
  - name: terminal
    display_name: "Terminal"
    hierarchy_level: 2

metrics:
  - name: gross_margin
    display_name: "Gross Margin"
    unit: "$"
    variance_type: maximize

time_config:
  primary_grain: month
  lookback_periods: 12
```

### Environment Variables

```bash
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_CLOUD_LOCATION=us-central1
ROOT_AGENT_MODEL=gemini-2.5-flash-exp
USE_CODE_INSIGHTS=true
EXECUTIVE_BRIEF_OUTPUT_FORMAT=pdf
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Root Agent (Sequential)                  │
└─────────────────────────────────────────────────────────────┘
                            │
    ┌───────────────────────┼───────────────────────┐
    │                       │                       │
┌───▼────┐          ┌──────▼──────┐       ┌───────▼────────┐
│Contract│          │Data Fetcher │       │Dimension Target│
│Loader  │          │  Workflow   │       │  Fan-Out       │
└────────┘          └─────────────┘       └────────────────┘
                                                  │
                    ┌─────────────────────────────┼─────────────────────────────┐
                    │                             │                             │
            ┌───────▼────────┐          ┌────────▼────────┐         ┌──────────▼─────────┐
            │ Parallel       │          │   Narrative     │         │  Report Synthesis  │
            │ Analysis       │──────────▶   Generator     │────────▶│    & Output        │
            │ (HVA, Stats,   │          │   (LLM)         │         │   Persistence      │
            │  Seasonal)     │          └─────────────────┘         └────────────────────┘
            └────────────────┘
```

## Pricing

**Estimated cost per analysis:** $0.50 - $2.00

Depends on:
- Dataset size (rows, dimensions)
- Model selection (Flash vs Pro)
- Analysis complexity (depth of drill-down)
- Number of parallel analyses

**Model costs:**
- Gemini 2.5 Flash: ~$0.15/1M input tokens, ~$0.60/1M output tokens
- Gemini 2.5 Pro: ~$1.25/1M input tokens, ~$5.00/1M output tokens

Typical analysis:
- 20K-50K input tokens (data + context)
- 5K-15K output tokens (narratives + synthesis)
- **Total: $0.50-$2.00 per run**

## Limitations

- **Max dataset size:** 100K rows (recommend aggregating larger datasets)
- **Max dimensions:** 10 (more = slower execution)
- **Max execution time:** 1 hour
- **Concurrent analyses:** 3 per project (increase via quota request)

## Security & Compliance

✅ **Data Privacy:**
- All processing in-memory only
- No persistent storage of customer data
- Outputs saved to customer-controlled GCS buckets

✅ **Encryption:**
- In-transit: TLS 1.3
- At-rest: AES-256 (GCS default)

✅ **Access Control:**
- IAM-based authorization
- VPC-SC support for data isolation
- Service account authentication

✅ **Compliance:**
- SOC 2 Type II
- GDPR Compliant

## Support

- **Documentation:** [GitHub Wiki](https://github.com/ty-hayes-82/data-analyst-agent/wiki)
- **Issues:** [GitHub Issues](https://github.com/ty-hayes-82/data-analyst-agent/issues)
- **Email:** ty-hayes-82@example.com
- **Slack:** [Join Community](https://example-workspace.slack.com/channels/data-analyst-agent)

## Version History

- **1.0.0** (2024-03-12): Initial Agent Garden release
  - Contract-driven architecture
  - Parallel analysis pipeline
  - PDF executive briefs
  - Vertex AI Agent Engine deployment

## License

Apache 2.0 — See [LICENSE](https://github.com/ty-hayes-82/data-analyst-agent/blob/main/LICENSE)
