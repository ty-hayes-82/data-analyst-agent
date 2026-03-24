"""Re-run CrossMetricExecutiveBriefAgent against an existing CLI output folder.

Uses metric_*.json (and optional metric_*.md) in the run directory. Does not
re-fetch data or re-run per-metric analysis.

Example:
  python scripts/rerun_executive_brief_from_output.py ^
    --output-dir outputs/ops_metrics_ds/lob_ref/Line_Haul/20260323_154943
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from google.adk.agents.invocation_context import InvocationContext
from google.adk.agents.run_config import RunConfig
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.adk.sessions.session import Session

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.dataset_resolver import get_dataset_dir  # noqa: E402
from data_analyst_agent.semantic.models import DatasetContract  # noqa: E402
from data_analyst_agent.sub_agents.executive_brief_agent.agent import (  # noqa: E402
    CrossMetricExecutiveBriefAgent,
)


def _infer_dataset_name(output_dir: Path) -> str:
    parts = output_dir.resolve().parts
    if "outputs" in parts:
        i = parts.index("outputs")
        if i + 1 < len(parts):
            return parts[i + 1]
    return os.environ.get("ACTIVE_DATASET", "ops_metrics_ds")


def _load_cache_meta(output_dir: Path) -> dict:
    # Priority 1: meta/ subfolder
    # Priority 2: root
    meta_dir = output_dir / "meta"
    search_paths = [meta_dir / "executive_brief_input_cache.json", output_dir / "executive_brief_input_cache.json"]
    
    for p in search_paths:
        if p.is_file():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
    return {}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="Run folder containing metric_*.json (e.g. outputs/.../20260323_154943)",
    )
    p.add_argument(
        "--dataset",
        default=None,
        help="Dataset name for contract.yaml (default: infer from outputs/<name>/...)",
    )
    p.add_argument(
        "--standard-brief",
        action="store_true",
        help="Use standard brief style instead of CEO hybrid",
    )
    p.add_argument(
        "--max-scoped-briefs",
        type=int,
        default=None,
        help="Override EXECUTIVE_BRIEF_MAX_SCOPED_BRIEFS for this run",
    )
    p.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print effective EXECUTIVE_BRIEF_MAX_SCOPED_BRIEFS (from env or code default)",
    )
    return p.parse_args()


async def _main_async() -> int:
    args = parse_args()
    load_dotenv(PROJECT_ROOT / ".env")

    out = args.output_dir.resolve()
    if not out.is_dir():
        print(f"ERROR: not a directory: {out}", file=sys.stderr)
        return 1
    
    # Check both layouts for metrics
    if not any(out.glob("metric_*.json")) and not any((out / "metrics").glob("metric_*.json")):
        print(f"ERROR: no metric_*.json under {out} or {out}/metrics/", file=sys.stderr)
        return 1

    dataset = args.dataset or _infer_dataset_name(out)
    contract_path = get_dataset_dir(dataset) / "contract.yaml"
    if not contract_path.is_file():
        print(f"ERROR: missing contract: {contract_path}", file=sys.stderr)
        return 1

    contract = DatasetContract.from_yaml(str(contract_path))
    cache = _load_cache_meta(out)

    os.environ["DATA_ANALYST_OUTPUT_DIR"] = str(out)
    os.environ["ACTIVE_DATASET"] = dataset
    if args.standard_brief:
        os.environ["EXECUTIVE_BRIEF_STYLE"] = "default"
    else:
        os.environ.setdefault("EXECUTIVE_BRIEF_STYLE", "ceo")
    if args.max_scoped_briefs is not None:
        os.environ["EXECUTIVE_BRIEF_MAX_SCOPED_BRIEFS"] = str(args.max_scoped_briefs)

    timeframe = cache.get("timeframe") if isinstance(cache.get("timeframe"), dict) else {}
    if not timeframe.get("end"):
        timeframe["end"] = cache.get("period_end") or "2026-03-14"

    session_state: dict = {
        "dataset_contract": contract,
        "dataset": dataset,
        "timeframe": timeframe,
        "analysis_period": cache.get("analysis_period"),
        "primary_query_end_date": timeframe.get("end"),
        "weather_context": cache.get("weather_context"),
    }
    if cache.get("metric_names"):
        session_state["extracted_targets"] = list(cache["metric_names"])

    agent = CrossMetricExecutiveBriefAgent()
    session = Session(
        id="rerun-brief",
        app_name="data_analyst_agent",
        user_id="cli_rerun",
        state=session_state,
        events=[],
    )
    ctx = InvocationContext(
        agent=agent,
        invocation_id="rerun-exec-brief",
        session=session,
        session_service=InMemorySessionService(),
        run_config=RunConfig(),
    )

    print(f"Dataset contract: {contract.name}")
    print(f"Output dir: {out}")
    if args.max_scoped_briefs is not None:
        print(f"Scoped brief cap: {args.max_scoped_briefs} (--max-scoped-briefs)")
    elif args.verbose:
        cap = os.environ.get("EXECUTIVE_BRIEF_MAX_SCOPED_BRIEFS", "(code default)")
        print(f"EXECUTIVE_BRIEF_MAX_SCOPED_BRIEFS={cap}")

    async for _ in agent._run_async_impl(ctx):
        pass

    # Result paths (check deliverables/ then root)
    deliverables = out / "deliverables"
    search_dirs = [deliverables, out] if deliverables.exists() else [out]
    
    brief_md = None
    scoped = []
    
    for s_dir in search_dirs:
        if not brief_md:
            p = s_dir / "brief.md"
            if p.is_file():
                brief_md = p
        
        for p in sorted(s_dir.glob("brief_*.md")):
            if p.name not in [f.name for f in scoped]:
                scoped.append(p)

    network_ok = brief_md is not None
    print("\n--- Result ---")
    print(f"brief.md: {'ok' if network_ok else 'MISSING'}")
    for p in scoped:
        print(f"  {p.name}")
    expected = {"brief_East.md", "brief_Central.md", "brief_West.md"}
    found = {p.name for p in scoped}
    if not expected.issubset(found):
        print(
            f"WARNING: expected regional files {sorted(expected)}; got {sorted(found)}",
            file=sys.stderr,
        )
        return 2
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_main_async()))


if __name__ == "__main__":
    main()
