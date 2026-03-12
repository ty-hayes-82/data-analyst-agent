# Cost Analysis & Optimization Strategy

## Executive Summary

**Estimated Monthly Cost (Prod):** $300 - $1,500
- Low usage (10 analyses/day): ~$300/month
- Medium usage (50 analyses/day): ~$800/month
- High usage (200 analyses/day): ~$1,500/month

**Primary Cost Drivers:**
1. Gemini API calls (60-70% of total cost)
2. Cloud Run compute (20-25%)
3. Cloud Storage (5-10%)
4. Vertex AI Agent Engine (platform fee, if applicable)

---

## Detailed Cost Breakdown

### 1. Gemini API Costs

**Per-Analysis Token Usage (typical):**
- Input tokens: 20,000 - 50,000 (data + context + prompts)
- Output tokens: 5,000 - 15,000 (narratives + synthesis)

**Model Pricing (as of March 2024):**
- **Gemini 2.5 Flash:**
  - Input: $0.15/1M tokens
  - Output: $0.60/1M tokens
  
- **Gemini 2.5 Pro:**
  - Input: $1.25/1M tokens
  - Output: $5.00/1M tokens

**Cost per Analysis:**
- **All-Flash configuration:**
  - Input: 35K tokens × $0.15/1M = $0.005
  - Output: 10K tokens × $0.60/1M = $0.006
  - **Total: ~$0.01 per analysis**

- **Flash + Pro (current default):**
  - Flash stages: $0.008
  - Pro synthesis: $0.025
  - **Total: ~$0.03 per analysis**

- **All-Pro configuration:**
  - Input: 35K tokens × $1.25/1M = $0.044
  - Output: 10K tokens × $5.00/1M = $0.050
  - **Total: ~$0.09 per analysis**

**Monthly Projections:**
| Usage Level | Analyses/Day | Monthly Analyses | LLM Cost (Flash+Pro) | LLM Cost (All-Pro) |
|-------------|--------------|------------------|----------------------|--------------------|
| Low         | 10           | 300              | $9                   | $27                |
| Medium      | 50           | 1,500            | $45                  | $135               |
| High        | 200          | 6,000            | $180                 | $540               |

### 2. Cloud Run Costs

**Pricing (us-central1):**
- CPU: $0.00002400 per vCPU-second
- Memory: $0.00000250 per GiB-second
- Requests: $0.40 per million requests

**Per Analysis (2 vCPU, 8 GiB, 45s average execution):**
- CPU: 2 vCPU × 45s × $0.000024 = $0.002
- Memory: 8 GiB × 45s × $0.0000025 = $0.001
- Request: $0.0000004
- **Total: ~$0.003 per analysis**

**Monthly Projections:**
| Usage Level | Monthly Analyses | Cloud Run Cost |
|-------------|------------------|----------------|
| Low         | 300              | $1             |
| Medium      | 1,500            | $5             |
| High        | 6,000            | $18            |

**Note:** With `minInstances=1`, add ~$100/month for always-on instance.

### 3. Cloud Storage Costs

**Pricing (Standard storage, us-central1):**
- Storage: $0.020 per GB-month
- Class A operations (writes): $0.05 per 10,000 operations
- Class B operations (reads): $0.004 per 10,000 operations

**Estimated Monthly:**
- Datasets bucket (10 GB): $0.20
- Outputs bucket (50 GB, 30-day retention): $1.00
- API operations (10K writes, 50K reads): $0.52
- **Total: ~$2/month**

### 4. Artifact Registry

**Pricing:**
- Storage: $0.10 per GB-month
- Container images (~5 GB total): $0.50/month

### 5. Vertex AI Agent Engine

**Platform fees:** TBD (not yet publicly priced)
- Estimated: $50-$200/month base fee + per-invocation charges

### 6. Monitoring & Logging

**Cloud Logging:**
- First 50 GB/month: Free
- Beyond: $0.50 per GB
- Estimated: $5-$10/month (structured logs from agents)

**Cloud Monitoring:**
- First 150 MB of metrics: Free
- Estimated: $2-$5/month

---

## Total Monthly Cost Estimates

| Component               | Low Usage | Medium Usage | High Usage |
|-------------------------|-----------|--------------|------------|
| Gemini API (Flash+Pro)  | $9        | $45          | $180       |
| Cloud Run               | $1        | $5           | $18        |
| Cloud Storage           | $2        | $2           | $3         |
| Artifact Registry       | $1        | $1           | $1         |
| Vertex AI Platform Fee  | $100      | $100         | $150       |
| Monitoring & Logging    | $7        | $10          | $15        |
| **TOTAL**               | **$120**  | **$163**     | **$367**   |

**With minInstances=1 (always-on):**
- Add $100/month for warm instance

**With All-Flash models:**
- Reduce LLM cost by 70% (saves $6-$126/month)

**With All-Pro models:**
- Increase LLM cost by 3x (adds $18-$360/month)

---

## Cost Optimization Strategies

### 1. Model Selection (High Impact)
**Recommendation:** Use Gemini Flash for all stages except final synthesis.

```yaml
# In agent_models.yaml
root_agent:
  model: gemini-2.5-flash-exp
planner_agent:
  model: gemini-2.5-flash-exp
narrative_agent:
  model: gemini-2.5-flash-exp
report_synthesis_agent:
  model: gemini-2.5-flash-exp  # Change from Pro to Flash
```

**Impact:** Reduces LLM cost from $0.03 → $0.01 per analysis (70% savings)

**Trade-off:** Slightly less sophisticated executive brief narratives.

### 2. Caching Strategy (Medium Impact)
**Implement response caching for repeated queries:**

```python
from functools import lru_cache
import hashlib

@lru_cache(maxsize=100)
def cached_analysis(dataset_name, dimension, metric, date_hash):
    # If same query within 1 hour, return cached result
    pass
```

**Impact:** 30-50% reduction in LLM calls for common queries.

### 3. Auto-Scaling Configuration (Medium Impact)
**Adjust Cloud Run auto-scaling:**

```yaml
# For low-traffic environments
autoscaling:
  minInstances: 0  # Scale to zero
  maxInstances: 5
  targetConcurrency: 1

# For high-traffic production
autoscaling:
  minInstances: 1  # Keep one warm (saves cold start latency)
  maxInstances: 10
  targetConcurrency: 1
```

**Impact:** Saves $100/month in dev/staging by scaling to zero.

### 4. Data Pre-Aggregation (High Impact for Large Datasets)
**Pre-aggregate datasets before analysis:**

```python
# Instead of processing 100K raw rows
df = df.groupby(['dimension', 'date']).agg({'metric': 'sum'})
# Now only 1K rows → faster, cheaper
```

**Impact:** Reduces token consumption by 50-80% for large datasets.

### 5. Focus Directives (Medium Impact)
**Skip unnecessary pipeline stages:**

```json
{
  "request": "Quick alert check",
  "dataset_name": "trade_data",
  "focus_directive": "alert_only"  // Skip narrative + synthesis
}
```

**Impact:** Reduces LLM calls by 60% for alerts-only queries.

### 6. Output Retention Policies (Low Impact)
**Configure GCS lifecycle policies:**

```yaml
lifecycle_rule:
  - action:
      type: Delete
    condition:
      age: 30  # Delete outputs older than 30 days
```

**Impact:** Saves $0.50-$2/month in storage costs.

### 7. Batch Processing (High Impact for Multiple Queries)
**Run multiple analyses in parallel:**

```python
analyses = ["gross margin by region", "revenue by product", "OpEx by dept"]
results = asyncio.gather(*[analyze(q) for q in analyses])
```

**Impact:** Amortizes fixed costs across multiple analyses.

---

## Cost Monitoring & Alerts

### 1. Set Up Budget Alerts

```bash
gcloud billing budgets create \
  --billing-account=YOUR_BILLING_ACCOUNT \
  --display-name="Data Analyst Agent Budget" \
  --budget-amount=500 \
  --threshold-rule=percent=50 \
  --threshold-rule=percent=90 \
  --threshold-rule=percent=100
```

### 2. Track Cost Per Analysis Metric

```python
# In agent code
cost_per_analysis = (total_tokens * avg_token_price) + compute_cost
log_metric("cost_per_analysis", cost_per_analysis)
```

### 3. Monthly Cost Review Checklist

- [ ] Review Cloud Billing dashboard
- [ ] Check Gemini API usage trends
- [ ] Analyze cost by dataset (which datasets are most expensive?)
- [ ] Review auto-scaling settings
- [ ] Audit unused resources (old container images, test deployments)

---

## Break-Even Analysis

**Scenario:** Replacing manual analyst work.

**Manual Cost:**
- Senior analyst: $150/hour
- Time per analysis: 2-4 hours
- **Cost per manual analysis: $300-$600**

**Agent Cost:**
- $0.03 per automated analysis
- **Payback after: 1-2 analyses**

**ROI:** 10,000x return on cost (ignoring development time).

---

## Recommendations by Environment

### Dev Environment
- Use Gemini Flash for all stages
- `minInstances=0` (scale to zero)
- 7-day output retention
- **Target cost: $50/month**

### Staging Environment
- Use Flash + Pro (match production config)
- `minInstances=0`
- 30-day output retention
- **Target cost: $100/month**

### Production Environment
- Use Flash for most stages, Pro for synthesis
- `minInstances=1` (keep warm instance)
- 90-day output retention
- Implement caching for common queries
- **Target cost: $300-$500/month at medium usage**

---

## Cost Escalation Triggers

**If monthly cost exceeds $1,000:**
1. Review top 10 most expensive analyses (by token count)
2. Check for runaway queries or infinite loops
3. Implement rate limiting (max 100 analyses/day per user)
4. Consider switching to Gemini Flash for all stages

**If monthly cost exceeds $2,000:**
1. Audit all LLM calls — look for inefficiencies
2. Implement aggressive caching
3. Pre-aggregate all datasets
4. Contact Google Cloud sales for volume discounts

---

## Conclusion

**Expected production cost: $300-$500/month at medium usage** (50 analyses/day).

**Key levers:**
1. Model selection (Flash vs Pro) — 70% cost reduction potential
2. Caching strategy — 30-50% reduction for repeated queries
3. Auto-scaling configuration — $100/month savings in non-prod
4. Data pre-aggregation — 50-80% reduction for large datasets

**Next steps:**
1. Implement cost tracking in agent code
2. Set up budget alerts at $500/month
3. Monitor cost per analysis metric
4. Review monthly and optimize based on usage patterns
