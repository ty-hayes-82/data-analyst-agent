import os
import sys
from pathlib import Path

# Add project root to sys.path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from data_analyst_agent.config import config
print(f"Auth Method: {os.getenv('GOOGLE_APPLICATION_CREDENTIALS')}")
print(f"Vertex AI Enabled: {os.getenv('GOOGLE_GENAI_USE_VERTEXAI')}")
print(f"API Key exists in env: {'GOOGLE_API_KEY' in os.environ}")
