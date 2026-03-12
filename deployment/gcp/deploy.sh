#!/bin/bash
# One-Command Deployment Script for Data Analyst Agent to GCP
# Usage: ./deploy.sh --project YOUR_PROJECT --region us-central1

set -euo pipefail

# ============================================================================
# Configuration
# ============================================================================

PROJECT_ID=""
REGION="us-central1"
ENVIRONMENT="prod"
SKIP_TERRAFORM=false
SKIP_BUILD=false
SKIP_AGENT_DEPLOY=false

# ============================================================================
# Parse Arguments
# ============================================================================

while [[ $# -gt 0 ]]; do
  case $1 in
    --project)
      PROJECT_ID="$2"
      shift 2
      ;;
    --region)
      REGION="$2"
      shift 2
      ;;
    --environment)
      ENVIRONMENT="$2"
      shift 2
      ;;
    --skip-terraform)
      SKIP_TERRAFORM=true
      shift
      ;;
    --skip-build)
      SKIP_BUILD=true
      shift
      ;;
    --skip-agent-deploy)
      SKIP_AGENT_DEPLOY=true
      shift
      ;;
    --help)
      echo "Usage: $0 --project PROJECT_ID [OPTIONS]"
      echo ""
      echo "Options:"
      echo "  --project PROJECT_ID      GCP Project ID (required)"
      echo "  --region REGION           GCP Region (default: us-central1)"
      echo "  --environment ENV         Environment (default: prod)"
      echo "  --skip-terraform          Skip Terraform infrastructure provisioning"
      echo "  --skip-build              Skip container image builds"
      echo "  --skip-agent-deploy       Skip agent deployment to Vertex AI"
      echo "  --help                    Show this help message"
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
done

# Validate required arguments
if [[ -z "$PROJECT_ID" ]]; then
  echo "ERROR: --project is required"
  exit 1
fi

echo "============================================================================"
echo "Data Analyst Agent - GCP Deployment"
echo "============================================================================"
echo "Project:     $PROJECT_ID"
echo "Region:      $REGION"
echo "Environment: $ENVIRONMENT"
echo "============================================================================"
echo ""

# ============================================================================
# Step 1: Terraform Infrastructure Provisioning
# ============================================================================

if [[ "$SKIP_TERRAFORM" == false ]]; then
  echo "[1/5] Provisioning GCP infrastructure with Terraform..."
  cd deployment/gcp/terraform
  
  # Initialize Terraform
  terraform init
  
  # Plan
  terraform plan \
    -var="project_id=$PROJECT_ID" \
    -var="region=$REGION" \
    -var="environment=$ENVIRONMENT" \
    -out=tfplan
  
  # Apply
  echo "Review the plan above. Press Enter to apply or Ctrl+C to cancel..."
  read
  terraform apply tfplan
  
  # Extract outputs
  DATASETS_BUCKET=$(terraform output -raw datasets_bucket)
  OUTPUTS_BUCKET=$(terraform output -raw outputs_bucket)
  SERVICE_ACCOUNT=$(terraform output -raw service_account_email)
  ARTIFACT_REGISTRY=$(terraform output -raw artifact_registry)
  
  cd ../../..
  
  echo "✓ Infrastructure provisioned"
  echo ""
else
  echo "[1/5] Skipping Terraform (--skip-terraform)"
  # Manually set expected values
  DATASETS_BUCKET="${PROJECT_ID}-data-analyst-datasets"
  OUTPUTS_BUCKET="${PROJECT_ID}-data-analyst-outputs"
  SERVICE_ACCOUNT="data-analyst-agent@${PROJECT_ID}.iam.gserviceaccount.com"
  ARTIFACT_REGISTRY="${REGION}-docker.pkg.dev/${PROJECT_ID}/data-analyst-agent"
  echo ""
fi

# ============================================================================
# Step 2: Upload Datasets and Contracts to Cloud Storage
# ============================================================================

echo "[2/5] Uploading datasets and contracts to Cloud Storage..."

# Upload dataset contracts
gsutil -m rsync -r config/datasets/ gs://${DATASETS_BUCKET}/datasets/

# Upload validation data
if [[ -d data/validation ]]; then
  gsutil -m rsync -r data/validation/ gs://${DATASETS_BUCKET}/validation/
fi

echo "✓ Datasets uploaded to gs://${DATASETS_BUCKET}"
echo ""

# ============================================================================
# Step 3: Build and Push Container Images
# ============================================================================

if [[ "$SKIP_BUILD" == false ]]; then
  echo "[3/5] Building and pushing container images..."
  
  # Authenticate Docker to Artifact Registry
  gcloud auth configure-docker ${REGION}-docker.pkg.dev --quiet
  
  # Build agent container
  echo "Building agent container..."
  docker build \
    -f deployment/vertex_ai/Dockerfile \
    -t ${ARTIFACT_REGISTRY}/agent:latest \
    -t ${ARTIFACT_REGISTRY}/agent:$(git rev-parse --short HEAD) \
    .
  
  docker push ${ARTIFACT_REGISTRY}/agent:latest
  docker push ${ARTIFACT_REGISTRY}/agent:$(git rev-parse --short HEAD)
  
  # Build web UI container
  echo "Building web UI container..."
  docker build \
    -f web/Dockerfile \
    -t ${ARTIFACT_REGISTRY}/web-ui:latest \
    -t ${ARTIFACT_REGISTRY}/web-ui:$(git rev-parse --short HEAD) \
    web/
  
  docker push ${ARTIFACT_REGISTRY}/web-ui:latest
  docker push ${ARTIFACT_REGISTRY}/web-ui:$(git rev-parse --short HEAD)
  
  echo "✓ Container images built and pushed"
  echo ""
else
  echo "[3/5] Skipping container builds (--skip-build)"
  echo ""
fi

# ============================================================================
# Step 4: Deploy Agent to Vertex AI Agent Engine
# ============================================================================

if [[ "$SKIP_AGENT_DEPLOY" == false ]]; then
  echo "[4/5] Deploying agent to Vertex AI Agent Engine..."
  
  # Substitute variables in agent_config.yaml
  sed -e "s/\${PROJECT_ID}/${PROJECT_ID}/g" \
      -e "s/\${REGION}/${REGION}/g" \
      deployment/vertex_ai/agent_config.yaml > /tmp/agent_config_resolved.yaml
  
  # Deploy (note: actual command may vary based on Vertex AI Agent Engine CLI)
  # This is a placeholder - adjust based on actual Vertex AI Agent Engine API
  gcloud ai agents deploy \
    --config=/tmp/agent_config_resolved.yaml \
    --region=${REGION} \
    --project=${PROJECT_ID}
  
  echo "✓ Agent deployed to Vertex AI Agent Engine"
  echo ""
else
  echo "[4/5] Skipping agent deployment (--skip-agent-deploy)"
  echo ""
fi

# ============================================================================
# Step 5: Deploy Web UI to Cloud Run
# ============================================================================

echo "[5/5] Deploying web UI to Cloud Run..."

gcloud run deploy data-analyst-ui \
  --image=${ARTIFACT_REGISTRY}/web-ui:latest \
  --region=${REGION} \
  --platform=managed \
  --service-account=${SERVICE_ACCOUNT} \
  --allow-unauthenticated \
  --set-env-vars="GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GOOGLE_CLOUD_LOCATION=${REGION}" \
  --project=${PROJECT_ID}

WEB_UI_URL=$(gcloud run services describe data-analyst-ui --region=${REGION} --project=${PROJECT_ID} --format='value(status.url)')

echo "✓ Web UI deployed to Cloud Run"
echo ""

# ============================================================================
# Deployment Summary
# ============================================================================

echo "============================================================================"
echo "Deployment Complete!"
echo "============================================================================"
echo "Datasets Bucket:  gs://${DATASETS_BUCKET}"
echo "Outputs Bucket:   gs://${OUTPUTS_BUCKET}"
echo "Web UI URL:       ${WEB_UI_URL}"
echo "Service Account:  ${SERVICE_ACCOUNT}"
echo "============================================================================"
echo ""
echo "Next Steps:"
echo "1. Store secrets in Secret Manager:"
echo "   echo -n 'YOUR_API_KEY' | gcloud secrets versions add google-api-key --data-file=-"
echo ""
echo "2. Test agent invocation:"
echo "   gcloud ai agents invoke data-analyst-agent --region=${REGION} \\"
echo "     --input='{\"request\": \"Analyze gross margin\", \"dataset_name\": \"trade_data\"}'"
echo ""
echo "3. Register in Agent Garden:"
echo "   cd deployment/agent_garden && gcloud agent-garden agents register --manifest=manifest.yaml"
echo ""
echo "4. Access web UI:"
echo "   open ${WEB_UI_URL}"
echo ""
