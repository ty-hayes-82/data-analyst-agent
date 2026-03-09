"""Data fetcher agents used in the root pipeline."""

from __future__ import annotations

from typing import AsyncGenerator

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions

from ..sub_agents.config_csv_fetcher import ConfigCSVFetcher
from ..utils.json_utils import safe_parse_json
from .proxy import DataSourceProxyAgent


class ContractDrivenDataFetcher(BaseAgent):
    """Fetches primary data using the agent specified in the dataset contract."""

    def __init__(self):
        super().__init__(name="contract_driven_data_fetcher")

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        from ..sub_agents.a2a_response_normalizer import tableau_account_research_ds_agent
        from ..sub_agents.a2a_response_normalizer import tableau_ops_metrics_ds_agent
        from ..sub_agents.a2a_response_normalizer import tableau_order_dispatch_revenue_ds_agent

        contract = ctx.session.state.get("dataset_contract")
        if not contract or not getattr(contract, "data_source", None):
            print("[ContractDrivenDataFetcher] Missing data_source config; skipping.")
            yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=EventActions())
            return

        agent_name = contract.data_source.agent
        registry = {
            "tableau_account_research_ds_agent": tableau_account_research_ds_agent,
            "tableau_ops_metrics_ds_agent": tableau_ops_metrics_ds_agent,
            "tableau_order_dispatch_revenue_ds_agent": tableau_order_dispatch_revenue_ds_agent,
        }
        target_agent = registry.get(agent_name)
        if not target_agent:
            print(f"[ContractDrivenDataFetcher] Unknown agent '{agent_name}'.")
            yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=EventActions())
            return

        proxy = DataSourceProxyAgent(target_agent, "data_fetch_query_primary")
        async for event in proxy.run_async(ctx):
            yield event
        result_key = f"{agent_name}_result"
        if result_key in ctx.session.state:
            ctx.session.state["primary_data_raw"] = ctx.session.state[result_key]


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
