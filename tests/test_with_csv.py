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
Test script for P&L Analyst using CSV data instead of Tableau A2A agents.

Usage:
    python test_with_csv.py
    
This script:
1. Enables TEST_MODE to use CSV data (data/PL-067-REVENUE-ONLY.csv)
2. Runs the P&L analyst on cost center 067 (revenue accounts only)
3. Tests the 3-level drill-down framework

Requirements:
- data/PL-067-REVENUE-ONLY.csv must exist
- All analysis agents must be functional
"""

import os
import asyncio
import sys
from pathlib import Path
import time

# Load environment variables from .env file if it exists
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent / '.env'
    if env_path.exists():
        load_dotenv(env_path)
        print(f"Loaded environment variables from .env")
except ImportError:
    print("python-dotenv not installed - skipping .env file loading")
except Exception as e:
    print(f"Could not load .env file: {e}")

# Fix UTF-8 encoding for Windows console to prevent Unicode crashes
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Enable test mode BEFORE importing pl_analyst_agent
os.environ["PL_ANALYST_TEST_MODE"] = "true"

# Setup authentication - use environment variable or default location
# Priority: 
#   1. Environment variables from .env file (GOOGLE_API_KEY or GOOGLE_APPLICATION_CREDENTIALS)
#   2. GOOGLE_APPLICATION_CREDENTIALS environment variable
#   3. service-account.json in current directory
#   4. service-account.json in parent directory

print("Setting up Google Cloud configuration...")

# Check for API key first (from .env or environment)
if os.environ.get("GOOGLE_API_KEY"):
    print("Using Google API Key authentication")
    print("Note: This uses google.ai API, not Vertex AI")
    # Don't set GOOGLE_GENAI_USE_VERTEXAI - let it use the API key
    
# Check for service account from environment variable
elif os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
    creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    print(f"Using service account from GOOGLE_APPLICATION_CREDENTIALS")
    print(f"  Path: {creds_path}")
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"
    os.environ["GOOGLE_CLOUD_PROJECT"] = os.environ.get("GOOGLE_CLOUD_PROJECT", "vertex-ai-bi-testing")
    os.environ["GOOGLE_CLOUD_LOCATION"] = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
    print(f"  Project ID: {os.environ['GOOGLE_CLOUD_PROJECT']}")
    print(f"  Location: {os.environ['GOOGLE_CLOUD_LOCATION']}")
    
# Check for service account file in current directory
else:
    service_account_path = Path(__file__).parent / "service-account.json"
    if service_account_path.exists():
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(service_account_path.absolute())
        os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"
        os.environ["GOOGLE_CLOUD_PROJECT"] = os.environ.get("GOOGLE_CLOUD_PROJECT", "vertex-ai-bi-testing")
        os.environ["GOOGLE_CLOUD_LOCATION"] = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
        print("Using service account from pl_analyst/service-account.json")
        print(f"  Project ID: {os.environ['GOOGLE_CLOUD_PROJECT']}")
        print(f"  Location: {os.environ['GOOGLE_CLOUD_LOCATION']}")
    else:
        # Check parent directory
        service_account_path = Path(__file__).parent.parent / "service-account.json"
        if service_account_path.exists():
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(service_account_path.absolute())
            os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"
            os.environ["GOOGLE_CLOUD_PROJECT"] = os.environ.get("GOOGLE_CLOUD_PROJECT", "vertex-ai-bi-testing")
            os.environ["GOOGLE_CLOUD_LOCATION"] = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
            print("Using service account from parent directory (service-account.json)")
            print(f"  Project ID: {os.environ['GOOGLE_CLOUD_PROJECT']}")
            print(f"  Location: {os.environ['GOOGLE_CLOUD_LOCATION']}")
        else:
            print()
            print("="*80)
            print("ERROR: No authentication configured!")
            print("="*80)
            print()
            print("Please configure one of the following:")
            print()
            print("1. API Key (EASIEST - Recommended for testing):")
            print("   Add to .env file: GOOGLE_API_KEY=your-api-key-here")
            print("   Get a key from: https://aistudio.google.com/apikey")
            print()
            print("2. Service Account (for production):")
            print("   Add to .env file: GOOGLE_APPLICATION_CREDENTIALS=./service-account.json")
            print("   Or set environment variable: GOOGLE_APPLICATION_CREDENTIALS")
            print()
            print("3. Place service-account.json in pl_analyst/ or parent directory")
            print()
            print("="*80)
            sys.exit(1)

print()

from pl_analyst.pl_analyst_agent.agent import root_agent
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.adk.runners import Runner
from google.genai import types


async def test_pl_analyst_with_csv():
    """Test P&L Analyst using CSV data."""
    
    print("="*80)
    print("P&L ANALYST - TEST MODE (CSV DATA)")
    print("="*80)
    print()
    print("This test runs the full P&L analyst workflow using CSV data from:")
    print("  pl_analyst/data/PL-067-REVENUE-ONLY.csv")
    print()
    print("Cost Center: 067 (Revenue Accounts Only)")
    print("Analysis: 3-Level Drill-Down Framework")
    print("  - Level 1: High-level summary with baselines (YoY, MoM, 3MMA, 6MMA)")
    print("  - Level 2: Category analysis (top 3-5 drivers explaining 80%+ variance)")
    print("  - Level 3: GL drill-down with root cause classification")
    print()
    print("="*80)
    print()
    
    # Create session service and runner
    session_service = InMemorySessionService()
    runner = Runner(
        app_name="pl_analyst_test",
        agent=root_agent,
        session_service=session_service
    )
    
    # Create session
    session = await session_service.create_session(
        app_name="pl_analyst_test",
        user_id="test_user"
    )
    
    # User request - analyze cost center 067
    user_message = """
    Analyze cost center 067 for the most recent period available in the data.
    
    Provide a 3-level drill-down analysis:
    1. High-level summary with variance analysis (YoY, MoM, 3MMA, 6MMA)
    2. Category-level drivers (identify top 3-5 categories explaining 80%+ of variance)
    3. GL-level drill-down for top categories with root cause analysis
    
    Focus on operational volume normalization (per mile, per load, per stop) where applicable.
    """
    
    # Create user message content
    content = types.Content(
        role="user",
        parts=[types.Part.from_text(text=user_message)]
    )
    
    print(f"User Request: {user_message.strip()}")
    print()
    print("="*80)
    print("STARTING ANALYSIS...")
    print("="*80)
    print()
    
    try:
        # Run the agent with timeout
        response_parts = []
        event_count = 0
        start_time = time.time()
        last_event_time = start_time
        
        print("[DEBUG] Starting agent execution...")
        print(f"[DEBUG] Start time: {time.strftime('%H:%M:%S', time.localtime(start_time))}")
        
        # Heartbeat monitoring
        heartbeat_active = True
        heartbeat_interval = 10  # seconds
        
        async def heartbeat_monitor():
            """Print heartbeat dots while waiting for LLM responses."""
            heartbeat_count = 0
            while heartbeat_active:
                await asyncio.sleep(heartbeat_interval)
                if heartbeat_active:
                    heartbeat_count += 1
                    elapsed_since_last_event = time.time() - last_event_time
                    if elapsed_since_last_event > heartbeat_interval:
                        print(f"  [HEARTBEAT {heartbeat_count}] Waiting... ({elapsed_since_last_event:.0f}s since last event)")
        
        async def run_with_timeout():
            nonlocal event_count, last_event_time
            async for event in runner.run_async(
                user_id="test_user",
                session_id=session.id,
                new_message=content
            ):
                event_count += 1
                current_time = time.time()
                elapsed = current_time - last_event_time
                total_elapsed = current_time - start_time
                last_event_time = current_time
                
                print(f"\n[DEBUG] Event #{event_count} from '{event.author}' (delta: {elapsed:.1f}s, total: {total_elapsed:.1f}s)")
                
                if event.content and event.content.parts:
                    for part in event.content.parts:
                        if part.text:
                            response_parts.append(part.text)
                            # Show more text for debugging
                            text_preview = part.text[:300] if len(part.text) > 300 else part.text
                            print(f"  Content: {text_preview}...")
                        if hasattr(part, 'function_call') and part.function_call:
                            print(f"  Function call: {part.function_call.name}")
                        if hasattr(part, 'function_response') and part.function_response:
                            resp_preview = str(part.function_response.response)[:200] if hasattr(part.function_response, 'response') else ''
                            print(f"  Function response from: {part.function_response.name}")
                            print(f"    Response preview: {resp_preview}...")
                else:
                    print(f"  No content parts")
        
        # Start heartbeat monitor
        heartbeat_task = asyncio.create_task(heartbeat_monitor())
        
        try:
            # Run with a 10 minute timeout (analysis can take 5-7 minutes)
            await asyncio.wait_for(run_with_timeout(), timeout=600)
        finally:
            # Stop heartbeat
            heartbeat_active = False
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass
        
        response = "\n".join(response_parts)
        
        print()
        print("="*80)
        print("ANALYSIS COMPLETE")
        print("="*80)
        print()
        print("Full Response:")
        print(response)
        print()
        
        # Check outputs
        print("="*80)
        print("CHECKING OUTPUTS...")
        print("="*80)
        
        from pathlib import Path
        outputs_dir = Path("outputs")
        
        if outputs_dir.exists():
            output_files = list(outputs_dir.glob("cost_center_*.json"))
            alert_files = list(outputs_dir.glob("alerts_payload_*.json"))
            
            print(f"\nGenerated files:")
            print(f"  Analysis outputs: {len(output_files)} file(s)")
            for f in output_files:
                print(f"    - {f.name}")
            
            print(f"  Alert payloads: {len(alert_files)} file(s)")
            for f in alert_files:
                print(f"    - {f.name}")
        else:
            print("  No outputs directory found")

        # Guard: warn if root outputs exists to avoid confusion during tests
        root_outputs = Path(__file__).parent.parent / "outputs"
        if root_outputs.exists() and root_outputs.resolve() != outputs_dir.resolve():
            print("\nNOTE: Detected root-level outputs directory; test writes only to pl_analyst/outputs.")
        
        print()
        print("="*80)
        print("TEST COMPLETE")
        print("="*80)
        
    except asyncio.TimeoutError:
        print()
        print("="*80)
        print("TIMEOUT - ANALYSIS TOOK TOO LONG")
        print("="*80)
        print(f"\nTimeout after 600 seconds (10 minutes)")
        print(f"Last event was from: {event.author if 'event' in locals() else 'unknown'}")
        print(f"Total events processed: {event_count}")
        print(f"\nThis usually means an agent is stuck in a loop or waiting for data.")
        print("Check the logs above to see which agent was running last.")
        print()
        
        # Show what outputs were generated before timeout
        from pathlib import Path
        outputs_dir = Path("outputs")
        if outputs_dir.exists():
            output_files = list(outputs_dir.glob("*.json"))
            if output_files:
                print("Partial outputs generated before timeout:")
                for f in output_files:
                    print(f"  - {f.name}")
        print()
        
    except Exception as e:
        print()
        print("="*80)
        print("ERROR DURING ANALYSIS")
        print("="*80)
        print(f"\nError: {str(e)}")
        import traceback
        traceback.print_exc()
        print()


if __name__ == "__main__":
    asyncio.run(test_pl_analyst_with_csv())


