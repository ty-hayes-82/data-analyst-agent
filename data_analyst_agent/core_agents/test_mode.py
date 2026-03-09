"""Test-mode validation and report synthesis helpers."""

from __future__ import annotations

from io import StringIO
from typing import AsyncGenerator

import pandas as pd

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.genai.types import Content, Part

from ..utils.json_utils import safe_parse_json


class TestModeValidationAgent(BaseAgent):
    """Validates cached CSV data during TEST_MODE runs."""

    def __init__(self):
        super().__init__(name="test_mode_validation_agent")

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        pl_data_csv = ctx.session.state.get("primary_data_csv", "")
        if not pl_data_csv:
            yield Event(
                invocation_id=ctx.invocation_id,
                author=self.name,
                content=Content(
                    role="model",
                    parts=[Part(text='{"status": "fatal_no_data", "error": "No data in session state"}')],
                ),
            )
            return

        df = pd.read_csv(StringIO(pl_data_csv))
        contract = ctx.session.state.get("dataset_contract")
        if contract:
            from ..semantic.policies import PolicyEngine

            engine = PolicyEngine(contract)
            df = engine.apply_sign_correction(df)
        updated_csv = df.to_csv(index=False)
        from ..sub_agents.data_cache import set_validated_csv

        set_validated_csv(updated_csv)
        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            content=Content(
                role="model",
                parts=[Part(text=f"Data validation complete. {len(df)} records validated using contract policies.")],
            ),
            actions=EventActions(state_delta={"validated_pl_data_csv": updated_csv}),
        )


class TestModeReportSynthesisAgent(BaseAgent):
    """Generates markdown reports from cached hierarchy results in TEST_MODE."""

    def __init__(self):
        super().__init__(name="test_mode_report_synthesis_agent")

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        import json
        from datetime import datetime

        analysis_target = ctx.session.state.get("current_analysis_target", "Unknown")
        timeframe = ctx.session.state.get("timeframe", {})
        period_str = f"{timeframe.get('start', 'N/A')} to {timeframe.get('end', 'N/A')}"

        level_analyses = {}
        levels_analyzed = []
        da_result_raw = ctx.session.state.get("data_analyst_result")
        da_result = safe_parse_json(da_result_raw) if da_result_raw else {}
        level_results_from_da = da_result.get("level_results", {})

        for level in range(6):
            level_key = f"level_{level}_analysis"
            level_data = ctx.session.state.get(level_key) or level_results_from_da.get(level_key)
            if not level_data:
                continue
            try:
                parsed = safe_parse_json(level_data)
            except (json.JSONDecodeError, TypeError) as exc:
                print(f"[TEST_REPORT_SYNTHESIS] Warning: could not parse level {level}: {exc}")
                continue
            top_drivers = parsed.get("top_drivers") or parsed.get("top_items") or []
            insight_cards = parsed.get("insight_cards", [])
            level_analyses[f"level_{level}"] = {
                "top_drivers": top_drivers,
                "insight_cards": insight_cards,
                "total_variance_dollar": parsed.get("total_variance_dollar", 0),
                "variance_explained_pct": parsed.get("variance_explained_pct", 0),
                "items_aggregated": len(top_drivers) if top_drivers else len(insight_cards),
                "top_drivers_identified": len(top_drivers) if top_drivers else len(insight_cards),
            }
            levels_analyzed.append(level)

        drill_down_path = " -> ".join([f"Level {l}" for l in sorted(levels_analyzed)]) if levels_analyzed else "N/A"
        hierarchical_results = {
            "levels_analyzed": sorted(levels_analyzed),
            "level_analyses": level_analyses,
            "drill_down_path": drill_down_path,
        }

        from ..sub_agents.report_synthesis_agent.tools.generate_markdown_report import generate_markdown_report

        try:
            markdown_report = await generate_markdown_report(
                hierarchical_results=json.dumps(hierarchical_results),
                analysis_target=analysis_target,
                analysis_period=period_str,
            )
        except ImportError:
            markdown_report = self._generate_basic_report(hierarchical_results, analysis_target, period_str)

        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            content=Content(role="model", parts=[Part(text=markdown_report)]),
            actions=EventActions(
                state_delta={
                    "report_synthesis_result": markdown_report,
                    "hierarchical_results": hierarchical_results,
                }
            ),
        )

    def _generate_basic_report(self, results: dict, analysis_target: str, period: str) -> str:
        from datetime import datetime

        md: list[str] = []
        md.append(f"# Analysis Report - {analysis_target}")
        md.append(f"**Generated:** {datetime.now():%Y-%m-%d %H:%M:%S}")
        md.append(f"**Period:** {period}")
        md.append("")

        levels_analyzed = results.get("levels_analyzed", [])
        level_analyses = results.get("level_analyses", {})
        drill_down_path = results.get("drill_down_path", "N/A")

        md.append("## Executive Summary")
        md.append("")
        md.append(f"- **Analysis Depth:** {drill_down_path}")
        md.append(f"- **Levels Analyzed:** {len(levels_analyzed)}")
        md.append("")

        md.append("## Variance Drivers")
        md.append("")
        all_drivers = []
        for level_data in level_analyses.values():
            all_drivers.extend(level_data.get("top_drivers", []))

        if all_drivers:
            md.append("| Rank | Category | Variance $ | Variance % | Materiality |")
            md.append("|------|----------|------------|------------|-------------|")
            for i, driver in enumerate(all_drivers[:10], 1):
                item = driver.get("item", "Unknown")
                var_dollar = driver.get("variance_dollar", 0)
                var_pct = driver.get("variance_pct", 0)
                materiality = driver.get("materiality", "LOW")
                md.append(f"| {i} | {item} | ${var_dollar:+,.0f} | {var_pct:+.1f}% | {materiality} |")
        else:
            md.append("*No variance drivers identified*")

        md.append("")
        md.append("## Recommended Actions")
        md.append("")
        actions = []
        for driver in all_drivers:
            if driver.get("materiality") == "HIGH":
                name = driver.get("item", "Unknown")
                var_dollar = driver.get("variance_dollar", 0)
                verb = "increase" if var_dollar > 0 else "decrease"
                actions.append(f"Investigate {verb} in {name} ({var_dollar:+,.0f})")
        if actions:
            for i, action in enumerate(actions[:5], 1):
                md.append(f"{i}. {action}")
        else:
            md.append("1. No high-materiality variances requiring immediate action")
            md.append("2. Continue monitoring trends for emerging patterns")

        md.append("")
        md.append("---")
        md.append("*This report was auto-generated by Data Analyst Agent*")
        return "\n".join(md)
