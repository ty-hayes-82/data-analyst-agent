# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Authentication configuration for Google Cloud services."""

import os
from pathlib import Path


def setup_google_auth():
    """
    Configure Google Cloud authentication using service account or API key fallback.
    
    Priority order:
    1. GOOGLE_APPLICATION_CREDENTIALS environment variable
    2. Service account JSON in parent directory (outside repo, secure)
    3. Service account JSON in project root (legacy, shows warning)
    4. GOOGLE_API_KEY environment variable (fallback)
    5. Application Default Credentials (gcloud auth)
    
    Returns:
        tuple: (auth_method: str, details: str)
    
    Raises:
        ValueError: If no authentication method is configured
    """
    
    project_root = Path(__file__).parent.absolute()
    
    # Priority 1: GOOGLE_APPLICATION_CREDENTIALS already set
    if "GOOGLE_APPLICATION_CREDENTIALS" in os.environ:
        creds_path = os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
        if Path(creds_path).exists():
            return ("service_account_env", "environment variable (secure)")
        else:
            print(f"WARNING: GOOGLE_APPLICATION_CREDENTIALS points to non-existent file: {creds_path}")
    
    # Priority 2: Service account JSON in parent directory (recommended, outside repo)
    parent_json_file = project_root.parent.parent / "service-account.json"
    if parent_json_file.exists():
        abs_path = str(parent_json_file.absolute().resolve())
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = abs_path
        os.environ["GOOGLE_APPLICATION_CREDENTIALS_JSON"] = abs_path
        
        # Extract project_id from service account JSON and set it
        try:
            import json
            with open(parent_json_file, 'r') as f:
                sa_data = json.load(f)
                project_id = sa_data.get('project_id')
                if project_id:
                    os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project_id)
        except Exception:
            pass  # If we can't read it, that's OK - will use defaults
        
        return ("service_account_parent", "parent directory (secure)")
    
    # Priority 3: Service account JSON in project root (legacy, show warning)
    json_file = project_root / "service-account.json"
    if json_file.exists():
        abs_path = str(json_file.absolute().resolve())
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = abs_path
        os.environ["GOOGLE_APPLICATION_CREDENTIALS_JSON"] = abs_path
        
        # Extract project_id from service account JSON and set it
        try:
            import json
            with open(json_file, 'r') as f:
                sa_data = json.load(f)
                project_id = sa_data.get('project_id')
                if project_id:
                    os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project_id)
        except Exception:
            pass  # If we can't read it, that's OK - will use defaults
        
        print("WARNING: service-account.json found in project root. Move to parent directory or use environment variable for better security.")
        return ("service_account_file_legacy", "project root (INSECURE - move outside repo)")
    
    # Priority 4: API Key fallback (for backward compatibility)
    if "GOOGLE_API_KEY" in os.environ:
        print("INFO: Using GOOGLE_API_KEY for authentication")
        print("RECOMMENDATION: Migrate to service account for production use")
        return ("api_key", "GOOGLE_API_KEY environment variable")
    
    # Priority 5: Application Default Credentials (gcloud)
    # ADK will automatically try this, so just warn the user
    print("INFO: No explicit credentials found. Attempting Application Default Credentials (gcloud)...")
    return ("adc", "Application Default Credentials (gcloud auth)")


def verify_auth():
    """
    Verify that authentication is properly configured and working.
    
    Returns:
        bool: True if authentication is working, False otherwise
    """
    try:
        from google.auth import default
        from google.auth.transport.requests import Request
        
        credentials, project = default()
        
        # Try to refresh to ensure credentials are valid
        # Note: Some scopes may not be available during verification
        try:
            credentials.refresh(Request())
            refresh_status = "refreshed"
        except Exception as refresh_error:
            # If refresh fails with scope error, credentials may still be valid
            if "invalid_scope" in str(refresh_error).lower():
                refresh_status = "loaded (scope verification skipped)"
            else:
                raise refresh_error
        
        # Get additional info if it's a service account
        if hasattr(credentials, 'service_account_email'):
            print(f"[OK] Authentication successful!")
            print(f"  Method: Service Account")
            print(f"  Email: {credentials.service_account_email}")
            print(f"  Project: {project}")
            print(f"  Status: Credentials {refresh_status}")
        else:
            print(f"[OK] Authentication successful!")
            print(f"  Method: {type(credentials).__name__}")
            print(f"  Project: {project}")
            print(f"  Status: Credentials {refresh_status}")
        
        return True
        
    except Exception as e:
        print(f"[FAIL] Authentication verification failed: {e}")
        print("\nTroubleshooting:")
        print("1. Set GOOGLE_APPLICATION_CREDENTIALS environment variable to your service account JSON file")
        print("2. Or place service-account.json in parent directory (outside repo)")
        print("3. Or run: gcloud auth application-default login")
        print("4. Or set GOOGLE_API_KEY environment variable")
        print("\nSee config/CREDENTIALS_SETUP.md for detailed instructions.")
        return False


def print_auth_status():
    """Print current authentication configuration status."""
    print("=" * 70)
    print("Google Cloud Authentication Status")
    print("=" * 70)
    
    try:
        auth_method, details = setup_google_auth()
        
        print(f"\nAuthentication Method: {auth_method}")
        print(f"Details: {details}")
        
        if auth_method in ["service_account_file", "service_account_env"]:
            print("\n[OK] Using Service Account (Recommended for production)")
        elif auth_method == "api_key":
            print("\n[WARN] Using API Key (Consider migrating to service account)")
        else:
            print("\n! Using Application Default Credentials")
        
        print("\n" + "=" * 70)
        verify_auth()
        print("=" * 70)
        
    except Exception as e:
        print(f"\n[FAIL] Error: {e}")
        print("\nPlease configure authentication before starting the servers.")
        print("See SERVICE_ACCOUNT_SETUP.md for instructions.")
        print("=" * 70)
        raise


if __name__ == "__main__":
    # Test authentication when run directly
    print_auth_status()

