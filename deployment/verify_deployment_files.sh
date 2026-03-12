#!/bin/bash
# Verify all deployment files are present

echo "============================================================================"
echo "Verifying Deployment Files"
echo "============================================================================"
echo ""

MISSING=0
TOTAL=0

check_file() {
    TOTAL=$((TOTAL + 1))
    if [[ -f "$1" ]]; then
        echo "✅ $1"
    else
        echo "❌ MISSING: $1"
        MISSING=$((MISSING + 1))
    fi
}

echo "Core Deployment Files:"
check_file "deployment/vertex_ai/agent_config.yaml"
check_file "deployment/vertex_ai/requirements.txt"
check_file "deployment/vertex_ai/Dockerfile"
check_file "deployment/gcp/deploy.sh"
check_file "deployment/gcp/config.yaml"
check_file "deployment/config/cloud_config.py"
check_file "config/env.cloud.example"

echo ""
echo "Infrastructure as Code:"
check_file "deployment/gcp/terraform/main.tf"
check_file "deployment/gcp/terraform/terraform.tfvars.example"

echo ""
echo "Data Management:"
check_file "deployment/data/sync_to_cloud.sh"
check_file "deployment/data/cloud_paths.yaml.template"

echo ""
echo "Agent Garden:"
check_file "deployment/agent_garden/manifest.yaml"
check_file "deployment/agent_garden/README.md"
check_file "deployment/agent_garden/examples.json"

echo ""
echo "Web UI:"
check_file "web/Dockerfile"
check_file "web/requirements.txt"
check_file "web/cloudbuild.yaml"

echo ""
echo "Monitoring:"
check_file "deployment/monitoring/dashboard.json"
check_file "deployment/monitoring/alerts.yaml"

echo ""
echo "CI/CD:"
check_file ".github/workflows/deploy-vertex-ai.yml"
check_file "cloudbuild.yaml"

echo ""
echo "Documentation:"
check_file "deployment/README.md"
check_file "deployment/ARCHITECTURE.md"
check_file "deployment/TROUBLESHOOTING.md"
check_file "deployment/SCALING.md"
check_file "deployment/cost_analysis.md"
check_file "deployment/DEPLOYMENT_CHECKLIST.md"
check_file "DEPLOYMENT_SUMMARY.md"

echo ""
echo "============================================================================"
echo "Verification Summary"
echo "============================================================================"
echo "Total files checked: $TOTAL"
echo "Missing files: $MISSING"
echo ""

if [[ $MISSING -eq 0 ]]; then
    echo "✅ All deployment files present!"
    echo ""
    echo "Next steps:"
    echo "1. Review: deployment/README.md"
    echo "2. Configure: deployment/gcp/terraform/terraform.tfvars"
    echo "3. Deploy: cd deployment/gcp && ./deploy.sh --project YOUR_PROJECT"
    exit 0
else
    echo "❌ Some deployment files are missing. Please recreate them."
    exit 1
fi
