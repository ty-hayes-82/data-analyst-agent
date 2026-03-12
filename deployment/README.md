# Data Analyst Agent — GCP Deployment Guide

Complete guide for deploying the ADK-based Data Analyst Agent to Google Cloud Platform using Vertex AI Agent Engine and Agent Garden.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Quick Start](#quick-start)
3. [Detailed Setup](#detailed-setup)
4. [Deployment Options](#deployment-options)
5. [Configuration](#configuration)
6. [Monitoring](#monitoring)
7. [Troubleshooting](#troubleshooting)
8. [Cost Management](#cost-management)

---

## Prerequisites

### 1. Google Cloud Project

- Active GCP project with billing enabled
- Project ID noted (e.g., `my-data-analyst-project`)
- Owner or Editor role

### 2. Required APIs

Enable these APIs (done automatically by Terraform):
- Vertex AI API
- Cloud Storage
- Secret Manager
- Cloud Run
- Artifact Registry
- Cloud Build (for CI/CD)
- Cloud Logging & Monitoring

### 3. Local Tools

```bash
# Install gcloud CLI
curl https://sdk.cloud.google.com | bash
exec -l $SHELL

# Authenticate
gcloud auth login
gcloud config set project YOUR_PROJECT_ID

# Install Terraform (for infrastructure provisioning)
brew install terraform  # macOS
# or
sudo apt-get install terraform  # Linux

# Install Docker (for container builds)
# Follow: https://docs.docker.com/get-docker/
```

---

## Quick Start

**Deploy everything with one command:**

```bash
cd deployment/gcp
./deploy.sh --project YOUR_PROJECT_ID --region us-central1
```

This script will:
1. ✅ Provision GCP infrastructure (Terraform)
2. ✅ Upload datasets to Cloud Storage
3. ✅ Build and push container images
4. ✅ Deploy agent to Vertex AI Agent Engine
5. ✅ Deploy web UI to Cloud Run
6. ✅ Run smoke tests

**Estimated time:** 15-20 minutes

---

## Detailed Setup

### Step 1: Infrastructure Provisioning (Terraform)

```bash
cd deployment/gcp/terraform

# Copy terraform.tfvars template
cp terraform.tfvars.example terraform.tfvars

# Edit with your values
vim terraform.tfvars
```

**terraform.tfvars:**
```hcl
project_id  = "your-gcp-project-id"
region      = "us-central1"
environment = "prod"
```

**Initialize and apply:**
```bash
terraform init
terraform plan
terraform apply
```

**What gets created:**
- ✅ Cloud Storage buckets (datasets + outputs)
- ✅ Service account with IAM roles
- ✅ Secret Manager secrets (placeholders)
- ✅ Artifact Registry repository
- ✅ Cloud Run service (web UI)
- ✅ Monitoring alert policies

### Step 2: Store Secrets

```bash
# Google API Key
echo -n 'YOUR_GOOGLE_API_KEY' | gcloud secrets versions add google-api-key --data-file=-

# Service Account JSON (if using external APIs)
gcloud secrets versions add service-account-json --data-file=./service-account.json
```

### Step 3: Upload Datasets

```bash
cd deployment/data
./sync_to_cloud.sh --project YOUR_PROJECT_ID
```

This uploads:
- Dataset contracts (`config/datasets/*/contract.yaml`)
- Validation data (`data/validation/`)
- Sample data (`data/synthetic/`)

### Step 4: Build and Push Containers

```bash
# Authenticate Docker to Artifact Registry
gcloud auth configure-docker us-central1-docker.pkg.dev

# Build agent container
docker build -f deployment/vertex_ai/Dockerfile -t us-central1-docker.pkg.dev/YOUR_PROJECT/data-analyst-agent/agent:latest .

# Push to Artifact Registry
docker push us-central1-docker.pkg.dev/YOUR_PROJECT/data-analyst-agent/agent:latest

# Build web UI container
docker build -f web/Dockerfile -t us-central1-docker.pkg.dev/YOUR_PROJECT/data-analyst-agent/web-ui:latest .

# Push web UI
docker push us-central1-docker.pkg.dev/YOUR_PROJECT/data-analyst-agent/web-ui:latest
```

### Step 5: Deploy Agent to Vertex AI

```bash
cd deployment/vertex_ai

# Substitute variables in agent_config.yaml
sed -e "s/\${PROJECT_ID}/YOUR_PROJECT/g" \
    -e "s/\${REGION}/us-central1/g" \
    agent_config.yaml > agent_config_resolved.yaml

# Deploy (command may vary based on Vertex AI Agent Engine CLI)
gcloud ai agents deploy --config=agent_config_resolved.yaml --region=us-central1
```

### Step 6: Deploy Web UI to Cloud Run

```bash
gcloud run deploy data-analyst-ui \
  --image=us-central1-docker.pkg.dev/YOUR_PROJECT/data-analyst-agent/web-ui:latest \
  --region=us-central1 \
  --platform=managed \
  --allow-unauthenticated \
  --service-account=data-analyst-agent@YOUR_PROJECT.iam.gserviceaccount.com \
  --set-env-vars="GOOGLE_CLOUD_PROJECT=YOUR_PROJECT,GOOGLE_CLOUD_LOCATION=us-central1"
```

Get the URL:
```bash
gcloud run services describe data-analyst-ui --region=us-central1 --format='value(status.url)'
```

### Step 7: Register in Agent Garden (Optional)

```bash
cd deployment/agent_garden

# Register agent
gcloud agent-garden agents register --manifest=manifest.yaml

# Verify listing
gcloud agent-garden agents list
```

---

## Deployment Options

### Option A: One-Command Deployment (Recommended)

```bash
./deployment/gcp/deploy.sh --project YOUR_PROJECT --region us-central1
```

### Option B: CI/CD with GitHub Actions

1. Set up GitHub secrets:
   - `GCP_PROJECT_ID_PROD`
   - `GCP_WORKLOAD_IDENTITY_PROVIDER`
   - `GCP_SERVICE_ACCOUNT`

2. Push to `main` branch:
   ```bash
   git push origin main
   ```

3. GitHub Actions will automatically:
   - Run tests
   - Build containers
   - Deploy to Vertex AI + Cloud Run
   - Run smoke tests

### Option C: CI/CD with Cloud Build

1. Connect GitHub repo to Cloud Build:
   ```bash
   gcloud builds triggers create github \
     --repo-name=data-analyst-agent \
     --repo-owner=ty-hayes-82 \
     --branch-pattern="^main$" \
     --build-config=cloudbuild.yaml
   ```

2. Push to trigger build:
   ```bash
   git push origin main
   ```

---

## Configuration

### Environment-Specific Configs

Edit `deployment/gcp/config.yaml`:

```yaml
prod:
  project_id: "prod-project"
  models:
    root_agent: "gemini-2.5-pro-exp"
  autoscaling:
    min_instances: 1  # Keep warm
    max_instances: 10
```

### Model Selection

**For cost optimization:**
```yaml
# All stages use Flash (cheapest)
root_agent:
  model: gemini-2.5-flash-exp
```

**For best quality:**
```yaml
# Use Pro for critical stages
report_synthesis_agent:
  model: gemini-2.5-pro-exp
```

### Feature Flags

```bash
# In .env or Cloud Run environment variables
USE_CODE_INSIGHTS=true
EXECUTIVE_BRIEF_OUTPUT_FORMAT=pdf
PHASE_LOGGING_ENABLED=true
```

---

## Monitoring

### 1. Cloud Monitoring Dashboard

Access: [Cloud Console → Monitoring → Dashboards](https://console.cloud.google.com/monitoring/dashboards)

**Pre-configured dashboard JSON:** `deployment/monitoring/dashboard.json`

Import:
```bash
gcloud monitoring dashboards create --config-from-file=deployment/monitoring/dashboard.json
```

**Key metrics:**
- Agent invocations per minute
- Error rate (%)
- Execution duration (p95)
- LLM token usage
- Active instances

### 2. Alert Policies

Create alerts:
```bash
# (Alert policies created automatically by Terraform)
# Or manually create from YAML:
gcloud alpha monitoring policies create --policy-from-file=deployment/monitoring/alerts.yaml
```

**Alerts configured:**
- High error rate (>10%)
- Slow response time (>10 min)
- High token usage (cost spike)
- No traffic (service down)

### 3. Cloud Logging

View logs:
```bash
# Agent errors
gcloud logging read "resource.type=cloud_run_revision AND severity>=ERROR" --limit 50

# Recent invocations
gcloud logging read "resource.type=cloud_run_revision AND httpRequest.requestUrl=~'.*invoke.*'" --limit 20
```

### 4. Cloud Trace

Access: [Cloud Console → Trace](https://console.cloud.google.com/traces)

Trace agent execution to identify bottlenecks.

---

## Troubleshooting

### Issue: "Permission denied" errors

**Cause:** Service account lacks required IAM roles.

**Fix:**
```bash
gcloud projects add-iam-policy-binding YOUR_PROJECT \
  --member="serviceAccount:data-analyst-agent@YOUR_PROJECT.iam.gserviceaccount.com" \
  --role="roles/aiplatform.user"
```

### Issue: Agent invocation fails with "Secret not found"

**Cause:** Secrets not set in Secret Manager.

**Fix:**
```bash
echo -n 'YOUR_API_KEY' | gcloud secrets versions add google-api-key --data-file=-
```

### Issue: "Container image not found"

**Cause:** Image not pushed to Artifact Registry.

**Fix:**
```bash
docker push us-central1-docker.pkg.dev/YOUR_PROJECT/data-analyst-agent/agent:latest
```

### Issue: High latency (>5 minutes per analysis)

**Possible causes:**
- Large dataset (>50K rows) → pre-aggregate data
- Cold start (minInstances=0) → set minInstances=1
- LLM throttling → check quota limits

**Debug:**
```bash
# Check Cloud Trace for bottlenecks
gcloud trace list --filter="displayName:data-analyst-agent"

# Check for throttling errors
gcloud logging read "severity=ERROR AND textPayload=~'429'" --limit 10
```

### Issue: Error rate >10%

**Steps:**
1. Check logs for stack traces:
   ```bash
   gcloud logging read "severity>=ERROR" --limit 50
   ```

2. Common errors:
   - **"Dataset contract not found"** → upload contracts to GCS
   - **"GOOGLE_API_KEY not set"** → check Secret Manager
   - **"Quota exceeded"** → request quota increase

3. Test agent locally:
   ```bash
   cd /data/data-analyst-agent
   python -m data_analyst_agent
   ```

---

## Cost Management

### 1. Monitor Monthly Costs

```bash
# View billing dashboard
gcloud billing accounts list
gcloud billing projects describe YOUR_PROJECT
```

### 2. Set Budget Alerts

```bash
gcloud billing budgets create \
  --billing-account=YOUR_BILLING_ACCOUNT \
  --display-name="Data Analyst Agent Budget" \
  --budget-amount=500 \
  --threshold-rule=percent=90
```

### 3. Optimize Costs

**Quick wins:**
- Use Gemini Flash for all stages (70% LLM cost reduction)
- Set `minInstances=0` in dev/staging
- Implement caching for repeated queries
- Pre-aggregate large datasets

**See full cost analysis:** [deployment/cost_analysis.md](cost_analysis.md)

---

## Next Steps

1. **Test agent invocation:**
   ```bash
   gcloud ai agents invoke data-analyst-agent \
     --region=us-central1 \
     --input='{"request": "Analyze gross margin by region", "dataset_name": "trade_data"}'
   ```

2. **Access web UI:**
   ```bash
   WEB_URL=$(gcloud run services describe data-analyst-ui --region=us-central1 --format='value(status.url)')
   open $WEB_URL
   ```

3. **Register in Agent Garden:**
   ```bash
   cd deployment/agent_garden
   gcloud agent-garden agents register --manifest=manifest.yaml
   ```

4. **Set up monitoring:**
   - Import dashboard: `deployment/monitoring/dashboard.json`
   - Configure alert notifications

5. **Review cost projections:**
   - See [cost_analysis.md](cost_analysis.md)
   - Set budget alerts

---

## Support

- **Documentation:** [GitHub Wiki](https://github.com/ty-hayes-82/data-analyst-agent/wiki)
- **Issues:** [GitHub Issues](https://github.com/ty-hayes-82/data-analyst-agent/issues)
- **Email:** ty-hayes-82@example.com

---

## Architecture Diagram

See [ARCHITECTURE.md](ARCHITECTURE.md) for detailed cloud architecture and data flow.

## Scaling Guide

See [SCALING.md](SCALING.md) for production scaling best practices.

## Troubleshooting Guide

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for common issues and solutions.
