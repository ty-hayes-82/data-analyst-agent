#!/usr/bin/env python
"""
Run P&L Analyst Agent using ADK programmatic interface.

This script runs the agent programmatically since the ADK CLI expects
specific package structures. This provides the same functionality as `adk run`
but with proper path configuration for this project.

Usage:
    python run_agent.py                              # Interactive mode
    python run_agent.py --test                       # CSV test mode
    python run_agent.py --query "Analyze CC 067"     # Non-interactive
    python run_agent.py --input input.json           # From file
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load .env file first
dotenv_path = Path(__file__).parent / '.env'
load_dotenv(dotenv_path=dotenv_path)

# Parse args first
parser = argparse.ArgumentParser(description="Run P&L Analyst Agent")
parser.add_argument("--test", action="store_true", help="Run in CSV test mode (no A2A agents)")
parser.add_argument("--query", type=str, help="Run single query non-interactively")
parser.add_argument("--input", type=str, help="Run from input JSON file")
parser.add_argument("--save-session", action="store_true", help="Save session on exit")
parser.add_argument("--session-id", type=str, help="Session ID to use/resume")
parser.add_argument("--user-id", type=str, default="default_user", help="User ID")
parser.add_argument("--app-name", type=str, default="pl_analyst", help="Application name")
args = parser.parse_args()

# Set TEST_MODE environment variable if --test flag
if args.test:
    os.environ["PL_ANALYST_TEST_MODE"] = "true"
    print("[INFO] Running in TEST_MODE with CSV data")

# Set Vertex AI flag for ADK
if "GOOGLE_CLOUD_PROJECT" in os.environ and "GOOGLE_CLOUD_LOCATION" in os.environ:
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "1"
    print(f"[INFO] Using Vertex AI (Project: {os.environ['GOOGLE_CLOUD_PROJECT']}, Location: {os.environ['GOOGLE_CLOUD_LOCATION']})")

# Add parent directory to path for pl_analyst package imports
# This allows: from pl_analyst.pl_analyst_agent.agent import root_agent
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Now import the agent (after setting environment and path)
from pl_analyst.pl_analyst_agent.agent import root_agent

# Import ADK components
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
from google.adk.auth.credential_service.in_memory_credential_service import InMemoryCredentialService
from google.adk.apps.app import App
from google.adk.runners import Runner
from google.genai import types
from google.adk.utils.context_utils import Aclosing


async def run_interactive():
    """Run agent in interactive mode."""
    # Create services
    session_service = InMemorySessionService()
    artifact_service = InMemoryArtifactService()
    credential_service = InMemoryCredentialService()

    # Create app
    app = App(name=args.app_name, root_agent=root_agent)
    runner = Runner(
        app=app,
        artifact_service=artifact_service,
        session_service=session_service,
        credential_service=credential_service,
    )

    # Create session
    if args.session_id:
        # Try to load existing session
        try:
            session = await session_service.get_session(session_id=args.session_id)
            print(f"[INFO] Resumed session: {session.id}")
        except:
            session = await session_service.create_session(
                app_name=args.app_name,
                user_id=args.user_id
            )
            print(f"[INFO] Created new session: {session.id}")
    else:
        session = await session_service.create_session(
            app_name=args.app_name,
            user_id=args.user_id
        )
        print(f"[INFO] Created session: {session.id}")

    print("\n" + "="*80)
    print("P&L Analyst Agent - Interactive Mode")
    print("="*80)
    print(f"App: {args.app_name}")
    print(f"User: {args.user_id}")
    print(f"Session: {session.id}")
    if args.test:
        print("Mode: TEST (using CSV data)")
    else:
        print("Mode: LIVE (using A2A agents)")
    print("\nType your query or 'exit' to quit")
    print("="*80 + "\n")

    while True:
        try:
            query = input('[user]: ')
            if not query or not query.strip():
                continue
            if query.lower() == 'exit':
                break

            # Run agent
            content = types.Content(role='user', parts=[types.Part(text=query)])
            async with Aclosing(
                runner.run_async(
                    user_id=session.user_id,
                    session_id=session.id,
                    new_message=content
                )
            ) as agen:
                async for event in agen:
                    if event.content and event.content.parts:
                        if text := ''.join(part.text or '' for part in event.content.parts):
                            print(f'[{event.author}]: {text}')

        except KeyboardInterrupt:
            print("\n[INFO] Interrupted by user")
            break
        except Exception as e:
            print(f"[ERROR] {e}")
            import traceback
            traceback.print_exc()

    # Save session if requested
    if args.save_session:
        session_file = f"session_{session.id}.json"
        print(f"[INFO] Session would be saved to: {session_file}")
        # TODO: Implement session serialization

    await runner.close()
    print("\n[INFO] Exiting...")


async def run_single_query():
    """Run agent with a single query."""
    # Create services
    session_service = InMemorySessionService()
    artifact_service = InMemoryArtifactService()
    credential_service = InMemoryCredentialService()

    # Create app
    app = App(name=args.app_name, root_agent=root_agent)
    runner = Runner(
        app=app,
        artifact_service=artifact_service,
        session_service=session_service,
        credential_service=credential_service,
    )

    # Create session
    session = await session_service.create_session(
        app_name=args.app_name,
        user_id=args.user_id
    )

    print(f"[INFO] Running query: {args.query}")
    print("="*80 + "\n")

    # Run agent
    content = types.Content(role='user', parts=[types.Part(text=args.query)])
    async with Aclosing(
        runner.run_async(
            user_id=session.user_id,
            session_id=session.id,
            new_message=content
        )
    ) as agen:
        async for event in agen:
            if event.content and event.content.parts:
                if text := ''.join(part.text or '' for part in event.content.parts):
                    print(f'[{event.author}]: {text}')

    await runner.close()
    print("\n[INFO] Query completed")


async def run_from_file():
    """Run agent from input JSON file."""
    import json

    # Create services
    session_service = InMemorySessionService()
    artifact_service = InMemoryArtifactService()
    credential_service = InMemoryCredentialService()

    # Create app
    app = App(name=args.app_name, root_agent=root_agent)
    runner = Runner(
        app=app,
        artifact_service=artifact_service,
        session_service=session_service,
        credential_service=credential_service,
    )

    # Load input file
    with open(args.input, 'r') as f:
        input_data = json.load(f)

    # Create session with initial state
    initial_state = input_data.get('state', {})
    session = await session_service.create_session(
        app_name=args.app_name,
        user_id=args.user_id,
        state=initial_state
    )

    print(f"[INFO] Running from file: {args.input}")
    print("="*80 + "\n")

    # Run queries
    queries = input_data.get('queries', [])
    for query in queries:
        print(f'[user]: {query}')

        content = types.Content(role='user', parts=[types.Part(text=query)])
        async with Aclosing(
            runner.run_async(
                user_id=session.user_id,
                session_id=session.id,
                new_message=content
            )
        ) as agen:
            async for event in agen:
                if event.content and event.content.parts:
                    if text := ''.join(part.text or '' for part in event.content.parts):
                        print(f'[{event.author}]: {text}')

    await runner.close()
    print("\n[INFO] All queries completed")


def main():
    """Main entry point."""
    try:
        if args.input:
            asyncio.run(run_from_file())
        elif args.query:
            asyncio.run(run_single_query())
        else:
            asyncio.run(run_interactive())
    except KeyboardInterrupt:
        print("\n[INFO] Interrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
