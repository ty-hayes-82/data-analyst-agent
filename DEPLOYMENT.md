# P&L Analyst Agent - Production Deployment Guide

## Table of Contents
1. [Prerequisites](#prerequisites)
2. [Initial Setup](#initial-setup)
3. [Configuration](#configuration)
4. [Testing Before Deployment](#testing-before-deployment)
5. [Deployment to Vertex AI](#deployment-to-vertex-ai)
6. [Post-Deployment Verification](#post-deployment-verification)
7. [Monitoring and Maintenance](#monitoring-and-maintenance)
8. [Troubleshooting](#troubleshooting)
9. [Rollback Procedures](#rollback-procedures)

---

## Prerequisites

### Required Software
- Python 3.9 or higher
- Git
- Google Cloud SDK (`gcloud` CLI)
- Access to Google Cloud Project with Vertex AI enabled

### Required Access
- GCP Project with Vertex AI API enabled
- Service account with following roles:
  - `roles/aiplatform.user` - For Vertex AI operations
  - `roles/storage.objectAdmin` - For Cloud Storage (if needed)
- Database access credentials:
  - AS400 (DSN: SWIFTC)
  - SQL Server (NDCSQLCLUS04/pCORE)
- Tableau A2A server access (for production mode)

### GCP Project Setup
```bash
# Set your project
gcloud config set project YOUR_PROJECT_ID

# Enable required APIs
gcloud services enable aiplatform.googleapis.com
gcloud services enable cloudresourcemanager.googleapis.com

# Verify authentication
gcloud auth application-default login
```

---

## Initial Setup

### 1. Clone the Repository
```bash
git clone <repository-url>
cd pl_analyst
```

### 2. Create Virtual Environment
```bash
python -m venv .venv

# On Windows
.venv\Scripts\activate

# On Linux/Mac
source .venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt

# Install ADK from source (if needed)
# pip install -e /path/to/adk-python
```

---

## Configuration

### 1. Create Service Account JSON

**Download from Google Cloud Console:**
1. Go to [GCP Console → IAM & Admin → Service Accounts](https://console.cloud.google.com/iam-admin/serviceaccounts)
2. Select or create a service account with Vertex AI permissions
3. Click **Keys** tab → **Add Key** → **Create New Key** → **JSON**
4. Save the downloaded file as `service-account.json` in the project root
5. **NEVER commit this file to git!**

**Verify the service account has required permissions:**
```bash
gcloud projects get-iam-policy YOUR_PROJECT_ID \
  --flatten="bindings[].members" \
  --filter="bindings.members:serviceAccount:YOUR_SERVICE_ACCOUNT_EMAIL"
```

### 2. Create Database Configuration

Copy the template and fill in your credentials:
```bash
cp config/database_config.yaml.example config/database_config.yaml
```

**Edit `config/database_config.yaml`:**
```yaml
dsn:
  name: SWIFTC
  username: YOUR_AS400_USERNAME
  password: YOUR_AS400_PASSWORD
  # ... other settings

direct:
  driver: "ODBC Driver 17 for SQL Server"
  server: "NDCSQLCLUS04"
  database: "pCORE"
  username: "YOUR_SQL_SERVER_USERNAME"
  password: "YOUR_SQL_SERVER_PASSWORD"
  # ... other settings
```

**IMPORTANT:** Never commit `config/database_config.yaml` with real credentials!

### 3. Create Environment File

Copy the template:
```bash
cp .env.example .env
```

**Edit `.env` and configure:**
```bash
# Authentication
GOOGLE_APPLICATION_CREDENTIALS=./service-account.json

# Project settings
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_CLOUD_LOCATION=us-central1

# Model configuration
ROOT_AGENT_MODEL=gemini-2.5-pro
MODEL_TEMPERATURE=0.0

# A2A Server (point to your Tableau agents server)
A2A_BASE_URL=http://your-tableau-server:8001
A2A_SERVER_PORT=8001

# Rate limiting
GOOGLE_GENAI_RPM_LIMIT=30

# Test mode (set to false for production)
PL_ANALYST_TEST_MODE=false

# Logging
PHASE_LOGGING_ENABLED=true
PHASE_LOG_LEVEL=INFO
```

**IMPORTANT:** Never commit `.env` with real credentials!

### 4. Verify Configuration Files

**Security Checklist:**
- [ ] `service-account.json` is in `.gitignore`
- [ ] `config/database_config.yaml` is in `.gitignore`
- [ ] `.env` is in `.gitignore`
- [ ] No hardcoded credentials in code
- [ ] Template files (`.example`) are committed

---

## Testing Before Deployment

### 1. Test Database Connections
```bash
# Test AS400 connection
python data/test_database_connection.py

# Test SQL Server connection
python data/validate_data_sources.py
```

### 2. Test Tableau A2A Connection (Production Mode)
```bash
# Verify A2A server is running
python data/test_tableau_connection.py
```

### 3. Run Unit Tests
```bash
# Run all unit tests
pytest tests/unit/ -v

# Run with coverage
pytest tests/unit/ --cov=pl_analyst_agent --cov-report=html
```

### 4. Run Integration Tests
```bash
# Test with actual Tableau data (requires A2A server)
pytest tests/integration/ -v -m "not slow"
```

### 5. Test in CSV Mode (Offline Testing)
```bash
# Set test mode in .env
export PL_ANALYST_TEST_MODE=true  # Linux/Mac
set PL_ANALYST_TEST_MODE=true     # Windows

# Run tests with CSV data
pytest tests/ -v
```

### 6. End-to-End Test
```bash
# Test full workflow
python test_with_csv.py  # For CSV mode
# OR
pytest tests/e2e/ -v     # For production mode
```

**Expected Results:**
- All tests pass ✓
- No authentication errors ✓
- Database connections successful ✓
- Analysis completes for sample cost centers ✓

---

## Deployment to Vertex AI

### 1. Review Deployment Script

Check `deployment/deploy_with_tracing.py` for deployment settings:
- Agent name and description
- Model configuration
- Environment variables
- Resource requirements

### 2. Set Environment Variables for Deployment

```bash
# Required for deployment
export GOOGLE_CLOUD_PROJECT=your-project-id
export GOOGLE_CLOUD_LOCATION=us-central1
export GOOGLE_APPLICATION_CREDENTIALS=./service-account.json

# Optional: Model overrides
export ROOT_AGENT_MODEL=gemini-2.5-pro
export MODEL_TEMPERATURE=0.0
```

### 3. Deploy to Vertex AI

```bash
cd deployment
python deploy_with_tracing.py
```

**Deployment Process:**
1. Validates configuration
2. Creates ADK App with tracing enabled
3. Deploys agent to Vertex AI
4. Returns deployment URL and ID

**Expected Output:**
```
✓ Deploying P&L Analyst Agent to Vertex AI...
✓ Agent deployed successfully!
✓ Agent ID: pl-analyst-agent-prod
✓ Agent URL: https://console.cloud.google.com/vertex-ai/agents/...
```

### 4. Note Deployment Details

Save the following for reference:
- Agent ID
- Deployment URL
- Deployment timestamp
- Git commit hash: `git rev-parse HEAD`

---

## Post-Deployment Verification

### 1. Verify Agent Status

```bash
# List agents in project
gcloud ai-platform agents list \
  --project=YOUR_PROJECT_ID \
  --region=us-central1
```

### 2. Test Deployed Agent

**Via Vertex AI Console:**
1. Go to Vertex AI → Agents
2. Find your deployed agent
3. Use the Test panel to run a query
4. Verify response and logs

**Via API (if available):**
```bash
# Test agent endpoint
curl -X POST "https://YOUR_AGENT_ENDPOINT/analyze" \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  -H "Content-Type: application/json" \
  -d '{"cost_center": "PL-067", "revenue_only": true}'
```

### 3. Monitor Initial Runs

**Check Cloud Logging:**
```bash
# View recent logs
gcloud logging read "resource.type=vertex_ai_agent" \
  --project=YOUR_PROJECT_ID \
  --limit=50 \
  --format=json
```

**Verify:**
- Agent starts successfully
- Database connections work
- Tableau A2A communication works
- Analysis completes end-to-end
- No error logs

---

## Monitoring and Maintenance

### 1. Set Up Monitoring

**Cloud Logging Filters:**
```
resource.type="vertex_ai_agent"
resource.labels.agent_id="pl-analyst-agent-prod"
severity>=ERROR
```

**Recommended Alerts:**
- Error rate > 5% over 5 minutes
- Agent response time > 120 seconds
- Database connection failures
- Rate limit exceeded

### 2. Performance Metrics

**Track These Metrics:**
- Average analysis time per cost center (target: 65-100s)
- Success rate (target: >95%)
- Database query times
- Model token usage
- Error rates by phase

### 3. Log Review Schedule

- **Daily:** Check error logs
- **Weekly:** Review performance metrics
- **Monthly:** Analyze usage patterns and costs

### 4. Credential Rotation

**Quarterly:** Rotate credentials:
1. Database passwords
2. Service account keys
3. API keys (if used)

---

## Troubleshooting

### Common Issues

#### 1. Authentication Errors
```
Error: Could not load credentials
```
**Solution:**
- Verify `GOOGLE_APPLICATION_CREDENTIALS` path
- Check service account has required roles
- Re-download service account JSON if needed

#### 2. Database Connection Failures
```
Error: Unable to connect to database
```
**Solution:**
- Verify database credentials in `config/database_config.yaml`
- Check network connectivity
- Verify ODBC driver is installed
- Test connection with `test_database_connection.py`

#### 3. Rate Limit Errors
```
Error: 429 Too Many Requests
```
**Solution:**
- Reduce `GOOGLE_GENAI_RPM_LIMIT` in `.env`
- Increase `GOOGLE_GENAI_RETRY_DELAY`
- Check quota limits in GCP Console

#### 4. A2A Connection Failures
```
Error: Could not connect to A2A server
```
**Solution:**
- Verify `A2A_BASE_URL` is correct
- Check Tableau agent server is running
- Test with `test_tableau_connection.py`
- Temporarily enable `PL_ANALYST_TEST_MODE=true` for testing

#### 5. Timeout Issues
```
Error: Analysis timed out
```
**Solution:**
- Check database query performance
- Verify model availability
- Review phase logs in `logs/` directory
- Consider increasing timeout settings

### Debug Mode

**Enable verbose logging:**
```bash
export PHASE_LOG_LEVEL=DEBUG
export PHASE_LOG_STACK_TRACES=true
```

**Run with detailed output:**
```bash
python -m pl_analyst_agent.agent --cost-center PL-067 --verbose
```

---

## Rollback Procedures

### Quick Rollback

If the deployment has issues:

**1. Deploy Previous Version:**
```bash
# Check previous deployments
gcloud ai-platform agents list --project=YOUR_PROJECT_ID

# Rollback to previous agent (if using versioning)
# OR redeploy from previous git commit
git checkout PREVIOUS_COMMIT_HASH
python deployment/deploy_with_tracing.py
```

**2. Disable New Agent:**
```bash
# Delete problematic deployment
gcloud ai-platform agents delete AGENT_ID \
  --project=YOUR_PROJECT_ID \
  --region=us-central1
```

### Emergency Fallback

If critical issues occur:

**Switch to CSV Test Mode:**
```bash
# Update .env
export PL_ANALYST_TEST_MODE=true

# Redeploy with test mode enabled
python deployment/deploy_with_tracing.py
```

This allows analysis to continue using cached CSV data while investigating issues.

---

## Production Readiness Checklist

Before declaring production-ready:

### Security
- [ ] All credentials rotated (not using exposed credentials)
- [ ] Service account has minimal required permissions
- [ ] No hardcoded secrets in code
- [ ] `.gitignore` properly configured
- [ ] Security scan completed (no critical vulnerabilities)

### Testing
- [ ] All unit tests passing
- [ ] Integration tests passing
- [ ] E2E test successful
- [ ] Performance benchmarks meet targets
- [ ] Load testing completed (if applicable)

### Configuration
- [ ] All template files created and documented
- [ ] Environment variables documented
- [ ] Database connections tested
- [ ] A2A server connections verified

### Deployment
- [ ] Deployment script tested
- [ ] Agent deploys successfully to Vertex AI
- [ ] Post-deployment verification passed
- [ ] Monitoring and alerting configured

### Documentation
- [ ] README updated with setup instructions
- [ ] DEPLOYMENT.md completed
- [ ] Runbook for common issues created
- [ ] Team trained on deployment process

### Operations
- [ ] On-call rotation defined
- [ ] Escalation procedures documented
- [ ] Backup and recovery tested
- [ ] Disaster recovery plan in place

---

## Support and Contacts

### Key Resources
- **Documentation**: See `docs/` directory
- **Architecture**: `docs/AGENT_ARCHITECTURE_SUMMARY.md`
- **Troubleshooting**: `docs/TROUBLESHOOTING.md` (if exists)
- **GitHub Issues**: [Repository Issues URL]

### Emergency Contacts
- **Primary On-Call**: [Contact Info]
- **Secondary On-Call**: [Contact Info]
- **GCP Support**: [Support Case Link]
- **Database Team**: [Contact Info]

---

## Version History

| Version | Date | Changes | Deployed By |
|---------|------|---------|-------------|
| 1.0.0 | YYYY-MM-DD | Initial production deployment | - |

---

**Last Updated**: 2025-11-13
**Maintained By**: Development Team
