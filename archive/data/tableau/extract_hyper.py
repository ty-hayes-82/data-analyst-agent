#!/usr/bin/env python
"""Extract Tableau Hyper file to CSV"""

from tableauhyperapi import HyperProcess, Connection, Telemetry
import pandas as pd
import os

hyper_file = "ops_metrics_extract/Data/Extracts/Ops Metrics Weekly Scorecard v2.hyper"

print(f"Opening Hyper file: {hyper_file}")

with HyperProcess(telemetry=Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU) as hyper:
    with Connection(endpoint=hyper.endpoint, database=hyper_file) as connection:
        
        # List all tables
        tables = connection.catalog.get_table_names("Extract")
        print(f"\nFound {len(tables)} tables:")
        for table in tables:
            print(f"  - {table}")
        
        # Export each table to CSV
        for table in tables:
            table_name = table.name.unescaped
            print(f"\nProcessing table: {table_name}")
            
            # Read table to DataFrame
            query = f'SELECT * FROM {table}'
            
            # Execute query and get schema
            with connection.execute_query(query) as result:
                columns = [col.name.unescaped for col in result.schema.columns]
                rows = list(result)
            
            # Create DataFrame
            df = pd.DataFrame(rows, columns=columns)
            
            print(f"  Rows: {len(df)}")
            print(f"  Columns: {len(df.columns)}")
            print(f"  Column types:")
            for col in df.columns:
                print(f"    {col}: {df[col].dtype}")
            
            # Save to CSV
            csv_filename = f"ops_metrics_weekly_{table_name.replace(' ', '_').lower()}.csv"
            df.to_csv(csv_filename, index=False)
            print(f"  Saved to: {csv_filename}")
            
            # Show first few rows
            print(f"\n  Sample data:")
            print(df.head(3).to_string())
            
            # Analyze structure
            print(f"\n  Data Analysis:")
            print(f"    Numeric columns: {df.select_dtypes(include=['number']).columns.tolist()}")
            print(f"    Text columns: {df.select_dtypes(include=['object']).columns.tolist()}")
            print(f"    DateTime columns: {df.select_dtypes(include=['datetime']).columns.tolist()}")

print("\nExtraction complete!")
