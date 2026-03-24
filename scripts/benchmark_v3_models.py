import os
import sys
import json
import time
import re
import asyncio
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Tuple

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from data_analyst_agent.config import config
from google import genai
from google.genai import types

# Import agent components
from data_analyst_agent.sub_agents.executive_brief_agent.agent import (
    EXECUTIVE_BRIEF_RESPONSE_SCHEMA,
    _format_instruction,
)
from data_analyst_agent.sub_agents.executive_brief_agent.prompt import EXECUTIVE_BRIEF_INSTRUCTION

# Benchmark candidates (Vertex AI short names)
# Focused on 3.0+ to diagnose the hang
MODELS = [
    "gemini-3-flash-preview",
    "gemini-3.1-flash-lite-preview",
    "gemini-3.1-pro-preview",
]

# Latest cache path
CACHE_PATH = PROJECT_ROOT / "outputs" / "ops_metrics_ds" / "lob_ref" / "Line_Haul" / "20260323_122337" / ".cache" / "digest.json"

async def run_targeted_benchmark():
    print(f"Loading cached digest from {CACHE_PATH}")
    payload = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    digest = payload.get("digest", "")
    metric_names = payload.get("metric_names", [])
    
    instruction = _format_instruction(
        EXECUTIVE_BRIEF_INSTRUCTION,
        metric_count=len(metric_names),
        analysis_period="Dec 07, 2025 - Mar 14, 2026",
        scope_preamble="Analysis for Line Haul division.",
        dataset_specific_append="",
        prompt_variant_append="",
    )
    
    user_message = (
        f"COMPARISON BASIS: WoW (week-over-week vs prior week).\n"
        f"Week ending: 2026-03-14\n"
        f"Metrics: {', '.join(sorted(metric_names))}\n\n"
        f"DIGEST:\n{digest}\n\n"
        "Generate the CEO brief JSON."
    )
    
    client = genai.Client(vertexai=True)
    loop = asyncio.get_running_loop()
    
    for model_name in MODELS:
        print(f"\nBenchmarking {model_name}...")
        for i in range(1, 2): # Just 1 iteration for now
            t0 = time.perf_counter()
            try:
                # Use a 60s timeout
                response = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        lambda: client.models.generate_content(
                            model=model_name,
                            contents=user_message,
                            config=types.GenerateContentConfig(
                                system_instruction=instruction,
                                response_mime_type="application/json",
                                response_schema=EXECUTIVE_BRIEF_RESPONSE_SCHEMA,
                                temperature=0.2,
                            )
                        )
                    ),
                    timeout=90
                )
                ms = int((time.perf_counter() - t0) * 1000)
                raw = response.text or ""
                print(f"  Iteration {i}: {ms}ms, length={len(raw)}")
            except asyncio.TimeoutError:
                print(f"  Iteration {i}: TIMEOUT after 90s")
            except Exception as e:
                print(f"  Iteration {i} ERROR: {e}")

if __name__ == "__main__":
    asyncio.run(run_targeted_benchmark())
