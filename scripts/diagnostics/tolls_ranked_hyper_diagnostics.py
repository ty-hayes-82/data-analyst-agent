"""Read-only Hyper diagnostics for tolls ranked weekly fetch (3-level slice).

Measures:
  - Distinct level-0 dimension values in range
  - Top level-0 rank slots used (<= ``top_level_0``)
  - Count of allowed (level-0, level-1[, level-2]) tuples after ranked CTEs
  - Main aggregation: row count = ``len(DataFrame)`` from the full ``build_query`` SQL
    (not a SQL COUNT wrapper; Hyper can mis-count nested WITH). Same frame is then run
    through the fetcher's column mapping, secondary date filter, and date parsing.

Also prints SUM(toll_expense) by shipper parent (level 0) for the last one or two week_end
values in the filtered frame (zero-week / sparse-week check).

Run from repository root::

    python scripts/diagnostics/tolls_ranked_hyper_diagnostics.py --start 2025-12-23 --end 2026-03-24
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare Hyper ranked-subset counts to pipeline expectations."
    )
    parser.add_argument(
        "--start",
        default="2025-12-23",
        help="Inclusive Hyper date filter start (matches primary_query_start_date)",
    )
    parser.add_argument(
        "--end",
        default="2026-03-24",
        help="Inclusive Hyper date filter end (matches primary_query_end_date)",
    )
    args = parser.parse_args()

    root = _repo_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    import pandas as pd

    from config.dataset_resolver import get_project_root
    from data_analyst_agent.sub_agents.tableau_hyper_fetcher.fetcher import TableauHyperFetcher
    from data_analyst_agent.sub_agents.tableau_hyper_fetcher.hyper_connection import (
        get_or_create_manager,
        reuse_hyper_manager_after_extract,
    )
    from data_analyst_agent.sub_agents.tableau_hyper_fetcher.loader_config import HyperLoaderConfig
    from data_analyst_agent.sub_agents.tableau_hyper_fetcher.query_builder import HyperQueryBuilder
    from data_analyst_agent.sub_agents.tableau_hyper_fetcher.ranked_subset import (
        resolve_ranked_subset_spec,
    )
    from data_analyst_agent.utils.contract_cache import load_contract_cached

    proj = get_project_root()
    ds_dir = proj / "config/datasets/tableau/tolls_expense_weekly_lane_ds"
    contract = load_contract_cached(ds_dir / "contract.yaml")
    cfg = HyperLoaderConfig.from_yaml(ds_dir / "loader.yaml")
    spec = resolve_ranked_subset_spec(contract)
    if spec is None:
        print("ranked_subset_fetch disabled or unresolved; nothing to diagnose.")
        return 1

    builder = HyperQueryBuilder(cfg)
    diag = builder.build_ranked_fetch_diagnostic_sqls(args.start, args.end, {}, spec)
    mgr = get_or_create_manager("diag_tolls_ranked", cfg)
    try:
        mgr.ensure_extracted(proj)
        mgr = reuse_hyper_manager_after_extract(mgr)
    except Exception as exc:
        print(f"Hyper extract failed ({exc}). Ensure the TDSX exists for this loader.")
        return 1

    print("=== Ranked fetch diagnostic SQL counts ===")
    for label, sql in diag.items():
        df = mgr.execute_query(sql)
        print(f"\n{label}:")
        print(df.to_string(index=False))

    main_sql = builder.build_query(args.start, args.end, {}, ranked_spec=spec)
    raw_df = mgr.execute_query(main_sql)
    n_sql = len(raw_df)
    time_col = (contract.time.column if contract.time else None) or "empty_call_dt"
    # Match fetcher.py: column_mapping -> secondary date filter -> date_parsing
    staged = TableauHyperFetcher._apply_column_mapping(raw_df.copy(), cfg)
    filtered = TableauHyperFetcher._apply_date_filter(
        staged, time_col, args.start, args.end
    )
    filtered = TableauHyperFetcher._apply_date_parsing(filtered, cfg)
    n_after = len(filtered)
    print("\n=== Row count: main query vs secondary date filter ===")
    print(f"rows_after_sql: {n_sql}")
    print(f"rows_after_secondary_date_filter ({time_col}): {n_after}")

    need = (time_col, "shpr_prnt_nm", "toll_expense")
    missing = [c for c in need if c not in filtered.columns]
    if filtered.empty or missing:
        print(
            "\n(skip last-two-week pivot: empty frame or missing columns "
            f"{missing or 'n/a'}; available: {list(filtered.columns)})"
        )
    else:
        s = pd.to_datetime(filtered[time_col], errors="coerce")
        tmp = filtered.assign(_wk=s)
        n_bad = int(tmp["_wk"].isna().sum())
        if n_bad:
            print(f"\nNote: {n_bad} rows had non-parseable {time_col} after to_datetime.")
        weeks = sorted(tmp["_wk"].dropna().unique())
        print(f"\nDistinct week_end values in filtered frame: {len(weeks)}")
        last2 = weeks[-2:] if len(weeks) >= 2 else list(weeks)
        sub = tmp[tmp["_wk"].isin(last2)] if last2 else tmp.iloc[0:0]
        if sub.empty:
            print(
                "(last-two-week slice empty: check date parsing vs Hyper DATE types)"
            )
        else:
            grouped = (
                sub.groupby("shpr_prnt_nm", as_index=False)["toll_expense"]
                .sum()
                .sort_values("toll_expense", ascending=False)
            )
            print("\n=== SUM(toll_expense) by shipper parent (last 1-2 week_end in frame) ===")
            print(grouped.to_string(index=False))
            print(f"(week_ends: {[str(x.date()) for x in last2]})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
