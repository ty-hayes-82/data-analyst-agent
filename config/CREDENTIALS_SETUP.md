# Google Cloud Credentials Setup

## Overview

This project requires Google Cloud service account credentials to access Vertex AI and other GCP services.

## Setup Methods

### Method 1: Environment Variable (Recommended)

Set the `GOOGLE_APPLICATION_CREDENTIALS` environment variable to point to your service account JSON file:

**PowerShell:**
```powershell
$env:GOOGLE_APPLICATION_CREDENTIALS = "C:\path\to\your\service-account.json"
```

**Bash/Linux:**
```bash
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/your/service-account.json"
```

**Permanent (add to profile):**
- PowerShell: Add to `$PROFILE` file
- Bash: Add to `~/.bashrc` or `~/.bash_profile`

### Method 2: Default Location

Place your `service-account.json` file in the parent directory (outside the repository):

```
C:\Streamlit\development\
  ├── service-account.json  <-- Place here (NOT committed)
  └── pl_analyst/
      └── ...
```

## Creating a Service Account

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Navigate to **IAM & Admin** > **Service Accounts**
3. Click **Create Service Account**
4. Provide a name and description
5. Grant required roles:
   - **Vertex AI User** (for Gemini API access)
   - **BigQuery Data Viewer** (if querying BigQuery)
   - **Storage Object Viewer** (if accessing GCS)
6. Click **Done**
7. Click on the created service account
8. Go to **Keys** tab
9. Click **Add Key** > **Create new key**
10. Choose **JSON** format
11. Download and save securely

## Required Permissions

Your service account needs these IAM roles:

- `roles/aiplatform.user` - Vertex AI access
- `roles/bigquery.dataViewer` - BigQuery read access (if applicable)
- `roles/storage.objectViewer` - GCS read access (if applicable)

## Security Best Practices

### DO:
- Store credentials OUTSIDE the repository
- Use environment variables for credential paths
- Rotate service account keys regularly (every 90 days)
- Restrict service account permissions to minimum required
- Use separate service accounts for dev/staging/prod

### DON'T:
- Commit `service-account.json` to Git
- Share service account keys in chat/email
- Use production keys for local development
- Hard-code credential paths in code

## Rotation & Recovery

### If a Key is Compromised:

1. Go to Google Cloud Console
2. Navigate to the service account
3. Delete the compromised key immediately
4. Create a new key
5. Update the file location
6. Clear your Git history if it was committed:
   ```bash
   # Use BFG Repo-Cleaner or git-filter-repo
   git filter-repo --path service-account.json --invert-paths
   ```

### Regular Rotation (Every 90 Days):

1. Create a new key (keep old one active)
2. Update environment variable/file location
3. Test the new key
4. Delete the old key once confirmed working

## Troubleshooting

### Error: "No credentials found"
- Ensure `GOOGLE_APPLICATION_CREDENTIALS` is set OR
- Place `service-account.json` in parent directory

### Error: "Permission denied"
- Check service account has required IAM roles
- Verify the project ID matches your GCP project

### Error: "Invalid JSON"
- Ensure the JSON file is not corrupted
- Check file encoding is UTF-8
- Verify the file matches the structure in `service-account.json.example`

## Testing Credentials

Run this Python snippet to test your credentials:

```python
import os
from google.cloud import aiplatform

# Initialize Vertex AI
aiplatform.init(
    project=os.environ.get("GOOGLE_CLOUD_PROJECT", "vertex-ai-bi-testing"),
    location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
)

print("Credentials working! Project:", aiplatform.initializer.global_config.project)
```

## Weather Context Agent (Spec 030)

The Weather Context Agent uses the ADK built-in `google_search` tool for grounding. It uses the same credentials as other agents (GOOGLE_API_KEY or Vertex AI service account). No additional API keys are required.

Set `WEATHER_CONTEXT_ENABLED=true` to enable. Default: `false`.

## Environment Variables Reference

```powershell
# Required
$env:GOOGLE_APPLICATION_CREDENTIALS = "C:\path\to\service-account.json"
$env:GOOGLE_CLOUD_PROJECT = "your-project-id"
$env:GOOGLE_CLOUD_LOCATION = "us-central1"

# For Vertex AI
$env:GOOGLE_GENAI_USE_VERTEXAI = "True"
```

## Additional Resources

- [Google Cloud Service Accounts Documentation](https://cloud.google.com/iam/docs/service-accounts)
- [Application Default Credentials](https://cloud.google.com/docs/authentication/application-default-credentials)
- [Vertex AI Authentication](https://cloud.google.com/vertex-ai/docs/authentication)


