import sys
from pathlib import Path
import yaml
import pandas as pd
import argparse

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from data_analyst_agent.sub_agents.tableau_hyper_fetcher.loader_config import HyperLoaderConfig
from data_analyst_agent.sub_agents.tableau_hyper_fetcher.hyper_connection import get_or_create_manager

def check_raw_data():
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", type=str, default=None)
    args = parser.parse_args()

    loader_path = PROJECT_ROOT / "config" / "datasets" / "tableau" / "ops_metrics" / "loader.yaml"
    with open(loader_path, "r") as f:
        loader_raw = yaml.safe_load(f)
    
    loader_raw["hyper"]["extract_dir"] = "temp_extracted/validation_check"
    loader_config = HyperLoaderConfig(**loader_raw)
    manager = get_or_create_manager("ops_metrics", loader_config)
    manager.ensure_extracted(PROJECT_ROOT)
    
    if args.query:
        df = manager.execute_query(args.query)
        print(f"\nQuery results:")
        print(df)
    else:
        # Default check
        sql = 'SELECT DISTINCT "gl_div_nm" FROM "Extract"."Extract" ORDER BY "gl_div_nm"'
        df = manager.execute_query(sql)
        print("\nDistinct terminals:")
        print(df["gl_div_nm"].tolist())

if __name__ == "__main__":
    check_raw_data()
