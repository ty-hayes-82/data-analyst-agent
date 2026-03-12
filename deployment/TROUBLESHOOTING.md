# Troubleshooting Guide — Data Analyst Agent on GCP

Complete guide for diagnosing and resolving common deployment and runtime issues.

---

## Quick Diagnostic Commands

```bash
# Check agent deployment status
gcloud ai agents list --region=us-central1

# View recent logs
gcloud logging read "resource.type=cloud_run_revision AND severity>=ERROR" --limit 50

# Check Cloud Run service status
gcloud run services describe data-analyst-ui --region=us-central1

# Test agent invocation
gcloud ai agents invoke data-analyst-agent --region=us-central1 \
  --input='{"request": "test", "dataset_name": "trade_data"}'

# Check resource quotas
gcloud compute project-info describe --project=YOUR_PROJECT
```

---

## Common Issues & Solutions

### 1. Deployment Issues

#### Issue: "Permission denied" during Terraform apply

**Error:**
```
Error: Error creating bucket: googleapi: Error 403: 
service-account@project.iam.gserviceaccount.com does not have 
storage.buckets.create access to the Google Cloud project
```

**Cause:** Insufficient IAM permissions.

**Solution:**
```bash
# Grant owner role to your user account
gcloud projects add-iam-policy-binding YOUR_PROJECT \
  --member="user:your-email@example.com" \
  --role="roles/owner"

# Or grant specific roles
gcloud projects add-iam-policy-binding YOUR_PROJECT \
  --member="user:your-email@example.com" \
  --role="roles/storage.admin"
```

#### Issue: Container build fails with "No space left on device"

**Error:**
```
Step 15/20 : RUN pip install -r requirements.txt
ERROR: failed to solve: error writing layer blob: write /var/lib/docker/tmp/...: no space left on device
```

**Cause:** Docker disk space exhausted.

**Solution:**
```bash
# Clean up Docker images/containers
docker system prune -a --volumes

# Or build on Cloud Build instead
gcloud builds submit --config=cloudbuild.yaml
```

#### Issue: "Secret not found" after deployment

**Error:**
```
google.api_core.exceptions.NotFound: 404 Secret [google-api-key] not found
```

**Cause:** Secrets not created in Secret Manager.

**Solution:**
```bash
# Create and set secret
echo -n 'YOUR_GOOGLE_API_KEY' | gcloud secrets create google-api-key --data-file=-

# Or add version to existing secret
echo -n 'YOUR_GOOGLE_API_KEY' | gcloud secrets versions add google-api-key --data-file=-

# Verify
gcloud secrets versions access latest --secret=google-api-key
```

---

### 2. Runtime Errors

#### Issue: Agent invocation times out after 10 minutes

**Error:**
```
Error: Request timed out after 600 seconds
```

**Cause:** Analysis exceeds Cloud Run timeout limit.

**Solution:**
```bash
# Increase Cloud Run timeout to 60 minutes
gcloud run services update data-analyst-ui \
  --region=us-central1 \
  --timeout=3600

# OR: Pre-aggregate large datasets
# Reduce dataset size from 100K → 10K rows before analysis
```

#### Issue: "Out of memory" error during analysis

**Error:**
```
MemoryError: Unable to allocate array with shape (100000, 50)
```

**Cause:** Dataset too large for available memory.

**Solution:**
```bash
# Increase Cloud Run memory
gcloud run services update data-analyst-ui \
  --region=us-central1 \
  --memory=8Gi

# OR: Optimize data loading
# Load only required columns instead of full dataset
```

#### Issue: "Rate limit exceeded" from Gemini API

**Error:**
```
google.api_core.exceptions.ResourceExhausted: 
429 Quota exceeded for quota metric 'Generate Content API requests per minute'
```

**Cause:** Exceeding default 60 RPM quota.

**Solutions:**

1. **Request quota increase:**
   - Navigate to: [Vertex AI Quotas](https://console.cloud.google.com/iam-admin/quotas)
   - Filter: "Vertex AI API"
   - Select: "Generate Content API requests per minute"
   - Click "EDIT QUOTAS" → Request increase to 120 RPM

2. **Implement exponential backoff:**
   ```python
   # Already implemented in ADK, but verify:
   GOOGLE_GENAI_EXPONENTIAL_BACKOFF=True
   GOOGLE_GENAI_BACKOFF_MULTIPLIER=2
   GOOGLE_GENAI_MAX_RETRIES=5
   ```

3. **Reduce parallel LLM calls:**
   - Run analyses sequentially instead of in parallel
   - Use code-based insights instead of LLM where possible

#### Issue: "Dataset contract not found"

**Error:**
```
FileNotFoundError: Contract file not found: 
gs://project-data-analyst-datasets/datasets/trade_data/contract.yaml
```

**Cause:** Contract not uploaded to Cloud Storage.

**Solution:**
```bash
# Upload contracts to GCS
cd /data/data-analyst-agent
gsutil -m rsync -r config/datasets/ gs://YOUR_PROJECT-data-analyst-datasets/datasets/

# Verify upload
gsutil ls -r gs://YOUR_PROJECT-data-analyst-datasets/datasets/
```

#### Issue: Analysis completes but no PDF generated

**Error:**
```
Warning: PDF generation failed, saving markdown only
```

**Cause:** WeasyPrint dependencies missing or font issues.

**Solution:**

1. **Verify Dockerfile includes WeasyPrint dependencies:**
   ```dockerfile
   RUN apt-get install -y libcairo2 libpango-1.0-0 libpangocairo-1.0-0
   ```

2. **Check logs for specific error:**
   ```bash
   gcloud logging read "textPayload=~'PDF generation'" --limit 10
   ```

3. **Fallback to fpdf2 (simpler PDF renderer):**
   ```python
   # In .env or Cloud Run env vars
   PDF_RENDERER=fpdf2  # Instead of weasyprint
   ```

---

### 3. Performance Issues

#### Issue: Analysis takes >5 minutes (too slow)

**Possible causes:**

1. **Cold start (minInstances=0)**
   ```bash
   # Keep one instance warm
   gcloud run services update data-analyst-ui --region=us-central1 --min-instances=1
   ```

2. **Large dataset (>50K rows)**
   - Pre-aggregate data in SQL/Tableau before loading
   - Filter to only required date range

3. **Parallel analysis not running**
   - Check logs: `gcloud logging read "textPayload=~'parallel'" --limit 20`
   - Verify `DynamicParallelAnalysisAgent` is enabled

4. **LLM throttling**
   - Check for 429 errors in logs
   - Request quota increase

**Debug with Cloud Trace:**
```bash
# Find slowest stages
gcloud trace list --filter="displayName:data-analyst-agent" --limit=5

# View specific trace
gcloud trace get <TRACE_ID>
```

#### Issue: High LLM token usage (cost spike)

**Symptom:** Monthly cost >$1,000 when expecting $300.

**Investigation:**
```bash
# Check token usage by analysis
gcloud logging read "metric.type='custom.googleapis.com/data_analyst_agent/llm_tokens'" \
  --format="table(timestamp, jsonPayload.tokens, jsonPayload.model)"

# Identify analyses with excessive tokens
gcloud logging read "jsonPayload.total_tokens>100000" --limit 10
```

**Solutions:**

1. **Switch to Gemini Flash for all stages:**
   ```yaml
   # In agent_models.yaml
   report_synthesis_agent:
     model: gemini-2.5-flash-exp  # Change from Pro to Flash
   ```

2. **Reduce context in prompts:**
   - Limit dataset sample size in prompts
   - Summarize statistical results before passing to LLM

3. **Implement caching:**
   - Cache repeated queries for 1 hour
   - Skip redundant LLM calls for identical inputs

---

### 4. Data Issues

#### Issue: "No data returned" from Tableau Hyper

**Error:**
```
ValueError: Primary data CSV is empty after data fetch
```

**Causes:**

1. **Date range outside available data**
   - Check `contract.yaml` time configuration
   - Verify data exists for requested period

2. **A2A server not accessible**
   ```bash
   # Test A2A server health
   curl http://localhost:8001/health
   ```

3. **Hyper file not found**
   - Verify file path in contract.yaml
   - Check file permissions

**Solution:**
```bash
# Enable detailed logging
PHASE_LOG_LEVEL=DEBUG python -m data_analyst_agent

# Check data fetch logs
gcloud logging read "textPayload=~'data_fetch'" --limit 20
```

#### Issue: Dimension not found in dataset

**Error:**
```
KeyError: "Dimension 'region' not found in dataset columns"
```

**Cause:** Mismatch between contract.yaml and actual data schema.

**Solution:**

1. **Verify contract dimensions match data columns:**
   ```yaml
   # contract.yaml
   dimensions:
     - name: region  # Must match column name exactly (case-sensitive)
   ```

2. **Check actual column names:**
   ```python
   import pandas as pd
   df = pd.read_csv("primary_data.csv")
   print(df.columns.tolist())
   ```

3. **Update contract or use column mapping:**
   ```yaml
   dimensions:
     - name: region
       source_column: "Region Name"  # Map to actual column
   ```

---

### 5. Authentication Issues

#### Issue: "401 Unauthorized" when accessing Secret Manager

**Error:**
```
google.api_core.exceptions.PermissionDenied: 
403 Permission 'secretmanager.versions.access' denied
```

**Cause:** Service account lacks Secret Manager access.

**Solution:**
```bash
# Grant Secret Manager accessor role
gcloud projects add-iam-policy-binding YOUR_PROJECT \
  --member="serviceAccount:data-analyst-agent@YOUR_PROJECT.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

# Verify IAM bindings
gcloud projects get-iam-policy YOUR_PROJECT \
  --flatten="bindings[].members" \
  --filter="bindings.members:data-analyst-agent@"
```

#### Issue: "Invalid API key" from Gemini API

**Error:**
```
google.api_core.exceptions.Unauthenticated: 
401 API key not valid
```

**Solutions:**

1. **Verify API key in Secret Manager:**
   ```bash
   gcloud secrets versions access latest --secret=google-api-key
   # Should print your API key (keep secret!)
   ```

2. **Check API key restrictions:**
   - Navigate to: [API Credentials](https://console.cloud.google.com/apis/credentials)
   - Ensure key allows Vertex AI API
   - Check IP restrictions (should allow Cloud Run IPs)

3. **Regenerate API key if needed:**
   - Create new key in console
   - Update Secret Manager: `echo -n 'NEW_KEY' | gcloud secrets versions add google-api-key --data-file=-`

---

### 6. Web UI Issues

#### Issue: Web UI shows "502 Bad Gateway"

**Cause:** Cloud Run service failed to start or crashed.

**Investigation:**
```bash
# Check service status
gcloud run services describe data-analyst-ui --region=us-central1

# View startup logs
gcloud logging read "resource.type=cloud_run_revision AND severity>=ERROR" --limit 50

# Check for OOM (out of memory) kills
gcloud logging read "textPayload=~'Memory limit exceeded'" --limit 10
```

**Solutions:**

1. **Increase memory:**
   ```bash
   gcloud run services update data-analyst-ui --memory=8Gi
   ```

2. **Fix application startup error:**
   - Check logs for Python import errors
   - Verify all dependencies in requirements.txt

3. **Test container locally:**
   ```bash
   docker run -p 8080:8080 \
     -e GOOGLE_CLOUD_PROJECT=YOUR_PROJECT \
     us-central1-docker.pkg.dev/YOUR_PROJECT/data-analyst-agent/web-ui:latest
   ```

#### Issue: Web UI accessible but agent invocation fails

**Error:** "Analysis request failed with status 500"

**Investigation:**
```bash
# Check agent invocation logs
gcloud logging read "resource.type=aiplatform.googleapis.com/Endpoint" --limit 20

# Test agent directly (bypass web UI)
gcloud ai agents invoke data-analyst-agent --region=us-central1 \
  --input='{"request": "test", "dataset_name": "trade_data"}'
```

**Solution:**
- If direct invocation works, issue is in web UI → agent communication
- Check service account permissions
- Verify web UI has `aiplatform.user` role

---

## Logging Best Practices

### 1. Structured Logging

**Use JSON format for Cloud Logging:**
```python
import json
import logging

# Configure structured logger
logging.basicConfig(
    format='%(message)s',
    level=logging.INFO
)

logger = logging.getLogger(__name__)

# Log structured data
logger.info(json.dumps({
    "message": "Analysis started",
    "analysis_id": "abc123",
    "dataset": "trade_data",
    "dimension": "region"
}))
```

### 2. Log Sampling for High-Volume Events

**For very frequent logs, sample:**
```python
import random

if random.random() < 0.1:  # Log 10% of events
    logger.debug("Detailed debug info...")
```

### 3. Error Context

**Always include context in error logs:**
```python
try:
    result = analyze_data(df)
except Exception as e:
    logger.error(json.dumps({
        "error": str(e),
        "dataset": dataset_name,
        "dimension": dimension_value,
        "row_count": len(df),
        "stack_trace": traceback.format_exc()
    }))
```

---

## Health Check Endpoint

**Implement for Cloud Run:**

```python
# In web/app.py
@app.get("/health")
async def health():
    checks = {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "checks": {
            "gcs": check_gcs_access(),
            "secret_manager": check_secret_manager(),
            "gemini_api": check_gemini_api()
        }
    }
    
    if all(checks["checks"].values()):
        return checks
    else:
        raise HTTPException(status_code=503, detail="Unhealthy")

def check_gcs_access():
    try:
        storage_client.list_buckets()
        return True
    except:
        return False
```

---

## Emergency Rollback

**If production deployment breaks:**

1. **Rollback Cloud Run to previous revision:**
   ```bash
   # List revisions
   gcloud run revisions list --service=data-analyst-ui --region=us-central1
   
   # Rollback to previous
   gcloud run services update-traffic data-analyst-ui \
     --region=us-central1 \
     --to-revisions=data-analyst-ui-00042-abc=100
   ```

2. **Rollback agent deployment:**
   ```bash
   # Deploy previous container image
   gcloud ai agents deploy \
     --config=agent_config.yaml \
     --image=us-central1-docker.pkg.dev/PROJECT/data-analyst-agent/agent:PREVIOUS_SHA
   ```

3. **Restore datasets from GCS versioning:**
   ```bash
   # List object versions
   gsutil ls -a gs://PROJECT-datasets/datasets/trade_data/contract.yaml
   
   # Restore previous version
   gsutil cp gs://PROJECT-datasets/datasets/trade_data/contract.yaml#VERSION ./
   gsutil cp ./contract.yaml gs://PROJECT-datasets/datasets/trade_data/
   ```

---

## Support Escalation

**If issue cannot be resolved:**

1. **Gather diagnostic data:**
   ```bash
   # Export logs
   gcloud logging read --limit=1000 --format=json > logs.json
   
   # Export recent traces
   gcloud trace list --limit=10 --format=json > traces.json
   
   # Export monitoring metrics
   gcloud monitoring time-series list --filter='metric.type="custom.googleapis.com/data_analyst_agent/*"' > metrics.json
   ```

2. **Open GitHub issue:**
   - [https://github.com/ty-hayes-82/data-analyst-agent/issues](https://github.com/ty-hayes-82/data-analyst-agent/issues)
   - Include: logs, error messages, dataset size, configuration

3. **Contact Google Cloud support:**
   - [https://cloud.google.com/support](https://cloud.google.com/support)
   - Provide: project ID, service account, error logs

---

## Preventive Measures

1. **Run smoke tests after every deployment**
2. **Monitor error rate dashboard daily**
3. **Set up budget alerts (>$500/month)**
4. **Review Cloud Logging weekly for warnings**
5. **Keep Terraform state in GCS (not local)**
6. **Document all manual configuration changes**
7. **Test rollback procedures quarterly**

---

## Additional Resources

- [Cloud Run Troubleshooting](https://cloud.google.com/run/docs/troubleshooting)
- [Vertex AI Debugging](https://cloud.google.com/vertex-ai/docs/troubleshooting)
- [Cloud Storage Troubleshooting](https://cloud.google.com/storage/docs/troubleshooting)
- [Secret Manager Troubleshooting](https://cloud.google.com/secret-manager/docs/troubleshooting)
