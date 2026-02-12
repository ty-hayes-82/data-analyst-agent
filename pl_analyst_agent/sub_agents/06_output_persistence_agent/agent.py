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

Saves category and GL-level analysis insights to JSON files.

Output structure:
{
  "category": "revenue.accessorial_revenue",
  "cost_center": "497",
  "timeframe": {"start": "YYYY-MM", "end": "YYYY-MM"},
  "aggregate": {
    "severity": float,
    "summary": str,
    "alert_scoring": {...},
    "gl_totals": {...}
  },
  "gl_drilldowns": [
    {
      "gl_string": "...-3116-00",
      "total": float,
      "severity": float,
      "summary": str,
      "alert_scoring": {...}
    }
  ]
}
"""

from __future__ import annotations

import json
import importlib
from pathlib import Path
from typing import Any, AsyncGenerator, Literal

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions

# Import markdown generator using importlib to handle numbered module name
_markdown_module = importlib.import_module('pl_analyst_agent.sub_agents.04_report_synthesis_agent.tools.generate_markdown_report')
generate_markdown_report = _markdown_module.generate_markdown_report


class OutputPersistenceAgent(BaseAgent):
    """
    Persists analysis insights to per-category JSON files.
    
    Modes:
    - aggregate: Creates/updates category file with aggregate analysis
    - gl: Appends GL drilldown to existing category file
    """

    level: Literal["aggregate", "gl", "cost_center"]

    def __init__(self, level: Literal["aggregate", "gl", "cost_center"] = "aggregate") -> None:
        super().__init__(name="output_persistence_agent", level=level)

    def _get_output_path(self, category: str, cost_center: str) -> Path:
        """Generate output file path for category."""
        # Normalize category path for filename (replace dots with underscores)
        category_name = category.replace(".", "_")
        filename = f"category_{category_name}_cc{cost_center}.json"
        return Path("outputs") / filename

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
            return alert_summary
        
        return {"severity_score": 0.0}

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        session_state = ctx.session.state
        
        print(f"\n{'='*80}")
        print(f"[PERSIST] OutputPersistenceAgent STARTING (level={self.level})")
        print(f"{'='*80}")
        
        try:
            category = session_state.get("current_category")
            # Try both possible keys for cost center
            cost_center = session_state.get("current_cost_center") or session_state.get("cost_center")
            
            print(f"[PERSIST] State check: cost_center={cost_center}, category={category}")
            
            # Support cost-center-only analysis (no category)
            if self.level == "cost_center":
                if not cost_center:
                    print(f"[PERSIST] ERROR: Missing cost center, skipping")
                    print(f"[PERSIST] Available keys: {[k for k in session_state.keys() if 'cost' in k.lower() or 'center' in k.lower()]}")
                    yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=EventActions())
                    return
                # Use cost center as category for file naming
                category = cost_center
                # Use absolute path to ensure we write to the correct location
                output_dir = Path("outputs").resolve()
                output_dir.mkdir(parents=True, exist_ok=True)
                output_path = output_dir / f"cost_center_{cost_center}.json"
                print(f"[PERSIST] Output directory: {output_dir}")
                print(f"[PERSIST] Output path: {output_path}")
            else:
                if not category or not cost_center:
                    print(f"[PERSIST] Missing category or cost center, skipping")
                    yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=EventActions())
                    return
                output_path = self._get_output_path(category, cost_center)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            if self.level in ("aggregate", "cost_center"):
                # Create new file with aggregate analysis
                timeframe = session_state.get("timeframe", {})
                # Try both keys for synthesis result
                synthesis = session_state.get("synthesis_result") or session_state.get("report_synthesis_result", "No synthesis available")
                alert_summary = session_state.get("alert_scoring_result")
                gl_totals = session_state.get("category_aggregate_totals", {})
                
                # Get hierarchical analysis results (from data_analyst_agent)
                hierarchical_results = {}
                for level in [2, 3, 4, 5]:
                    level_key = f"level_{level}_analysis"
                    if level_key in session_state:
                        hierarchical_results[f"level_{level}"] = session_state[level_key]
                
                # Parse alert summary and extract severity
                alert_data = self._parse_alert_summary(alert_summary)
                severity = alert_data.get("severity_score", 0.0)
                
                data = {
                    "cost_center": cost_center,
                    "timeframe": timeframe,
                    "analysis": {
                        "severity": severity,
                        "summary": synthesis if isinstance(synthesis, str) else str(synthesis),
                        "alert_scoring": alert_data,
                        "gl_totals": gl_totals,
                    },
                    "hierarchical_analysis": hierarchical_results if hierarchical_results else None,
                }
                
                # Add category field if it exists (for category analysis)
                if self.level == "aggregate":
                    data["category"] = category
                    data["gl_drilldowns"] = []
                
                with output_path.open("w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                
                print(f"[PERSIST] [OK] Successfully saved JSON analysis to {output_path.name}")
                print(f"[PERSIST] File size: {output_path.stat().st_size} bytes")
                
                # Generate and save Markdown report for cost_center level
                if self.level == "cost_center":
                    try:
                        # First, try to use the already-generated synthesis result
                        # This is populated by TestModeReportSynthesisAgent or report_synthesis_agent
                        markdown_content = synthesis if isinstance(synthesis, str) and synthesis.startswith("#") else None

                        if not markdown_content and hierarchical_results:
                            # Fallback: generate markdown report from hierarchical data
                            analysis_period = f"{timeframe.get('start', 'N/A')} to {timeframe.get('end', 'N/A')}"
                            markdown_content = await generate_markdown_report(
                                hierarchical_results=json.dumps(hierarchical_results) if not isinstance(hierarchical_results, str) else hierarchical_results,
                                cost_center=cost_center,
                                analysis_period=analysis_period
                            )

                        if markdown_content:
                            # Save markdown file
                            markdown_path = output_path.with_suffix('.md')
                            markdown_path.write_text(markdown_content, encoding="utf-8")
                            print(f"[PERSIST] [OK] Saved Markdown report to {markdown_path.name}")
                        else:
                            print(f"[PERSIST] WARNING: No markdown content available, skipping Markdown generation")
                    except Exception as e:
                        print(f"[PERSIST] WARNING: Failed to generate Markdown report: {e}")
                        import traceback
                        traceback.print_exc()
            
            else:
                # Append GL drilldown to existing file
                if not output_path.exists():
                    print(f"[PERSIST] WARNING: Aggregate file not found, creating minimal structure")
                    data = {
                        "category": category,
                        "cost_center": cost_center,
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
        
        print(f"{'='*80}")
        print(f"[PERSIST] OutputPersistenceAgent COMPLETE")
        print(f"{'='*80}\n")
        
        actions = EventActions()
        yield Event(invocation_id=ctx.invocation_id, author=self.name, actions=actions)
