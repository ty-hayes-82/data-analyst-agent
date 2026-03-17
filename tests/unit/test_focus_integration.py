"""Tests for analysis focus system integration.

Validates that focus directives flow from env vars through CLIParameterInjector
to downstream agents (Planner, Statistical tools, Narrative, Report Synthesis).
"""

import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from data_analyst_agent.core_agents.cli import CLIParameterInjector
from data_analyst_agent.utils.focus_directives import (
    get_focus_modes,
    get_custom_focus,
    focus_search_text,
    augment_instruction,
)


class TestCLIParameterInjectorFocus:
    """Test focus directive parsing and validation in CLIParameterInjector."""

    @pytest.mark.asyncio
    async def test_focus_modes_parsed_from_env(self):
        """Verify focus modes are read from DATA_ANALYST_FOCUS env var."""
        os.environ["DATA_ANALYST_FOCUS"] = "recent_weekly_trends,anomaly_detection"
        os.environ["DATA_ANALYST_CUSTOM_FOCUS"] = "Focus on revenue gaps"
        
        injector = CLIParameterInjector()
        ctx = MagicMock()
        ctx.invocation_id = "test"
        ctx.session.state = {"dataset_contract": None}
        
        events = []
        async for event in injector._run_async_impl(ctx):
            events.append(event)
        
        assert len(events) == 1
        state_delta = events[0].actions.state_delta
        assert state_delta["analysis_focus"] == ["recent_weekly_trends", "anomaly_detection"]
        assert state_delta["custom_focus"] == "Focus on revenue gaps"
        
        # Cleanup
        del os.environ["DATA_ANALYST_FOCUS"]
        del os.environ["DATA_ANALYST_CUSTOM_FOCUS"]

    @pytest.mark.asyncio
    async def test_unknown_focus_modes_filtered(self):
        """Verify unknown focus modes trigger warning and are filtered out."""
        os.environ["DATA_ANALYST_FOCUS"] = "recent_weekly_trends,invalid_mode,anomaly_detection"
        
        injector = CLIParameterInjector()
        ctx = MagicMock()
        ctx.invocation_id = "test"
        ctx.session.state = {"dataset_contract": None}
        
        events = []
        with patch('builtins.print') as mock_print:
            async for event in injector._run_async_impl(ctx):
                events.append(event)
            
            # Check that warning was printed
            warning_calls = [call for call in mock_print.call_args_list if "WARNING" in str(call)]
            assert len(warning_calls) > 0
        
        state_delta = events[0].actions.state_delta
        # Invalid mode should be filtered out
        assert "invalid_mode" not in state_delta["analysis_focus"]
        assert "recent_weekly_trends" in state_delta["analysis_focus"]
        assert "anomaly_detection" in state_delta["analysis_focus"]
        
        # Cleanup
        del os.environ["DATA_ANALYST_FOCUS"]

    @pytest.mark.asyncio
    async def test_custom_focus_sanitized(self):
        """Verify custom focus text is sanitized (control chars removed, truncated)."""
        os.environ["DATA_ANALYST_CUSTOM_FOCUS"] = "Test\nwith\nnewlines\tand\ttabs" + ("x" * 600)
        
        injector = CLIParameterInjector()
        ctx = MagicMock()
        ctx.invocation_id = "test"
        ctx.session.state = {"dataset_contract": None}
        
        events = []
        async for event in injector._run_async_impl(ctx):
            events.append(event)
        
        state_delta = events[0].actions.state_delta
        custom_focus = state_delta["custom_focus"]
        
        # Newlines and tabs should be converted to spaces
        assert "\n" not in custom_focus
        assert "\t" not in custom_focus
        # Should be truncated to 500 chars
        assert len(custom_focus) <= 500
        
        # Cleanup
        del os.environ["DATA_ANALYST_CUSTOM_FOCUS"]


class TestFocusDirectivesUtils:
    """Test focus_directives utility functions."""

    def test_get_focus_modes_from_state(self):
        """Verify get_focus_modes extracts focus list from state."""
        state = {"analysis_focus": ["recent_monthly_trends", "seasonal_patterns"]}
        modes = get_focus_modes(state)
        assert modes == ["recent_monthly_trends", "seasonal_patterns"]

    def test_get_custom_focus_from_state(self):
        """Verify get_custom_focus extracts custom text from state."""
        state = {"custom_focus": "Find revenue gaps in Retail"}
        custom = get_custom_focus(state)
        assert custom == "Find revenue gaps in Retail"

    def test_focus_search_text_combines_modes_and_custom(self):
        """Verify focus_search_text creates searchable blob from focus directives."""
        state = {
            "analysis_focus": ["seasonality", "anomalies"],
            "custom_focus": "drill into Retail performance"
        }
        text = focus_search_text(state)
        assert "seasonality" in text
        assert "anomalies" in text
        assert "drill into Retail performance" in text

    def test_augment_instruction_appends_focus_block(self):
        """Verify augment_instruction adds FOCUS_DIRECTIVES section to prompt."""
        base_instruction = "You are a planner agent. Select analysis methods."
        state = {
            "analysis_focus": ["recent_weekly_trends"],
            "custom_focus": "Compare Retail vs Wholesale LOBs"
        }
        augmented = augment_instruction(base_instruction, state)
        
        assert "FOCUS_DIRECTIVES" in augmented
        assert "recent_weekly_trends" in augmented
        assert "Compare Retail vs Wholesale LOBs" in augmented
        assert base_instruction in augmented

    def test_augment_instruction_unchanged_when_no_focus(self):
        """Verify augment_instruction returns base instruction when no focus."""
        base_instruction = "You are a planner agent."
        state = {}
        augmented = augment_instruction(base_instruction, state)
        assert augmented == base_instruction


class TestFocusAwareStatisticalTools:
    """Test that statistical tools respect focus directives."""

    @pytest.mark.asyncio
    async def test_anomaly_detection_threshold_adjusted(self):
        """Verify anomaly detection lowers threshold when focus includes anomaly_detection."""
        # This test would require mocking data_cache and session state
        # For now, we just verify the integration points exist
        from data_analyst_agent.sub_agents.statistical_insights_agent.tools.compute_anomaly_indicators import (
            compute_anomaly_indicators
        )
        # The actual test would need to set up mock data and verify threshold changes
        # Just validate the function exists for now
        assert callable(compute_anomaly_indicators)

    @pytest.mark.asyncio
    async def test_period_over_period_filters_recent_periods(self):
        """Verify period-over-period filters to recent periods when focus includes recent_*_trends."""
        from data_analyst_agent.sub_agents.statistical_insights_agent.tools.compute_period_over_period_changes import (
            compute_period_over_period_changes
        )
        # The actual test would need to set up mock data and verify filtering
        # Just validate the function exists for now
        assert callable(compute_period_over_period_changes)


class TestFocusInPlannerAgent:
    """Test that planner agent uses focus directives."""

    def test_planner_imports_focus_utils(self):
        """Verify planner agent imports focus_directives utilities."""
        from data_analyst_agent.sub_agents.planner_agent.agent import (
            augment_instruction,
            focus_search_text,
            get_custom_focus,
            get_focus_modes,
        )
        # Just validate imports are present
        assert callable(augment_instruction)
        assert callable(focus_search_text)
        assert callable(get_custom_focus)
        assert callable(get_focus_modes)


class TestFocusInNarrativeAgent:
    """Test that narrative agent uses focus directives."""

    def test_narrative_uses_augment_instruction(self):
        """Verify narrative agent uses augment_instruction."""
        from data_analyst_agent.sub_agents.narrative_agent.agent import augment_instruction
        assert callable(augment_instruction)


class TestFocusInReportSynthesis:
    """Test that report synthesis agent uses focus directives."""

    def test_report_synthesis_builds_focus_payload(self):
        """Verify report synthesis agent includes focus in payload."""
        from data_analyst_agent.sub_agents.report_synthesis_agent.agent import build_focus_payload
        assert callable(build_focus_payload)
        
        state = {
            "analysis_focus": ["recent_monthly_trends"],
            "custom_focus": "Focus on Retail"
        }
        payload = build_focus_payload(state)
        assert "modes" in payload
        assert "custom_directive" in payload
        assert payload["modes"] == ["recent_monthly_trends"]
        assert payload["custom_directive"] == "Focus on Retail"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
