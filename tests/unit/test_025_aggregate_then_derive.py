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

"""Unit tests for Spec 025: aggregate-then-derive for ratio metrics."""

import json
import pytest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATASETS_DIR = PROJECT_ROOT / "config" / "datasets"


def test_ratio_config_resolution_rev_trk_wk():
    """get_ratio_config_for_metric returns numerator/denominator for Rev/Trk/Wk."""
    from data_analyst_agent.semantic.models import DatasetContract
    from data_analyst_agent.sub_agents.statistical_insights_agent.tools.ratio_metrics_config import (
        get_ratio_config_for_metric,
    )

    contract_path = DATASETS_DIR / "validation_ops" / "contract.yaml"
    if not contract_path.exists():
        pytest.skip("validation_ops contract not found")
    contract = DatasetContract.from_yaml(str(contract_path))
    contract._source_path = str(contract_path)

    cfg = get_ratio_config_for_metric(contract, "Rev/Trk/Wk")
    assert cfg is not None
    assert cfg.get("numerator_metric") == "Revenue xFuel"
    assert cfg.get("denominator_metric") == "Truck Count"


def test_ratio_config_returns_none_for_additive_metric():
    """get_ratio_config_for_metric returns None for non-ratio metric."""
    from data_analyst_agent.semantic.models import DatasetContract
    from data_analyst_agent.sub_agents.statistical_insights_agent.tools.ratio_metrics_config import (
        get_ratio_config_for_metric,
    )

    contract_path = DATASETS_DIR / "validation_ops" / "contract.yaml"
    if not contract_path.exists():
        pytest.skip("validation_ops contract not found")
    contract = DatasetContract.from_yaml(str(contract_path))
    contract._source_path = str(contract_path)

    cfg = get_ratio_config_for_metric(contract, "Truck Count")
    assert cfg is None


def test_ratio_config_lrpm():
    """LRPM is in ratio_metrics with Revenue xFuel / Loaded Miles."""
    from data_analyst_agent.semantic.models import DatasetContract
    from data_analyst_agent.sub_agents.statistical_insights_agent.tools.ratio_metrics_config import (
        get_ratio_config_for_metric,
    )

    contract_path = DATASETS_DIR / "validation_ops" / "contract.yaml"
    if not contract_path.exists():
        pytest.skip("validation_ops contract not found")
    contract = DatasetContract.from_yaml(str(contract_path))
    contract._source_path = str(contract_path)

    cfg = get_ratio_config_for_metric(contract, "LRPM")
    assert cfg is not None
    assert cfg.get("numerator_metric") == "Revenue xFuel"
    assert cfg.get("denominator_metric") == "Loaded Miles"


@pytest.mark.asyncio
async def test_statistical_summary_additive_metric_unchanged():
    """For additive metric (Truck Count), monthly_totals remain sum of values."""
    from data_analyst_agent.tools.validation_data_loader import load_validation_data
    from data_analyst_agent.sub_agents.data_cache import (
        set_validated_csv,
        set_analysis_context,
        clear_all_caches,
    )
    from data_analyst_agent.semantic.models import DatasetContract, AnalysisContext
    from data_analyst_agent.sub_agents.statistical_insights_agent.tools.compute_statistical_summary import (
        compute_statistical_summary,
    )

    try:
        clear_all_caches()
        df = load_validation_data(metric_filter="Truck Count", exclude_partial_week=True)
        if df.empty:
            pytest.skip("No validation data")
        set_validated_csv(df.to_csv(index=False))
        contract_path = DATASETS_DIR / "validation_ops" / "contract.yaml"
        contract = DatasetContract.from_yaml(str(contract_path))
        contract._source_path = str(contract_path)
        ctx = AnalysisContext(
            contract=contract,
            df=df,
            target_metric=contract.get_metric("value"),
            primary_dimension=contract.get_dimension("terminal"),
            run_id="test-025-additive",
            max_drill_depth=2,
        )
        set_analysis_context(ctx)

        result_str = await compute_statistical_summary()
        result = json.loads(result_str)
        assert "error" not in result
        monthly_totals = result.get("monthly_totals") or {}
        # Truck Count totals should be sum across terminals (large numbers)
        if monthly_totals:
            one_total = next(iter(monthly_totals.values()))
            assert one_total >= 100, f"Truck Count total should be sum (large), got {one_total}"
    finally:
        clear_all_caches()
