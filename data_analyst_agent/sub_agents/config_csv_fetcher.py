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
ConfigCSVFetcher — data-source adapter for local CSV datasets using loader.yaml.

This fetcher uses the generic config_data_loader.py to perform ETL based on 
the rules defined in the dataset's loader.yaml.
"""

import json
import os
import time
from typing import AsyncGenerator

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
# from google.adk.events.event_actions import EventActions
from google.genai.types import Content, Part

from ..tools.config_data_loader import load_from_config
from ..utils.dimension_filters import describe_dimension_filters, extract_dimension_filters


class ConfigCSVFetcher(BaseAgent):
    """Fetches data from local CSV files using dataset-specific loader.yaml rules."""

    def __init__(self):
        super().__init__(name="config_csv_fetcher")

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        # Resolve target and filters from session state
        metric_filter = ctx.session.state.get("current_analysis_target")
        req_analysis_raw = ctx.session.state.get("request_analysis", {})
        if isinstance(req_analysis_raw, str):
            try:
                req_analysis = json.loads(req_analysis_raw)
            except json.JSONDecodeError:
                req_analysis = {}
        elif isinstance(req_analysis_raw, dict):
            req_analysis = req_analysis_raw
        else:
            req_analysis = {}

        contract = ctx.session.state.get("dataset_contract")
        if not contract:
            print("[ConfigCSVFetcher] ERROR: No dataset contract found in state.")
            yield Event(invocation_id=ctx.invocation_id, author=self.name)
            return

        dimension_filters = extract_dimension_filters(
            contract,
            request_analysis=req_analysis,
            candidates=[
                (req_analysis.get("primary_dimension"), ctx.session.state.get("dimension_value")),
                (ctx.session.state.get("dimension"), ctx.session.state.get("dimension_value")),
            ],
        )

        dataset_name = contract.name.lower().replace(" ", "_")
        # Ensure we use the folder name, not display name
        # The contract object should ideally store the dataset name (folder name)
        # For now, we'll try to infer it or look for it in state
        dataset_name = ctx.session.state.get("active_dataset") or dataset_name

        exclude_partial = (
            os.environ.get("DATA_ANALYST_EXCLUDE_PARTIAL_WEEK", "false").lower() == "true"
        )

        print("\n" + "=" * 80)
        print(f"[ConfigCSVFetcher] Loading {dataset_name} data via loader.yaml")
        print(f"  metric   : {metric_filter or '(all)'}")
        print(
            f"  dimension filters : {describe_dimension_filters(contract, dimension_filters)}"
        )
        print(f"  excl_partial : {exclude_partial}")
        print("=" * 80 + "\n")

        start_time = time.perf_counter()
        try:
            # We use the generic loader which handles wide-to-long, cleaning, and filtering
            df = load_from_config(
                dataset_name=dataset_name,
                dimension_filters=dimension_filters,
                metric_filter=metric_filter,
                exclude_partial_week=exclude_partial,
            )
            duration = time.perf_counter() - start_time
            print(f"[TIMER] <<< ConfigCSVFetcher: Loaded {len(df)} rows in {duration:.2f}s")

            # --- Pre-flight validation logging ---
            if not df.empty:
                time_col = contract.time.column if contract.time else None
                print("\n" + "="*80)
                print("[ConfigCSVFetcher] PRE-FLIGHT VALIDATION")
                print(f"  Rows: {len(df)}")
                print(f"  Columns: {len(df.columns)}")
                if time_col and time_col in df.columns:
                    print(f"  Date range: {df[time_col].min()} to {df[time_col].max()}")
                print(f"\nFirst 5 rows:")
                print(df.head().to_string())
                print("="*80 + "\n")
            else:
                print(
                    f"[ConfigCSVFetcher] WARNING: No rows returned for metric={metric_filter}, filters={describe_dimension_filters(contract, dimension_filters)}."
                )
            
            # Populate cache and state
            csv_content = df.to_csv(index=False)
            ctx.session.state["primary_data_csv"] = csv_content
            
            try:
                from .data_cache import set_validated_csv
                set_validated_csv(csv_content)
            except Exception as e:
                print(f"[ConfigCSVFetcher] WARNING: Failed to populate data_cache: {e}")

            # Get actual grain column names for the message
            grain_cols = contract.grain.columns if contract.grain else []
            primary_grain = grain_cols[1] if len(grain_cols) > 1 else (grain_cols[0] if grain_cols else "entities")
            time_col = contract.time.column if contract.time else "week_ending"
            
            n_entities = df[primary_grain].nunique() if primary_grain in df.columns else 0
            n_weeks = df[time_col].nunique() if time_col in df.columns else 0

            message = f"Loaded {len(df):,} rows for {metric_filter} ({n_entities} {primary_grain}, {n_weeks} {time_col})."
            
        except Exception as exc:
            import traceback
            error_msg = f"[ConfigCSVFetcher] ERROR: {exc}\n{traceback.format_exc()}"
            print(error_msg)
            message = f"Error loading data: {exc}"

        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            content=Content(role="model", parts=[Part(text=message)]),
        )
