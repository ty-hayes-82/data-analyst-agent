"""Proxy agent that sanitizes data-source requests."""

from __future__ import annotations

import uuid
from typing import AsyncGenerator

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.genai.types import Content, Part

from ..utils.json_utils import safe_parse_json


class DataSourceProxyAgent(BaseAgent):
    """Wraps upstream Tableau/Hyper agents with a clean query context."""

    query_key: str

    def __init__(self, agent, query_key: str):
        super().__init__(name=f"proxy_{agent.name}", query_key=query_key)
        object.__setattr__(self, "agent", agent)

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        from google.adk.sessions.session import Session

        req_analysis_raw = ctx.session.state.get("request_analysis", {})
        req_analysis = safe_parse_json(req_analysis_raw)
        clean_query = req_analysis.get(self.query_key)

        start = ctx.session.state.get("primary_query_start_date", "24 months ago")
        end = ctx.session.state.get("primary_query_end_date", "today")

        if not clean_query:
            dim = req_analysis.get("primary_dimension", "unknown_dimension")
            val = req_analysis.get("primary_dimension_value", "unknown_value")
            contract = ctx.session.state.get("dataset_contract")
            ds_label = getattr(contract, "display_name", "data") if contract else "data"
            clean_query = f"Retrieve monthly {ds_label} for {dim} '{val}'."

        date_suffix = f" Time period: {start} to {end}. Return all available rows."
        if start not in clean_query and end not in clean_query:
            clean_query = clean_query.rstrip(".") + "." + date_suffix

        temp_session = await ctx.session_service.create_session(
            app_name=f"temp_{self.agent.name}",
            user_id=ctx.session.user_id,
        )
        temp_session.events.append(
            Event(
                invocation_id="clean_input",
                author="user",
                content=Content(role="user", parts=[Part(text=clean_query)]),
            )
        )
        temp_session.state.update(
            {k: v for k, v in ctx.session.state.items() if any(tok in k for tok in ("date", "period", "time"))}
        )

        temp_ctx = InvocationContext(
            agent=self.agent,
            session=temp_session,
            session_service=ctx.session_service,
            invocation_id=str(uuid.uuid4()),
            run_config=ctx.run_config,
        )

        final_content = ""
        result_key = f"{self.agent.name}_result"
        async for event in self.agent.run_async(temp_ctx):
            yield event
            if event.content and event.content.role == "model":
                for part in event.content.parts:
                    if part.text:
                        final_content += part.text
        if result_key in temp_session.state:
            ctx.session.state[result_key] = temp_session.state[result_key]
        elif final_content:
            ctx.session.state[result_key] = final_content
        else:
            print(f"[{self.name}] WARNING: {result_key} missing and no content captured")
