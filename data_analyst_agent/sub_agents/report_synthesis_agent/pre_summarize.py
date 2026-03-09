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
Pre-summarize report synthesis prompt components via a fast LLM.

When REPORT_SYNTHESIS_PRE_SUMMARIZE=1, each of the 5 prompt sections is sent
to a quick LLM call before the main synthesis to reduce input size and latency.
"""

import asyncio
import os
from typing import Any

# Per-call timeout (seconds) to avoid hangs
_SUMMARY_TIMEOUT_S = 60


SUMMARY_PROMPT = (
    "Summarize the following for executive report synthesis. "
    "Preserve: key numbers, insight titles, priorities, materiality. "
    "MANDATORY: If the input contains 'temporal_grain', 'period_unit', or date timeframe fields, "
    "preserve them exactly as provided. Do not summarize or remove temporal metadata. "
    "Max 500 chars. Be concise."
)


def _summarize_one(client: Any, model: str, section_name: str, text: Any, config: Any = None) -> str:
    """Synchronous single-section summarization."""
    # Ensure text is a string
    import json
    if isinstance(text, (dict, list)):
        text = json.dumps(text, indent=2)
    elif not isinstance(text, str):
        text = str(text) if text is not None else ""

    if not text or len(text.strip()) < 100:
        return text
    
    # Skip summarization for machine-readable context blocks that must remain exact
    if section_name == "temporal_context":
        return text

    try:
        prompt = f"{SUMMARY_PROMPT}\n\nSection: {section_name}\n\n{text}"
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=config,
        )
        out = (response.text or "").strip()
        return out[:600] if out else text[:600]  # Cap at 600 chars
    except Exception as e:
        print(f"[REPORT_SYNTHESIS] Pre-summarize failed for {section_name}: {e}")
        return text[:600]  # Fallback: truncate on error


async def summarize_components(
    components: dict[str, str],
    model: str | None = None,
) -> dict[str, str]:
    """Summarize each component via a fast LLM (sequential to avoid rate limits and thread-safety issues).

    Args:
        components: Dict of section_name -> raw text.
        model: Model to use (default from REPORT_SYNTHESIS_SUMMARIZER_MODEL or gemini-2.5-flash-lite).

    Returns:
        Dict of section_name -> summarized text.
    """
    from google.genai import Client
    from google.genai import types

    model = model or os.environ.get("REPORT_SYNTHESIS_SUMMARIZER_MODEL", "gemini-2.5-flash-lite")
    location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    use_vertex = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "false").lower() == "true"
    project = os.getenv("GOOGLE_CLOUD_PROJECT") if use_vertex else None

    client = Client(
        vertexai=use_vertex,
        project=project,
        location=location if use_vertex else None,
    )

    # No thinking for summarization (fast, lightweight calls)
    config = types.GenerateContentConfig(
        temperature=0,
        response_modalities=["TEXT"],
        max_output_tokens=512,
    )

    out = {}
    for name, text in components.items():
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(_summarize_one, client, model, name, text, config),
                timeout=_SUMMARY_TIMEOUT_S,
            )
            out[name] = result
        except asyncio.TimeoutError:
            print(f"[REPORT_SYNTHESIS] Pre-summarize timeout for {name} ({_SUMMARY_TIMEOUT_S}s)")
            val = components[name]
            if not isinstance(val, str):
                import json
                val = json.dumps(val)
            out[name] = val[:600]
        except Exception as e:
            print(f"[REPORT_SYNTHESIS] Pre-summarize error for {name}: {e}")
            val = components[name]
            if not isinstance(val, str):
                import json
                val = json.dumps(val)
            out[name] = val[:600]
    return out
