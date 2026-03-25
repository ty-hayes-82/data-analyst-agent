"""Evaluation dataset configurations for autoresearch experiments."""

EVAL_DATASETS = [
    {
        "name": "global_superstore",
        "metrics": "Sales,Profit",
        "description": "Global retail: 51K rows, 4 years, Market > Region > Country hierarchy",
        "weight": 1.0,
    },
    {
        "name": "iowa_liquor_sales",
        "metrics": "sale_dollars",
        "description": "Iowa liquor: 50K rows, County > City > Store hierarchy",
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
]
