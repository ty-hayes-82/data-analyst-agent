"""
Cloud Configuration Loader for GCP Deployment

Loads configuration from:
1. Secret Manager (for sensitive values)
2. Cloud Storage (for dataset contracts)
3. Environment variables (for runtime config)
4. deployment/gcp/config.yaml (for environment-specific settings)
"""

import os
import json
from pathlib import Path
from typing import Dict, Any, Optional
import yaml

try:
    from google.cloud import secretmanager
    from google.cloud import storage
    HAS_GCP_LIBS = True
except ImportError:
    HAS_GCP_LIBS = False


class CloudConfig:
    """Cloud-native configuration loader for GCP deployment."""
    
    def __init__(self, environment: Optional[str] = None):
        """
        Initialize cloud config loader.
        
        Args:
            environment: Environment name (dev, staging, prod).
                        If None, reads from ENVIRONMENT env var (default: prod)
        """
        self.environment = environment or os.getenv("ENVIRONMENT", "prod")
        self.project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
        self.region = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
        
        # Initialize clients if running in cloud
        self._secret_client = None
        self._storage_client = None
        
        if HAS_GCP_LIBS and self.project_id:
            try:
                self._secret_client = secretmanager.SecretManagerServiceClient()
                self._storage_client = storage.Client(project=self.project_id)
            except Exception as e:
                print(f"Warning: Could not initialize GCP clients: {e}")
        
        # Load environment config
        self.config = self._load_environment_config()
    
    def _load_environment_config(self) -> Dict[str, Any]:
        """Load environment-specific configuration from config.yaml."""
        config_path = Path(__file__).parent.parent / "gcp" / "config.yaml"
        
        if not config_path.exists():
            return {}
        
        with open(config_path) as f:
            all_config = yaml.safe_load(f)
        
        return all_config.get(self.environment, {})
    
    def get_secret(self, secret_name: str, default: Optional[str] = None) -> Optional[str]:
        """
        Retrieve secret from Secret Manager.
        
        Args:
            secret_name: Name of the secret in Secret Manager
            default: Default value if secret not found or running locally
        
        Returns:
            Secret value or default
        """
        # If running locally, fall back to environment variables
        if not self._secret_client or not self.project_id:
            return os.getenv(secret_name.upper().replace("-", "_"), default)
        
        try:
            secret_path = f"projects/{self.project_id}/secrets/{secret_name}/versions/latest"
            response = self._secret_client.access_secret_version(request={"name": secret_path})
            return response.payload.data.decode("UTF-8")
        except Exception as e:
            print(f"Warning: Could not access secret {secret_name}: {e}")
            return default
    
    def get_gcs_path(self, path_type: str) -> str:
        """
        Get Cloud Storage path for datasets or outputs.
        
        Args:
            path_type: "datasets" or "outputs"
        
        Returns:
            GCS path (gs://bucket-name/...)
        """
        bucket_name = self.config.get(f"{path_type}_bucket")
        
        if not bucket_name and self.project_id:
            # Construct default bucket name
            bucket_name = f"{self.project_id}-data-analyst-{path_type}"
        
        return f"gs://{bucket_name}" if bucket_name else f"/app/{path_type}"
    
    def download_contract(self, dataset_name: str, local_path: Path) -> bool:
        """
        Download dataset contract from Cloud Storage.
        
        Args:
            dataset_name: Dataset identifier
            local_path: Local path to save contract.yaml
        
        Returns:
            True if download successful, False otherwise
        """
        if not self._storage_client:
            return False
        
        try:
            bucket_name = self.config.get("datasets_bucket")
            if not bucket_name:
                return False
            
            bucket = self._storage_client.bucket(bucket_name)
            blob = bucket.blob(f"datasets/{dataset_name}/contract.yaml")
            
            local_path.parent.mkdir(parents=True, exist_ok=True)
            blob.download_to_filename(str(local_path))
            
            return True
        except Exception as e:
            print(f"Warning: Could not download contract for {dataset_name}: {e}")
            return False
    
    def upload_output(self, local_path: Path, gcs_subpath: str) -> Optional[str]:
        """
        Upload output file to Cloud Storage.
        
        Args:
            local_path: Local file path
            gcs_subpath: Subpath within outputs bucket
        
        Returns:
            Public GCS URL or None if upload failed
        """
        if not self._storage_client:
            return None
        
        try:
            bucket_name = self.config.get("outputs_bucket")
            if not bucket_name:
                return None
            
            bucket = self._storage_client.bucket(bucket_name)
            blob = bucket.blob(gcs_subpath)
            
            blob.upload_from_filename(str(local_path))
            
            return f"gs://{bucket_name}/{gcs_subpath}"
        except Exception as e:
            print(f"Warning: Could not upload output to GCS: {e}")
            return None
    
    def get_model_config(self, agent_name: str) -> str:
        """
        Get model configuration for specific agent.
        
        Args:
            agent_name: Agent identifier (root_agent, planner, narrative, synthesis)
        
        Returns:
            Model name
        """
        models = self.config.get("models", {})
        return models.get(agent_name, os.getenv("ROOT_AGENT_MODEL", "gemini-2.5-flash-exp"))
    
    def get_resource_limits(self) -> Dict[str, Any]:
        """Get resource limits for this environment."""
        return self.config.get("resources", {
            "cpu": "2",
            "memory": "8Gi",
            "timeout": "3600s"
        })
    
    def get_feature_flags(self) -> Dict[str, bool]:
        """Get feature flags for this environment."""
        return self.config.get("features", {
            "phase_logging": True,
            "code_insights": True,
            "pdf_generation": True
        })
    
    def to_env_dict(self) -> Dict[str, str]:
        """
        Convert cloud config to environment variable dictionary.
        
        Returns:
            Dictionary of environment variables
        """
        env = {
            "GOOGLE_CLOUD_PROJECT": self.project_id or "",
            "GOOGLE_CLOUD_LOCATION": self.region,
            "ENVIRONMENT": self.environment,
        }
        
        # Add API keys from secrets
        api_key = self.get_secret("google-api-key")
        if api_key:
            env["GOOGLE_API_KEY"] = api_key
        
        # Add feature flags
        features = self.get_feature_flags()
        env["USE_CODE_INSIGHTS"] = str(features.get("code_insights", True)).lower()
        env["PHASE_LOGGING_ENABLED"] = str(features.get("phase_logging", True)).lower()
        env["EXECUTIVE_BRIEF_OUTPUT_FORMAT"] = "pdf" if features.get("pdf_generation", True) else "md"
        
        # Add model configs
        env["ROOT_AGENT_MODEL"] = self.get_model_config("root_agent")
        
        return env


# Global instance (lazy-loaded)
_cloud_config_instance: Optional[CloudConfig] = None


def get_cloud_config(environment: Optional[str] = None) -> CloudConfig:
    """
    Get global CloudConfig instance.
    
    Args:
        environment: Environment name (dev, staging, prod)
    
    Returns:
        CloudConfig instance
    """
    global _cloud_config_instance
    
    if _cloud_config_instance is None:
        _cloud_config_instance = CloudConfig(environment=environment)
    
    return _cloud_config_instance


# Example usage:
if __name__ == "__main__":
    config = get_cloud_config()
    
    print(f"Environment: {config.environment}")
    print(f"Project ID: {config.project_id}")
    print(f"Region: {config.region}")
    print(f"Datasets path: {config.get_gcs_path('datasets')}")
    print(f"Outputs path: {config.get_gcs_path('outputs')}")
    print(f"Root model: {config.get_model_config('root_agent')}")
    print(f"Feature flags: {config.get_feature_flags()}")
