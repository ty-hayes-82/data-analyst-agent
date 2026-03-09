#!/usr/bin/env python3
"""
Start A2A Server for Remote Data Agents.

Launches the Google ADK A2A server hosting multiple data source agents.
By default, pre-extracts all Hyper files before starting the server to
eliminate cold-start delays on first request.

Usage:
    python scripts/start_a2a_server.py
    python scripts/start_a2a_server.py --port 8001
    python scripts/start_a2a_server.py --agent some_data_ds_agent
    python scripts/start_a2a_server.py --skip-extract
"""

import os
import sys
import argparse
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Start A2A server for data source agents")
    parser.add_argument("--port", type=int, default=8001, help="Port to run the A2A server on (default: 8001)")
    parser.add_argument("--agent", type=str, default=None, help="Specific agent module to start")
    parser.add_argument(
        "--skip-extract", action="store_true",
        help="Skip Hyper file pre-extraction (use when files are already extracted)"
    )
    args = parser.parse_args()

    # Resolve workspace root (c:\GITLAB)
    script_dir = Path(__file__).parent.resolve()
    workspace_root = script_dir.parent.parent
    project_root = workspace_root / "pl_analyst" # Keep the folder name for now as it is the repo root
    remote_a2a_root = workspace_root / "remote_a2a"

    if not remote_a2a_root.exists():
        print(f"[ERROR] remote_a2a directory not found at: {remote_a2a_root}")
        sys.exit(1)

    # Load .env file
    env = os.environ.copy()
    dotenv_path = project_root / ".env"
    if dotenv_path.exists():
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=dotenv_path, override=True)
        env = os.environ.copy()
        print(f"[OK] Loaded .env from {dotenv_path}")
    else:
        print(f"[WARN] .env not found at {dotenv_path}")

    # Ensure workspace root is on PYTHONPATH
    python_path = env.get("PYTHONPATH", "")
    if str(workspace_root) not in python_path:
        env["PYTHONPATH"] = f"{workspace_root}{os.pathsep}{python_path}" if python_path else str(workspace_root)

    # Service account
    sa_file = remote_a2a_root / "service-account.json"
    if not sa_file.exists():
        sa_file = project_root / "service-account.json"

    # Set up Vertex AI defaults
    has_sa = sa_file.exists()
    if has_sa:
        env["GOOGLE_GENAI_USE_VERTEXAI"] = "True"
        env["GOOGLE_APPLICATION_CREDENTIALS"] = str(sa_file)
        print(f"[OK] Using service account: {sa_file}")
        # If we have a service account, we MUST use Vertex AI and ignore any API key
        if "GOOGLE_API_KEY" in env:
            print("[INFO] Service account detected - ignoring GOOGLE_API_KEY to avoid rate limits")
    elif env.get("GOOGLE_API_KEY"):
        env["GOOGLE_GENAI_USE_VERTEXAI"] = "False"
        print("[INFO] No service account found -- using Google AI (API Key)")
    else:
        env.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")
        print("[INFO] No explicit auth -- defaulting to Vertex AI (Application Default Credentials)")
    
    env.setdefault("GOOGLE_CLOUD_PROJECT", "vertex-ai-bi-testing")
    env.setdefault("GOOGLE_CLOUD_LOCATION", "us-central1")

    # Pre-extract Hyper files before starting the server
    if not args.skip_extract:
        print("\n[PRE-EXTRACT] Ensuring all Hyper files are extracted...")
        sys.path.insert(0, str(workspace_root))
        try:
            from pl_analyst.scripts.extract_hyper import run_extraction, print_summary
            filter_agent = args.agent if args.agent and args.agent != "remote_a2a" else None
            results = run_extraction(remote_a2a_root, filter_agent=filter_agent)
            exit_code = print_summary(results)
            if exit_code != 0:
                print("[WARN] Some Hyper files failed extraction. Server will start but those agents may not work.")
        except Exception as e:
            print(f"[WARN] Pre-extraction failed: {e}. Server will attempt to start anyway.")
        print()
    else:
        print("[INFO] Skipping Hyper file pre-extraction (--skip-extract)")

    # Determine which agent directory to start
    if args.agent:
        agent_dir = args.agent
    else:
        agent_dir = "remote_a2a"

    print(f"\n{'='*60}")
    print(f"Starting A2A Server")
    print(f"  Port: {args.port}")
    print(f"  Agents Dir: {agent_dir}")
    print(f"  Working Dir: {workspace_root}")
    print(f"{'='*60}\n")

    cmd = [
        sys.executable, "-m", "google.adk.cli",
        "api_server",
        "--a2a",
        "--port", str(args.port),
        agent_dir
    ]

    print(f"Running: {' '.join(cmd)}")
    print()

    try:
        subprocess.run(cmd, cwd=str(workspace_root), env=env)
    except KeyboardInterrupt:
        print("\n[INFO] Server stopped.")
    except Exception as e:
        print(f"[ERROR] Failed to start server: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
