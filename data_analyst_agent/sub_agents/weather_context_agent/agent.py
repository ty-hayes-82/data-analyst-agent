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
Weather Context Agent - ADK LLM agent grounded in Google Search.

Uses google.adk.tools.google_search to check whether weather may explain
insight card anomalies. The LLM decides when to invoke search.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import AsyncGenerator, Any

from google.adk import Agent
from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.genai import types
from google.genai.types import Content, Part

from config.model_loader import get_agent_model, get_agent_thinking_config
from .prompt import WEATHER_CONTEXT_AGENT_INSTRUCTION


def _collect_insight_cards_from_reports(outputs_dir: Path, max_cards: int = 5) -> str:
    """Extract insight card text from metric_*.md for the weather agent input."""
    lines_by_metric: list[str] = []
    for md_file in sorted(outputs_dir.glob("metric_*.md")):
        name = md_file.stem.replace("metric_", "").replace("_", " ").replace("-", "/")
        content = md_file.read_text(encoding="utf-8", errors="replace")
        # Pull Insight Cards section
        in_section = False
        card_lines: list[str] = []
        card_count = 0
        for line in content.splitlines():
            if line.startswith("## Insight Cards"):
                in_section = True
                continue
            if in_section:
                if line.startswith("## ") and "Insight Cards" not in line:
                    break
                if line.startswith("### "):
                    card_count += 1
                    if card_count > max_cards:
                        break
                card_lines.append(line)
        if card_lines:
            lines_by_metric.append(f"=== {name} ===\n" + "\n".join(card_lines))
    return "\n\n".join(lines_by_metric)


def _parse_weather_response(text: str) -> dict[str, Any]:
    """Extract JSON from agent response. Returns {"results": []} on parse failure."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "results" in data:
            return data
        return {"results": data} if isinstance(data, list) else {"results": []}
    except json.JSONDecodeError:
        return {"results": []}


_base_agent = Agent(
    model=get_agent_model("narrative_agent"),
    name="weather_context_agent",
    description="Checks whether weather may explain insight card anomalies using Google Search.",
    instruction=WEATHER_CONTEXT_AGENT_INSTRUCTION,
    output_key="weather_context",
    tools=[],
    generate_content_config=types.GenerateContentConfig(
        response_modalities=["TEXT"],
        temperature=0.2,
        thinking_config=get_agent_thinking_config("narrative_agent"),
    ),
)


class WeatherContextWrapper(BaseAgent):
    """Wrapper that injects insight cards and uses ADK Agent with google_search."""

    def __init__(self):
        super().__init__(name="weather_context_agent")

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        if os.environ.get("WEATHER_CONTEXT_ENABLED", "false").lower() != "true":
            print("[WEATHER] WEATHER_CONTEXT_ENABLED=false. Skipping.")
            yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=EventActions())
            return

        print("\n" + "=" * 80)
        print("[WEATHER] WeatherContextAgent starting (ADK agent + Google Search grounding)")
        print("=" * 80)

        outputs_dir = Path(os.environ.get("WEATHER_OUTPUTS_DIR") or "outputs").resolve()
        if not outputs_dir.exists():
            print("[WEATHER] outputs/ not found. Skipping.")
            yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=EventActions())
            return

        cards_text = _collect_insight_cards_from_reports(
            outputs_dir,
            max_cards=int(os.environ.get("WEATHER_CONTEXT_MAX_CHECKS", "5")),
        )
        if not cards_text.strip():
            print("[WEATHER] No insight cards found. Skipping.")
            yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=EventActions())
            return

        user_message = (
            "Check whether weather may explain any of these insight card anomalies. "
            "Use Google Search for each relevant location and date range. "
            "Return the structured JSON as instructed.\n\n"
            f"{cards_text}"
        )

        from google.adk.tools import google_search

        agent_with_search = Agent(
            model=_base_agent.model,
            name=_base_agent.name,
            description=_base_agent.description,
            instruction=_base_agent.instruction,
            output_key=_base_agent.output_key,
            tools=[google_search],
            generate_content_config=_base_agent.generate_content_config,
        )

        ctx.session.events.append(
            Event(
                invocation_id="weather_injection",
                author="user",
                content=Content(role="user", parts=[Part(text=user_message)]),
            )
        )

        raw_text = ""
        try:
            gen = agent_with_search.run_async(ctx)
            async for event in gen:
                yield event
                if getattr(event, "content", None) and hasattr(event.content, "parts"):
                    for part in getattr(event.content, "parts", []) or []:
                        if hasattr(part, "text") and part.text:
                            raw_text += part.text
                if getattr(event, "actions", None) and event.actions.state_delta:
                    val = event.actions.state_delta.get("weather_context")
                    if isinstance(val, str):
                        raw_text = val
            raw_text = raw_text or ctx.session.state.get("weather_context") or ""
        except Exception as e:
            print(f"[WEATHER] Agent error: {e}")
            raw_text = ctx.session.state.get("weather_context") or ""

        weather_context = _parse_weather_response(raw_text) if raw_text else {"results": []}
        explicable_count = sum(
            1 for r in weather_context.get("results", []) if r.get("weather_explicable")
        )
        print(f"[WEATHER] Done. {explicable_count} weather-explicable of {len(weather_context.get('results', []))} checked.")

        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            actions=EventActions(state_delta={"weather_context": weather_context}),
        )
        print("\n[WEATHER] WeatherContextAgent complete")


root_agent = WeatherContextWrapper()
