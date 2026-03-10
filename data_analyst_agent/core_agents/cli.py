"""CLI/test harness helpers."""

from __future__ import annotations

import os
from typing import AsyncGenerator

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions



class CLIParameterInjector(BaseAgent):
    """Injects CLI-provided parameters into session state."""

    def __init__(self):
        super().__init__(name="cli_parameter_injector")

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        import json as _json

        metrics_raw = os.environ.get("DATA_ANALYST_METRICS", "")
        metrics = [m.strip() for m in metrics_raw.split(",") if m.strip()]
        dim = os.environ.get("DATA_ANALYST_DIMENSION")
        dim_val = os.environ.get("DATA_ANALYST_DIMENSION_VALUE")
        start = os.environ.get("DATA_ANALYST_START_DATE")
        end = os.environ.get("DATA_ANALYST_END_DATE")

        contract = ctx.session.state.get("dataset_contract")
        display_name = getattr(contract, "display_name", getattr(contract, "name", "dataset")) if contract else "dataset"
        frequency = getattr(getattr(contract, "time", None), "frequency", "weekly")
        target_label = getattr(contract, "target_label", "Metric") if contract else "Metric"

        # Fall back to all metrics from contract when CLI does not specify any
        if not metrics and contract:
            contract_metrics = getattr(contract, "metrics", None) or []
            if contract_metrics:
                metrics = [
                    m.get("name") if isinstance(m, dict) else getattr(m, "name", str(m))
                    for m in contract_metrics
                ]
                print(f"[CLIParameterInjector] No DATA_ANALYST_METRICS -- defaulting to contract metrics: {metrics}")

        state_delta: dict = {}
        if metrics:
            state_delta["extracted_targets_raw"] = _json.dumps(metrics)
            state_delta["extracted_targets"] = metrics
            state_delta["target_label"] = target_label
            state_delta["target_loop_state"] = {"target_index": -1}
            state_delta["target_loop_complete"] = False

        primary_dim = dim or "terminal"
        primary_val = dim_val or "Total"
        focus = f"CLI analysis of {', '.join(metrics)}" if metrics else "CLI analysis"
        data_query = f"Retrieve {frequency} {display_name} for {primary_dim} {primary_val}."
        state_delta["request_analysis"] = {
            "analysis_type": "operational_trend",
            "primary_dimension": primary_dim,
            "primary_dimension_value": primary_val,
            "metrics": metrics,
            "focus": focus,
            "needs_supplementary_data": False,
            "description": focus,
            "data_fetch_query_primary": data_query,
            "data_fetch_query_supplementary": None,
        }

        if start or end:
            overrides = {
                "primary_query_start_date": start,
                "primary_query_end_date": end,
                "supplementary_query_start_date": start,
                "supplementary_query_end_date": end,
                "detail_query_start_date": start,
                "detail_query_end_date": end,
            }
            overrides = {k: v for k, v in overrides.items() if v}
            state_delta.update(overrides)
            if start and end:
                state_delta["timeframe"] = {"start": start, "end": end}

        yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=EventActions(state_delta=state_delta))
