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

"""Configuration management for Data Analyst Agent."""

import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# Load environment variables from .env file if it exists.
# config.py lives at data_analyst_agent/config.py; the .env is in the project root
# (one level up: pl_analyst/.env). Fall back to looking inside data_analyst_agent/
# as a secondary location so local overrides still work.
_agent_env = Path(__file__).parent / ".env"
_root_env = Path(__file__).parent.parent / ".env"
for env_path in [_root_env, _agent_env]:
    if env_path.exists():
        load_dotenv(env_path, override=False)
        break


class Config:
    """Configuration class for Data Analyst Agent."""
    
    def __init__(self):
        # Google Cloud Configuration (Required)
        self.project_id: str = os.getenv("GOOGLE_CLOUD_PROJECT", "vertex-ai-bi-testing")
        self.location: str = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1").lower()
        
        # Model Configuration
        self.root_agent_model: str = os.getenv("ROOT_AGENT_MODEL", "gemini-2.5-pro")
        self.temperature: float = float(os.getenv("MODEL_TEMPERATURE", "0.0"))
        
        # Rate Limiting Configuration (for parallel agent execution)
        self.rpm_limit: str = os.getenv("GOOGLE_GENAI_RPM_LIMIT", "5")
        self.retry_delay: str = os.getenv("GOOGLE_GENAI_RETRY_DELAY", "3")
        self.max_retries: str = os.getenv("GOOGLE_GENAI_MAX_RETRIES", "5")
        self.exponential_backoff: str = os.getenv("GOOGLE_GENAI_EXPONENTIAL_BACKOFF", "True")
        self.backoff_multiplier: str = os.getenv("GOOGLE_GENAI_BACKOFF_MULTIPLIER", "2")
        
        # Remote A2A Agent Configuration
        self.a2a_base_url: str = os.getenv("A2A_BASE_URL", "http://localhost:8001")
        
        # Logging
        self.log_level: str = os.getenv("LOG_LEVEL", "INFO")
        
        # Paths (computed)
        self._project_root = Path(__file__).parent.absolute()
    
    @property
    def project_root(self) -> Path:
        """Get the project root directory path."""
        return self._project_root
    
    @property
    def service_account_file(self) -> Path:
        """
        Get the path to the service account JSON file.
        
        Returns the pl_analyst root path as primary location.
        """
        # Check pl_analyst root first
        pl_analyst_sa = self._project_root.parent / "service-account.json"
        if pl_analyst_sa.exists():
            return pl_analyst_sa
        
        # Check parent directory (outside repo)
        parent_sa = self._project_root.parent.parent / "service-account.json"
        if parent_sa.exists():
            return parent_sa
        
        # Legacy: check data_analyst_agent dir
        agent_sa = self._project_root / "service-account.json"
        return agent_sa
    
    @property
    def database_config_file(self) -> Path:
        """Get the path to the database configuration file."""
        return self._project_root / "database_config.yaml"
    
    @property
    def config_dir(self) -> Path:
        """Get the configuration directory path."""
        return self._project_root / "config"
    
    @property
    def outputs_dir(self) -> Path:
        """Get the outputs directory path."""
        return self._project_root / "outputs"
    
    @property
    def logs_dir(self) -> Path:
        """Get the logs directory path."""
        return self._project_root / "logs"
    
    def setup_google_auth(self) -> tuple[str, str]:
        """
        Configure Google Cloud authentication using service account or API key fallback.
        
        Priority order:
        1. GOOGLE_APPLICATION_CREDENTIALS environment variable
        2. Service account JSON in parent directory (outside repo)
        3. Service account JSON in project root (legacy, shows warning)
        4. GOOGLE_API_KEY environment variable (fallback)
        5. Application Default Credentials (gcloud auth)
        
        Returns:
            tuple: (auth_method: str, details: str)
        """
        # Priority 1: GOOGLE_APPLICATION_CREDENTIALS already set
        if "GOOGLE_APPLICATION_CREDENTIALS" in os.environ:
            creds_path = os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
            if Path(creds_path).exists():
                # Service account present — remove API key to prevent ADK from using
                # the free-tier key and ignoring the service account credentials.
                os.environ.pop("GOOGLE_API_KEY", None)
                return ("service_account_env", "environment variable (secure)")
            else:
                print(f"WARNING: GOOGLE_APPLICATION_CREDENTIALS points to non-existent file: {creds_path}")
        
        # Priority 2: Service account JSON in pl_analyst root
        pl_analyst_sa = self._project_root.parent / "service-account.json"
        if pl_analyst_sa.exists():
            abs_path = str(pl_analyst_sa.absolute().resolve())
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = abs_path
            os.environ["GOOGLE_APPLICATION_CREDENTIALS_JSON"] = abs_path
            os.environ.pop("GOOGLE_API_KEY", None)
            
            try:
                import json
                with open(pl_analyst_sa, 'r') as f:
                    sa_data = json.load(f)
                    project_id = sa_data.get('project_id')
                    if project_id:
                        os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project_id)
                        self.project_id = project_id
            except Exception:
                pass
            
            return ("service_account_pl_analyst", "pl_analyst root")

        # Priority 2b: Service account JSON in parent directory (outside repo)
        parent_sa = self._project_root.parent.parent / "service-account.json"
        if parent_sa.exists():
            abs_path = str(parent_sa.absolute().resolve())
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = abs_path
            os.environ["GOOGLE_APPLICATION_CREDENTIALS_JSON"] = abs_path
            os.environ.pop("GOOGLE_API_KEY", None)
            
            try:
                import json
                with open(parent_sa, 'r') as f:
                    sa_data = json.load(f)
                    project_id = sa_data.get('project_id')
                    if project_id:
                        os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project_id)
                        self.project_id = project_id
            except Exception:
                pass
            
            return ("service_account_parent", "parent directory (secure)")
        
        # Priority 3: Service account JSON in project root (legacy, show warning)
        if self.service_account_file.exists() and self.service_account_file == self._project_root / "service-account.json":
            abs_path = str(self.service_account_file.absolute().resolve())
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = abs_path
            os.environ["GOOGLE_APPLICATION_CREDENTIALS_JSON"] = abs_path
            os.environ.pop("GOOGLE_API_KEY", None)
            
            try:
                import json
                with open(self.service_account_file, 'r') as f:
                    sa_data = json.load(f)
                    project_id = sa_data.get('project_id')
                    if project_id:
                        os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project_id)
                        self.project_id = project_id
            except Exception:
                pass
            
            print("WARNING: service-account.json found in project root. Move to parent directory or use environment variable for better security.")
            return ("service_account_file_legacy", "project root (INSECURE - move outside repo)")
        
        # Priority 4: API Key fallback (for backward compatibility)
        if "GOOGLE_API_KEY" in os.environ:
            return ("api_key", "GOOGLE_API_KEY environment variable")
        
        # Priority 5: Application Default Credentials (gcloud)
        return ("adc", "Application Default Credentials (gcloud auth)")
    
    def setup_environment(self):
        """Set up environment variables for Vertex AI and rate limiting."""
        # Configure Vertex AI vs Google AI (API Key) endpoint selection.
        #
        # Priority:
        #   1. GOOGLE_GENAI_USE_VERTEXAI already set in environment (explicit, respected as-is)
        #   2. GOOGLE_APPLICATION_CREDENTIALS present -> prefer Vertex AI (service account)
        #   3. GOOGLE_API_KEY present (no service account) -> default to Google AI
        #   4. Neither -> default to Vertex AI (ADC / gcloud auth)
        use_vertex = os.getenv("GOOGLE_GENAI_USE_VERTEXAI")
        if use_vertex is None:
            has_service_account = bool(os.getenv("GOOGLE_APPLICATION_CREDENTIALS"))
            has_api_key = bool(os.getenv("GOOGLE_API_KEY"))
            if has_service_account:
                os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"
                print("[INFO] Service account detected -- using Vertex AI (GOOGLE_GENAI_USE_VERTEXAI=True)")
            elif has_api_key:
                os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "False"
                print("[INFO] No service account found -- defaulting to Google AI (API Key)")
            else:
                os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"
                print("[INFO] No explicit auth -- defaulting to Vertex AI (Application Default Credentials)")
        
        os.environ.setdefault("GOOGLE_CLOUD_PROJECT", self.project_id)
        os.environ.setdefault("GOOGLE_CLOUD_LOCATION", self.location)
        
        # Configure rate limiting
        os.environ.setdefault("GOOGLE_GENAI_RPM_LIMIT", self.rpm_limit)
        os.environ.setdefault("GOOGLE_GENAI_RETRY_DELAY", self.retry_delay)
        os.environ.setdefault("GOOGLE_GENAI_MAX_RETRIES", self.max_retries)
        os.environ.setdefault("GOOGLE_GENAI_EXPONENTIAL_BACKOFF", self.exponential_backoff)
        os.environ.setdefault("GOOGLE_GENAI_BACKOFF_MULTIPLIER", self.backoff_multiplier)
        
        # Set up authentication
        self.setup_google_auth()
    
    def validate(self) -> bool:
        """Validate that all required configuration is present."""
        # Check for service account file
        if not self.service_account_file.exists():
            if "GOOGLE_APPLICATION_CREDENTIALS" not in os.environ and "GOOGLE_API_KEY" not in os.environ:
                print("WARNING: No authentication method configured. Agent may fail to initialize.")
                return False
        
        return True
    
    def __repr__(self) -> str:
        """String representation of configuration."""
        return (
            f"Config(project_id={self.project_id}, "
            f"location={self.location}, "
            f"model={self.root_agent_model})"
        )


# Create a global config instance
config = Config()

# Setup environment on import
config.setup_environment()

