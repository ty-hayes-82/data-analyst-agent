"""Test Analysis Focus Feature (P0)

Verifies that DATA_ANALYST_FOCUS and DATA_ANALYST_CUSTOM_FOCUS env vars
are correctly injected into session state and used by analysis agents.
"""

import os
import pytest
from unittest.mock import AsyncMock, MagicMock
from data_analyst_agent.core_agents.cli import CLIParameterInjector
from data_analyst_agent.utils.focus_directives import (
    get_focus_modes,
    get_custom_focus,
    focus_block,
    augment_instruction,
)


@pytest.fixture
def mock_session_state():
    """Mock session state with contract."""
    from types import SimpleNamespace
    
    contract = SimpleNamespace(
        name="trade_data",
        display_name="Trade Data",
        dimensions=[
            SimpleNamespace(name="region", role="primary"),
        ],
        hierarchies=[
            SimpleNamespace(level_names={0: "Total", 1: "Region", 2: "State"}),
        ],
        metrics=["trade_value_usd", "volume_units"],
    )
    
    return {
        "dataset_contract": contract,
    }


@pytest.mark.asyncio
async def test_cli_injects_focus_modes(mock_session_state):
    """Test CLIParameterInjector reads and injects focus env vars."""
    
    # Set env vars
    os.environ["DATA_ANALYST_FOCUS"] = "anomaly_detection,recent_monthly_trends"
    os.environ["DATA_ANALYST_CUSTOM_FOCUS"] = "Focus on Q4 performance"
    os.environ["DATA_ANALYST_METRICS"] = "trade_value_usd"
    
    try:
        # Create injector
        injector = CLIParameterInjector()
        
        # Create mock context
        ctx = MagicMock()
        ctx.invocation_id = "test-123"
        ctx.session.state = mock_session_state.copy()
        
        # Run injector
        events = []
        async for event in injector._run_async_impl(ctx):
            events.append(event)
        
        # Verify event was yielded
        assert len(events) == 1
        event = events[0]
        
        # Check state delta
        state_delta = event.actions.state_delta
        assert "analysis_focus" in state_delta
        assert "custom_focus" in state_delta
        
        # Verify focus modes parsed correctly
        assert state_delta["analysis_focus"] == ["anomaly_detection", "recent_monthly_trends"]
        assert state_delta["custom_focus"] == "Focus on Q4 performance"
        
        # Verify focus included in request_analysis
        request = state_delta.get("request_analysis", {})
        assert request["analysis_focus"] == ["anomaly_detection", "recent_monthly_trends"]
        assert request["custom_focus"] == "Focus on Q4 performance"
        assert "anomaly_detection" in request["focus"]
        
    finally:
        # Clean up env vars
        os.environ.pop("DATA_ANALYST_FOCUS", None)
        os.environ.pop("DATA_ANALYST_CUSTOM_FOCUS", None)
        os.environ.pop("DATA_ANALYST_METRICS", None)


def test_focus_directives_helper_functions():
    """Test focus_directives utility functions."""
    
    # Test with focus modes
    state = {
        "analysis_focus": ["anomaly_detection", "recent_monthly_trends"],
        "custom_focus": "Focus on Q4 performance",
    }
    
    # Test get_focus_modes
    modes = get_focus_modes(state)
    assert modes == ["anomaly_detection", "recent_monthly_trends"]
    
    # Test get_custom_focus
    custom = get_custom_focus(state)
    assert custom == "Focus on Q4 performance"
    
    # Test focus_block
    block = focus_block(state)
    assert "FOCUS_DIRECTIVES:" in block
    assert "anomaly_detection" in block
    assert "recent_monthly_trends" in block
    assert "Q4 performance" in block
    
    # Test augment_instruction
    base_instruction = "Analyze the data carefully."
    augmented = augment_instruction(base_instruction, state)
    assert "Analyze the data carefully." in augmented
    assert "FOCUS_DIRECTIVES:" in augmented
    assert "anomaly_detection" in augmented


def test_focus_directives_empty_state():
    """Test focus directives with no focus set."""
    
    state = {}
    
    # Should return empty lists/strings
    assert get_focus_modes(state) == []
    assert get_custom_focus(state) == ""
    assert focus_block(state) == ""
    
    # augment_instruction should return unchanged instruction
    base = "Test instruction"
    assert augment_instruction(base, state) == base


def test_focus_directives_normalization():
    """Test focus modes are normalized properly."""
    
    # Test with list containing whitespace and empty strings
    # Note: The CLI injector does the comma-splitting; focus_directives expects a list
    state = {
        "analysis_focus": ["anomaly_detection", "", "recent_monthly_trends", "  "],
    }
    
    modes = get_focus_modes(state)
    # Should strip whitespace and filter empty strings
    assert len(modes) == 2  # Empty strings are filtered out
    assert modes == ["anomaly_detection", "recent_monthly_trends"]
    
    # Test with None
    state = {"analysis_focus": None}
    assert get_focus_modes(state) == []
    
    # Test with single string (not a list)
    state = {"analysis_focus": "single_focus_mode"}
    modes = get_focus_modes(state)
    assert modes == ["single_focus_mode"]


@pytest.mark.asyncio
async def test_cli_focus_with_empty_env_vars(mock_session_state):
    """Test CLIParameterInjector with no focus env vars set."""
    
    # Ensure env vars are not set
    os.environ.pop("DATA_ANALYST_FOCUS", None)
    os.environ.pop("DATA_ANALYST_CUSTOM_FOCUS", None)
    os.environ["DATA_ANALYST_METRICS"] = "trade_value_usd"
    
    try:
        injector = CLIParameterInjector()
        
        ctx = MagicMock()
        ctx.invocation_id = "test-456"
        ctx.session.state = mock_session_state.copy()
        
        events = []
        async for event in injector._run_async_impl(ctx):
            events.append(event)
        
        assert len(events) == 1
        state_delta = events[0].actions.state_delta
        
        # Should have empty focus lists
        assert state_delta["analysis_focus"] == []
        assert state_delta["custom_focus"] is None
        
    finally:
        os.environ.pop("DATA_ANALYST_METRICS", None)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
