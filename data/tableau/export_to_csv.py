#!/usr/bin/env python
"""Export Hyper file to CSV in chunks"""

from tableauhyperapi import HyperProcess, Connection, Telemetry
import csv

hyper_file = "ops_metrics_extract/Data/Extracts/Ops Metrics Weekly Scorecard v2.hyper"
output_csv = "ops_metrics_weekly_extract.csv"

print(f"Opening Hyper file: {hyper_file}")
print(f"Exporting to: {output_csv}")

with HyperProcess(telemetry=Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU) as hyper:
    with Connection(endpoint=hyper.endpoint, database=hyper_file) as connection:
        
        table_name = '"Extract"."Extract"'
        query = f'SELECT * FROM {table_name}'
        
        print("Executing query...")
        with connection.execute_query(query) as result:
            # Get column names
            columns = [col.name.unescaped for col in result.schema.columns]
            print(f"Columns: {len(columns)}")
            
            # Write to CSV
            with open(output_csv, 'w', newline='') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(columns)
                
                row_count = 0
                for row in result:
                    writer.writerow(row)
                    row_count += 1
                    if row_count % 100000 == 0:
                        print(f"  Exported {row_count:,} rows...")
                
                print(f"\nTotal rows exported: {row_count:,}")

print(f"\nExport complete: {output_csv}")
