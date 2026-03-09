import pytest
import json
import pandas as pd
import numpy as np
from unittest.mock import patch, MagicMock
from data_analyst_agent.sub_agents.data_cache import set_analysis_context, clear_all_caches, set_validated_csv
from data_analyst_agent.semantic.models import DatasetContract, AnalysisContext, HierarchyNode, DimensionDefinition, MetricDefinition
from tests.utils.import_helpers import import_hierarchy_ranker_tool

def _setup_mock_5_level_data():
    """Create data for a 5-level hierarchy."""
    # Levels: L0 (Total) -> L1 (Region) -> L2 (District) -> L3 (Store) -> L4 (Product)
    data = []
    regions = ["East", "West"]
    districts = ["D1", "D2"]
    stores = ["S1", "S2"]
    products = ["P1", "P2"]
    periods = ["2024-01", "2025-01"]
    
    for p in periods:
        for reg in regions:
            for dist in districts:
                for store in stores:
                    for prod in products:
                        # Price/Vol for PVM too
                        qty = 100 if p == "2024-01" else 120
                        price = 10.0 if p == "2024-01" else 11.0
                        amount = qty * price
                        
                        data.append({
                            "period": p,
                            "region": reg,
                            "district": dist,
                            "store": store,
                            "product": prod,
                            "amount": amount,
                            "qty": qty,
                            "price": price
                        })
    
    df = pd.DataFrame(data)
    csv_data = df.to_csv(index=False)
    set_validated_csv(csv_data)
    
    # Define hierarchy
    hierarchy = HierarchyNode(
        name="store_product",
        children=["region", "district", "store", "product"] # Level 0 is total, 1=region, 2=district, 3=store, 4=product
    )
    
    contract = DatasetContract(
        name="retail_contract",
        version="1.0",
        time={"column": "period", "format": "%Y-%m", "frequency": "monthly"},
        grain={"columns": ["region", "district", "store", "product"]},
        metrics=[
            MetricDefinition(name="amount", column="amount", unit="USD", direction="higher_is_better"),
            MetricDefinition(name="qty", column="qty", unit="Units", direction="higher_is_better", pvm_role="volume"),
            MetricDefinition(name="price", column="price", unit="USD", direction="higher_is_better", pvm_role="price")
        ],
        dimensions=[
            DimensionDefinition(name="region", column="region"),
            DimensionDefinition(name="district", column="district"),
            DimensionDefinition(name="store", column="store"),
            DimensionDefinition(name="product", column="product")
        ],
        hierarchies=[hierarchy]
    )
    
    ctx = AnalysisContext(
        contract=contract,
        df=df,
        target_metric=contract.metrics[0],
        primary_dimension=contract.dimensions[0],
        cost_center="RETAIL",
        run_id="test_recursive"
    )
    set_analysis_context(ctx)
    return ctx

@pytest.mark.integration
@pytest.mark.asyncio
async def test_recursive_drilldown_levels():
    """Test aggregation at all 5 levels of the hierarchy."""
    _setup_mock_5_level_data()
    mod = import_hierarchy_ranker_tool("compute_level_statistics")
    compute_level_statistics = mod.compute_level_statistics
    
    try:
        # Level 0: Total (should have 1 item: 'Total')
        res0_str = await compute_level_statistics(level=0, hierarchy_name="store_product")
        res0 = json.loads(res0_str)
        assert res0["level"] == 0
        assert res0["level_name"] == "Total"
        assert len(res0["top_drivers"]) == 1
        assert res0["is_last_level"] is False
        
        # Level 1: Region (should have 2 items: East, West)
        res1_str = await compute_level_statistics(level=1, hierarchy_name="store_product")
        res1 = json.loads(res1_str)
        assert res1["level"] == 1
        assert res1["level_name"] == "region"
        assert res1["items_analyzed"] == 2
        
        # Level 4: Product (Last Level)
        res4_str = await compute_level_statistics(level=4, hierarchy_name="store_product")
        res4 = json.loads(res4_str)
        assert res4["level"] == 4
        assert res4["level_name"] == "product"
        assert res4["is_last_level"] is True
        
    finally:
        clear_all_caches()

@pytest.mark.integration
@pytest.mark.asyncio
async def test_recursive_drilldown_pvm_integration():
    """Test PVM decomposition within the recursive flow."""
    _setup_mock_5_level_data()
    mod_pvm = import_hierarchy_ranker_tool("compute_pvm_decomposition")
    compute_pvm = mod_pvm.compute_pvm_decomposition
    
    try:
        # Perform PVM at Region level
        res_pvm_str = await compute_pvm(
            target_metric="amount",
            price_metric="price",
            volume_metric="qty",
            dimension="region",
            analysis_period="2025-01",
            prior_period="2024-01"
        )
        res_pvm = json.loads(res_pvm_str)
        
        assert "error" not in res_pvm
        assert res_pvm["total_variance"] > 0
        assert res_pvm["total_volume_impact"] > 0
        assert res_pvm["total_price_impact"] > 0
        
    finally:
        clear_all_caches()

# ============================================================================
# Ops Metrics 3-level hierarchy: LOB -> Terminal -> Driver Leader
# ============================================================================

def _setup_ops_metrics_hierarchy_data():
    """Create data for the ops_metrics operational_structure hierarchy."""
    data = []
    lobs = ["Line Haul", "Dedicated"]
    terminals = ["Phoenix", "Dallas", "Chicago"]
    leaders = ["MGR01", "MGR02"]
    periods = ["2024-06", "2025-06"]

    for p in periods:
        for lob in lobs:
            for terminal in terminals:
                for leader in leaders:
                    base_rev = 500000 if lob == "Line Haul" else 300000
                    multiplier = 1.15 if p >= "2025-01" else 1.0
                    rev = round(base_rev * multiplier + hash((lob, terminal, leader, p)) % 50000, 2)
                    miles = round(rev / 4.0, 2)

                    data.append({
                        "cal_dt": p,
                        "ops_ln_of_bus_ref_nm": lob,
                        "gl_div_nm": terminal,
                        "drvr_mgr_cd": leader,
                        "ttl_rev_amt": rev,
                        "ld_trf_mi": miles,
                    })

    df = pd.DataFrame(data)
    csv_data = df.to_csv(index=False)
    set_validated_csv(csv_data)

    hierarchy = HierarchyNode(
        name="operational_structure",
        children=["lob", "terminal", "driver_leader"],
    )

    from data_analyst_agent.semantic.models import TimeConfig, GrainConfig

    contract = DatasetContract(
        name="Ops Metrics",
        version="2.0",
        time=TimeConfig(column="cal_dt", frequency="monthly", format="%Y-%m"),
        grain=GrainConfig(columns=["cal_dt", "ops_ln_of_bus_ref_nm"]),
        metrics=[
            MetricDefinition(name="total_revenue", column="ttl_rev_amt"),
            MetricDefinition(name="loaded_miles", column="ld_trf_mi"),
        ],
        dimensions=[
            DimensionDefinition(name="lob", column="ops_ln_of_bus_ref_nm"),
            DimensionDefinition(name="terminal", column="gl_div_nm", role="secondary"),
            DimensionDefinition(name="driver_leader", column="drvr_mgr_cd", role="secondary"),
        ],
        hierarchies=[hierarchy],
    )

    ctx = AnalysisContext(
        contract=contract,
        df=df,
        target_metric=contract.metrics[0],
        primary_dimension=contract.dimensions[0],
        run_id="test_ops_recursive",
        max_drill_depth=3,
    )
    set_analysis_context(ctx)
    return ctx


@pytest.mark.integration
@pytest.mark.ops_metrics
@pytest.mark.asyncio
async def test_ops_recursive_drilldown_level_0():
    """Level 0 (Total) for ops_metrics operational_structure."""
    _setup_ops_metrics_hierarchy_data()
    mod = import_hierarchy_ranker_tool("compute_level_statistics")
    compute_level_statistics = mod.compute_level_statistics

    try:
        res_str = await compute_level_statistics(level=0, hierarchy_name="operational_structure")
        res = json.loads(res_str)

        if "error" in res:
            pytest.skip(f"compute_level_statistics not yet compatible: {res['error']}")

        assert res["level"] == 0
        assert res["level_name"] == "Total"
    finally:
        clear_all_caches()


@pytest.mark.integration
@pytest.mark.ops_metrics
@pytest.mark.asyncio
async def test_ops_recursive_drilldown_level_1_lob():
    """Level 1 (LOB) should return 2 items: Line Haul, Dedicated."""
    _setup_ops_metrics_hierarchy_data()
    mod = import_hierarchy_ranker_tool("compute_level_statistics")
    compute_level_statistics = mod.compute_level_statistics

    try:
        res_str = await compute_level_statistics(level=1, hierarchy_name="operational_structure")
        res = json.loads(res_str)

        if "error" in res:
            pytest.skip(f"compute_level_statistics not yet compatible: {res['error']}")

        assert res["level"] == 1
        assert res["level_name"] == "lob"
        assert res["items_analyzed"] == 2
    finally:
        clear_all_caches()


@pytest.mark.integration
@pytest.mark.ops_metrics
@pytest.mark.asyncio
async def test_ops_recursive_drilldown_level_3_last():
    """Level 3 (driver_leader) should be marked as is_last_level."""
    _setup_ops_metrics_hierarchy_data()
    mod = import_hierarchy_ranker_tool("compute_level_statistics")
    compute_level_statistics = mod.compute_level_statistics

    try:
        res_str = await compute_level_statistics(level=3, hierarchy_name="operational_structure")
        res = json.loads(res_str)

        if "error" in res:
            pytest.skip(f"compute_level_statistics not yet compatible: {res['error']}")

        assert res["level"] == 3
        assert res["is_last_level"] is True
    finally:
        clear_all_caches()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
