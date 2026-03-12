# Cloud Architecture — Data Analyst Agent on GCP

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         End Users                                   │
└──────────────┬──────────────────────────────────────────────────────┘
               │
               ↓
┌──────────────────────────────────────────────────────────────────────┐
│                      Cloud Run (Web UI)                              │
│  - FastAPI/Uvicorn                                                   │
│  - Authentication                                                    │
│  - Request routing                                                   │
└──────────────┬───────────────────────────────────────────────────────┘
               │
               ↓
┌──────────────────────────────────────────────────────────────────────┐
│               Vertex AI Agent Engine                                 │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │  Root Agent (SequentialAgent)                                  │ │
│  │    │                                                            │ │
│  │    ├─→ ContractLoader ──→ [Read from GCS]                      │ │
│  │    ├─→ DataFetchWorkflow ──→ [Tableau/CSV/SQL]                 │ │
│  │    ├─→ ParallelDimensionTargetAgent (fan-out per dimension)    │ │
│  │    │      │                                                     │ │
│  │    │      ├─→ DynamicParallelAnalysisAgent (3+ agents)         │ │
│  │    │      │      ├─→ HierarchyVarianceAgent                    │ │
│  │    │      │      ├─→ StatisticalInsightsAgent                  │ │
│  │    │      │      └─→ SeasonalBaselineAgent                     │ │
│  │    │      ├─→ NarrativeAgent (Gemini LLM)                      │ │
│  │    │      ├─→ AlertScoringAgent                                │ │
│  │    │      ├─→ ReportSynthesisAgent (Gemini LLM)                │ │
│  │    │      └─→ OutputPersistenceAgent ──→ [Write to GCS]        │ │
│  │    └─→ CrossMetricExecutiveBrief                               │ │
│  └────────────────────────────────────────────────────────────────┘ │
└──────────────┬───────────────────────────────────────────────────────┘
               │
               ├──────────────────────────────────────────────┐
               │                                              │
               ↓                                              ↓
┌──────────────────────────────┐        ┌────────────────────────────────┐
│   Vertex AI (Gemini API)     │        │  Cloud Storage (GCS)           │
│  - gemini-2.5-flash-exp      │        │  ┌──────────────────────────┐  │
│  - gemini-2.5-pro-exp        │        │  │ Datasets Bucket          │  │
│  - Token-based pricing       │        │  │  - contract.yaml         │  │
│                              │        │  │  - validation data       │  │
└──────────────────────────────┘        │  └──────────────────────────┘  │
                                        │  ┌──────────────────────────┐  │
┌──────────────────────────────┐        │  │ Outputs Bucket           │  │
│   Secret Manager             │        │  │  - analysis JSON         │  │
│  - google-api-key            │        │  │  - executive briefs      │  │
│  - service-account-json      │        │  │  - PDF reports           │  │
└──────────────────────────────┘        │  └──────────────────────────┘  │
                                        └────────────────────────────────┘
┌──────────────────────────────┐
│  Cloud Logging & Monitoring  │        ┌────────────────────────────────┐
│  - Structured logs           │        │  Artifact Registry             │
│  - Metrics                   │        │  - Agent container images      │
│  - Traces                    │        │  - Web UI container images     │
│  - Alert policies            │        └────────────────────────────────┘
└──────────────────────────────┘
```

---

## Component Details

### 1. Cloud Run (Web UI)

**Purpose:** User-facing web interface for agent invocations.

**Tech Stack:**
- FastAPI + Uvicorn (async ASGI server)
- Gunicorn (process manager)
- Jinja2 templates

**Configuration:**
- Memory: 4 GiB
- CPU: 2 vCPUs
- Max instances: 10
- Request timeout: 600s (10 min)
- Auto-scaling: 0-10 instances based on request concurrency

**Authentication:**
- Public (allow-unauthenticated) for demo/testing
- IAM-based (invoker role) for production

**Endpoints:**
- `GET /` — Web UI homepage
- `POST /analyze` — Submit analysis request
- `GET /status/{analysis_id}` — Poll analysis status
- `GET /results/{analysis_id}` — Download results
- `GET /health` — Health check

---

### 2. Vertex AI Agent Engine

**Purpose:** Hosts and orchestrates the ADK-based multi-agent pipeline.

**Agent Hierarchy:**

```
root_agent (SequentialAgent)
├── ContractLoader (BaseAgent)
├── CLIParameterInjector (BaseAgent)
├── OutputDirInitializer (BaseAgent)
├── data_fetch_workflow (SequentialAgent)
│   ├── DateInitializer (BaseAgent)
│   └── DataFetcher (BaseAgent or A2A agent)
├── ParallelDimensionTargetAgent (custom BaseAgent with fan-out)
│   └── [For each dimension value]
│       ├── AnalysisContextInitializer (BaseAgent)
│       ├── planner_agent (LlmAgent)
│       ├── DynamicParallelAnalysisAgent (ParallelAgent)
│       │   ├── HierarchyVarianceAgent (SequentialAgent)
│       │   ├── StatisticalInsightsAgent (LlmAgent)
│       │   └── SeasonalBaselineAgent (BaseAgent)
│       ├── narrative_agent (LlmAgent)
│       ├── alert_scoring_coordinator (LlmAgent or BaseAgent)
│       ├── report_synthesis_agent (LlmAgent)
│       └── OutputPersistenceAgent (BaseAgent)
└── CrossMetricExecutiveBrief (LlmAgent)
```

**State Management:**
- All data flows through `session.state` (ADK whiteboard model)
- No global variables
- Each agent writes to unique `output_key` to prevent collisions
- `data_cache.py` uses `sys.modules` hack for DataFrame sharing (needs initialization guards)

**Resource Limits:**
- Memory: 8 GiB
- CPU: 2 vCPUs
- Timeout: 3600s (1 hour)
- Auto-scaling: 0-10 instances

---

### 3. Gemini API (Vertex AI)

**Models Used:**

| Agent                   | Model                     | Purpose                      |
|-------------------------|---------------------------|------------------------------|
| planner_agent           | gemini-2.5-flash-exp      | Generate execution plan      |
| narrative_agent         | gemini-2.5-flash-exp      | Semantic insight cards       |
| report_synthesis_agent  | gemini-2.5-pro-exp        | Executive brief synthesis    |
| alert_scoring (optional)| gemini-2.5-flash-exp      | Alert prioritization (LLM)   |

**Token Usage (typical analysis):**
- Input: 20K-50K tokens (data + context + prompts)
- Output: 5K-15K tokens (narratives + synthesis)
- **Total: ~30K-65K tokens per analysis**

**Cost:**
- Flash: $0.15/1M input, $0.60/1M output
- Pro: $1.25/1M input, $5.00/1M output

**Rate Limits:**
- Default: 60 RPM (requests per minute)
- Can request increase via quota management

---

### 4. Cloud Storage (GCS)

**Buckets:**

1. **Datasets Bucket** (`${PROJECT_ID}-data-analyst-datasets`)
   - Dataset contracts (`datasets/*/contract.yaml`)
   - Validation data (`validation/`)
   - Sample/synthetic data (`synthetic/`)
   - **Retention:** Indefinite (versioning enabled)

2. **Outputs Bucket** (`${PROJECT_ID}-data-analyst-outputs`)
   - Analysis JSON (`analysis/YYYY-MM-DD_*.json`)
   - Executive briefs (`executive_briefs/*.pdf`, `*.md`)
   - Logs (`logs/`)
   - **Retention:** 90 days (lifecycle policy)

**Access Control:**
- Service account has `roles/storage.objectAdmin` on outputs bucket
- Service account has `roles/storage.objectViewer` on datasets bucket

**Signed URLs:**
- Used for sharing PDF reports with external users
- Expiration: 7 days

---

### 5. Secret Manager

**Secrets Stored:**

1. **google-api-key** (required)
   - Gemini API key for LLM calls
   - Accessed by service account

2. **service-account-json** (optional)
   - Service account credentials for external APIs (Tableau, SQL)
   - Only needed if not using Application Default Credentials

**Access Pattern:**
```python
from google.cloud import secretmanager
client = secretmanager.SecretManagerServiceClient()
secret_name = f"projects/{project_id}/secrets/google-api-key/versions/latest"
response = client.access_secret_version(request={"name": secret_name})
api_key = response.payload.data.decode("UTF-8")
```

---

### 6. Artifact Registry

**Repository:** `us-central1-docker.pkg.dev/${PROJECT_ID}/data-analyst-agent`

**Images:**
- `agent:latest` — ADK agent runtime container
- `agent:{git_sha}` — Versioned agent builds
- `web-ui:latest` — Web UI container
- `web-ui:{git_sha}` — Versioned web UI builds

**Image Size:**
- Agent: ~2.5 GB (includes Python, ADK, pandas, scipy, matplotlib)
- Web UI: ~1.5 GB (includes FastAPI, agent code)

**Build Process:**
- GitHub Actions or Cloud Build
- Multi-stage Docker builds for size optimization

---

### 7. Cloud Logging & Monitoring

**Logging:**
- Structured JSON logs sent to Cloud Logging
- Log levels: DEBUG, INFO, WARNING, ERROR, CRITICAL
- Retention: 30 days (configurable)

**Metrics:**
- `analysis_duration` (gauge) — Time per analysis
- `llm_calls` (counter) — Total LLM API calls
- `llm_tokens` (counter) — Token consumption
- `error_count` (counter) — Failed analyses

**Traces:**
- Cloud Trace enabled for performance profiling
- Spans: contract loading, data fetch, LLM calls, output persistence

**Alerts:**
- High error rate (>10%)
- Slow response time (>10 min)
- High token usage (cost spike)
- No traffic (service down)

---

## Data Flow

### 1. User Submits Analysis Request

```
User (Web UI) → Cloud Run → Vertex AI Agent Engine
```

**Request payload:**
```json
{
  "request": "Analyze gross margin by region",
  "dataset_name": "trade_data"
}
```

### 2. Contract Loading

```
ContractLoader → GCS (datasets bucket) → contract.yaml
```

**Contract defines:**
- Dimensions (hierarchy levels)
- Metrics (variance types)
- Time configuration
- Data source (Tableau/CSV/SQL)

### 3. Data Fetching

```
DataFetchWorkflow → Tableau Hyper / CSV / SQL → DataFrame
```

**Data cached in:**
- `session.state['primary_data_csv']` (ADK state)
- `data_cache._cache` (sys.modules hack for cross-agent sharing)

### 4. Parallel Analysis

```
ParallelDimensionTargetAgent (fan-out per dimension value)
  └─→ For each entity (e.g., West Region, East Region):
      DynamicParallelAnalysisAgent (runs 3+ agents concurrently)
        ├─→ HierarchyVarianceAgent → hierarchy_results
        ├─→ StatisticalInsightsAgent → statistical_summary
        └─→ SeasonalBaselineAgent → seasonal_baseline
```

**State keys:**
```python
session.state[f"hierarchy_results_{dimension_value}"]
session.state[f"statistical_summary_{dimension_value}"]
session.state[f"seasonal_baseline_{dimension_value}"]
```

### 5. Narrative Generation

```
NarrativeAgent (Gemini LLM) → Semantic insight cards
```

**Input:**
- `hierarchy_results`
- `statistical_summary`
- `seasonal_baseline`
- Contract metadata

**Output:**
```python
session.state["narrative_cards"] = [
  {
    "title": "West Region — Margin Decline",
    "insight": "Gross margin down 8.5% due to higher COGS...",
    "severity": "high"
  },
  ...
]
```

### 6. Report Synthesis

```
ReportSynthesisAgent (Gemini LLM) → Executive brief
```

**Input:**
- All narrative cards
- Alert scores
- Top variance drivers

**Output:**
```python
session.state["executive_brief"] = {
  "summary": "...",
  "key_findings": [...],
  "recommendations": [...]
}
```

### 7. Output Persistence

```
OutputPersistenceAgent → GCS (outputs bucket)
  ├─→ analysis.json (structured data)
  ├─→ executive_brief.md (markdown)
  └─→ executive_brief.pdf (rendered PDF)
```

**GCS paths:**
```
gs://PROJECT-outputs/analysis/2024-03-12_gross_margin_region.json
gs://PROJECT-outputs/executive_briefs/2024-03-12_gross_margin_region.md
gs://PROJECT-outputs/executive_briefs/2024-03-12_gross_margin_region.pdf
```

### 8. Return Results to User

```
Vertex AI Agent Engine → Cloud Run → User (Web UI)
```

**Response payload:**
```json
{
  "status": "success",
  "analysis_id": "a1b2c3d4-...",
  "outputs": {
    "executive_brief_pdf": "gs://...",
    "executive_brief_md": "gs://...",
    "analysis_json": "gs://..."
  },
  "metrics": {
    "duration_seconds": 45,
    "llm_calls": 12,
    "total_tokens": 25000
  }
}
```

---

## Security Architecture

### 1. Authentication & Authorization

**Service Account:** `data-analyst-agent@${PROJECT_ID}.iam.gserviceaccount.com`

**IAM Roles:**
- `roles/aiplatform.user` — Vertex AI access
- `roles/storage.objectAdmin` — Write to outputs bucket
- `roles/storage.objectViewer` — Read from datasets bucket
- `roles/secretmanager.secretAccessor` — Access API keys
- `roles/logging.logWriter` — Write structured logs
- `roles/monitoring.metricWriter` — Publish custom metrics
- `roles/cloudtrace.agent` — Send traces

### 2. Network Security

**Cloud Run:**
- Ingress: All traffic (allow-unauthenticated for demo)
- Egress: All allowed (needs Gemini API, GCS access)

**Vertex AI Agent Engine:**
- Private endpoint (no public IP)
- VPC-SC compatible for data isolation

### 3. Data Encryption

**In-transit:**
- TLS 1.3 for all HTTPS traffic
- gRPC with mTLS for Gemini API

**At-rest:**
- GCS: AES-256 encryption (Google-managed keys)
- Secret Manager: Encrypted with Google Cloud KMS

### 4. Secrets Management

**Never store in code:**
- API keys
- Service account credentials
- Database passwords

**Always use Secret Manager:**
```python
from deployment.config.cloud_config import get_cloud_config
config = get_cloud_config()
api_key = config.get_secret("google-api-key")
```

---

## Scalability

### Horizontal Scaling

**Cloud Run:**
- Auto-scales from 0 to 10 instances
- Target concurrency: 1 (one request per instance)
- Cold start: ~3-5 seconds

**Vertex AI Agent Engine:**
- Auto-scales based on concurrent agent invocations
- Max concurrent: 10 (configurable)

### Vertical Scaling

**Increase resources if needed:**
```yaml
# In agent_config.yaml
resources:
  cpu: "4"       # Up from 2
  memory: "16Gi" # Up from 8Gi
```

### Caching Strategy

**Implement response caching:**
```python
from functools import lru_cache
import hashlib

@lru_cache(maxsize=100)
def cached_analysis(dataset, dimension, metric, date_hash):
    # Cache analysis results for 1 hour
    pass
```

**Impact:** 30-50% reduction in LLM calls for repeated queries.

---

## High Availability

**SLA:**
- Cloud Run: 99.95% uptime SLA
- Vertex AI: 99.9% uptime SLA (varies by model)
- Cloud Storage: 99.95% uptime SLA

**Fault Tolerance:**
- Automatic retries for transient failures
- Exponential backoff for rate limiting
- Graceful degradation (skip non-critical stages if failure)

**Disaster Recovery:**
- Multi-region deployment (deploy to us-central1 + us-east1)
- GCS versioning enabled (recover deleted outputs)
- Daily backups of datasets bucket

---

## Observability Stack

```
┌──────────────────────────────────────────────────────────┐
│                    Cloud Logging                         │
│  - Structured JSON logs                                  │
│  - Log-based metrics                                     │
│  - Error Reporting integration                           │
└──────────────────────────────────────────────────────────┘
                          ↓
┌──────────────────────────────────────────────────────────┐
│                   Cloud Monitoring                       │
│  - Custom metrics (analysis_duration, llm_tokens)        │
│  - Dashboards (pre-configured)                           │
│  - Alert policies (email, Slack, PagerDuty)              │
└──────────────────────────────────────────────────────────┘
                          ↓
┌──────────────────────────────────────────────────────────┐
│                     Cloud Trace                          │
│  - Request tracing (identify bottlenecks)                │
│  - Latency analysis by agent stage                       │
└──────────────────────────────────────────────────────────┘
```

---

## Cost Breakdown

See [cost_analysis.md](cost_analysis.md) for detailed cost projections.

**Summary (medium usage — 50 analyses/day):**
- Gemini API: $45/month
- Cloud Run: $5/month
- Cloud Storage: $2/month
- Monitoring: $10/month
- **Total: ~$160/month**

---

## Future Enhancements

1. **Multi-region deployment** (for global low-latency)
2. **Streaming responses** (progressive results as analysis runs)
3. **WebSocket support** (real-time progress updates)
4. **Result caching** (Redis/Memorystore for hot queries)
5. **Batch processing** (Cloud Tasks for asynchronous analyses)
6. **Custom models** (fine-tuned Gemini for domain-specific insights)

---

## References

- [Google ADK Documentation](https://github.com/google/adk-python)
- [Vertex AI Agent Engine](https://cloud.google.com/vertex-ai/docs/agent-engine)
- [Cloud Run Best Practices](https://cloud.google.com/run/docs/best-practices)
- [Cloud Storage Performance](https://cloud.google.com/storage/docs/request-rate)
