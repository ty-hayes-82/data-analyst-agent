import requests
import json

url = "http://localhost:8001/a2a/tableau_ops_metrics_ds_agent"

# SQL to pull actual data for the last 24 months for CC 067
sql_query = """
SELECT 
    TO_CHAR("empty_call_dt", 'YYYY-MM') as "period",
    SUM(CAST("ld_trf_mi" AS FLOAT)) as "loaded_miles",
    SUM(CAST("empty_trf_mi" AS FLOAT)) as "empty_miles",
    AVG(CAST("truck_count" AS FLOAT)) as "avg_truck_count",
    SUM(CAST("ttl_rev_amt" AS FLOAT)) as "total_revenue",
    SUM(CAST("lh_rev_amt" AS FLOAT)) as "linehaul_revenue",
    SUM(CAST("ordr_cnt" AS FLOAT)) as "order_count",
    SUM(CAST("stop_count" AS FLOAT)) as "stop_count",
    SUM(CAST("dot_ocrnce_cnt" AS FLOAT)) as "dot_incidents"
FROM "Extract"."Extract"
WHERE "empty_call_dt" >= DATE '2024-02-01'
  AND "empty_call_dt" < DATE '2026-03-01'
  AND "icc_cst_ctr_cd" = '067'
GROUP BY 1
ORDER BY 1 ASC
"""

payload = {
    "jsonrpc": "2.0",
    "id": "3",
    "method": "message/send",
    "params": {
        "message": {
            "role": "user",
            "messageId": "cli-3",
            "parts": [{"text": f"Run this exact SQL query using run_sql_query_tool with output_format=json: {sql_query}"}]
        }
    }
}

try:
    response = requests.post(url, json=payload)
    print(json.dumps(response.json(), indent=2))
except Exception as e:
    print(f"Error: {e}")
