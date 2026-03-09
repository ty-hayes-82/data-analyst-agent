import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import pytest
import json
import pandas as pd
import numpy as np
from unittest.mock import patch, MagicMock
from tests.utils.import_helpers import import_hierarchy_ranker_tool

@pytest.mark.asyncio
async def test_pvm_math_logic():
    """Test the core math of PVM decomposition."""
    mod = import_hierarchy_ranker_tool("compute_pvm_decomposition")
    compute_pvm_decomposition = mod.compute_pvm_decomposition
    
    # Mock data
    data = [
        {"period": "2024-01", "item": "A", "revenue": 200, "miles": 100},
        {"period": "2025-01", "item": "A", "revenue": 300, "miles": 120},
    ]
    df = pd.DataFrame(data)
    
    mock_ctx = MagicMock()
    mock_ctx.contract.time.format = "%Y-%m"
    
    with patch.object(mod, "resolve_data_and_columns") as mock_resolve:
        mock_resolve.return_value = (df, "period", "revenue", "item", "item", mock_ctx)
        
        result_str = await compute_pvm_decomposition(
            target_metric="revenue",
            price_metric="price",
            volume_metric="miles",
            dimension="item",
            analysis_period="2025-01",
            prior_period="2024-01"
        )
        
        result = json.loads(result_str)
        
        assert "error" not in result
        assert result["total_variance"] == 100.0
        assert result["total_volume_impact"] == 40.0
        assert result["total_price_impact"] == 60.0

@pytest.mark.asyncio
async def test_pvm_with_multiple_items():
    """Test PVM with multiple items to ensure aggregation works."""
    mod = import_hierarchy_ranker_tool("compute_pvm_decomposition")
    compute_pvm_decomposition = mod.compute_pvm_decomposition
    
    data = [
        {"period": "2024-01", "item": "A", "revenue": 100, "miles": 50},
        {"period": "2024-01", "item": "B", "revenue": 200, "miles": 40},
        {"period": "2025-01", "item": "A", "revenue": 150, "miles": 60},
        {"period": "2025-01", "item": "B", "revenue": 180, "miles": 45},
    ]
    df = pd.DataFrame(data)
    mock_ctx = MagicMock()
    
    with patch.object(mod, "resolve_data_and_columns") as mock_resolve:
        mock_resolve.return_value = (df, "period", "revenue", "item", "item", mock_ctx)
        
        result_str = await compute_pvm_decomposition(
            target_metric="revenue",
            price_metric="price",
            volume_metric="miles",
            dimension="item",
            analysis_period="2025-01",
            prior_period="2024-01"
        )
        
        result = json.loads(result_str)
        assert result["total_variance"] == 30.0
        assert result["total_volume_impact"] == 45.0
        assert result["total_price_impact"] == -15.0

# ============================================================================
# Ops Metrics PVM tests (total_revenue = total, linehaul_revenue = price,
#                         loaded_miles = volume)
# ============================================================================

@pytest.mark.asyncio
async def test_pvm_ops_metrics_roles():
    """Test PVM with ops metrics contract roles (revenue/miles decomposition)."""
    mod = import_hierarchy_ranker_tool("compute_pvm_decomposition")
    compute_pvm_decomposition = mod.compute_pvm_decomposition

    data = [
        {"period": "2024-01", "lob": "Line Haul", "ttl_rev_amt": 500000, "ld_trf_mi": 120000},
        {"period": "2025-01", "lob": "Line Haul", "ttl_rev_amt": 600000, "ld_trf_mi": 140000},
    ]
    df = pd.DataFrame(data)
    mock_ctx = MagicMock()
    mock_ctx.contract.time.format = "%Y-%m"

    with patch.object(mod, "resolve_data_and_columns") as mock_resolve:
        mock_resolve.return_value = (df, "period", "ttl_rev_amt", "lob", "lob", mock_ctx)

        result_str = await compute_pvm_decomposition(
            target_metric="ttl_rev_amt",
            price_metric="lh_rev_amt",
            volume_metric="ld_trf_mi",
            dimension="lob",
            analysis_period="2025-01",
            prior_period="2024-01",
        )

        result = json.loads(result_str)
        assert "error" not in result
        assert result["total_variance"] == 100000.0
        # Volume should be positive (miles increased)
        assert result["total_volume_impact"] > 0


@pytest.mark.asyncio
async def test_pvm_zero_prior_period():
    """PVM should handle zero values in prior period gracefully."""
    mod = import_hierarchy_ranker_tool("compute_pvm_decomposition")
    compute_pvm_decomposition = mod.compute_pvm_decomposition

    data = [
        {"period": "2024-01", "item": "A", "revenue": 0, "miles": 0},
        {"period": "2025-01", "item": "A", "revenue": 100, "miles": 50},
    ]
    df = pd.DataFrame(data)
    mock_ctx = MagicMock()
    mock_ctx.contract.time.format = "%Y-%m"

    with patch.object(mod, "resolve_data_and_columns") as mock_resolve:
        mock_resolve.return_value = (df, "period", "revenue", "item", "item", mock_ctx)

        result_str = await compute_pvm_decomposition(
            target_metric="revenue",
            price_metric="price",
            volume_metric="miles",
            dimension="item",
            analysis_period="2025-01",
            prior_period="2024-01",
        )

        result = json.loads(result_str)
        # Should not crash; total_variance = 100
        assert result["total_variance"] == 100.0


if __name__ == "__main__":
    import pytest
    pytest.main([__file__])
