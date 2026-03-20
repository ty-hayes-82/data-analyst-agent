"""
TableauHyperFetcher
===================

A ``BaseAgent`` that loads data from a local Tableau TDSX / Hyper file
directly via the Tableau HyperAPI.

This agent is a drop-in replacement for the ``A2A`` fetch path.  It reads
the active dataset's ``loader.yaml`` (which must declare
``source.type: tableau_hyper``) to determine:

  - The TDSX file location
  - Pre-aggregation rules (period bucketing, group-by, SUM columns)
  - Filter column mappings (logical session-state keys -> physical Hyper columns)
  - Column renaming and date reformatting

The agent populates exactly the same session-state keys as
``ValidationCSVFetcher`` and ``ConfigCSVFetcher`` so that all downstream
agents (planner, stats, hierarchy, narrative, synthesis) run unchanged.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import AsyncGenerator, Dict, List, Optional

import pandas as pd
from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.genai.types import Content, Part

from .hyper_connection import HyperConnectionManager, get_or_create_manager
from .loader_config import HyperLoaderConfig
from .query_builder import HyperQueryBuilder

# Project root is four levels up from this file:
# sub_agents/tableau_hyper_fetcher/fetcher.py
# -> sub_agents/
# -> data_analyst_agent/
# -> pl_analyst/  (project root)
_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.resolve()

# Values that mean "no filter — load everything"
_BASE_UNFILTERED = frozenset({"all", "total", "none", "", "entire network", "entire scope"})


class TableauHyperFetcher(BaseAgent):
    """Generic data-source adapter for Tableau TDSX / Hyper datasets.

    Reads ``loader.yaml`` for the active dataset and fetches pre-aggregated
    data directly via the Tableau HyperAPI.  No A2A server required.
    """

    def __init__(self) -> None:
        super().__init__(name="tableau_hyper_fetcher")

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:

        # ------------------------------------------------------------------ #
        # Step 1 — Load the dataset contract and loader config                #
        # ------------------------------------------------------------------ #
        contract = ctx.session.state.get("dataset_contract")
        if not contract:
            yield self._error_event(ctx, "[TableauHyperFetcher] No dataset_contract in session state.")
            return

        active_dataset = ctx.session.state.get("active_dataset") or (
            contract.name.lower().replace(" ", "_")
        )

        loader_config = self._load_loader_config(active_dataset)
        unfiltered_tokens = _build_unfiltered_tokens(contract)
        if loader_config is None:
            yield self._error_event(
                ctx,
                f"[TableauHyperFetcher] loader.yaml for '{active_dataset}' either does not exist "
                "or is not a 'tableau_hyper' source. Check config/datasets/<dataset>/loader.yaml.",
            )
            return

        # ------------------------------------------------------------------ #
        # Step 2 — Initialize the Hyper connection                            #
        # ------------------------------------------------------------------ #
        manager = get_or_create_manager(active_dataset, loader_config)

        try:
            manager.ensure_extracted(_PROJECT_ROOT)
        except FileNotFoundError as exc:
            yield self._error_event(ctx, str(exc))
            return
        except ImportError as exc:
            yield self._error_event(ctx, str(exc))
            return
        except Exception as exc:
            yield self._error_event(
                ctx, f"[TableauHyperFetcher] Failed to extract Hyper file: {exc}"
            )
            return

        # ------------------------------------------------------------------ #
        # Step 3 — Read session-state filters                                 #
        # ------------------------------------------------------------------ #
        req_raw = ctx.session.state.get("request_analysis", {})
        req_analysis: dict = self._safe_parse_json(req_raw)

        date_start: Optional[str] = ctx.session.state.get("primary_query_start_date")
        date_end: Optional[str] = ctx.session.state.get("primary_query_end_date")

        # Map session-state logical filter keys to physical Hyper columns
        physical_filters: Dict[str, List[str]] = {}
        prefetch_all = os.environ.get("DATA_ANALYST_PREFETCH_ALL", "false").lower() == "true"
        
        if prefetch_all:
            print("[TableauHyperFetcher] PREFETCH_ALL=true: Skipping dimension filters to pull all data up front.")
        
        for logical_key, physical_col in (loader_config.filter_columns or {}).items():
            if logical_key == "date":
                # Date handled via date_start / date_end
                continue
            
            if prefetch_all:
                continue
                
            value = req_analysis.get(logical_key) or req_analysis.get("primary_dimension_value")
            if value and str(value).lower() not in unfiltered_tokens:
                primary_dim = req_analysis.get("primary_dimension", "")
                if not primary_dim or primary_dim.lower() == logical_key.lower():
                    physical_filters[physical_col] = [str(value)]

        # ------------------------------------------------------------------ #
        # Step 4 — Build and execute SQL query                                #
        # ------------------------------------------------------------------ #
        # [PROFILING] Query parameters
        print(f"\n[HyperQuery] Building query with parameters:")
        print(f"[HyperQuery]   Date range: {date_start} to {date_end}")
        print(f"[HyperQuery]   Filters: {physical_filters}")
        print(f"[HyperQuery]   Metrics requested: {req_analysis.get('metrics', 'N/A')}")
        
        # Allow CLI override of aggregation period_type via env var
        period_override = os.environ.get("DATA_ANALYST_PERIOD_TYPE", "").strip().lower()
        if period_override and loader_config.aggregation:
            if period_override in ("month_end", "week_end", "day"):
                print(f"[HyperQuery] Overriding period_type: {loader_config.aggregation.period_type} -> {period_override}")
                loader_config.aggregation.period_type = period_override

        builder = HyperQueryBuilder(loader_config)
        sql = builder.build_query(
            date_start=date_start,
            date_end=date_end,
            filters=physical_filters,
        )
        print(f"\n[HyperQuery] Generated SQL:\n{sql}\n")

        start_time = time.perf_counter()
        try:
            df = manager.execute_query(sql)
        except Exception as exc:
            yield self._error_event(
                ctx, f"[TableauHyperFetcher] Query failed: {exc}"
            )
            return
        elapsed = time.perf_counter() - start_time
        print(f"[TIMER] <<< TableauHyperFetcher: {len(df):,} rows in {elapsed:.2f}s")

        # ------------------------------------------------------------------ #
        # Step 5 — Post-process: column renaming, date filtering, formatting #
        # ------------------------------------------------------------------ #
        df = self._apply_column_mapping(df, loader_config)

        # Apply secondary date range filter BEFORE stringifying dates
        # (after column renaming, the date column may now have a different name)
        time_col = (contract.time.column if contract.time else None) or "period"
        df = self._apply_date_filter(df, time_col, date_start, date_end)

        df = self._apply_date_parsing(df, loader_config)

        # Apply explicit output_columns selection/ordering
        if loader_config.output_columns:
            available = [c for c in loader_config.output_columns if c in df.columns]
            df = df[available]

        if df.empty:
            print(
                f"[TableauHyperFetcher] WARNING: No rows returned "
                f"(date_start={date_start}, date_end={date_end}, filters={physical_filters})"
            )

        # ------------------------------------------------------------------ #
        # Step 6 — Populate session state and data cache                      #
        # ------------------------------------------------------------------ #
        csv_data = df.to_csv(index=False)
        session_id = getattr(ctx.session, "id", None)

        try:
            from ..data_cache import set_validated_csv
            set_validated_csv(csv_data, session_id=session_id)
        except Exception as exc:
            print(f"[TableauHyperFetcher] WARNING: Failed to populate data_cache: {exc}")

        # Compute summary stats for the event message
        grain_col = _first_non_time_grain(contract)
        
        # Determine actual columns present in df for summary
        summary_grain_col = grain_col
        if grain_col not in df.columns:
            # Maybe it was remapped? Try to find by name in dimensions
            dim = next((d for d in (contract.dimensions or []) if d.column == grain_col), None)
            if dim and dim.name in df.columns:
                summary_grain_col = dim.name
        
        n_entities = int(df[summary_grain_col].nunique()) if summary_grain_col in df.columns else 0
        n_periods = int(df[time_col].nunique()) if time_col in df.columns else 0
        n_rows = len(df)

        state_delta: dict = {
            "primary_data_csv": csv_data,
            "validated_pl_data_csv": csv_data,
            "data_summary": {
                "total_rows": n_rows,
                "entities": n_entities,
                "periods": n_periods,
                "source": "tableau_hyper",
                "dataset": active_dataset,
                "elapsed_s": round(elapsed, 2),
            },
        }

        message = (
            f"[TableauHyperFetcher] Loaded {n_rows:,} rows "
            f"({n_entities} {summary_grain_col or 'entities'}, {n_periods} {time_col or 'periods'}) "
            f"in {elapsed:.2f}s from '{active_dataset}' Hyper file."
        )
        print(message)

        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            content=Content(role="model", parts=[Part(text=message)]),
            actions=EventActions(state_delta=state_delta),
        )

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _load_loader_config(dataset_name: str) -> Optional[HyperLoaderConfig]:
        """Load and parse loader.yaml for *dataset_name*.  Returns None on failure."""
        import yaml
        from config.dataset_resolver import get_dataset_dir

        dataset_dir = get_dataset_dir(dataset_name)
        loader_path = dataset_dir / "loader.yaml"

        if not loader_path.exists():
            print(f"[TableauHyperFetcher] loader.yaml not found: {loader_path}")
            return None

        with open(loader_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        source_type = (raw.get("source") or {}).get("type", "")
        if source_type != "tableau_hyper":
            print(
                f"[TableauHyperFetcher] loader.yaml source.type is '{source_type}', "
                "expected 'tableau_hyper'. Skipping."
            )
            return None

        try:
            return HyperLoaderConfig(**raw)
        except Exception as exc:
            print(f"[TableauHyperFetcher] Failed to parse loader.yaml: {exc}")
            return None

    @staticmethod
    def _safe_parse_json(raw) -> dict:
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                return {}
        return {}

    @staticmethod
    def _apply_column_mapping(df: pd.DataFrame, config: HyperLoaderConfig) -> pd.DataFrame:
        """Rename physical columns to semantic names per column_mapping."""
        mapping = config.column_mapping
        if not mapping:
            return df
        rename = {src: dst for src, dst in mapping.items() if src in df.columns}
        if rename:
            df = df.rename(columns=rename)
        return df

    @staticmethod
    def _apply_date_parsing(df: pd.DataFrame, config: HyperLoaderConfig) -> pd.DataFrame:
        """Reformat the date column per date_parsing config."""
        dp = config.date_parsing
        if not dp:
            return df
        src_col = dp.source_column
        out_col = dp.output_column
        out_fmt = dp.output_format

        # After column renaming the source_column may already have its new name
        actual_col = src_col if src_col in df.columns else None
        if not actual_col:
            return df

        try:
            series = df[actual_col]
            if series.dtype == object:
                series = series.astype(str)
            parsed = pd.to_datetime(series, errors="coerce")
            df = df.copy()
            df[actual_col] = parsed.dt.strftime(out_fmt)
            if actual_col != out_col:
                df = df.rename(columns={actual_col: out_col})
        except Exception as exc:
            print(f"[TableauHyperFetcher] WARNING: date_parsing failed: {exc}")
        return df

    @staticmethod
    def _apply_date_filter(
        df: pd.DataFrame,
        time_col: Optional[str],
        date_start: Optional[str],
        date_end: Optional[str],
    ) -> pd.DataFrame:
        """Apply secondary date range filter after column mapping."""
        if df.empty or not time_col or time_col not in df.columns:
            return df
        if not date_start and not date_end:
            return df

        original_count = len(df)
        try:
            # Ensure we are dealing with strings or standard datetimes before conversion
            series = df[time_col]
            if series.dtype == object:
                series = series.astype(str)
            col = pd.to_datetime(series, errors="coerce")
            if date_start:
                start_ts = pd.Timestamp(date_start)
                df = df[col >= start_ts]
                col = col[col >= start_ts]
            if date_end:
                end_ts = pd.Timestamp(date_end)
                df = df[col <= end_ts]
        except Exception as exc:
            print(f"[TableauHyperFetcher] WARNING: secondary date filter failed: {exc}")
            return df

        print(
            f"[TableauHyperFetcher] Date filter: {date_start or 'min'} to {date_end or 'max'}. "
            f"Rows: {original_count} -> {len(df)}"
        )
        return df

    @staticmethod
    def _error_event(ctx: InvocationContext, message: str) -> Event:
        print(message)
        return Event(
            invocation_id=ctx.invocation_id,
            author="tableau_hyper_fetcher",
            content=Content(role="model", parts=[Part(text=message)]),
            actions=EventActions(state_delta={"primary_data_csv": "", "validated_pl_data_csv": ""}),
        )


def _first_non_time_grain(contract) -> Optional[str]:
    """Return the first non-time grain column name, if any."""
    if contract is None or not contract.grain:
        return None
    time_col = contract.time.column if contract.time else None
    for col in contract.grain.columns:
        if col != time_col:
            return col
    return contract.grain.columns[0] if contract.grain.columns else None



def _build_unfiltered_tokens(contract) -> set[str]:
    tokens = set(_BASE_UNFILTERED)
    dimensions = getattr(contract, "dimensions", []) or []
    for dim in dimensions:
        label_candidates = {
            str(getattr(dim, "name", "")).replace("_", " "),
            str(getattr(dim, "column", "")).replace("_", " "),
            str(getattr(dim, "description", "")).split("(")[0].strip(),
        }
        tags = getattr(dim, "tags", []) or []
        label_candidates.update(tag.replace("_", " ") for tag in tags)
        for label in label_candidates:
            clean = label.strip().lower()
            if not clean:
                continue
            tokens.add(f"all {clean}")
            tokens.add(f"entire {clean}")
            tokens.add(f"{clean} (all)")
    return tokens

