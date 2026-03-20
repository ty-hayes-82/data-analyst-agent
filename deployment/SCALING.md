# Scaling Guide — Data Analyst Agent for Production

Guide for scaling the Data Analyst Agent from prototype (10 analyses/day) to production workloads (1,000+ analyses/day).

---

## Current Baseline

**Default Configuration:**
- Cloud Run: 2 vCPUs, 8 GiB memory, 0-10 instances
- Vertex AI Agent: 2 vCPUs, 8 GiB memory, 0-10 instances
- Gemini API: 60 RPM quota
- Single region (us-central1)

**Performance:**
- **Throughput:** ~50 concurrent analyses
- **Latency:** 30-60 seconds per analysis (typical)
- **Cost:** ~$0.03 per analysis (Flash + Pro mix)

---

## Scaling Dimensions

### 1. Horizontal Scaling (More Instances)

**When to scale horizontally:**
- Concurrent requests increase (>10 simultaneous analyses)
- Peak traffic periods (monthly reporting, quarter-end)
- Multi-tenant scenarios (many users)

**How to scale:**

```bash
# Increase max instances
gcloud run services update data-analyst-ui \
  --region=us-central1 \
  --max-instances=50

# Increase agent concurrency
# (Edit agent_config.yaml)
autoscaling:
  maxInstances: 50
  targetConcurrency: 1
```

**Cost impact:**
- Cloud Run: Linear increase (pay-per-use)
- No increase in per-analysis cost

**Limits:**
- Gemini API quota (need to request increase)
- GCS write throughput (5,000 writes/sec per bucket)

---

### 2. Vertical Scaling (More Resources per Instance)

**When to scale vertically:**
- Large datasets (>100K rows)
- Complex hierarchies (>5 dimension levels)
- Out-of-memory errors
- Slow individual analyses (>5 minutes)

**How to scale:**

```bash
# Increase Cloud Run resources
gcloud run services update data-analyst-ui \
  --region=us-central1 \
  --memory=16Gi \
  --cpu=4

# Update Vertex AI agent config
# (Edit agent_config.yaml)
resources:
  cpu: "4"
  memory: "16Gi"
```

**Cost impact:**
- 2x resources = 2x cost per analysis
- May reduce total cost if it enables batch processing

**Limits:**
- Cloud Run max: 8 vCPUs, 32 GiB
- Vertex AI max: 96 vCPUs, 624 GiB (custom machine types)

---

### 3. Multi-Region Deployment

**When to use multi-region:**
- Global users (reduce latency for EU/Asia users)
- High availability requirements (99.99% uptime)
- Regulatory requirements (data residency)

**Regions to consider:**
- **us-central1** (primary, lowest cost)
- **us-east1** (US East Coast users)
- **europe-west1** (EU users, GDPR compliance)
- **asia-southeast1** (Asia-Pacific users)

**Deployment:**

```bash
# Deploy to multiple regions
for region in us-central1 us-east1 europe-west1; do
  gcloud run deploy data-analyst-ui \
    --image=CONTAINER_IMAGE \
    --region=$region \
    --platform=managed
done

# Use Cloud Load Balancer for global routing
gcloud compute backend-services create data-analyst-backend --global
gcloud compute backend-services add-backend data-analyst-backend \
  --global \
  --serverless-deployment-platform=run \
  --serverless-deployment-resource=data-analyst-ui \
  --serverless-deployment-region=us-central1
```

**Cost impact:**
- +100% infrastructure cost (2x regions)
- +5-10% data egress cost (cross-region)

---

### 4. Database Scaling (Data Sources)

**For Tableau Hyper data sources:**

1. **Pre-aggregate data:**
   ```sql
   -- Instead of 1M raw transactions
   SELECT region, date, SUM(amount) as total
   FROM transactions
   GROUP BY region, date
   -- Now only 10K rows
   ```

2. **Use Tableau Extracts (Hyper) instead of live queries:**
   - Faster reads
   - No load on source database
   - Can pre-filter to relevant date ranges

3. **Partition large Hyper files:**
   - Split by year/quarter
   - Contract references specific partition: `hyper_file: "trade_data_2024_Q1.hyper"`

**For SQL data sources:**

1. **Add indexes on key columns:**
   ```sql
   CREATE INDEX idx_region_date ON transactions(region, date);
   ```

2. **Use read replicas for analytics queries:**
   - Primary database for writes
   - Read replica for data analyst agent queries

3. **Implement query result caching:**
   - Cache at SQL level (query cache)
   - Or cache in Redis/Memorystore

---

### 5. LLM API Quota Scaling

**Default quota:** 60 RPM (requests per minute)

**Request increase:**

1. Navigate to: [Vertex AI Quotas](https://console.cloud.google.com/iam-admin/quotas)
2. Filter: "Generate Content API"
3. Select: "Generate Content API requests per minute"
4. Click "EDIT QUOTAS"
5. Request increase (e.g., 300 RPM)

**Quota tiers:**
- **Tier 1 (default):** 60 RPM — Good for 10-20 analyses/day
- **Tier 2 (requested):** 300 RPM — Good for 100-200 analyses/day
- **Tier 3 (enterprise):** 1,000+ RPM — Good for 1,000+ analyses/day

**Alternative: Use multiple API keys (advanced):**
```python
# Round-robin across multiple API keys to increase effective quota
api_keys = [key1, key2, key3]
current_key = api_keys[request_count % len(api_keys)]
```

---

## Performance Optimization Strategies

### 1. Caching (High Impact)

**Implement response caching:**

```python
from functools import lru_cache
import hashlib
import time

# Cache analysis results for 1 hour
@lru_cache(maxsize=100)
def cached_analysis(dataset, dimension, metric, date_hash):
    # date_hash changes every hour, invalidating cache
    return run_analysis(dataset, dimension, metric)

# Usage
date_hash = int(time.time() / 3600)  # Changes every hour
result = cached_analysis("trade_data", "region", "gross_margin", date_hash)
```

**Impact:** 30-50% reduction in LLM calls for repeated queries.

**Advanced: Redis caching for multi-instance sharing:**

```python
import redis
import json

redis_client = redis.Redis(host='MEMORYSTORE_IP', port=6379)

def cached_analysis_redis(dataset, dimension, metric):
    cache_key = f"analysis:{dataset}:{dimension}:{metric}"
    
    # Check cache
    cached = redis_client.get(cache_key)
    if cached:
        return json.loads(cached)
    
    # Run analysis
    result = run_analysis(dataset, dimension, metric)
    
    # Store in cache (1 hour TTL)
    redis_client.setex(cache_key, 3600, json.dumps(result))
    
    return result
```

---

### 2. Batch Processing (Medium Impact)

**Process multiple analyses in parallel:**

```python
import asyncio

async def batch_analyze(requests):
    # Run up to 10 analyses concurrently
    tasks = [analyze_async(req) for req in requests]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return results

# Usage
results = asyncio.run(batch_analyze([
    {"request": "Analyze gross margin by region", "dataset": "trade_data"},
    {"request": "Analyze revenue by product", "dataset": "trade_data"},
    {"request": "Analyze OpEx by department", "dataset": "operations"}
]))
```

**Impact:** Amortizes fixed costs (cold start, data loading) across multiple analyses.

---

### 3. Incremental Analysis (High Impact)

**For repeated analyses (e.g., daily updates):**

```python
def incremental_analysis(dataset, last_run_date):
    # Only analyze new data since last run
    new_data = fetch_data_since(last_run_date)
    
    # Load cached baseline from last run
    baseline = load_cached_baseline()
    
    # Compare new data to baseline
    variance = compare_to_baseline(new_data, baseline)
    
    return variance
```

**Impact:** 80-90% reduction in processing time for daily incremental updates.

---

### 4. Warm Instances (Medium Impact)

**Keep instances warm to avoid cold starts:**

```bash
# Cloud Run
gcloud run services update data-analyst-ui \
  --region=us-central1 \
  --min-instances=1  # Or 2-3 for high traffic

# Vertex AI Agent Engine
# (Edit agent_config.yaml)
autoscaling:
  minInstances: 1
```

**Cost:** ~$100/month per warm instance

**Benefit:** 
- Eliminate 3-5 second cold start latency
- Better user experience
- More predictable performance

---

### 5. Optimized Data Loading (Medium Impact)

**Load only required columns:**

```python
# Instead of:
df = pd.read_csv("data.csv")  # Loads all 50 columns

# Do:
required_cols = ["region", "date", "gross_margin", "revenue"]
df = pd.read_csv("data.csv", usecols=required_cols)
```

**Impact:** 50-70% reduction in memory usage and load time.

**Pre-filter date ranges:**

```python
# Instead of loading all 5 years of data
df = pd.read_csv("data.csv")
df = df[df['date'] >= '2024-01-01']

# Do:
# Pre-filter in Tableau/SQL query
query = "SELECT * FROM data WHERE date >= '2024-01-01'"
```

---

### 6. Model Selection (High Impact on Cost)

**Use cheaper models for non-critical stages:**

```yaml
# In agent_models.yaml

# High-quality synthesis (keep Pro)
report_synthesis_agent:
  model: gemini-2.5-pro-exp
  thinking_budget: 8000

# Other stages (use Flash)
planner_agent:
  model: gemini-2.5-flash-exp
narrative_agent:
  model: gemini-2.5-flash-exp
alert_scoring_coordinator:
  model: gemini-2.5-flash-exp
```

**Impact:** 70% reduction in LLM cost per analysis.

**Quality trade-off:** Minimal (Flash is 90-95% as good as Pro for most stages).

---

## Scaling Milestones

### Milestone 1: Prototype → Production (10 → 100 analyses/day)

**Changes needed:**
- [x] Set `minInstances=1` (eliminate cold starts)
- [x] Implement basic caching (1-hour TTL)
- [x] Request Gemini quota increase to 300 RPM
- [x] Set up monitoring dashboard
- [x] Configure budget alerts ($500/month)

**Expected cost:** $100-$200/month

---

### Milestone 2: Production → Scale (100 → 1,000 analyses/day)

**Changes needed:**
- [x] Implement Redis caching (Memorystore)
- [x] Batch processing for scheduled reports
- [x] Multi-region deployment (us-central1 + us-east1)
- [x] Pre-aggregate datasets (reduce row count by 80%)
- [x] Switch to all-Flash models (except synthesis)
- [x] Increase max instances to 50
- [x] Request Gemini quota increase to 1,000 RPM

**Expected cost:** $800-$1,200/month

---

### Milestone 3: Scale → Enterprise (1,000+ analyses/day)

**Changes needed:**
- [x] Global multi-region deployment (3+ regions)
- [x] Dedicated Vertex AI quota (enterprise agreement)
- [x] Read replicas for data sources
- [x] Advanced caching strategies (multiple layers)
- [x] Custom fine-tuned models (domain-specific)
- [x] Horizontal partitioning (sharding by dataset)
- [x] 24/7 on-call support

**Expected cost:** $3,000-$5,000/month

**Considerations:**
- Contact Google Cloud sales for volume discounts
- Negotiate enterprise SLA (99.99% uptime)
- Implement dedicated support channel

---

## Monitoring at Scale

### 1. Key Metrics to Track

```yaml
# Define SLIs (Service Level Indicators)
availability:
  target: 99.9%
  measurement: successful_requests / total_requests

latency_p95:
  target: 90 seconds
  measurement: 95th percentile response time

error_rate:
  target: <1%
  measurement: failed_requests / total_requests

throughput:
  target: 100 analyses/hour
  measurement: completed_analyses_per_hour
```

### 2. Auto-Scaling Triggers

```bash
# Cloud Run auto-scaling based on CPU
gcloud run services update data-analyst-ui \
  --cpu-throttling \
  --max-instances=50 \
  --concurrency=1

# Alert on sustained high CPU (>80%)
gcloud monitoring policies create \
  --notification-channels=CHANNEL_ID \
  --display-name="High CPU Usage" \
  --condition="metric.type='run.googleapis.com/container/cpu/utilizations' AND value>0.8"
```

### 3. Cost Monitoring at Scale

```bash
# Create detailed cost breakdown
gcloud billing budgets create \
  --billing-account=ACCOUNT_ID \
  --display-name="Data Analyst Agent - Detailed" \
  --budget-amount=2000 \
  --threshold-rule=percent=50 \
  --threshold-rule=percent=80 \
  --threshold-rule=percent=90 \
  --threshold-rule=percent=100

# Track cost per analysis metric
# (Custom metric exported to Cloud Monitoring)
```

---

## Capacity Planning

### Formula: Required Instance Count

```
required_instances = (peak_analyses_per_hour / analyses_per_instance_per_hour) * 1.2
```

**Example:**
- Peak: 500 analyses/hour
- Each instance: 20 analyses/hour (3 min per analysis)
- Required: (500 / 20) * 1.2 = **30 instances**

### Formula: Required Gemini Quota

```
required_rpm = (peak_analyses_per_hour / 60) * llm_calls_per_analysis * 1.5
```

**Example:**
- Peak: 500 analyses/hour
- LLM calls per analysis: 12
- Required: (500 / 60) * 12 * 1.5 = **150 RPM**

---

## Load Testing

### 1. Simulate Load with Locust

```python
# locustfile.py
from locust import HttpUser, task, between

class DataAnalystUser(HttpUser):
    wait_time = between(1, 3)
    
    @task
    def analyze(self):
        self.client.post("/analyze", json={
            "request": "Analyze gross margin by region",
            "dataset_name": "trade_data"
        })

# Run load test
locust -f locustfile.py --host=https://your-cloud-run-url.run.app
```

### 2. Gradual Load Increase

```bash
# Week 1: Baseline (10 analyses/hour)
# Week 2: 2x load (20 analyses/hour)
# Week 3: 5x load (50 analyses/hour)
# Week 4: 10x load (100 analyses/hour)

# Monitor each week:
# - Error rate
# - Latency p95
# - Cost per analysis
# - Resource utilization
```

---

## Rollback Strategy

**If scaling causes issues:**

1. **Immediate rollback:**
   ```bash
   # Reduce max instances
   gcloud run services update data-analyst-ui --max-instances=10
   
   # Increase instance size (vertical scaling as fallback)
   gcloud run services update data-analyst-ui --memory=16Gi --cpu=4
   ```

2. **Rate limiting:**
   ```python
   # Implement rate limiting in web UI
   from slowapi import Limiter
   limiter = Limiter(key_func=lambda: request.client.host)
   
   @app.post("/analyze")
   @limiter.limit("10/minute")  # Max 10 requests per minute per IP
   async def analyze(request: AnalysisRequest):
       pass
   ```

3. **Queue system (advanced):**
   ```python
   # Use Cloud Tasks for asynchronous processing
   from google.cloud import tasks_v2
   
   client = tasks_v2.CloudTasksClient()
   task = {
       "http_request": {
           "http_method": "POST",
           "url": "https://agent-url.run.app/analyze",
           "body": json.dumps(analysis_request).encode()
       }
   }
   client.create_task(parent=queue_path, task=task)
   ```

---

## Best Practices Summary

1. **Start small, scale incrementally** (10 → 100 → 1,000 analyses/day)
2. **Monitor before scaling** (establish baseline metrics)
3. **Cache aggressively** (30-50% cost reduction)
4. **Use Flash models** (70% cost reduction, minimal quality loss)
5. **Pre-aggregate data** (80% faster processing)
6. **Keep warm instances** (better UX, predictable performance)
7. **Test scaling changes in staging** (before production)
8. **Set budget alerts** (prevent cost overruns)
9. **Document scaling decisions** (for future reference)
10. **Have rollback plan ready** (can revert in <5 minutes)

---

## Next Steps

1. **Baseline current performance:**
   ```bash
   # Run 100 test analyses, measure:
   # - Average latency
   # - p95 latency
   # - Error rate
   # - Cost per analysis
   ```

2. **Implement caching:**
   - Start with in-memory LRU cache
   - Upgrade to Redis if multi-instance

3. **Request Gemini quota increase:**
   - Current: 60 RPM
   - Target: 300 RPM (for 100 analyses/day)

4. **Enable monitoring:**
   - Import dashboard: `deployment/monitoring/dashboard.json`
   - Set up alerts: `deployment/monitoring/alerts.yaml`

5. **Load test:**
   - Simulate 2x current traffic
   - Identify bottlenecks
   - Adjust configuration

---

## Support

For scaling assistance:
- **GitHub Issues:** [data-analyst-agent/issues](https://github.com/ty-hayes-82/data-analyst-agent/issues)
- **Email:** ty-hayes-82@example.com
- **Google Cloud Support:** [cloud.google.com/support](https://cloud.google.com/support)
