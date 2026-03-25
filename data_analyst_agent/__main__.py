"""Entry point for ``python -m data_analyst_agent``.

Supports two invocation modes:

  CLI parameter mode:
    python -m data_analyst_agent --dataset trade_data \\
        --metrics "Truck Count,Rev/Trk/Wk" --dimension region \\
        --dimension-value Central

  Interactive mode (guided terminal menus):
    python -m data_analyst_agent --interactive

Pre-processes --model-config before importing the agent module so that
model_loader.py reads the override path during module-level agent construction.
"""

import os
import sys

# Track file dependencies for cleanup investigation
import data_analyst_agent.utils.dependency_tracker

# ------------------------------------------------------------------
# 1. Pre-import flag scanning
# ------------------------------------------------------------------
for _i, _arg in enumerate(sys.argv):
    if _arg == "--model-config" and _i + 1 < len(sys.argv):
        os.environ["MODEL_CONFIG_PATH"] = os.path.abspath(sys.argv[_i + 1])
        sys.argv = sys.argv[:_i] + sys.argv[_i + 2:]
        break


# ------------------------------------------------------------------
# 2. Argument parsing
# ------------------------------------------------------------------
import argparse

parser = argparse.ArgumentParser(
    description="Data Analyst Agent - CLI Parameter Mode",
    formatter_class=argparse.RawDescriptionHelpFormatter,
    epilog="""\
examples:
  # Single metric analysis:
  python -m data_analyst_agent --dataset trade_data --metrics "Truck Count"

  # Multi-metric with dimension filter:
  python -m data_analyst_agent --dataset trade_data \\
      --metrics "Truck Count,Rev/Trk/Wk" --dimension region --dimension-value Central

  # Interactive mode (guided menus):
  python -m data_analyst_agent --interactive

  # Legacy shorthand:
  python -m data_analyst_agent --validation --metric "Truck Count"
""",
)

parser.add_argument("--dataset", default=None, metavar="NAME",
                     help="Dataset folder name (e.g. trade_data)")
parser.add_argument("--metrics", default=None, metavar="M1,M2",
                     help="Comma-separated metric names (required unless --interactive)")
parser.add_argument("--dimension", default=None, metavar="DIM",
                     help="Primary dimension name (e.g. region, terminal)")
parser.add_argument("--dimension-value", default=None, metavar="VAL",
                     help="Value to filter the dimension by (e.g. Central)")
parser.add_argument(
    "--lob",
    default=None,
    metavar="NAME",
    help=(
        "Line-of-business filter for Hyper loaders that define filter_columns.lob "
        "(e.g. Dedicated for tolls_expense_weekly_lane_ds)"
    ),
)
parser.add_argument("--start-date", default=None, metavar="YYYY-MM-DD",
                     help="Override analysis start date")
parser.add_argument("--end-date", default=None, metavar="YYYY-MM-DD",
                     help="Override analysis end date")
parser.add_argument("--interactive", action="store_true",
                     help="Interactive mode: guided terminal menus for all parameters")
parser.add_argument("--exclude-partial-week", action="store_true",
                     help="Drop the most recent partial week from the loaded data")
parser.add_argument(
    "--write-metric-markdown",
    action="store_true",
    help=(
        "Write metric_*.md for each metric (default is skip). "
        "JSON is always written; executive brief uses JSON-backed digest when .md is absent."
    ),
)
parser.add_argument("--period-type", default=None, choices=["week_end", "month_end", "day"],
                     help="Override aggregation period type (default: from loader.yaml)")
parser.add_argument(
    "--standard-brief",
    action="store_true",
    help=(
        "Use standard executive brief (single digest LLM). Default is CEO hybrid: "
        "code rank -> gemini-3.1-flash-lite curate -> gemini-3.1-pro synthesis."
    ),
)
parser.add_argument(
    "--brief-style",
    default=None,
    choices=["ceo", "billing_auditor", "default"],
    metavar="STYLE",
    help=(
        "Override network executive brief persona. "
        "billing_auditor = customer/lane billing review queue; "
        "ceo = COO-style hybrid; default = standard JSON brief. "
        "When omitted, uses contract reporting.executive_brief_style if set, else CEO hybrid."
    ),
)
parser.add_argument(
    "--tier-filter",
    default=None,
    metavar="SPEC",
    help=(
        "Override hierarchy tier filters (requires hierarchy_entity_filters in contract). "
        "Comma-separated segments: level:top_pct|top_n:value, optional @partition_dim per segment. "
        "Example: 1:top_pct:100,2:top_pct:95,3:top_n:20@gl_div_nm"
    ),
)

# Cache / brief-only mode
parser.add_argument("--from-cache", default=None, metavar="PATH",
                     help="Path to an output directory with cached results (skips full analysis)")
parser.add_argument("--brief-only", action="store_true",
                     help="Only regenerate the brief (requires --from-cache)")

# Legacy compat
parser.add_argument("--validation", action="store_true",
                     help="Shorthand for --dataset trade_data")
parser.add_argument("--metric", default=None,
                     help="(Legacy) Same as --metrics")

args = parser.parse_args()


# ------------------------------------------------------------------
# 2b. --from-cache / --brief-only early exit
# ------------------------------------------------------------------
if args.brief_only and not args.from_cache:
    parser.error("--brief-only requires --from-cache <output_dir>")

if args.from_cache:
    import json
    from pathlib import Path
    from data_analyst_agent.cache import InsightCache

    cache_dir = Path(args.from_cache) / ".cache"
    digest_path = cache_dir / "digest.json"

    if not digest_path.exists():
        print(f"ERROR: No cached digest found at {digest_path}")
        sys.exit(1)

    cache = InsightCache(str(cache_dir))
    digest = cache.load("digest")

    if digest is None:
        print(f"ERROR: Failed to load digest from {digest_path}")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  Loaded cached digest from: {digest_path}")
    print(f"  Cache keys: {', '.join(digest.keys()) if isinstance(digest, dict) else '(non-dict payload)'}")
    if args.brief_only:
        print(f"  Mode: brief-only (regeneration will be wired up later)")
    print(f"{'='*60}\n")

    # TODO: wire up actual brief regeneration here
    sys.exit(0)


# ------------------------------------------------------------------
# 3. Interactive mode
# ------------------------------------------------------------------
if args.interactive:
    from data_analyst_agent.interactive_selector import run_interactive
    params = run_interactive()
    args.dataset = params.get("dataset", args.dataset)
    if params.get("metrics"):
        args.metrics = ",".join(params["metrics"])
    args.dimension = params.get("dimension", args.dimension)
    args.dimension_value = params.get("dimension_value", args.dimension_value)
    args.start_date = params.get("start_date", args.start_date)
    args.end_date = params.get("end_date", args.end_date)


# ------------------------------------------------------------------
# 4. Normalise legacy flags
# ------------------------------------------------------------------
if args.validation:
    args.dataset = args.dataset or "validation_ops"
    args.exclude_partial_week = True

if args.metric and not args.metrics:
    args.metrics = args.metric


# ------------------------------------------------------------------
# 5. Require --metrics (or --interactive must have provided them)
# ------------------------------------------------------------------
if not args.metrics:
    parser.error(
        "--metrics is required (or use --interactive).\n\n"
        "Example:\n"
        "  python -m data_analyst_agent --dataset trade_data --metrics \"Truck Count\"\n"
        "  python -m data_analyst_agent --interactive"
    )

if not args.dataset:
    args.dataset = os.getenv("ACTIVE_DATASET", "trade_data")


# ------------------------------------------------------------------
# 6. Validate --dataset and --metrics before heavy imports
# ------------------------------------------------------------------
from data_analyst_agent.cli_validator import (
    validate_dataset, list_datasets, validate_metrics,
    validate_date, validate_date_range,
)

if not validate_dataset(args.dataset):
    print(f"ERROR: Unknown dataset '{args.dataset}'.\n\nAvailable datasets:")
    for ds in list_datasets():
        print(f"  {ds['name']:<20} {ds['display_name']} ({ds['frequency']})")
    sys.exit(1)

metric_list = [m.strip() for m in args.metrics.split(",") if m.strip()]
valid, invalid = validate_metrics(args.dataset, metric_list)
if invalid:
    for bad in invalid:
        print(f"ERROR: Unknown metric '{bad}'.")
    print(f"\nUse --interactive to browse available metrics:")
    print(f"  python -m data_analyst_agent --interactive")
    sys.exit(1)
args.metrics = ",".join(valid)

if args.start_date and not validate_date(args.start_date):
    print(f"ERROR: Invalid start date '{args.start_date}'. Expected YYYY-MM-DD.")
    sys.exit(1)
if args.end_date and not validate_date(args.end_date):
    print(f"ERROR: Invalid end date '{args.end_date}'. Expected YYYY-MM-DD.")
    sys.exit(1)
if args.start_date and args.end_date and not validate_date_range(args.start_date, args.end_date):
    print(f"ERROR: Start date must be before end date.")
    sys.exit(1)


# ------------------------------------------------------------------
# 7. Set environment variables for the agent pipeline
# ------------------------------------------------------------------
os.environ["ACTIVE_DATASET"] = args.dataset

# CEO hybrid brief by default (Pass1: 3.1 Flash-Lite, Pass2: 3.1 Pro). Override with .env, --brief-style, or --standard-brief.
if args.brief_style:
    os.environ["EXECUTIVE_BRIEF_STYLE"] = args.brief_style
    os.environ["EXECUTIVE_BRIEF_STYLE_FROM_CLI"] = "1"
elif args.standard_brief:
    os.environ["EXECUTIVE_BRIEF_STYLE"] = "default"
else:
    os.environ.setdefault("EXECUTIVE_BRIEF_STYLE", "ceo")

ds_csv_datasets = {"validation_ops"}
if args.dataset in ds_csv_datasets:
    os.environ["DATA_ANALYST_VALIDATION_CSV_MODE"] = "true"

os.environ["DATA_ANALYST_METRICS"] = args.metrics

if args.dimension:
    os.environ["DATA_ANALYST_DIMENSION"] = args.dimension
if args.dimension_value:
    os.environ["DATA_ANALYST_DIMENSION_VALUE"] = args.dimension_value
if args.lob:
    os.environ["DATA_ANALYST_LOB"] = args.lob
if args.start_date:
    os.environ["DATA_ANALYST_START_DATE"] = args.start_date
if args.end_date:
    os.environ["DATA_ANALYST_END_DATE"] = args.end_date
if args.exclude_partial_week:
    os.environ["DATA_ANALYST_EXCLUDE_PARTIAL_WEEK"] = "true"
if args.period_type:
    os.environ["DATA_ANALYST_PERIOD_TYPE"] = args.period_type
if args.tier_filter:
    os.environ["DATA_ANALYST_TIER_FILTER"] = args.tier_filter.strip()
if args.write_metric_markdown:
    os.environ["DATA_ANALYST_SKIP_METRIC_MARKDOWN"] = "false"

# Initialize OutputManager and set run-specific environment
from data_analyst_agent.utils.output_manager import OutputManager
output_manager = OutputManager(
    dataset=args.dataset,
    dimension=args.dimension,
    dimension_value=args.dimension_value
)
os.environ["DATA_ANALYST_RUN_ID"] = output_manager.run_id
os.environ["DATA_ANALYST_OUTPUT_DIR"] = str(output_manager.run_dir)
output_manager.create_run_directory()
output_manager.save_run_metadata(vars(args))


# ------------------------------------------------------------------
# 8. Build the query string (for session state / logging only)
# ------------------------------------------------------------------
parts = [f"Analyze {args.metrics.replace(',', ' and ')}"]
if args.dimension_value:
    parts.append(f"for {args.dimension_value}")
elif args.dimension:
    parts.append(f"across all {args.dimension}s")
query = " ".join(parts)
os.environ["DATA_ANALYST_QUERY"] = query


# ------------------------------------------------------------------
# 9. Print summary
# ------------------------------------------------------------------
print(f"\n{'='*60}")
print(f"  Dataset   : {args.dataset}")
print(f"  Metrics   : {args.metrics}")
print(f"  Dimension : {args.dimension or '(all)'}{'=' + args.dimension_value if args.dimension_value else ''}")
print(f"  LOB       : {args.lob or '(none)'}")
print(f"  Tier filt.: {args.tier_filter or '(contract default / env DATA_ANALYST_TIER_FILTER)'}")
print(f"  Dates     : {args.start_date or '(auto)'} to {args.end_date or '(auto)'}")
print(f"  Output    : {os.environ.get('DATA_ANALYST_OUTPUT_DIR', '(default)')}")
if args.write_metric_markdown:
    print(f"  Metric MD : write enabled (metric_*.md + .json)")
else:
    print(f"  Metric MD : skipped by default (metric_*.json only; --write-metric-markdown for .md)")
if args.standard_brief:
    print(f"  Brief style: standard (digest + single LLM)")
else:
    print(f"  Brief style: CEO hybrid (Lite curate + Pro); use --standard-brief to disable")
print(f"  Query     : {query[:80]}{'...' if len(query) > 80 else ''}")
print(f"{'='*60}\n")


# ------------------------------------------------------------------
# 10. Import agent module and run
# ------------------------------------------------------------------
import asyncio
from data_analyst_agent.agent import run_analysis

try:
    asyncio.run(run_analysis(query))
except KeyboardInterrupt:
    print("\nAnalysis cancelled by user.")
except Exception as e:
    print(f"\nAnalysis failed: {str(e)}")
    import traceback
    traceback.print_exc()
