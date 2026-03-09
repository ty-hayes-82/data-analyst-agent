"""Incremental E2E pipeline tests (trade_data only).

Strategy: validate the pipeline one agent at a time, building state incrementally.

Per Ty's instruction, we implement Level 0 first and only proceed once it passes.
"""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pandas as pd
import pytest

from data_analyst_agent.sub_agents.data_cache import clear_all_caches, get_validated_csv, set_validated_csv


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_C_PATH = REPO_ROOT / "data" / "validation" / "fixture_c_minimal_lax_8542.csv"


@pytest.mark.e2e
@pytest.mark.trade_data
@pytest.mark.csv_mode
class TestLevel0_DataLoading:
    def test_load_fixture_c_into_data_cache(self) -> None:
        """Load fixture_c via data_cache.set_validated_csv() and assert integrity."""
        clear_all_caches()
        try:
            df = pd.read_csv(FIXTURE_C_PATH)
            assert len(df) > 0

            set_validated_csv(df.to_csv(index=False))

            cached = get_validated_csv()
            assert cached, "Expected validated CSV to be present in cache"

            cached_df = pd.read_csv(StringIO(cached))
            assert len(cached_df) == len(df)

            required_cols = {
                # time + value
                "period_end",
                "trade_value_usd",
                # minimal identity/hierarchy
                "flow",
                "region",
                "state",
                "port_code",
                "hs2",
                "hs4",
                "hierarchy_path",
                "hierarchy_depth",
                # temporal helpers
                "grain",
                "year",
                "month",
                "iso_week",
                # anomaly labels (used by later assertions)
                "anomaly_flag",
            }
            missing = required_cols - set(cached_df.columns)
            assert not missing, f"Missing required columns: {sorted(missing)}"
        finally:
            clear_all_caches()
