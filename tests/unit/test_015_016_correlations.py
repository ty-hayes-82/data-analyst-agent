import pytest
import json
import importlib
import pandas as pd
import numpy as np
from io import StringIO
import os
from pathlib import Path

# ============================================================================
# Dynamic import helper
# ============================================================================

def _import_stat_tool(tool_name: str):
    """Import a tool from statistical_insights_agent using importlib."""
    mod = importlib.import_module(
        f"data_analyst_agent.sub_agents.statistical_insights_agent.tools.{tool_name}"
    )
    return getattr(mod, tool_name)

# ============================================================================
# Helper: populate the data cache with synthetic multi-metric data
# ============================================================================

def _populate_cache_with_synthetic_data():
    """Create synthetic multi-metric data and set up AnalysisContext."""
    from data_analyst_agent.sub_agents.data_cache import (
        set_validated_csv,
        clear_all_caches,
        set_analysis_context,
    )
    from data_analyst_agent.semantic.models import AnalysisContext, DatasetContract, MetricDefinition, DimensionDefinition, TimeConfig, GrainConfig

    clear_all_caches()

    # 1. Create 24 periods of data
    periods = pd.date_range(start="2024-01-01", periods=24, freq="W-SAT").strftime("%Y-%m-%d").tolist()
    terminals = ["T1", "T2", "T3"]
    
    rows = []
    for p in periods:
        for t in terminals:
            # Base volume (Truck Count)
            truck_count = 100 + np.random.randint(-10, 10)
            
            # Miles depends on truck count (Correlation!)
            # Add a trend to truck_count to see it lead revenue later
            idx = periods.index(p)
            if idx < 12:
                truck_count += idx * 2
            else:
                truck_count += 24 - (idx - 12) * 2
                
            miles = truck_count * 1000 + np.random.randint(-1000, 1000)
            
            # Revenue depends on miles (Correlation!)
            revenue = miles * 2.5 + np.random.randint(-5000, 5000)
            
            # Add a lagged relationship: Order Count leads Revenue by 1 week
            # We'll shift Order Count 1 week early
            if idx < 23:
                # Order count for NEXT week's revenue
                order_count = 50 + np.random.randint(-5, 5)
            else:
                order_count = 50
            
            # Metric dimension style (like validation_data.csv)
            rows.append({"week_ending": p, "terminal": t, "metric": "Truck Count", "value": truck_count})
            rows.append({"week_ending": p, "terminal": t, "metric": "Total Miles", "value": miles})
            rows.append({"week_ending": p, "terminal": t, "metric": "Total Revenue", "value": revenue})
            rows.append({"week_ending": p, "terminal": t, "metric": "Order Count", "value": order_count})

    df = pd.DataFrame(rows)
    
    # We also need a "wide" format version for the AnalysisContext primary metric
    df_revenue = df[df["metric"] == "Total Revenue"].copy()
    set_validated_csv(df_revenue.to_csv(index=False))

    # 2. Create Contract
    metrics = [
        MetricDefinition(name="Truck Count", column="value", type="additive"),
        MetricDefinition(name="Total Miles", column="value", type="additive"),
        MetricDefinition(name="Total Revenue", column="value", type="additive", tags=["revenue"]),
        MetricDefinition(name="Order Count", column="value", type="additive"),
        MetricDefinition(name="value", column="value", type="additive") # Target metric
    ]
    
    # Set dependencies
    metrics[2].depends_on = ["Total Miles"]
    
    contract = DatasetContract(
        name="Synthetic Ops",
        version="1.0",
        time=TimeConfig(column="week_ending", frequency="weekly", format="%Y-%m-%d"),
        grain=GrainConfig(columns=["week_ending", "terminal"]),
        metrics=metrics,
        dimensions=[
            DimensionDefinition(name="terminal", column="terminal", role="primary"),
            DimensionDefinition(name="metric", column="metric", role="secondary")
        ]
    )

    ctx = AnalysisContext(
        contract=contract,
        df=df_revenue,
        target_metric=metrics[4], # value
        primary_dimension=contract.dimensions[0],
        run_id="test_synthetic_correlations"
    )
    set_analysis_context(ctx)
    
    # Mock load_validation_data to return our synthetic df
    import data_analyst_agent.tools.validation_data_loader as vdl
    vdl.load_validation_data = lambda **kwargs: df
    
    return df, ctx

def _teardown_cache():
    from data_analyst_agent.sub_agents.data_cache import clear_all_caches
    clear_all_caches()

# ============================================================================
# Tests
# ============================================================================

@pytest.mark.unit
@pytest.mark.asyncio
async def test_compute_cross_metric_correlation_synthetic():
    """Test cross-metric correlation with synthetic data."""
    compute_cross_metric_correlation = _import_stat_tool("compute_cross_metric_correlation")
    _populate_cache_with_synthetic_data()

    try:
        result_str = await compute_cross_metric_correlation(per_dimension=True)
        result = json.loads(result_str)

        assert "error" not in result
        assert "matrix" in result
        assert result["summary"]["significant_pairs"] > 0
        
        # Check Total Revenue vs Total Miles (Expected)
        pairs = result["significant_pairs"]
        rev_miles = [p for p in pairs if (p["metric_a"] == "Total Revenue" and p["metric_b"] == "Total Miles") or 
                                         (p["metric_b"] == "Total Revenue" and p["metric_a"] == "Total Miles")]
        assert len(rev_miles) > 0
        assert rev_miles[0]["expected"] == True
        
        print(f"[PASS] Synthetic Cross-metric: {result['summary']['significant_pairs']} significant pairs found")
    finally:
        _teardown_cache()

@pytest.mark.unit
@pytest.mark.asyncio
async def test_compute_lagged_correlation_synthetic():
    """Test lagged correlation with synthetic data."""
    compute_lagged_correlation = _import_stat_tool("compute_lagged_correlation")
    _populate_cache_with_synthetic_data()

    try:
        # Lower min_r for synthetic tests
        result_str = await compute_lagged_correlation(min_r=0.3)
        result = json.loads(result_str)

        assert "error" not in result
        assert "leading_indicators" in result
        
        print(f"[PASS] Synthetic Lagged: {result['summary']['leading_pairs_found']} leading pairs found")
    finally:
        _teardown_cache()

@pytest.mark.unit
@pytest.mark.asyncio
async def test_compute_statistical_summary_integration_synthetic():
    """Test integration into summary with synthetic data."""
    compute_statistical_summary = _import_stat_tool("compute_statistical_summary")
    _populate_cache_with_synthetic_data()

    try:
        result_str = await compute_statistical_summary()
        result = json.loads(result_str)

        assert "cross_metric_correlations" in result
        assert "lagged_correlations" in result
        assert "error" not in result
        
        print("[PASS] Synthetic Statistical summary integration successful")
    finally:
        _teardown_cache()

if __name__ == "__main__":
    import sys
    sys.path.append(os.getcwd())
    pytest.main([__file__, "-v", "-s", "--tb=short"])
