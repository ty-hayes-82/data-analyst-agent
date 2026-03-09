import os
import sys
from pathlib import Path
import pandas as pd

# Add the project root to sys.path
sys.path.insert(0, str(Path(os.getcwd())))

from pl_analyst.data_analyst_agent.tools.config_data_loader import load_from_config

def test_toll_load():
    try:
        df = load_from_config("toll_data")
        print(f"Successfully loaded {len(df):,} rows from toll_data")
        print("\nColumns:", df.columns.tolist())
        print("\nFirst 5 rows:")
        print(df.head())
        print("\nDtypes:")
        print(df.dtypes)
        print("\nMetrics found:", df['metric'].unique().tolist())
    except Exception as e:
        print(f"Failed to load toll_data: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_toll_load()
