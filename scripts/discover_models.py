import os
import sys
from pathlib import Path

# Add project root to sys.path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from data_analyst_agent.config import config
from google import genai

def list_models(location="us-central1"):
    print(f"\nListing available models on Vertex AI ({location})...")
    try:
        client = genai.Client(vertexai=True, location=location)
        models = client.models.list()
        
        candidates = []
        for m in models:
            if "gemini" in m.name.lower():
                print(f"  - {m.name}")
                candidates.append(m.name)
        
        if not candidates:
            print("  No Gemini models found.")
        return candidates
    except Exception as e:
        print(f"  Error: {e}")
        return []

if __name__ == "__main__":
    regions = ["us-central1", "us-east4", "us-west1", "europe-west1", "europe-west4", "asia-northeast1"]
    all_models = {}
    for region in regions:
        all_models[region] = list_models(region)
