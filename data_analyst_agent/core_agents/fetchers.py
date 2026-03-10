"""Data fetcher agents used in the root pipeline."""

from __future__ import annotations

from typing import AsyncGenerator

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions

from ..sub_agents.config_csv_fetcher import ConfigCSVFetcher



class UniversalDataFetcher(BaseAgent):
    """Generic fetcher that dispatches to Hyper or CSV based on contract."""

    def __init__(self):
        super().__init__(name="universal_data_fetcher")

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        if ctx.session.state.get("primary_data_csv") or ctx.session.state.get("validated_pl_data_csv"):
            print("[UniversalDataFetcher] Data already cached; skipping fetch.")
            yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=EventActions())
            return

        contract = ctx.session.state.get("dataset_contract")
        if not contract:
            print("[UniversalDataFetcher] No contract in state.")
            yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=EventActions())
            return

        source_type = getattr(getattr(contract, "data_source", None), "type", "tableau_hyper")
        if source_type == "csv":
            fetcher = ConfigCSVFetcher()
        else:
            from ..sub_agents.tableau_hyper_fetcher.fetcher import TableauHyperFetcher

            fetcher = TableauHyperFetcher()

        async for event in fetcher.run_async(ctx):
            yield event
