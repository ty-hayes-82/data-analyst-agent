# GCP Deployment Checklist — Data Analyst Agent

Complete step-by-step checklist for deploying to production.

---

## Pre-Deployment Checklist

### 1. Prerequisites

- [ ] GCP project created with billing enabled
- [ ] Project ID noted: `__________________`
- [ ] gcloud CLI installed and authenticated
- [ ] Terraform installed (v1.5+)
- [ ] Docker installed
- [ ] Owner or Editor role granted to deployment account

### 2. API Enablement

- [ ] Vertex AI API enabled
- [ ] Cloud Storage API enabled
- [ ] Secret Manager API enabled
- [ ] Cloud Run API enabled
- [ ] Artifact Registry API enabled
- [ ] Cloud Build API enabled
- [ ] Cloud Logging & Monitoring enabled

### 3. Configuration Files

- [ ] `deployment/gcp/terraform/terraform.tfvars` created and filled
- [ ] Google API key obtained from [AI Studio](https://aistudio.google.com/apikey)
- [ ] Service account JSON created (if needed for external APIs)
- [ ] Dataset contracts uploaded to `config/datasets/`

---

## Deployment Steps

### Phase 1: Infrastructure Provisioning (15 min)

- [ ] **1.1** Navigate to Terraform directory
  ```bash
  cd deployment/gcp/terraform
  ```

- [ ] **1.2** Copy terraform.tfvars template
  ```bash
  cp terraform.tfvars.example terraform.tfvars
  vim terraform.tfvars  # Fill in project_id, region, environment
  ```

- [ ] **1.3** Initialize Terraform
  ```bash
  terraform init
  ```

- [ ] **1.4** Plan infrastructure
  ```bash
  terraform plan
  ```

- [ ] **1.5** Review plan output (ensure resources match expectations)

- [ ] **1.6** Apply infrastructure
  ```bash
  terraform apply
  # Type 'yes' to confirm
  ```

- [ ] **1.7** Note outputs
  - Datasets bucket: `__________________`
  - Outputs bucket: `__________________`
  - Service account email: `__________________`

### Phase 2: Secrets Configuration (5 min)

- [ ] **2.1** Store Google API key
  ```bash
  echo -n 'YOUR_GOOGLE_API_KEY' | gcloud secrets versions add google-api-key --data-file=-
  ```

- [ ] **2.2** Verify secret stored
  ```bash
  gcloud secrets versions access latest --secret=google-api-key
  # Should print your API key (keep confidential!)
  ```

- [ ] **2.3** (Optional) Store service account JSON
  ```bash
  gcloud secrets versions add service-account-json --data-file=./service-account.json
  ```

### Phase 3: Data Upload (10 min)

- [ ] **3.1** Navigate to data sync directory
  ```bash
  cd ../../data
  ```

- [ ] **3.2** Run sync script (dry-run first)
  ```bash
  ./sync_to_cloud.sh --project YOUR_PROJECT_ID --dry-run
  ```

- [ ] **3.3** Review what will be uploaded

- [ ] **3.4** Execute actual sync
  ```bash
  ./sync_to_cloud.sh --project YOUR_PROJECT_ID
  ```

- [ ] **3.5** Verify upload
  ```bash
  gsutil ls -r gs://YOUR_PROJECT-data-analyst-datasets/datasets/
  ```

### Phase 4: Container Build (20 min)

- [ ] **4.1** Authenticate Docker to Artifact Registry
  ```bash
  gcloud auth configure-docker us-central1-docker.pkg.dev
  ```

- [ ] **4.2** Build agent container
  ```bash
  cd ../..
  docker build -f deployment/vertex_ai/Dockerfile \
    -t us-central1-docker.pkg.dev/YOUR_PROJECT/data-analyst-agent/agent:latest .
  ```

- [ ] **4.3** Push agent container
  ```bash
  docker push us-central1-docker.pkg.dev/YOUR_PROJECT/data-analyst-agent/agent:latest
  ```

- [ ] **4.4** Build web UI container
  ```bash
  docker build -f web/Dockerfile \
    -t us-central1-docker.pkg.dev/YOUR_PROJECT/data-analyst-agent/web-ui:latest .
  ```

- [ ] **4.5** Push web UI container
  ```bash
  docker push us-central1-docker.pkg.dev/YOUR_PROJECT/data-analyst-agent/web-ui:latest
  ```

- [ ] **4.6** Verify images in Artifact Registry
  ```bash
  gcloud artifacts docker images list us-central1-docker.pkg.dev/YOUR_PROJECT/data-analyst-agent
  ```

### Phase 5: Agent Deployment (10 min)

- [ ] **5.1** Navigate to Vertex AI config
  ```bash
  cd deployment/vertex_ai
  ```

- [ ] **5.2** Substitute variables in agent_config.yaml
  ```bash
  sed -e "s/\${PROJECT_ID}/YOUR_PROJECT/g" \
      -e "s/\${REGION}/us-central1/g" \
      agent_config.yaml > agent_config_resolved.yaml
  ```

- [ ] **5.3** Deploy agent to Vertex AI
  ```bash
  # Note: Command syntax may vary based on Vertex AI Agent Engine CLI version
  gcloud ai agents deploy --config=agent_config_resolved.yaml --region=us-central1
  ```

- [ ] **5.4** Verify deployment
  ```bash
  gcloud ai agents list --region=us-central1
  ```

### Phase 6: Web UI Deployment (5 min)

- [ ] **6.1** Deploy to Cloud Run
  ```bash
  gcloud run deploy data-analyst-ui \
    --image=us-central1-docker.pkg.dev/YOUR_PROJECT/data-analyst-agent/web-ui:latest \
    --region=us-central1 \
    --platform=managed \
    --allow-unauthenticated \
    --service-account=data-analyst-agent@YOUR_PROJECT.iam.gserviceaccount.com \
    --set-env-vars="GOOGLE_CLOUD_PROJECT=YOUR_PROJECT,GOOGLE_CLOUD_LOCATION=us-central1"
  ```

- [ ] **6.2** Get Cloud Run URL
  ```bash
  gcloud run services describe data-analyst-ui --region=us-central1 --format='value(status.url)'
  ```
  Web UI URL: `__________________`

- [ ] **6.3** Test web UI health endpoint
  ```bash
  curl https://YOUR_CLOUD_RUN_URL/health
  # Should return: {"status": "healthy"}
  ```

### Phase 7: Smoke Tests (10 min)

- [ ] **7.1** Test agent invocation via gcloud
  ```bash
  gcloud ai agents invoke data-analyst-agent \
    --region=us-central1 \
    --input='{"request": "Analyze gross margin by region", "dataset_name": "trade_data"}'
  ```

- [ ] **7.2** Verify response contains:
  - `"status": "success"`
  - GCS URLs for outputs
  - Metrics (duration, tokens, etc.)

- [ ] **7.3** Download and verify output PDF
  ```bash
  gsutil cp gs://YOUR_PROJECT-data-analyst-outputs/executive_briefs/LATEST.pdf ./test_output.pdf
  open test_output.pdf  # Verify PDF renders correctly
  ```

- [ ] **7.4** Test web UI manually
  - Navigate to Cloud Run URL
  - Submit test analysis request
  - Verify results display correctly

### Phase 8: Monitoring Setup (10 min)

- [ ] **8.1** Import monitoring dashboard
  ```bash
  cd ../../monitoring
  gcloud monitoring dashboards create --config-from-file=dashboard.json
  ```

- [ ] **8.2** Get dashboard URL
  ```bash
  echo "https://console.cloud.google.com/monitoring/dashboards?project=YOUR_PROJECT"
  ```

- [ ] **8.3** Set up notification channels
  ```bash
  gcloud alpha monitoring channels create \
    --display-name="Email Alerts" \
    --type=email \
    --channel-labels=email_address=your-email@example.com
  ```

- [ ] **8.4** Create alert policies (manual step)
  - Navigate to Cloud Monitoring → Alerting
  - Reference: `deployment/monitoring/alerts.yaml`
  - Create policies for:
    - High error rate
    - Slow response time
    - High token usage

### Phase 9: Cost Management (5 min)

- [ ] **9.1** Set up budget alerts
  ```bash
  gcloud billing budgets create \
    --billing-account=YOUR_BILLING_ACCOUNT \
    --display-name="Data Analyst Agent Budget" \
    --budget-amount=500 \
    --threshold-rule=percent=50 \
    --threshold-rule=percent=90 \
    --threshold-rule=percent=100
  ```

- [ ] **9.2** Review cost projections
  - Read: `deployment/cost_analysis.md`
  - Expected cost: `$__________/month`

- [ ] **9.3** Enable detailed billing export
  ```bash
  # Navigate to: Billing → Billing export
  # Enable export to BigQuery
  ```

### Phase 10: Agent Garden Registration (Optional, 15 min)

- [ ] **10.1** Navigate to Agent Garden config
  ```bash
  cd ../agent_garden
  ```

- [ ] **10.2** Review and customize manifest
  ```bash
  vim manifest.yaml
  # Update: publisher, support email, etc.
  ```

- [ ] **10.3** Register agent
  ```bash
  gcloud agent-garden agents register --manifest=manifest.yaml
  ```

- [ ] **10.4** Verify listing
  ```bash
  gcloud agent-garden agents list
  ```

- [ ] **10.5** Test Agent Garden invocation
  ```bash
  gcloud agent-garden agents invoke data-analyst-agent \
    --input='{"request": "test", "dataset_name": "trade_data"}'
  ```

---

## Post-Deployment Verification

### Functional Tests

- [ ] Agent invocation completes without errors
- [ ] Analysis JSON generated in GCS outputs bucket
- [ ] Executive brief PDF generated and renders correctly
- [ ] Web UI accessible and functional
- [ ] Health check endpoint returns 200 OK
- [ ] Logs appear in Cloud Logging
- [ ] Metrics appear in Cloud Monitoring dashboard

### Performance Tests

- [ ] Analysis completes in <2 minutes (typical dataset)
- [ ] p95 latency <90 seconds
- [ ] Error rate <1%
- [ ] Cold start latency <5 seconds

### Security Tests

- [ ] Service account has minimal required permissions (least privilege)
- [ ] Secrets not exposed in logs
- [ ] GCS buckets have appropriate IAM policies
- [ ] Cloud Run requires authentication (if production)
- [ ] API keys stored only in Secret Manager

---

## Production Readiness Checklist

### Scalability

- [ ] Auto-scaling configured (max instances set)
- [ ] Gemini API quota sufficient for expected load
- [ ] GCS buckets have lifecycle policies (30-90 day retention)
- [ ] Load testing completed (2x expected traffic)

### Reliability

- [ ] Health check endpoint implemented
- [ ] Retry logic enabled for transient failures
- [ ] Graceful degradation for non-critical stages
- [ ] Rollback procedure documented and tested

### Monitoring & Alerting

- [ ] Dashboard shows key metrics
- [ ] Alerts configured for error rate, latency, cost
- [ ] Notification channels tested (receive test alert)
- [ ] On-call rotation established (if 24/7 support)

### Documentation

- [ ] Deployment guide (this checklist) complete
- [ ] Architecture diagram reviewed
- [ ] Troubleshooting guide accessible to ops team
- [ ] Scaling guide reviewed and understood
- [ ] Runbook created for common operational tasks

### Cost Optimization

- [ ] Budget alerts set at 50%, 90%, 100%
- [ ] Cost analysis reviewed and approved
- [ ] Gemini Flash models used where possible
- [ ] Caching strategy implemented
- [ ] Warm instances justified or disabled (minInstances)

### Compliance & Security

- [ ] Data residency requirements met (region selection)
- [ ] GDPR compliance verified (if EU users)
- [ ] Access controls reviewed (service account permissions)
- [ ] Audit logging enabled
- [ ] Security scan passed (no critical vulnerabilities)

---

## CI/CD Setup (Optional but Recommended)

### GitHub Actions

- [ ] **CD.1** Set up GitHub repository secrets
  - `GCP_PROJECT_ID_PROD`
  - `GCP_WORKLOAD_IDENTITY_PROVIDER`
  - `GCP_SERVICE_ACCOUNT`

- [ ] **CD.2** Review GitHub Actions workflow
  ```bash
  cat .github/workflows/deploy-vertex-ai.yml
  ```

- [ ] **CD.3** Push to main branch to trigger deployment
  ```bash
  git push origin main
  ```

- [ ] **CD.4** Monitor GitHub Actions run
  - Navigate to: GitHub → Actions tab
  - Verify all jobs pass (test → build → deploy)

### Cloud Build

- [ ] **CB.1** Connect GitHub repository to Cloud Build
  ```bash
  gcloud builds triggers create github \
    --repo-name=data-analyst-agent \
    --repo-owner=ty-hayes-82 \
    --branch-pattern="^main$" \
    --build-config=cloudbuild.yaml
  ```

- [ ] **CB.2** Test trigger manually
  ```bash
  gcloud builds triggers run TRIGGER_NAME --branch=main
  ```

- [ ] **CB.3** Verify build succeeds and deploys

---

## Rollback Procedure

### If deployment fails or causes issues:

1. **Immediate mitigation:**
   ```bash
   # Rollback Cloud Run to previous revision
   gcloud run revisions list --service=data-analyst-ui --region=us-central1
   gcloud run services update-traffic data-analyst-ui \
     --region=us-central1 \
     --to-revisions=PREVIOUS_REVISION=100
   ```

2. **Restore previous agent version:**
   ```bash
   # Deploy previous container image
   docker pull us-central1-docker.pkg.dev/PROJECT/data-analyst-agent/agent:PREVIOUS_SHA
   gcloud ai agents deploy --config=agent_config.yaml --image=...
   ```

3. **Restore datasets from GCS versioning:**
   ```bash
   gsutil ls -a gs://PROJECT-datasets/datasets/trade_data/contract.yaml
   gsutil cp gs://PROJECT-datasets/datasets/trade_data/contract.yaml#VERSION ./
   gsutil cp ./contract.yaml gs://PROJECT-datasets/datasets/trade_data/
   ```

4. **Notify stakeholders:**
   - Post incident in Slack/email
   - Update status page (if applicable)

---

## Sign-Off

**Deployment Date:** `____________`

**Deployed By:** `____________`

**Project ID:** `____________`

**Environment:** `____________`

**Web UI URL:** `____________`

**Monitoring Dashboard:** `____________`

**Approvals:**
- [ ] Technical Lead: `____________` (signature/date)
- [ ] Product Owner: `____________` (signature/date)
- [ ] Security Review: `____________` (signature/date)

---

## Quick Links

- **Documentation:**
  - [Deployment Guide](README.md)
  - [Architecture](ARCHITECTURE.md)
  - [Troubleshooting](TROUBLESHOOTING.md)
  - [Scaling Guide](SCALING.md)
  - [Cost Analysis](cost_analysis.md)

- **GCP Console:**
  - [Cloud Run Services](https://console.cloud.google.com/run)
  - [Vertex AI Agents](https://console.cloud.google.com/vertex-ai/agents)
  - [Cloud Storage](https://console.cloud.google.com/storage)
  - [Secret Manager](https://console.cloud.google.com/security/secret-manager)
  - [Monitoring Dashboard](https://console.cloud.google.com/monitoring/dashboards)
  - [Cloud Logging](https://console.cloud.google.com/logs)

- **Support:**
  - GitHub Issues: https://github.com/ty-hayes-82/data-analyst-agent/issues
  - Email: ty-hayes-82@example.com
  - Slack: #data-analyst-agent

---

**Deployment Complete! 🚀**

Next steps:
1. Monitor dashboard for first 24 hours
2. Review costs after first week
3. Gather user feedback
4. Plan scaling adjustments based on usage
