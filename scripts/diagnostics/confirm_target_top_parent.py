"""One-off: list top shipper parents by toll_expense in Hyper; check for Target."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2025-12-28")
    parser.add_argument("--end", default="2026-03-21")
    parser.add_argument("--lob", default=None, help="Optional ops_ln_of_bus_ref_nm filter")
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument(
        "--find-target-rank",
        action="store_true",
        help="List parents containing 'Target' and ROW_NUMBER rank by SUM(toll_expense)",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    from config.dataset_resolver import get_project_root
    from data_analyst_agent.sub_agents.tableau_hyper_fetcher.hyper_connection import (
        get_or_create_manager,
        reuse_hyper_manager_after_extract,
    )
    from data_analyst_agent.sub_agents.tableau_hyper_fetcher.loader_config import (
        HyperLoaderConfig,
    )

    proj = get_project_root()
    cfg = HyperLoaderConfig.from_yaml(
        proj / "config/datasets/tableau/tolls_expense_weekly_lane_ds/loader.yaml"
    )
    mgr = get_or_create_manager("confirm_target_top_parent", cfg)
    mgr.ensure_extracted(proj)
    mgr = reuse_hyper_manager_after_extract(mgr)

    if args.find_target_rank:
        lob_f = ""
        if args.lob:
            esc = str(args.lob).replace("'", "''")
            lob_f = f' AND "ops_ln_of_bus_ref_nm" = \'{esc}\''
        sql_rank = f"""
WITH agg AS (
  SELECT "shpr_prnt_nm" AS p, SUM("toll_expense") AS te
  FROM "Extract"."Extract"
  WHERE "empty_call_dt" < DATE '2100-01-01'
    AND "empty_call_dt" >= DATE '{args.start}'
    AND "empty_call_dt" <= DATE '{args.end}'
{lob_f}
  GROUP BY 1
), ranked AS (
  SELECT p, te, ROW_NUMBER() OVER (ORDER BY te DESC NULLS LAST) AS rnk
  FROM agg
)
SELECT rnk, p, te FROM ranked
WHERE UPPER(CAST(p AS VARCHAR)) LIKE '%TARGET%'
ORDER BY rnk
"""
        df_r = mgr.execute_query(sql_rank)
        print(
            f"=== Parents with 'TARGET' in name, ranked by toll_expense "
            f"(start={args.start} end={args.end} lob={args.lob!r}) ==="
        )
        print(df_r.to_string(index=False) if len(df_r) else "(no matching parent)")
        return 0

    lob_clause = ""
    if args.lob:
        esc = str(args.lob).replace("'", "''")
        lob_clause = f' AND "ops_ln_of_bus_ref_nm" = \'{esc}\''

    sql = f"""
SELECT "shpr_prnt_nm" AS parent, SUM("toll_expense") AS toll_expense
FROM "Extract"."Extract"
WHERE "empty_call_dt" < DATE '2100-01-01'
  AND "empty_call_dt" >= DATE '{args.start}'
  AND "empty_call_dt" <= DATE '{args.end}'
{lob_clause}
GROUP BY 1
ORDER BY 2 DESC NULLS LAST
LIMIT {int(args.limit)}
"""
    df = mgr.execute_query(sql)
    df.insert(0, "rank", range(1, len(df) + 1))

    for label in ["Top by toll_expense"]:
        print(f"=== {label} (start={args.start} end={args.end} lob={args.lob!r}) ===")
        print(df.head(20).to_string(index=False))

    mask = df["parent"].astype(str).str.contains("target", case=False, na=False)
    hits = df[mask]
    print()
    if hits.empty:
        print("CONFIRM: No shipper parent name containing 'Target' in top", args.limit, "for this window/filter.")
    else:
        print("CONFIRM: Found shipper parent(s) containing 'Target':")
        print(hits.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
