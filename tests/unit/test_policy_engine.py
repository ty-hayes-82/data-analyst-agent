import pytest
import pandas as pd
from data_analyst_agent.semantic.policies import PolicyEngine
from data_analyst_agent.semantic.models import DatasetContract, MetricDefinition, DimensionDefinition, TimeConfig, GrainConfig

def test_sign_correction_policy():
    """Test that PolicyEngine correctly applies sign flips based on contract."""
    
    contract = DatasetContract(
        name="test",
        version="1.0",
        time=TimeConfig(column="date", frequency="daily"),
        grain=GrainConfig(columns=["date"]),
        metrics=[MetricDefinition(name="amount", column="amount")],
        dimensions=[DimensionDefinition(name="item", column="item")],
        policies={
            "sign_correction": [
                {"column": "item", "starts_with": "3", "multiplier": -1}
            ]
        }
    )
    
    df = pd.DataFrame({
        "item": ["3100", "4100", "3200"],
        "amount": [100.0, 200.0, 300.0]
    })
    
    engine = PolicyEngine(contract)
    df_corrected = engine.apply_sign_correction(df)
    
    # Items starting with 3 should be flipped
    assert df_corrected.loc[0, "amount"] == -100.0
    assert df_corrected.loc[1, "amount"] == 200.0
    assert df_corrected.loc[2, "amount"] == -300.0

def test_item_classification_policy():
    """Test semantic classification logic."""
    
    contract = DatasetContract(
        name="test",
        version="1.0",
        time=TimeConfig(column="date", frequency="daily"),
        grain=GrainConfig(columns=["date"]),
        metrics=[MetricDefinition(name="amount", column="amount")],
        dimensions=[DimensionDefinition(name="item", column="item")],
        policies={
            "item_classification": {
                "revenue": {"starts_with": "3"},
                "expense": {"starts_with": ["5", "6"]},
                "specific_item": {"values": ["9999"]}
            }
        }
    )
    
    engine = PolicyEngine(contract)
    
    assert engine.evaluate_item_classification("3100") == "revenue"
    assert engine.evaluate_item_classification("5010") == "expense"
    assert engine.evaluate_item_classification("6010") == "expense"
    assert engine.evaluate_item_classification("9999") == "specific_item"
    assert engine.evaluate_item_classification("4000") is None

# ============================================================================
# Ops Metrics contract policy tests (Spec 001 + 004)
# ============================================================================

def test_ops_metrics_item_classification():
    """Test item classification with ops_metrics contract policies."""

    contract = DatasetContract(
        name="ops_metrics_test",
        version="1.0",
        time=TimeConfig(column="cal_dt", frequency="monthly"),
        grain=GrainConfig(columns=["cal_dt", "ops_ln_of_bus_ref_nm"]),
        metrics=[MetricDefinition(name="total_revenue", column="ttl_rev_amt")],
        dimensions=[DimensionDefinition(name="lob", column="ops_ln_of_bus_ref_nm")],
        policies={
            "item_classification": {
                "company_drivers": {"values": ["Company"]},
                "owner_operators": {"values": ["Owner Operator"]},
            }
        }
    )

    engine = PolicyEngine(contract)

    assert engine.evaluate_item_classification("Company") == "company_drivers"
    assert engine.evaluate_item_classification("Owner Operator") == "owner_operators"
    assert engine.evaluate_item_classification("Independent") is None


def test_degradation_threshold_policy():
    """Test that degradation_threshold is retrievable as a raw policy value."""

    contract = DatasetContract(
        name="ops_metrics_test",
        version="1.0",
        time=TimeConfig(column="cal_dt", frequency="monthly"),
        grain=GrainConfig(columns=["cal_dt"]),
        metrics=[MetricDefinition(name="total_revenue", column="ttl_rev_amt")],
        dimensions=[DimensionDefinition(name="lob", column="ops_ln_of_bus_ref_nm")],
        policies={
            "degradation_threshold": 0.10,
            "item_classification": {},
        }
    )

    engine = PolicyEngine(contract)

    threshold = engine.get_policy("degradation_threshold")
    assert threshold == 0.10

    # Non-existent policy should return None
    assert engine.get_policy("non_existent") is None


def test_sign_correction_no_policy():
    """PolicyEngine with empty sign_correction should return df unchanged."""

    contract = DatasetContract(
        name="ops_no_sign",
        version="1.0",
        time=TimeConfig(column="cal_dt", frequency="monthly"),
        grain=GrainConfig(columns=["cal_dt"]),
        metrics=[MetricDefinition(name="total_revenue", column="ttl_rev_amt")],
        dimensions=[DimensionDefinition(name="lob", column="ops_ln_of_bus_ref_nm")],
        policies={},
    )

    df = pd.DataFrame({"ttl_rev_amt": [100.0, 200.0]})
    engine = PolicyEngine(contract)
    result = engine.apply_sign_correction(df)

    assert result["ttl_rev_amt"].iloc[0] == 100.0
    assert result["ttl_rev_amt"].iloc[1] == 200.0


if __name__ == "__main__":
    pytest.main([__file__])
