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

"""Unit tests for compute_derived_metrics -- Phase 3 verification (T035)."""

import json
import pandas as pd
import pytest
from unittest.mock import MagicMock


def _make_contract(metrics):
    """Build a minimal mock DatasetContract."""
    contract = MagicMock()
    contract.metrics = metrics
    contract.time = MagicMock()
    contract.time.column = "cal_dt"
    contract.policies = {"degradation_threshold": 0.10}
    return contract


def _make_metric(name, formula=None, computed_by=None, col=None, opt="maximize"):
    m = MagicMock()
    m.name = name
    m.type = "derived"
    m.formula = formula
    m.computed_by = computed_by
    m.column = col
    m.optimization = opt
    m.format = "float"
    return m


def _make_df():
    """Minimal 3-period DataFrame with pre-computed miles_per_truck."""
    return pd.DataFrame({
        "cal_dt": ["2025-01-31", "2025-02-28", "2025-03-31"],
        "ld_trf_mi": [100_000.0, 110_000.0, 105_000.0],
        "truck_count": [50.0, 55.0, 52.0],
        "miles_per_truck": [2000.0, 2000.0, 2019.23],  # pre-computed column
    })


def _import_compute_derived_series():
    """Import _compute_derived_series using importlib (handles numeric-prefix path)."""
    import importlib
    mod = importlib.import_module(
        "data_analyst_agent.sub_agents.statistical_insights_agent.tools.compute_derived_metrics"
    )
    return mod._compute_derived_series


def test_skip_precomputed_column_not_overwritten():
    """If miles_per_truck is already in the DataFrame, _compute_derived_series
    should use the pre-computed column directly, NOT try to recompute from formula."""
    _compute_derived_series = _import_compute_derived_series()
    df = _make_df()
    original_values = df["miles_per_truck"].tolist()

    metric = _make_metric(
        name="miles_per_truck",
        formula="wrong_col_a / wrong_col_b",  # wrong tokens -- would produce nothing if evaluated
        computed_by="a2a_agent",
        col=None,
    )
    contract = _make_contract([metric])

    ratios, alerts = _compute_derived_series(df, contract, "cal_dt")

    assert any(r["metric"] == "miles_per_truck" for r in ratios), \
        "miles_per_truck should appear in derived series output"

    mpt = next(r for r in ratios if r["metric"] == "miles_per_truck")
    assert mpt["values"] == [round(v, 4) for v in original_values], \
        "Pre-computed column values should be used verbatim, not recalculated"


def test_formula_used_when_column_missing():
    """When the column is NOT in the DataFrame, the formula should be evaluated."""
    _compute_derived_series = _import_compute_derived_series()
    df = pd.DataFrame({
        "cal_dt": ["2025-01-31", "2025-02-28"],
        "ld_trf_mi": [100_000.0, 110_000.0],
        "truck_count": [50.0, 55.0],
        # no miles_per_truck column
    })
    metric = _make_metric(
        name="miles_per_truck",
        formula="ld_trf_mi / truck_count",
        computed_by=None,
        col=None,
    )
    contract = _make_contract([metric])

    ratios, alerts = _compute_derived_series(df, contract, "cal_dt")

    mpt = next((r for r in ratios if r["metric"] == "miles_per_truck"), None)
    assert mpt is not None, "miles_per_truck should be computed from formula"
    assert mpt["values"][0] == pytest.approx(2000.0, rel=1e-3)
    assert mpt["values"][1] == pytest.approx(2000.0, rel=1e-3)


def test_computed_by_a2a_agent_missing_column_skipped(capsys):
    """If computed_by=a2a_agent but the column is absent, the metric should be
    silently skipped (no crash) and a warning printed."""
    _compute_derived_series = _import_compute_derived_series()
    df = pd.DataFrame({
        "cal_dt": ["2025-01-31"],
        "ld_trf_mi": [100_000.0],
        "truck_count": [50.0],
        # miles_per_truck absent
    })
    metric = _make_metric(
        name="miles_per_truck",
        formula=None,
        computed_by="a2a_agent",
    )
    contract = _make_contract([metric])

    ratios, alerts = _compute_derived_series(df, contract, "cal_dt")

    assert not any(r["metric"] == "miles_per_truck" for r in ratios), \
        "Metric with computed_by=a2a_agent and missing column should be skipped"

    captured = capsys.readouterr()
    assert "miles_per_truck" in captured.out
    assert "skipping" in captured.out.lower() or "not present" in captured.out.lower()
