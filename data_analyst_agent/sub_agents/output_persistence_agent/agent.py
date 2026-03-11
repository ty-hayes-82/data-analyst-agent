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

"""
Output Persistence Agent

Saves analysis insights to JSON and Markdown files.
Supports dimension-value-level, aggregate, and drill-down persistence modes.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, AsyncGenerator, Literal

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions

from ..report_synthesis_agent.tools.generate_markdown_report import generate_markdown_report
from ...utils.stub_guard import contains_stub_content, stub_outputs_allowed


def _timeframe_label(timeframe: dict[str, Any] | None) -> str:
    timeframe = timeframe or {}
    start = timeframe.get("start")
    end = timeframe.get("end")
    if start and end:
        return start if start == end else f"{start} to {end}"
    return start or end or "current period"


def _analysis_period_label(session_state: dict[str, Any]) -> str:
    return session_state.get("analysis_period") or _timeframe_label(session_state.get("timeframe"))


def _extract_summary_from_markdown(markdown: str | None) -> str:
    if not markdown:
        return "No synthesis available"
    lines = [line.strip() for line in markdown.splitlines() if line.strip()]
    for line in lines:
        if line.startswith("#"):
            continue
        if line.startswith("**Generated") or line.startswith("**Period"):
            continue
        return line
    return lines[0] if lines else "No synthesis available"


def _should_drop_stub(value: Any) -> bool:
    return contains_stub_content(value) and not stub_outputs_allowed()


class OutputPersistenceAgent(BaseAgent):
    """
    Persists analysis insights to per-category JSON files.
    
    Modes:
    - aggregate: Creates/updates category file with aggregate analysis
    - gl: Appends GL drilldown to existing category file
    """

    level: Literal["aggregate", "gl", "dimension_value"]

    def __init__(self, level: Literal["aggregate", "gl", "dimension_value"] = "aggregate") -> None:
        super().__init__(name="output_persistence_agent", level=level)

    def _get_output_path(self, category: str, analysis_target: str) -> Path:
        """Generate output file path for category."""
        # Use run-specific directory if available
        run_dir = os.getenv("DATA_ANALYST_OUTPUT_DIR")
        
        category_name = category.replace(".", "_") if category else "all"
        safe_target = str(analysis_target).replace("/", "-").replace("\\", "-").replace(":", "-").replace(" ", "_")
        
        if run_dir:
            base_path = Path(run_dir)
            # Include target name to avoid collisions in parallel runs
            filename = f"category_{category_name}_{safe_target}.json"
            return base_path / filename
        
        # Fallback to legacy behavior
        filename = f"category_{category_name}_{safe_target}.json"
        return Path("outputs") / filename

    async def _generate_metric_markdown(
        self,
        session_state: dict[str, Any],
        hierarchical_results: Any,
        analysis_target: str,
        target_label: str,
    ) -> str:
        analysis_period = _analysis_period_label(session_state)
        narrative_raw = session_state.get("narrative_results") or session_state.get("narrative_result", "")
        stats_raw = session_state.get("statistical_summary", "")
        anomaly_raw = session_state.get("alert_scoring_result", "")
        dataset = session_state.get("dataset_contract")
        dataset_display_name = getattr(dataset, "display_name", None) or getattr(dataset, "name", None)
        dataset_description = getattr(dataset, "description", "") if dataset else ""
        if not isinstance(hierarchical_results, str):
            try:
                hierarchical_payload = json.dumps(hierarchical_results or {})
            except (TypeError, ValueError):
                hierarchical_payload = "{}"
        else:
            hierarchical_payload = hierarchical_results or "{}"
        return await generate_markdown_report(
            hierarchical_results=hierarchical_payload,
            analysis_target=analysis_target,
            analysis_period=analysis_period,
            statistical_summary=stats_raw,
            narrative_results=narrative_raw,
            target_label=target_label,
            anomaly_indicators=anomaly_raw,
            seasonal_decomposition=session_state.get("seasonal_decomposition"),
            dataset_display_name=dataset_display_name,
            dataset_description=dataset_description,
        )

    def _parse_alert_summary(self, alert_summary: Any) -> dict[str, Any]:
        """Parse alert scoring result into structured format."""
        if not alert_summary:
            return {"severity_score": 0.0, "priority": "none"}
        
        if isinstance(alert_summary, str):
            try:
                alert_summary = json.loads(alert_summary)
            except (json.JSONDecodeError, ValueError):
                return {"severity_score": 0.0, "raw": alert_summary}
        
        if isinstance(alert_summary, dict):
            # Filter out unknown/zero-impact noise (Spec 039 cleanup)
            return self._filter_invalid_alerts(alert_summary)
        
        return {"severity_score": 0.0}

    def _filter_invalid_alerts(self, alert_summary: dict[str, Any]) -> dict[str, Any]:
        """Filter out unknown or zero-impact alerts from the summary."""
        def _is_valid(alert: dict) -> bool:
            if not isinstance(alert, dict): return False
            aid = str(alert.get("id", "")).lower()
            # If it's an 'unknown' placeholder alert, only keep if it has actual impact
            if "unknown" in aid:
                score = float(alert.get("score") or 0)
                impact = float(alert.get("impact") or 0)
                var_amt = float(alert.get("variance_amount") or 0)
                if score == 0 and impact == 0 and var_amt == 0:
                    return False
            return True

        if "top_alerts" in alert_summary:
            alert_summary["top_alerts"] = [a for a in alert_summary["top_alerts"] if _is_valid(a)]
        if "all_scored_alerts" in alert_summary:
            alert_summary["all_scored_alerts"] = [a for a in alert_summary["all_scored_alerts"] if _is_valid(a)]
            
        return alert_summary

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        session_state = ctx.session.state
        
        print(f"\n{'='*80}")
        print(f"[PERSIST] OutputPersistenceAgent STARTING (level={self.level})")
        print(f"{'='*80}")
        
        try:
            category = session_state.get("current_category")
            # Get analysis target from state
            analysis_target = (
                session_state.get("current_analysis_target")
                or session_state.get("dimension_value")
            )
            
            # Retrieve target_label from the contract so file names are dataset-aware
            contract = session_state.get("dataset_contract")
            target_label = getattr(contract, "target_label", "analysis_target") if contract else "analysis_target"
            # Sanitise for use in file names (lower-case, spaces to underscore)
            target_slug = target_label.lower().replace(" ", "_")

            print(f"[PERSIST] State check: analysis_target={analysis_target}, category={category}, target_label={target_label}")

            # Support analysis-target-only runs (no category)
            if self.level == "dimension_value":
                if not analysis_target:
                    print(f"[PERSIST] ERROR: Missing analysis target, skipping")
                    print(f"[PERSIST] Available keys: {[k for k in session_state.keys() if 'target' in k.lower() or 'cost' in k.lower()]}")
                    yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=EventActions())
                    return
                # Use analysis target as the file category
                category = analysis_target
                
                # Use run-specific directory if available
                run_dir = os.getenv("DATA_ANALYST_OUTPUT_DIR")
                
                # Sanitize analysis_target for use as a filename (replace path separators and spaces)
                safe_target_name = (
                    str(analysis_target)
                    .replace("/", "-")
                    .replace("\\", "-")
                    .replace(":", "-")
                    .replace(" ", "_")
                )
                
                if run_dir:
                    output_dir = Path(run_dir).resolve()
                    # Use metric_ prefix to match executive brief glob, even in standardized run-dir
                    # to prevent collisions when multiple metrics run in parallel.
                    output_path = output_dir / f"metric_{safe_target_name}.json"
                else:
                    output_dir = Path("outputs").resolve()
                    output_dir.mkdir(parents=True, exist_ok=True)
                    output_path = output_dir / f"{target_slug}_{safe_target_name}.json"
                
                print(f"[PERSIST] Output directory: {output_dir}")
                print(f"[PERSIST] Output path: {output_path}")
            else:
                if not category or not analysis_target:
                    print(f"[PERSIST] Missing category or analysis target, skipping")
                    yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=EventActions())
                    return
                output_path = self._get_output_path(category, analysis_target)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            if self.level in ("aggregate", "dimension_value"):
                # Create new file with aggregate analysis
                timeframe = session_state.get("timeframe", {})
                
                # Retrieve narrative and synthesis results for summary
                narrative_raw = session_state.get("narrative_results") or session_state.get("narrative_result")
                narrative_data = None
                if narrative_raw:
                    if isinstance(narrative_raw, str):
                        try:
                            narrative_data = json.loads(narrative_raw)
                        except (json.JSONDecodeError, ValueError):
                            narrative_data = {"narrative_summary": narrative_raw}
                    elif isinstance(narrative_raw, dict):
                        narrative_data = narrative_raw

                # Determine executive summary fallback using precedence:
                # 1. synthesis_result (usually from report_synthesis_agent)
                # 2. report_synthesis_result (fallback key)
                # 3. narrative_results.narrative_summary (from narrative_agent)
                # 4. Deterministic fallback
                summary_source = session_state.get("synthesis_result")
                if not summary_source or summary_source == "No synthesis available":
                    summary_source = session_state.get("report_synthesis_result")
                if _should_drop_stub(summary_source):
                    summary_source = None
                if not summary_source or summary_source == "No synthesis available":
                    if narrative_data and narrative_data.get("narrative_summary"):
                        summary_source = narrative_data.get("narrative_summary")
                analysis_summary = str(summary_source or "No synthesis available")

                alert_summary = session_state.get("alert_scoring_result")
                gl_totals = session_state.get("category_aggregate_totals", {})
                
                # Get hierarchical analysis results (from data_analyst_agent)
                # First try the consolidated data_analyst_result which is more robustly propagated
                da_result_raw = session_state.get("data_analyst_result")
                da_result = {}
                if da_result_raw:
                    from ...utils.json_utils import safe_parse_json
                    da_result = safe_parse_json(da_result_raw) if isinstance(da_result_raw, str) else da_result_raw
                
                hierarchical_results = da_result.get("level_results", {})
                
                # Fallback: check session state directly for level-specific keys
                if not hierarchical_results:
                    print(f"[PERSIST] Checking for hierarchical results in session state. keys: {[k for k in session_state.keys() if 'level_' in k]}")
                    for level in [0, 1, 2, 3, 4, 5]:
                        level_key = f"level_{level}_analysis"
                        if level_key in session_state:
                            lvl_val = session_state[level_key]
                            from ...utils.json_utils import safe_parse_json
                            hierarchical_results[f"level_{level}"] = safe_parse_json(lvl_val) if isinstance(lvl_val, str) else lvl_val
                
                # Parse alert summary and extract severity
                alert_data = self._parse_alert_summary(alert_summary)
                severity = alert_data.get("severity_score", 0.0)

                # Persist narrative_results and statistical_summary for executive brief (Spec 029)
                narrative_raw = session_state.get("narrative_results") or session_state.get("narrative_result", "")
                narrative_data = None
                if narrative_raw:
                    if isinstance(narrative_raw, str):
                        try:
                            narrative_data = json.loads(narrative_raw)
                        except (json.JSONDecodeError, ValueError):
                            narrative_data = {"raw": narrative_raw}
                    elif isinstance(narrative_raw, dict):
                        narrative_data = narrative_raw

                stats_raw = session_state.get("statistical_summary", "")
                statistical_summary = None
                if stats_raw:
                    if isinstance(stats_raw, str):
                        try:
                            parsed = json.loads(stats_raw)
                            statistical_summary = {
                                "summary_stats": parsed.get("summary_stats", {}),
                                "top_drivers": parsed.get("top_drivers", [])[:10],
                                "anomalies": parsed.get("anomalies", [])[:15],
                            }
                        except (json.JSONDecodeError, ValueError):
                            statistical_summary = {"raw": stats_raw[:2000]}
                    elif isinstance(stats_raw, dict):
                        statistical_summary = {
                            "summary_stats": stats_raw.get("summary_stats", {}),
                            "top_drivers": stats_raw.get("top_drivers", [])[:10],
                            "anomalies": stats_raw.get("anomalies", [])[:15],
                        }

                data = {
                    "dimension_value": analysis_target,
                    "timeframe": timeframe,
                    "temporal_grain": session_state.get("temporal_grain"),
                    "temporal_grain_confidence": session_state.get("temporal_grain_confidence"),
                    "analysis": {
                        "severity": severity,
                        "summary": analysis_summary,
                        "alert_scoring": alert_data,
                        "gl_totals": gl_totals,
                    },
                    "hierarchical_analysis": hierarchical_results if hierarchical_results else None,
                    "narrative_results": narrative_data,
                    "statistical_summary": statistical_summary,
                }
                
                # Add category field if it exists (for category analysis)
                if self.level == "aggregate":
                    data["category"] = category
                    data["gl_drilldowns"] = []
                
                # Generate and save Markdown report for analysis_target level
                if self.level == "dimension_value":
                    try:
                        markdown_content = await self._generate_metric_markdown(
                            session_state=session_state,
                            hierarchical_results=hierarchical_results,
                            analysis_target=analysis_target,
                            target_label=target_label,
                        )
                        if markdown_content and not markdown_content.lstrip().startswith("# Error"):
                            summary_override = _extract_summary_from_markdown(markdown_content)
                            if summary_override:
                                data["analysis"]["summary"] = summary_override
                        if markdown_content:
                            markdown_path = output_path.with_suffix('.md')
                            markdown_path.write_text(markdown_content, encoding="utf-8")
                            print(f"[PERSIST] [OK] Saved Markdown report to {markdown_path.name}")
                        else:
                            print("[PERSIST] WARNING: No markdown content available, skipping Markdown generation")
                    except Exception as e:
                        print(f"[PERSIST] WARNING: Failed to generate Markdown report: {e}")
                        import traceback
                        traceback.print_exc()
                
                with output_path.open("w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                print(f"[PERSIST] [OK] Successfully saved JSON analysis to {output_path.name}")
                print(f"[PERSIST] File size: {output_path.stat().st_size} bytes")
            
            else:
                # Append GL drilldown to existing file
                if not output_path.exists():
                    print(f"[PERSIST] WARNING: Aggregate file not found, creating minimal structure")
                    data = {
                        "category": category,
                        "dimension_value": analysis_target,
                        "timeframe": session_state.get("timeframe", {}),
                        "aggregate": {},
                        "gl_drilldowns": []
                    }
                else:
                    with output_path.open("r", encoding="utf-8") as f:
                        data = json.load(f)
                
                # Extract GL drilldown data
                gl_string = session_state.get("current_gl_string")
                gl_total = session_state.get("current_gl_total", 0.0)
                synthesis = session_state.get("synthesis_result", "No synthesis available")
                if _should_drop_stub(synthesis):
                    synthesis = "No synthesis available"
                alert_summary = session_state.get("alert_scoring_result")
                
                if not gl_string:
                    print(f"[PERSIST] WARNING: No GL string found, skipping GL persistence")
                    yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=EventActions())
                    return
                
                alert_data = self._parse_alert_summary(alert_summary)
                severity = alert_data.get("severity_score", 0.0)
                
                gl_entry = {
                    "gl_string": gl_string,
                    "total": gl_total,
                    "severity": severity,
                    "summary": synthesis if isinstance(synthesis, str) else str(synthesis),
                    "alert_scoring": alert_data,
                }
                
                data["gl_drilldowns"].append(gl_entry)
                
                with output_path.open("w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                
                print(f"[PERSIST] [OK] Appended GL drilldown to {output_path.name} ({len(data['gl_drilldowns'])} total)")
        
        except Exception as e:
            print(f"[PERSIST] ERROR: Failed to persist output: {e}")
            import traceback
            traceback.print_exc()
            # Still yield event to continue workflow
            yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=EventActions())
            return
        
        # Save phase logger summary if available
        phase_logger = session_state.get("phase_logger")
        if phase_logger and hasattr(phase_logger, "save_phase_summary"):
            try:
                # Use DATA_ANALYST_OUTPUT_DIR if available for summary location
                summary_dir = None
                run_dir = os.getenv("DATA_ANALYST_OUTPUT_DIR")
                if run_dir:
                    summary_dir = Path(run_dir) / "logs"
                
                phase_logger.save_phase_summary(output_dir=summary_dir)
            except Exception as logger_err:
                print(f"[PERSIST] WARNING: Failed to save phase summary: {logger_err}")

        print(f"{'='*80}")
        print(f"[PERSIST] OutputPersistenceAgent COMPLETE")
        print(f"{'='*80}\n")
        
        actions = EventActions()
        yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=actions)
