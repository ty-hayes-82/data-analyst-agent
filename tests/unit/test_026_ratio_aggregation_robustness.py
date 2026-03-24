import json
import pandas as pd
import numpy as np
import asyncio
import pytest
from unittest.mock import MagicMock, patch
from data_analyst_agent.sub_agents.hierarchy_variance_agent.tools.compute_level_statistics import compute_level_statistics
from data_analyst_agent.sub_agents.statistical_insights_agent.tools.compute_statistical_summary import compute_statistical_summary

@pytest.mark.asyncio
async def test_statistical_summary_robust_ratio_detection():
    """
    Test that compute_statistical_summary correctly detects a ratio metric
    even if the input dataframe contains multiple metrics and the target_metric
    name is generic ("value").
    """
    # 1. Create a mock AnalysisContext with a GENERIC metric name
    mock_contract = MagicMock()
    mock_contract.name = "validation_ops"
    mock_contract.time.column = "week_ending"
    mock_contract.time.format = "%Y-%m-%d"
    mock_contract.grain.columns = ["terminal"]
    
    # Generic target metric name (common in long-format datasets like validation_ops)
    mock_target_metric = MagicMock()
    mock_target_metric.name = "value" 
    mock_target_metric.column = "value"
    
    mock_ctx = MagicMock()
    mock_ctx.contract = mock_contract
    mock_ctx.target_metric = mock_target_metric
    
    # 2. Create a dataframe with TWO metrics (Rev/Trk/Wk and some other)
    df = pd.DataFrame([
        {"terminal": "T1", "week_ending": "2025-01-04", "metric": "Rev/Trk/Wk", "value": 3000.0},
        {"terminal": "T1", "week_ending": "2025-01-04", "metric": "Other Metric", "value": 5000.0},
    ])
    
    # 3. Mock resolve_data_and_columns (where it's defined in data_cache)
    with patch("data_analyst_agent.sub_agents.data_cache.resolve_data_and_columns") as mock_resolve:
        mock_resolve.return_value = (df, "week_ending", "value", "terminal", "terminal", mock_ctx)
        
        # Patch the ratio config to return config for Rev/Trk/Wk
        with patch("data_analyst_agent.semantic.ratio_metrics_config.get_ratio_config_for_metric") as mock_get_rc:
            def side_effect(contract, name):
                if name == "Rev/Trk/Wk":
                    return {
                        "numerator_metric": "Revenue xFuel",
                        "denominator_metric": "Truck Count",
                        "materiality_min_share": 0.005
                    }
                return None
            mock_get_rc.side_effect = side_effect
            
            # Mock load_validation_data
            with patch("data_analyst_agent.tools.validation_data_loader.load_validation_data") as mock_lvd:
                lvd_df = pd.DataFrame([
                    {"terminal": "T1", "week_ending": "2025-01-04", "metric": "Revenue xFuel", "value": 3000.0},
                    {"terminal": "T1", "week_ending": "2025-01-04", "metric": "Truck Count", "value": 1.0},
                ])
                mock_lvd.return_value = lvd_df
                
                # Mock advanced analysis tools to skip them
                with patch("data_analyst_agent.sub_agents.statistical_insights_agent.tools.compute_seasonal_decomposition.compute_seasonal_decomposition", return_value='{}'), \
                     patch("data_analyst_agent.sub_agents.statistical_insights_agent.tools.detect_change_points.detect_change_points", return_value='{}'), \
                     patch("data_analyst_agent.sub_agents.statistical_insights_agent.tools.detect_mad_outliers.detect_mad_outliers", return_value='{}'), \
                     patch("data_analyst_agent.sub_agents.statistical_insights_agent.tools.compute_forecast_baseline.compute_forecast_baseline", return_value='{}'), \
                     patch("data_analyst_agent.sub_agents.statistical_insights_agent.tools.compute_derived_metrics.compute_derived_metrics", return_value='{}'), \
                     patch("data_analyst_agent.sub_agents.statistical_insights_agent.tools.compute_new_lost_same_store.compute_new_lost_same_store", return_value='{}'), \
                     patch("data_analyst_agent.sub_agents.statistical_insights_agent.tools.compute_concentration_analysis.compute_concentration_analysis", return_value='{}'):
                    
                    # Run statistical summary
                    result_json = await compute_statistical_summary()
                    result = json.loads(result_json)
                    
                    assert "error" not in result
                    # Rev/Trk/Wk should be isolated (3000) and not summed with "Other Metric" (8000)
                    assert result["monthly_totals"]["2025-01-04"] == 3000.0

@pytest.mark.asyncio
async def test_level_statistics_robust_ratio_detection():
    """
    Test that compute_level_statistics correctly detects a ratio metric
    even if the input dataframe contains multiple metrics and uses
    aggregate-then-derive.
    """
    # 1. Create a mock AnalysisContext
    mock_contract = MagicMock()
    mock_contract.name = "validation_ops"
    mock_contract.time.column = "week_ending"
    mock_contract.time.format = "%Y-%m-%d"
    mock_contract.grain.columns = ["terminal"]
    mock_contract.dimensions = []
    mock_contract.hierarchies = []
    mock_contract.materiality = {"variance_pct": 5.0, "variance_absolute": 10.0}
    
    mock_target_metric = MagicMock()
    mock_target_metric.name = "value" 
    mock_target_metric.column = "value"
    
    mock_ctx = MagicMock()
    mock_ctx.contract = mock_contract
    mock_ctx.target_metric = mock_target_metric
    
    # 2. Create a dataframe with TWO metrics
    df = pd.DataFrame([
        {"terminal": "T1", "region": "East", "week_ending": "2025-01-04", "metric": "Rev/Trk/Wk", "value": 3000.0},
        {"terminal": "T1", "region": "East", "week_ending": "2025-01-04", "metric": "Other", "value": 5000.0},
        # Prior period
        {"terminal": "T1", "region": "East", "week_ending": "2024-01-04", "metric": "Rev/Trk/Wk", "value": 3000.0},
        {"terminal": "T1", "region": "East", "week_ending": "2024-01-04", "metric": "Other", "value": 5000.0},
    ])
    
    # 3. Mock resolve_data_and_columns
    with patch("data_analyst_agent.sub_agents.hierarchy_variance_agent.tools.compute_level_statistics.resolve_data_and_columns") as mock_resolve:
        mock_resolve.return_value = (df, "week_ending", "value", "terminal", "terminal", mock_ctx)
        
        # Patch the ratio config
        with patch("data_analyst_agent.semantic.ratio_metrics_config.get_ratio_config_for_metric") as mock_get_rc:
            def side_effect(contract, name):
                if name == "Rev/Trk/Wk":
                    return {
                        "numerator_metric": "Revenue xFuel",
                        "denominator_metric": "Truck Count",
                        "materiality_min_share": 0.005
                    }
                return None
            mock_get_rc.side_effect = side_effect
            
            # Mock load_validation_data
            with patch("data_analyst_agent.tools.validation_data_loader.load_validation_data") as mock_lvd:
                lvd_df = pd.DataFrame([
                    {"terminal": "T1", "region": "East", "week_ending": "2025-01-04", "metric": "Revenue xFuel", "value": 3000.0},
                    {"terminal": "T1", "region": "East", "week_ending": "2025-01-04", "metric": "Truck Count", "value": 1.0},
                    {"terminal": "T1", "region": "East", "week_ending": "2024-01-04", "metric": "Revenue xFuel", "value": 3000.0},
                    {"terminal": "T1", "region": "East", "week_ending": "2024-01-04", "metric": "Truck Count", "value": 1.0},
                ])
                mock_lvd.return_value = lvd_df
                
                # Run level statistics (level=1 corresponds to terminal in this mock)
                result_json = await compute_level_statistics(level=1, analysis_period="2025-01-04")
                result = json.loads(result_json)
                
                assert "error" not in result
                # Should be 3000 (filtered and ratio-aggregated), not 8000 (sum of both metrics)
                assert result["top_drivers"][0]["current"] == 3000.0
