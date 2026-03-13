#!/usr/bin/env python
"""Analyze Tableau Hyper file structure without loading all data"""

from tableauhyperapi import HyperProcess, Connection, Telemetry
import pandas as pd

hyper_file = "ops_metrics_extract/Data/Extracts/Ops Metrics Weekly Scorecard v2.hyper"

print(f"Opening Hyper file: {hyper_file}")

with HyperProcess(telemetry=Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU) as hyper:
    with Connection(endpoint=hyper.endpoint, database=hyper_file) as connection:
        
        # List all tables
        tables = connection.catalog.get_table_names("Extract")
        print(f"\nFound {len(tables)} tables:")
        for table in tables:
            print(f"  - {table}")
        
        # Analyze each table
        for table in tables:
            table_name = table.name.unescaped
            print(f"\n{'='*60}")
            print(f"Table: {table_name}")
            print(f"{'='*60}")
            
            # Get table definition
            table_def = connection.catalog.get_table_definition(table)
            print(f"\nColumns ({len(table_def.columns)}):")
            for col in table_def.columns:
                print(f"  {col.name.unescaped}: {col.type}")
            
            # Get row count
            count_query = f'SELECT COUNT(*) FROM {table}'
            with connection.execute_query(count_query) as result:
                row_count = list(result)[0][0]
            print(f"\nTotal rows: {row_count:,}")
            
            # Get sample data (first 100 rows)
            sample_query = f'SELECT * FROM {table} LIMIT 100'
            with connection.execute_query(sample_query) as result:
                columns = [col.name.unescaped for col in result.schema.columns]
                rows = list(result)
            
            df_sample = pd.DataFrame(rows, columns=columns)
            
            print(f"\nSample data (first 5 rows):")
            print(df_sample.head().to_string())
            
            # Analyze column types
            print(f"\nColumn Analysis:")
            numeric_cols = []
            text_cols = []
            date_cols = []
            
            for col in columns:
                col_data = df_sample[col]
                if pd.api.types.is_numeric_dtype(col_data):
                    numeric_cols.append(col)
                    print(f"  {col}: NUMERIC (min={col_data.min()}, max={col_data.max()}, mean={col_data.mean():.2f})")
                elif pd.api.types.is_datetime64_any_dtype(col_data):
                    date_cols.append(col)
                    print(f"  {col}: DATE (min={col_data.min()}, max={col_data.max()})")
                else:
                    text_cols.append(col)
                    unique_count = col_data.nunique()
                    print(f"  {col}: TEXT (unique={unique_count}, sample={list(col_data.unique()[:3])})")
            
            print(f"\nSummary:")
            print(f"  Numeric columns: {len(numeric_cols)} - {numeric_cols}")
            print(f"  Text columns: {len(text_cols)} - {text_cols}")
            print(f"  Date columns: {len(date_cols)} - {date_cols}")

print("\n\nAnalysis complete!")
