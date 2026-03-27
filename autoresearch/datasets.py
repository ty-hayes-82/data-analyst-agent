"""Evaluation dataset configurations for autoresearch experiments."""

EVAL_DATASETS = [
    {
        "name": "ops_metrics_ds",
        "metrics": "ttl_rev_amt,ordr_cnt,dh_miles,truck_count",
        "description": "Ops Metrics DS (Tableau): 16 base metrics + 9 derived KPIs, weekly trucking ops with geographic hierarchy (region > terminal > driver mgr). Revenue, volume, productivity, and efficiency cross-metric analysis.",
        "weight": 1.0,
        "extra_args": [
            "--lob", "Line Haul",
            "--end-date", "2026-03-14",
            "--period-type", "week_end",
        ],
    },
]

# Kept for reference — re-enable for multi-dataset runs
CSV_EVAL_DATASETS = [
    {
        "name": "global_superstore",
        "metrics": "Sales,Profit",
        "description": "Global retail: 51K rows, 4 years, Market > Region > Country hierarchy, Sales + Profit enables margin analysis",
        "weight": 1.0,
    },
    {
        "name": "iowa_liquor_sales",
        "metrics": "sale_dollars",
        "description": "Iowa liquor: 50K rows, County > City > Store hierarchy. Auto-enrichment adds supporting metrics from contract.",
        "weight": 1.0,
    },
]

HOLDOUT_DATASETS = [
    {
        "name": "online_retail",
        "metrics": "Quantity",
        "description": "UK e-commerce: 531K rows, Country-level",
        "weight": 1.0,
    },
    {
        "name": "tolls_expense_ds",
        "metrics": "toll_expense,toll_revenue",
        "description": "Tolls Expense (Tableau): dispatch-level toll data with shipper/region/plaza hierarchies. Cost vs revenue analysis.",
        "weight": 1.0,
    },
]
