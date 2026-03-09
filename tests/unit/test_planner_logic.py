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
from unittest.mock import patch, MagicMock

from data_analyst_agent.sub_agents.planner_agent.tools.generate_execution_plan import generate_execution_plan
from data_analyst_agent.semantic.models import DatasetContract, AnalysisContext, MetricDefinition, DimensionDefinition, TimeConfig, GrainConfig, HierarchyNode

@pytest.mark.asyncio
async def test_planner_seasonal_requirement():
    """Test seasonal_baseline_agent: skipped when statistical_insights is present (20+ periods),
    and skipped when < 18 periods."""
    
    # Setup mock data with 20 periods
    periods = [f"2024-{i:02d}" for i in range(1, 13)] + [f"2025-{i:02d}" for i in range(1, 9)]
    df = pd.DataFrame({"period": periods, "amount": [100] * 20})
    
    contract = DatasetContract(
        name="test_contract",
        version="1.0",
        time=TimeConfig(column="period", frequency="monthly", format="%Y-%m"),
        grain=GrainConfig(columns=["period"]),
        metrics=[MetricDefinition(name="amount", column="amount")],
        dimensions=[DimensionDefinition(name="item", column="item")],
        hierarchies=[]
    )
    
    ctx = AnalysisContext(
        contract=contract,
        df=df,
        target_metric=contract.metrics[0],
        primary_dimension=contract.dimensions[0],
        run_id="test",
        max_drill_depth=3
    )
    
    with patch("data_analyst_agent.sub_agents.planner_agent.tools.generate_execution_plan.get_analysis_context") as mock_get_ctx:
        mock_get_ctx.return_value = ctx
        
        result_str = await generate_execution_plan()
        result = json.loads(result_str)
        
        agent_names = [a["name"] for a in result["recommended_agents"]]
        # When statistical_insights_agent is selected (periods >= 2), seasonal_baseline is skipped
        # because statistical summary already includes seasonal analysis.
        assert "statistical_insights_agent" in agent_names
        assert "seasonal_baseline_agent" not in agent_names
        
    # Setup mock data with 10 periods
    df_short = pd.DataFrame({"period": periods[:10], "amount": [100] * 10})
    ctx_short = AnalysisContext(
        contract=contract,
        df=df_short,
        target_metric=contract.metrics[0],
        primary_dimension=contract.dimensions[0],
        run_id="test",
        max_drill_depth=3
    )
    
    with patch("data_analyst_agent.sub_agents.planner_agent.tools.generate_execution_plan.get_analysis_context") as mock_get_ctx:
        mock_get_ctx.return_value = ctx_short
        
        result_str = await generate_execution_plan()
        result = json.loads(result_str)
        
        agent_names = [a["name"] for a in result["recommended_agents"]]
        assert "seasonal_baseline_agent" not in agent_names

@pytest.mark.asyncio
async def test_planner_pvm_requirement():
    """Test that PVM is only recommended if pvm_roles are defined."""
    
    # Contract WITHOUT PVM
    contract_no_pvm = DatasetContract(
        name="test_contract",
        version="1.0",
        time=TimeConfig(column="period", frequency="monthly", format="%Y-%m"),
        grain=GrainConfig(columns=["period"]),
        metrics=[MetricDefinition(name="amount", column="amount")],
        dimensions=[DimensionDefinition(name="item", column="item")],
        hierarchies=[]
    )
    
    df = pd.DataFrame({"period": ["2024-01", "2024-02"], "amount": [100, 110]})
    ctx = AnalysisContext(
        contract=contract_no_pvm,
        df=df,
        target_metric=contract_no_pvm.metrics[0],
        primary_dimension=contract_no_pvm.dimensions[0],
        run_id="test"
    )
    
    with patch("data_analyst_agent.sub_agents.planner_agent.tools.generate_execution_plan.get_analysis_context") as mock_get_ctx:
        mock_get_ctx.return_value = ctx
        result_str = await generate_execution_plan()
        result = json.loads(result_str)
        agent_names = [a["name"] for a in result["recommended_agents"]]
        assert "pvm_decomposition" not in agent_names

    # Contract WITH PVM
    contract_pvm = DatasetContract(
        name="test_contract",
        version="1.0",
        time=TimeConfig(column="period", frequency="monthly", format="%Y-%m"),
        grain=GrainConfig(columns=["period"]),
        metrics=[
            MetricDefinition(name="amount", column="amount", pvm_role="total"),
            MetricDefinition(name="price", column="price", pvm_role="price"),
            MetricDefinition(name="qty", column="qty", pvm_role="volume")
        ],
        dimensions=[DimensionDefinition(name="item", column="item")],
        hierarchies=[]
    )
    
    ctx_pvm = AnalysisContext(
        contract=contract_pvm,
        df=df,
        target_metric=contract_pvm.metrics[0],
        primary_dimension=contract_pvm.dimensions[0],
        run_id="test"
    )
    
    with patch("data_analyst_agent.sub_agents.planner_agent.tools.generate_execution_plan.get_analysis_context") as mock_get_ctx:
        mock_get_ctx.return_value = ctx_pvm
        result_str = await generate_execution_plan()
        result = json.loads(result_str)
        agent_names = [a["name"] for a in result["recommended_agents"]]
        assert "pvm_decomposition" in agent_names

# ============================================================================
# Ops Metrics planner tests (Spec 003)
# ============================================================================

@pytest.mark.asyncio
async def test_planner_ops_metrics_contract():
    """
    With the ops_metrics contract (has hierarchies AND pvm_role), the planner
    should recommend hierarchy drill-down, PVM decomposition, and statistical
    insights (>= 2 periods in data).
    """
    from data_analyst_agent.semantic.models import HierarchyNode

    contract_ops = DatasetContract(
        name="Ops Metrics",
        version="2.0",
        time=TimeConfig(column="cal_dt", frequency="monthly", format="%Y-%m"),
        grain=GrainConfig(columns=["cal_dt", "ops_ln_of_bus_ref_nm"]),
        metrics=[
            MetricDefinition(name="total_revenue", column="ttl_rev_amt", pvm_role="total"),
            MetricDefinition(name="linehaul_revenue", column="lh_rev_amt", pvm_role="price"),
            MetricDefinition(name="loaded_miles", column="ld_trf_mi", pvm_role="volume"),
        ],
        dimensions=[
            DimensionDefinition(name="lob", column="ops_ln_of_bus_ref_nm"),
            DimensionDefinition(name="terminal", column="gl_div_nm", role="secondary"),
        ],
        hierarchies=[
            HierarchyNode(name="operational_structure", children=["lob", "terminal"]),
        ],
    )

    df = pd.DataFrame({
        "cal_dt": [f"2024-{m:02d}" for m in range(1, 13)],
        "ttl_rev_amt": [500000 + i * 10000 for i in range(12)],
        "ops_ln_of_bus_ref_nm": ["Line Haul"] * 12,
    })

    ctx = AnalysisContext(
        contract=contract_ops,
        df=df,
        target_metric=contract_ops.metrics[0],
        primary_dimension=contract_ops.dimensions[0],
        run_id="test-ops",
        max_drill_depth=3,
    )

    with patch(
        "data_analyst_agent.sub_agents.planner_agent.tools.generate_execution_plan.get_analysis_context"
    ) as mock_get_ctx:
        mock_get_ctx.return_value = ctx

        result_str = await generate_execution_plan()
        result = json.loads(result_str)

        agent_names = [a["name"] for a in result["recommended_agents"]]
        assert "hierarchical_analysis_agent" in agent_names, "Should recommend hierarchy drill-down"
        assert "pvm_decomposition" in agent_names, "Should recommend PVM (contract has pvm_role)"
        assert "statistical_insights_agent" in agent_names, "Should recommend stats (12 periods)"


@pytest.mark.asyncio
async def test_planner_no_hierarchy_contract():
    """Without hierarchies, planner should NOT recommend hierarchical_analysis_agent."""

    contract_flat = DatasetContract(
        name="flat_contract",
        version="1.0",
        time=TimeConfig(column="period", frequency="monthly", format="%Y-%m"),
        grain=GrainConfig(columns=["period"]),
        metrics=[MetricDefinition(name="amount", column="amount")],
        dimensions=[DimensionDefinition(name="item", column="item")],
        hierarchies=[],
    )

    df = pd.DataFrame({"period": ["2024-01", "2024-02"], "amount": [100, 110]})
    ctx = AnalysisContext(
        contract=contract_flat,
        df=df,
        target_metric=contract_flat.metrics[0],
        primary_dimension=contract_flat.dimensions[0],
        run_id="test-flat",
    )

    with patch(
        "data_analyst_agent.sub_agents.planner_agent.tools.generate_execution_plan.get_analysis_context"
    ) as mock_get_ctx:
        mock_get_ctx.return_value = ctx

        result_str = await generate_execution_plan()
        result = json.loads(result_str)

        agent_names = [a["name"] for a in result["recommended_agents"]]
        assert "hierarchical_analysis_agent" not in agent_names


if __name__ == "__main__":
    import pytest
    pytest.main([__file__])
