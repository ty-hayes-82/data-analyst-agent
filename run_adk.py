#!/usr/bin/env python
"""
Wrapper to run ADK agent on Windows with UTF-8 encoding.

Usage:
    echo "analyze tolls revenue for cost center 067" | python run_adk.py
    python run_adk.py  (interactive mode)
"""
import sys
import os
import subprocess

# Re-launch with PYTHONUTF8=1 if not already set
if os.environ.get("PYTHONUTF8") != "1":
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PL_ANALYST_TEST_MODE"] = "true"
    result = subprocess.run(
        [sys.executable, "-X", "utf8", "-m", "google.adk.cli", "run", "pl_analyst_agent"],
        env=env,
        cwd=os.path.dirname(os.path.abspath(__file__)),
    )
    sys.exit(result.returncode)
