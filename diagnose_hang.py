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

"""
Diagnostic script to identify why the agent hangs at load_from_global_cache.

This script tests:
1. Rate limit configuration
2. Model response time with large data
3. Function execution time
4. API timeout settings
"""

import os
import sys
import time
import asyncio
from pathlib import Path
from dotenv import load_dotenv

# Load environment
env_path = Path(__file__).parent / '.env'
if env_path.exists():
    load_dotenv(env_path)
    print(f"Loaded environment from .env")

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Enable test mode
os.environ["PL_ANALYST_TEST_MODE"] = "true"

# Setup authentication
if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
    print(f"Using service account: {os.environ['GOOGLE_APPLICATION_CREDENTIALS']}")
elif os.environ.get("GOOGLE_API_KEY"):
    print(f"Using API Key")
else:
    service_account_path = Path(__file__).parent / "service-account.json"
    if service_account_path.exists():
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(service_account_path.absolute())
        print(f"Using service account from pl_analyst/service-account.json")

os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"
os.environ["GOOGLE_CLOUD_PROJECT"] = os.environ.get("GOOGLE_CLOUD_PROJECT", "vertex-ai-bi-testing")
os.environ["GOOGLE_CLOUD_LOCATION"] = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")


print("="*80)
print("DIAGNOSTIC TEST - Identifying Hang Issue")
print("="*80)
print()


def check_rate_limits():
    """Check rate limit configuration."""
    print("[1] Rate Limit Configuration")
    print("-" * 40)
    rpm_limit = os.environ.get("GOOGLE_GENAI_RPM_LIMIT", "not set")
    retry_delay = os.environ.get("GOOGLE_GENAI_RETRY_DELAY", "not set")
    max_retries = os.environ.get("GOOGLE_GENAI_MAX_RETRIES", "not set")
    exponential_backoff = os.environ.get("GOOGLE_GENAI_EXPONENTIAL_BACKOFF", "not set")
    
    print(f"  RPM Limit: {rpm_limit}")
    print(f"  Retry Delay: {retry_delay}s")
    print(f"  Max Retries: {max_retries}")
    print(f"  Exponential Backoff: {exponential_backoff}")
    print()
    
    # Check if limits are too restrictive
    if rpm_limit != "not set" and int(rpm_limit) < 10:
        print(f"  WARNING: RPM limit ({rpm_limit}) is very low. This may cause slow processing.")
        print(f"  RECOMMENDATION: Try increasing to 15-30 for testing")
    
    print()


def test_csv_loading():
    """Test CSV data loading performance."""
    print("[2] CSV Data Loading Test")
    print("-" * 40)
    
    csv_file = Path(__file__).parent / "data" / "PL-067-REVENUE-ONLY.csv"
    if not csv_file.exists():
        print(f"  ERROR: CSV file not found at {csv_file}")
        return
    
    import pandas as pd
    
    start = time.time()
    df = pd.read_csv(csv_file)
    load_time = time.time() - start
    
    print(f"  File: {csv_file.name}")
    print(f"  Rows: {len(df)}")
    print(f"  Columns: {len(df.columns)}")
    print(f"  Load time: {load_time:.3f}s")
    
    # Convert to JSON (what the function does)
    start = time.time()
    json_data = df.to_dict(orient="records")
    json_time = time.time() - start
    
    print(f"  JSON conversion time: {json_time:.3f}s")
    print(f"  JSON record count: {len(json_data)}")
    
    # Serialize to string (final step)
    import json
    start = time.time()
    json_str = json.dumps({"time_series": json_data, "status": "success"}, indent=2)
    serialize_time = time.time() - start
    json_size_kb = len(json_str) / 1024
    
    print(f"  JSON serialization time: {serialize_time:.3f}s")
    print(f"  JSON string size: {json_size_kb:.1f} KB")
    print()
    
    total_time = load_time + json_time + serialize_time
    print(f"  Total processing time: {total_time:.3f}s")
    
    if json_size_kb > 500:
        print(f"  WARNING: JSON payload is large ({json_size_kb:.1f} KB)")
        print(f"  RECOMMENDATION: This large payload may cause LLM processing delays")
    
    print()


async def test_function_directly():
    """Test the load_from_global_cache function directly."""
    print("[3] Direct Function Test")
    print("-" * 40)
    
    # Load the CSV data into cache first
    from pl_analyst.pl_analyst_agent.sub_agents.data_cache import set_validated_csv
    import pandas as pd
    
    csv_file = Path(__file__).parent / "data" / "PL-067-REVENUE-ONLY.csv"
    df = pd.read_csv(csv_file)
    csv_str = df.to_csv(index=False)
    set_validated_csv(csv_str)
    
    print(f"  Loaded {len(df)} records into cache")
    
    # Now test the function
    import importlib
    tools_module = importlib.import_module('pl_analyst.pl_analyst_agent.sub_agents.01_data_validation_agent.tools.load_from_global_cache')
    load_from_global_cache = tools_module.load_from_global_cache
    
    print(f"  Calling load_from_global_cache()...")
    start = time.time()
    result = await load_from_global_cache()
    elapsed = time.time() - start
    
    print(f"  Function completed in {elapsed:.3f}s")
    print(f"  Result size: {len(result) / 1024:.1f} KB")
    
    if elapsed > 1.0:
        print(f"  WARNING: Function took longer than expected")
    
    print()


async def test_model_with_large_input():
    """Test model response time with a large input similar to what it will receive."""
    print("[4] Model Response Time Test")
    print("-" * 40)
    
    from google.genai import types
    from google.adk import Agent
    from pl_analyst.config.model_loader import get_agent_model
    
    # Create a simple test agent
    test_agent = Agent(
        model=get_agent_model("data_validation_agent"),  # Uses "ultra" tier (gemini-2.0-flash-lite)
        name="test_agent",
        instruction="You are a test agent. When you receive function response data, simply respond with 'Data received and validated.'",
        generate_content_config=types.GenerateContentConfig(
            response_modalities=["TEXT"],
            temperature=0.0,
        ),
    )
    
    print(f"  Model: {get_agent_model('data_validation_agent')}")
    
    # Create a large mock function response (similar size to actual response)
    import json
    mock_records = [{"period": f"2024-{i:02d}", "amount": i * 1000, "gl_account": f"3{j:03d}_00"} 
                    for i in range(1, 16) for j in range(1, 61)]
    
    mock_response = json.dumps({
        "analysis_type": "ingest_validation",
        "status": "success",
        "time_series": mock_records,
        "quality_flags": {"total_records": len(mock_records)}
    }, indent=2)
    
    print(f"  Mock response size: {len(mock_response) / 1024:.1f} KB")
    print(f"  Mock record count: {len(mock_records)}")
    
    # Test 1: Simple text input (baseline)
    print(f"\n  Test 1: Simple text input (baseline)")
    start = time.time()
    
    from google.adk.sessions.in_memory_session_service import InMemorySessionService
    from google.adk.runners import Runner
    
    session_service = InMemorySessionService()
    runner = Runner(
        app_name="diagnostic_test",
        agent=test_agent,
        session_service=session_service
    )
    
    session = await session_service.create_session(
        app_name="diagnostic_test",
        user_id="test_user"
    )
    
    simple_message = types.Content(
        role="user",
        parts=[types.Part.from_text(text="Hello, this is a simple test.")]
    )
    
    response_received = False
    async for event in runner.run_async(
        user_id="test_user",
        session_id=session.id,
        new_message=simple_message
    ):
        if event.content and event.content.parts:
            response_received = True
            break
    
    baseline_time = time.time() - start
    print(f"    Response time: {baseline_time:.3f}s")
    
    # Test 2: Large JSON input (simulating function response)
    print(f"\n  Test 2: Large JSON input (simulating function response)")
    
    session2 = await session_service.create_session(
        app_name="diagnostic_test",
        user_id="test_user_2"
    )
    
    large_message = types.Content(
        role="user",
        parts=[types.Part.from_text(text=f"Process this data:\n{mock_response[:1000]}...")]
    )
    
    start = time.time()
    response_received = False
    async for event in runner.run_async(
        user_id="test_user_2",
        session_id=session2.id,
        new_message=large_message
    ):
        if event.content and event.content.parts:
            response_received = True
            break
    
    large_input_time = time.time() - start
    print(f"    Response time: {large_input_time:.3f}s")
    print(f"    Delta: +{large_input_time - baseline_time:.3f}s vs baseline")
    
    if large_input_time > 30:
        print(f"\n  WARNING: Model takes {large_input_time:.1f}s to process large inputs")
        print(f"  DIAGNOSIS: This is likely the root cause of the hang")
        print(f"  RECOMMENDATIONS:")
        print(f"    1. Reduce data size (filter to recent periods only)")
        print(f"    2. Use a faster model tier for data_validation_agent")
        print(f"    3. Store data in session state instead of returning via function")
    elif large_input_time > 10:
        print(f"\n  CAUTION: Model processing time is significant ({large_input_time:.1f}s)")
    else:
        print(f"\n  OK: Model processing time is acceptable")
    
    print()


async def run_diagnostics():
    """Run all diagnostic tests."""
    check_rate_limits()
    test_csv_loading()
    await test_function_directly()
    await test_model_with_large_input()
    
    print("="*80)
    print("DIAGNOSTIC COMPLETE")
    print("="*80)
    print()
    print("NEXT STEPS:")
    print("  1. Review warnings above")
    print("  2. If model processing is slow, consider:")
    print("     - Reducing data payload size")
    print("     - Using faster model tier")
    print("     - Optimizing data storage pattern")
    print("  3. If rate limits are too low, increase RPM_LIMIT")
    print()


if __name__ == "__main__":
    asyncio.run(run_diagnostics())

