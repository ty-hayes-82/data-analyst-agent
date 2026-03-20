#!/usr/bin/env python3
"""Helper to run the Data Analyst Agent with LLM calls stubbed out.

This lets us generate deterministic outputs (Markdown + JSON) for QA checks
without needing live Gemini access. It mirrors the CLI environment that
`python -m data_analyst_agent` would set up, but swaps the LLM-powered agents
(planner, narrative, report synthesis) with code stubs so the pipeline can run
end-to-end offline.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from google.adk.agents.llm_agent import Agent as LlmAgent  # type: ignore
from google.adk.events.event import Event  # type: ignore
from google.adk.events.event_actions import EventActions  # type: ignore
from google.genai.models import Models  # type: ignore
from google.genai.types import Candidate, Content, GenerateContentResponse, Part  # type: ignore

from config.dataset_resolver import get_dataset_dir
from data_analyst_agent.semantic.models import DatasetContract


def _humanize_metric_name(name: str) -> str:
    return name.replace('_', ' ').replace('-', ' ').strip() or name


def build_stub_context(dataset: str, metrics: list[str]) -> dict[str, str]:
    metric_names = [ _humanize_metric_name(m) for m in metrics ] or ["key metrics"]
    metric_label = ", ".join(metric_names)
    metric_label_lower = metric_label.lower()
    dataset_label = dataset.replace('_', ' ').title() or dataset
    domain_label = "Network"
    try:
        dataset_dir = get_dataset_dir(dataset)
        contract_path = dataset_dir / "contract.yaml"
        if contract_path.exists():
            contract = DatasetContract.from_yaml(str(contract_path))
            dataset_label = getattr(contract, "display_name", getattr(contract, "name", dataset_label)) or dataset_label
            dimensions = getattr(contract, "dimensions", None) or []
            primary = next((d for d in dimensions if getattr(d, 'role', '').lower() == 'primary'), None)
            if primary and getattr(primary, 'name', None):
                domain_label = primary.name
    except Exception:
        pass
    return {
        "dataset_label": dataset_label,
        "domain_label": domain_label,
        "domain_title": domain_label.title(),
        "domain_lower": domain_label.lower(),
        "metric_label": metric_label,
        "metric_label_lower": metric_label_lower,
    }


def install_llm_stub(stub_context: dict[str, str] | None = None) -> None:
    context = stub_context or {}
    dataset_label = context.get("dataset_label", "the dataset")
    domain_title = context.get("domain_title", "Network")
    domain_lower = context.get("domain_lower", "network")
    metric_label = context.get("metric_label", "key metrics")
    metric_label_lower = context.get("metric_label_lower", metric_label.lower())
    summary_line = (
        f"{domain_title}-level performance for {metric_label} remained stable across {dataset_label}; "
        "focus on localized movements rather than aggregate totals."
    )
    driver_line = (
        f"- {domain_title} drill-down confirms one {domain_lower} driving most of the {metric_label_lower} variance."
    )
    anomaly_line = f"- Review detected {metric_label_lower} spikes for data integrity before publishing."
    action_items = [
        f"Coordinate with {domain_lower} owners on {metric_label_lower} reconciliation.",
        f"Audit reporting lags before the next cycle to protect {metric_label_lower} accuracy.",
    ]
    actions_block = "\n".join(f"{idx}. {item}" for idx, item in enumerate(action_items, 1))
    markdown_text = (
        "# Executive Brief\n\n"
        "## Executive Summary\n"
        f"{summary_line}\n\n"
        "## Variance Drivers\n"
        f"{driver_line}\n\n"
        "## Anomalies\n"
        f"{anomaly_line}\n\n"
        "## Recommended Actions\n"
        f"{actions_block}\n"
    )

    async def _stub_run_async(self: LlmAgent, ctx):  # type: ignore[override]
        name = getattr(self, "name", "") or "llm_stub"
        output_key = getattr(self, "output_key", None) or "output"

        if "planner" in name:
            payload = {
                "selected_agents": [
                    {"name": "hierarchical_analysis_agent"},
                    {"name": "statistical_insights_agent"},
                    {"name": "alert_scoring_coordinator"},
                ]
            }
            state_delta = {"execution_plan": json.dumps(payload)}
        elif "narrative" in name:
            payload = {
                "narrative_summary": summary_line,
                "insight_cards": [
                    {
                        "title": f"{domain_title} hotspot",
                        "what_changed": f"One {domain_lower} drove most of the {metric_label_lower} variance",
                        "why": f"Concentrated {metric_label_lower} spike",
                        "priority": "high",
                    }
                ],
                "recommended_actions": action_items,
            }
            state_delta = {output_key: json.dumps(payload)}
        elif "report_synthesis" in name or "report" in name:
            state_delta = {output_key: markdown_text, "report_markdown": markdown_text}
        else:
            state_delta = {output_key: json.dumps({"stub": True, "agent": name})}

        yield Event(invocation_id=ctx.invocation_id, author=name, actions=EventActions(state_delta=state_delta))

    def _stub_generate_content(self: Models, *, model: str, contents, config=None):  # type: ignore[override]
        return GenerateContentResponse(candidates=[Candidate(content=Content(role="model", parts=[Part(text=markdown_text)]))])

    setattr(LlmAgent, "run_async", _stub_run_async)
    setattr(Models, "generate_content", _stub_generate_content)


def configure_environment(args) -> Path:
    os.environ.setdefault("DATA_ANALYST_ALLOW_STUB_OUTPUTS", "true")
    os.environ["ACTIVE_DATASET"] = args.dataset
    os.environ["DATA_ANALYST_METRICS"] = ",".join(args.metrics)
    if args.dimension:
        os.environ["DATA_ANALYST_DIMENSION"] = args.dimension
    if args.dimension_value:
        os.environ["DATA_ANALYST_DIMENSION_VALUE"] = args.dimension_value
    if args.focus:
        os.environ["DATA_ANALYST_FOCUS"] = args.focus
    if args.hierarchy:
        os.environ["DATA_ANALYST_HIERARCHY"] = args.hierarchy
    if args.hierarchy_levels:
        os.environ["DATA_ANALYST_HIERARCHY_LEVELS"] = args.hierarchy_levels
    if args.start_date:
        os.environ["DATA_ANALYST_START_DATE"] = args.start_date
    if args.end_date:
        os.environ["DATA_ANALYST_END_DATE"] = args.end_date
    if args.max_drill_depth:
        os.environ["DATA_ANALYST_MAX_DRILL_DEPTH"] = str(args.max_drill_depth)

    from data_analyst_agent.utils.output_manager import OutputManager

    output_manager = OutputManager(
        dataset=args.dataset,
        dimension=args.dimension,
        dimension_value=args.dimension_value,
    )
    os.environ["DATA_ANALYST_RUN_ID"] = output_manager.run_id
    os.environ["DATA_ANALYST_OUTPUT_DIR"] = str(output_manager.run_dir)

    output_manager.create_run_directory()
    metadata = {
        "dataset": args.dataset,
        "metrics": args.metrics,
        "dimension": args.dimension,
        "dimension_value": args.dimension_value,
        "focus": args.focus,
        "start_date": args.start_date,
        "end_date": args.end_date,
        "max_drill_depth": args.max_drill_depth,
        "stubbed_llm": True,
    }
    output_manager.save_run_metadata(metadata)
    return output_manager.run_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Data Analyst Agent with stubbed LLM components.")
    parser.add_argument("dataset")
    parser.add_argument("metrics", nargs="+")
    parser.add_argument("--dimension")
    parser.add_argument("--dimension-value")
    parser.add_argument("--focus", default="")
    parser.add_argument("--hierarchy", default="")
    parser.add_argument("--hierarchy-levels", default="")
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--query", default="")
    parser.add_argument("--max-drill-depth", type=int, default=0)
    args = parser.parse_args()

    stub_context = build_stub_context(args.dataset, args.metrics)
    install_llm_stub(stub_context)
    run_dir = configure_environment(args)

    query = args.query or f"Analyze {'/'.join(args.metrics)}"

    from data_analyst_agent.agent import run_analysis

    asyncio.run(run_analysis(query))
    print(run_dir)


if __name__ == "__main__":
    main()
