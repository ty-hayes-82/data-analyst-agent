#!/usr/bin/env python
"""Analyze Tableau Hyper schema using tableauhyperapi"""

from tableauhyperapi import HyperProcess, Connection, Telemetry
from pathlib import Path

hyper_file = "ops_metrics_extract/Data/Extracts/Ops Metrics Weekly Scorecard v2.hyper"

print(f"Analyzing Hyper file: {hyper_file}\n")

with HyperProcess(telemetry=Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU) as hyper:
    with Connection(hyper.endpoint, hyper_file) as connection:
        
        # Get table names
        tables = connection.catalog.get_table_names('Extract')
        print(f"Tables found: {len(tables)}")
        for table in tables:
            print(f"  - {table}")
        
        print("\n" + "="*80)
        
        # For each table, get schema
        for table in tables:
            schema = connection.catalog.get_table_definition(table)
            print(f"\nTable: {table}")
            print(f"Columns: {len(schema.columns)}\n")
            
            # Categorize columns
            time_cols = []
            text_cols = []
            numeric_cols = []
            
            for col in schema.columns:
                col_name = col.name.unescaped
                col_type = str(col.type)
                print(f"  {col_name:30} {col_type}")
                
                if 'TIMESTAMP' in col_type or 'DATE' in col_type:
                    time_cols.append(col_name)
                elif 'TEXT' in col_type:
                    text_cols.append(col_name)
                elif any(t in col_type for t in ['INT', 'DOUBLE', 'NUMERIC', 'BIG_INT']):
                    numeric_cols.append(col_name)
            
            print(f"\n{'='*80}")
            print(f"SUMMARY:")
            print(f"  Time columns ({len(time_cols)}): {time_cols}")
            print(f"  Text columns ({len(text_cols)}): {text_cols[:10]}...")  # First 10
            print(f"  Numeric columns ({len(numeric_cols)}): {numeric_cols[:10]}...")  # First 10
            
            # Get row count
            count_query = f'SELECT COUNT(*) FROM {table}'
            with connection.execute_query(count_query) as result:
                row_count = list(result)[0][0]
            print(f"  Total rows: {row_count:,}")
            
            # Get sample data
            sample_query = f'SELECT * FROM {table} LIMIT 5'
            with connection.execute_query(sample_query) as result:
                columns = [col.name.unescaped for col in result.schema.columns]
                rows = list(result)
            
            print(f"\n{'='*80}")
            print("SAMPLE DATA (first 5 rows):")
            print(f"Columns: {', '.join(columns[:10])}...")
            for i, row in enumerate(rows):
                print(f"Row {i+1}: {row[:5]}...")

print("\n\nAnalysis complete!")
