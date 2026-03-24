import os
import sys
import json
import time
from pathlib import Path
from google import genai
from google.genai import types

# Set up project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from data_analyst_agent.config import config

async def test_single_model():
    client = genai.Client(vertexai=True)
    model_name = "gemini-3.1-flash-lite-preview"
    print(f"Testing {model_name}...")
    try:
        t0 = time.perf_counter()
        response = client.models.generate_content(
            model=model_name,
            contents="Hello, how are you?",
            config=types.GenerateContentConfig(
                temperature=0.2,
            )
        )
        ms = int((time.perf_counter() - t0) * 1000)
        print(f"Success in {ms}ms: {response.text}")
    except Exception as e:
        print(f"Error with {model_name}: {e}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(test_single_model())
