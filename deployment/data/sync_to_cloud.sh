#!/bin/bash
# Sync datasets and contracts to Cloud Storage
# Usage: ./sync_to_cloud.sh --project YOUR_PROJECT [--environment prod]

set -euo pipefail

# ============================================================================
# Configuration
# ============================================================================

PROJECT_ID=""
ENVIRONMENT="prod"
DRY_RUN=false

# ============================================================================
# Parse Arguments
# ============================================================================

while [[ $# -gt 0 ]]; do
  case $1 in
    --project)
      PROJECT_ID="$2"
      shift 2
      ;;
    --environment)
      ENVIRONMENT="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --help)
      echo "Usage: $0 --project PROJECT_ID [OPTIONS]"
      echo ""
      echo "Options:"
      echo "  --project PROJECT_ID    GCP Project ID (required)"
      echo "  --environment ENV       Environment (default: prod)"
      echo "  --dry-run               Show what would be uploaded without uploading"
      echo "  --help                  Show this help message"
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
done

if [[ -z "$PROJECT_ID" ]]; then
  echo "ERROR: --project is required"
  exit 1
fi

# ============================================================================
# Bucket Names
# ============================================================================

DATASETS_BUCKET="${PROJECT_ID}-data-analyst-datasets"
OUTPUTS_BUCKET="${PROJECT_ID}-data-analyst-outputs"

echo "============================================================================"
echo "Syncing Data to Cloud Storage"
echo "============================================================================"
echo "Project:         $PROJECT_ID"
echo "Environment:     $ENVIRONMENT"
echo "Datasets Bucket: gs://${DATASETS_BUCKET}"
echo "Outputs Bucket:  gs://${OUTPUTS_BUCKET}"
if [[ "$DRY_RUN" == true ]]; then
  echo "DRY RUN MODE:    No files will be uploaded"
fi
echo "============================================================================"
echo ""

GSUTIL_OPTS="-m"
if [[ "$DRY_RUN" == true ]]; then
  GSUTIL_OPTS="${GSUTIL_OPTS} -n"
fi

# ============================================================================
# 1. Upload Dataset Contracts
# ============================================================================

echo "[1/4] Uploading dataset contracts..."

if [[ -d config/datasets ]]; then
  gsutil ${GSUTIL_OPTS} rsync -r -d \
    -x ".*\.pyc$|.*__pycache__.*" \
    config/datasets/ \
    gs://${DATASETS_BUCKET}/datasets/
  
  echo "✓ Dataset contracts synced to gs://${DATASETS_BUCKET}/datasets/"
else
  echo "⚠ config/datasets/ not found, skipping"
fi

echo ""

# ============================================================================
# 2. Upload Validation Data
# ============================================================================

echo "[2/4] Uploading validation data..."

if [[ -d data/validation ]]; then
  gsutil ${GSUTIL_OPTS} rsync -r -d \
    data/validation/ \
    gs://${DATASETS_BUCKET}/validation/
  
  echo "✓ Validation data synced to gs://${DATASETS_BUCKET}/validation/"
else
  echo "⚠ data/validation/ not found, skipping"
fi

echo ""

# ============================================================================
# 3. Upload Synthetic/Sample Data (if exists)
# ============================================================================

echo "[3/4] Uploading sample data..."

if [[ -d data/synthetic ]]; then
  gsutil ${GSUTIL_OPTS} rsync -r -d \
    data/synthetic/ \
    gs://${DATASETS_BUCKET}/synthetic/
  
  echo "✓ Synthetic data synced to gs://${DATASETS_BUCKET}/synthetic/"
else
  echo "⚠ data/synthetic/ not found, skipping"
fi

echo ""

# ============================================================================
# 4. Create Cloud Path Mappings
# ============================================================================

echo "[4/4] Generating cloud path mappings..."

cat > deployment/data/cloud_paths.yaml <<EOF
# Auto-generated Cloud Storage path mappings
# Generated: $(date -u +"%Y-%m-%dT%H:%M:%SZ")

project_id: ${PROJECT_ID}
environment: ${ENVIRONMENT}

buckets:
  datasets: ${DATASETS_BUCKET}
  outputs: ${OUTPUTS_BUCKET}

paths:
  # Dataset contracts
  contracts: gs://${DATASETS_BUCKET}/datasets/
  
  # Validation data
  validation: gs://${DATASETS_BUCKET}/validation/
  
  # Sample/synthetic data
  synthetic: gs://${DATASETS_BUCKET}/synthetic/
  
  # Output directories
  outputs: gs://${OUTPUTS_BUCKET}/
  analysis_json: gs://${OUTPUTS_BUCKET}/analysis/
  executive_briefs: gs://${OUTPUTS_BUCKET}/executive_briefs/
  logs: gs://${OUTPUTS_BUCKET}/logs/

# Example dataset paths
datasets:
  trade_data:
    contract: gs://${DATASETS_BUCKET}/datasets/trade_data/contract.yaml
    validation: gs://${DATASETS_BUCKET}/validation/trade_data/
  
  # Add more datasets as needed

# Usage in code:
# from pathlib import Path
# import yaml
# paths = yaml.safe_load(Path("deployment/data/cloud_paths.yaml").read_text())
# contract_url = paths["datasets"]["trade_data"]["contract"]
EOF

echo "✓ Cloud path mappings saved to deployment/data/cloud_paths.yaml"
echo ""

# ============================================================================
# Summary
# ============================================================================

if [[ "$DRY_RUN" == false ]]; then
  echo "============================================================================"
  echo "Sync Complete!"
  echo "============================================================================"
  echo ""
  echo "Verify uploads:"
  echo "  gsutil ls -r gs://${DATASETS_BUCKET}/"
  echo ""
  echo "Grant public read access (if needed for validation data):"
  echo "  gsutil iam ch allUsers:objectViewer gs://${DATASETS_BUCKET}/validation/"
  echo ""
else
  echo "============================================================================"
  echo "Dry Run Complete (no files uploaded)"
  echo "============================================================================"
  echo "Remove --dry-run to perform actual sync"
  echo ""
fi
