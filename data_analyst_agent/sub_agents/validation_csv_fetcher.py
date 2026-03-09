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
ValidationCSVFetcher — data-source adapter for validation_data.csv.

Replaces the A2A ContractDrivenDataFetcher when DATA_ANALYST_VALIDATION_CSV_MODE
is enabled.  All downstream agents (planner, statistical analysis, hierarchy
variance, narrative, synthesis) run without modification — this agent is purely
a data-source swap, not a test shortcut.

Data loading logic
------------------
The analysis pipeline calls this once per dimension target (metric name). The
current target is stored in session state as ``current_analysis_target``.
validation_ops dataset those targets are metric names (e.g. "Truck Count",
"Revenue xFuel"), so we use the target directly as the ``metric_filter`` for
``load_validation_data``.

Optional narrowing filters (region or terminal) are read from the
``request_analysis`` session key if the user asked for a specific geography.

Environment variables
---------------------
DATA_ANALYST_EXCLUDE_PARTIAL_WEEK
    Set to "true" to drop the most recent partial week (2/21/2026) from the
    loaded data.  Defaults to false.
"""

import json
import os
import time
from typing import AsyncGenerator

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.genai.types import Content, Part

from .data_cache import set_validated_csv
from ..tools.validation_data_loader import load_validation_data


# Values that mean "no specific dimension filter — load all"
_UNFILTERED = {"all", "total", "none", "067", "unknown", "", "all regions", "all terminals"}

class ValidationCSVFetcher(BaseAgent):
    """
    Data-source adapter: loads validation_data.csv for the current analysis
    target and populates the shared data cache.

    This is NOT a test agent.  It is a CSV-backed data source that replaces
    the Tableau A2A server call.  All downstream agents run identically
    whether data arrived from A2A or from this fetcher.
    """

    def __init__(self) -> None:
        super().__init__(name="validation_csv_fetcher")

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        # ------------------------------------------------------------------
        # 1. Determine the current analysis target (metric name)
        # ------------------------------------------------------------------
        current_target: str = (
            ctx.session.state.get("current_analysis_target", "")
        )

        # ------------------------------------------------------------------
        # 2. Read optional region / terminal filter from request analysis
        # ------------------------------------------------------------------
        req_raw = ctx.session.state.get("request_analysis", {})
        if isinstance(req_raw, str):
            try:
                req_analysis: dict = json.loads(req_raw)
            except Exception:
                req_analysis = {}
        else:
            req_analysis = req_raw if isinstance(req_raw, dict) else {}

        primary_dim: str = req_analysis.get("primary_dimension", "terminal")
        primary_val: str = str(req_analysis.get("primary_dimension_value") or "")

        region_filter = None
        terminal_filter = None

        if primary_dim == "region" and primary_val.lower() not in _UNFILTERED:
            region_filter = primary_val
        elif primary_dim == "terminal" and primary_val.lower() not in _UNFILTERED:
            terminal_filter = primary_val

        # ------------------------------------------------------------------
        # 3. The current target IS the metric name for validation_ops data.
        #    Target names have already been resolved to actual CSV column
        #    names by the DimensionTargetInitializer (LLM-based resolution).
        #
        #    Pass as a single-item list to force exact matching in
        #    load_validation_data — a bare string uses substring matching
        #    which pulls in related sub-metrics (e.g. "Seated Truck Count",
        #    "Solo Truck Count" when the target is "Truck Count") and causes
        #    the statistical analysis to aggregate unrelated rows together.
        # ------------------------------------------------------------------
        metric_filter = [current_target] if current_target else None

        # ------------------------------------------------------------------
        # 4. Read env-var overrides
        # ------------------------------------------------------------------
        exclude_partial: bool = (
            os.environ.get("DATA_ANALYST_EXCLUDE_PARTIAL_WEEK", "false").lower()
            == "true"
        )

        print(f"\n{'='*80}")
        print(f"[ValidationCSVFetcher] Loading validation_data.csv")
        print(f"  metric   : {metric_filter or '(all)'}")
        print(f"  region   : {region_filter or '(all)'}")
        print(f"  terminal : {terminal_filter or '(all)'}")
        print(f"  excl_partial : {exclude_partial}")
        print(f"{'='*80}\n")

        # ------------------------------------------------------------------
        # 5. Load data
        # ------------------------------------------------------------------
        start_time = time.perf_counter()
        print(f"[TIMER] >>> ValidationCSVFetcher: Loading data for metric='{metric_filter or '(all)'}'...")
        try:
            df = load_validation_data(
                metric_filter=metric_filter,
                region_filter=region_filter,
                terminal_filter=terminal_filter,
                exclude_partial_week=exclude_partial,
            )
            
            # --- NEW: Apply Date Range Filters from Session State ---
            start_date = ctx.session.state.get("primary_query_start_date")
            end_date = ctx.session.state.get("primary_query_end_date")
            
            if not df.empty and (start_date or end_date):
                original_count = len(df)
                if start_date:
                    df = df[df["week_ending"] >= start_date]
                if end_date:
                    df = df[df["week_ending"] <= end_date]
                print(f"[ValidationCSVFetcher] Date filter applied: {start_date or 'min'} to {end_date or 'max'}. "
                      f"Rows: {original_count} -> {len(df)}")

            duration = time.perf_counter() - start_time
            print(f"[TIMER] <<< ValidationCSVFetcher: Loaded {len(df)} rows in {duration:.2f}s")
        except Exception as exc:
            error_msg = f"[ValidationCSVFetcher] ERROR: {exc}"
            print(error_msg)
            import traceback
            traceback.print_exc()
            yield Event(
                invocation_id=ctx.invocation_id,
                author=self.name,
                content=Content(role="model", parts=[Part(text=error_msg)]),
                actions=EventActions(
                    state_delta={"primary_data_csv": "", "validated_pl_data_csv": ""}
                ),
            )
            return

        if df.empty:
            warning = (
                f"[ValidationCSVFetcher] WARNING: No rows returned for "
                f"metric={metric_filter!r}, region={region_filter!r}, "
                f"terminal={terminal_filter!r}."
            )
            print(warning)

        # ------------------------------------------------------------------
        # 6. Populate the shared data cache
        # ------------------------------------------------------------------
        csv_data = df.to_csv(index=False)
        # Use session ID for cache isolation in parallel runs
        session_id = getattr(ctx.session, "id", None)
        set_validated_csv(csv_data, session_id=session_id)

        n_terminals = int(df["terminal"].nunique()) if not df.empty else 0
        n_weeks = int(df["week_ending"].nunique()) if not df.empty else 0
        n_rows = len(df)

        state_delta = {
            "primary_data_csv": csv_data,
            "validated_pl_data_csv": csv_data,
            "data_summary": {
                "total_rows": n_rows,
                "terminals": n_terminals,
                "metric": metric_filter or "(all)",
                "weeks": n_weeks,
                "exclude_partial_week": exclude_partial,
            },
        }

        message = (
            f"[ValidationCSVFetcher] Loaded {n_rows:,} rows for "
            f"'{metric_filter or 'all metrics'}' "
            f"({n_terminals} terminals, {n_weeks} weeks)."
        )
        print(message)

        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            content=Content(role="model", parts=[Part(text=message)]),
            actions=EventActions(state_delta=state_delta),
        )
