# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Get Order Details For Period tool for alert_scoring_coordinator_agent.
"""

import json
from typing import Any


async def get_order_details_for_period(
    start_date: str,
    end_date: str,
    cost_center: str
) -> str:
    """Retrieve order details from the Order Dispatch Revenue dataset for a specific time period and cost center.
    
    This tool pulls detailed order-level data to investigate anomalies or variances identified in P&L analysis.
    Use this when you need to drill down from aggregate financial data to understand what specific orders,
    shipments, or operational activities contributed to a variance.
    
    Args:
        start_date: Start date for the period in YYYY-MM-DD format (e.g., "2025-06-01")
        end_date: End date for the period in YYYY-MM-DD format (e.g., "2025-06-30")
        cost_center: Cost center code to filter by (e.g., "497", "094")
        
    Returns:
        JSON string with order details including: Order #, Dispatch #, dates, miles, revenue, 
        customer info, origin/destination, and billing details. Returns default columns configured
        in the schema (72 core fields).
        
    Example:
        # To investigate June 2025 anomaly for cost center 497:
        get_order_details_for_period("2025-06-01", "2025-06-30", "497")
    """
    try:
        # Get path to the Order Dispatch Revenue agent
        project_root = Path(__file__).parent.parent.parent
        agent_dir = project_root / "remote_a2a" / "tableau_order_dispatch_revenue_ds_agent"
        
        # Import tools from the Order Dispatch Revenue agent
        import sys
        agent_tools_path = str(agent_dir)
        if agent_tools_path not in sys.path:
            sys.path.insert(0, agent_tools_path)
        
        try:
            # Import from the remote_a2a package structure
            from remote_a2a.tableau_order_dispatch_revenue_ds_agent.tools.data_tools import run_sql_query_tool
            from remote_a2a.tableau_order_dispatch_revenue_ds_agent.shared_libraries import hyper_manager
        except ImportError as import_err:
            return json.dumps({
                "error": "ImportError",
                "detail": f"Could not import Order Dispatch Revenue agent tools: {str(import_err)}",
                "action": "Verify remote_a2a/tableau_order_dispatch_revenue_ds_agent is configured",
                "agent_dir": str(agent_dir)
            })
        
        # Initialize Hyper connection if not already done
        if not hyper_manager.is_dataset_available():
            hyper_manager.extract_hyper_at_startup(agent_dir)
        
        # Load schema to get default columns
        schema_file = agent_dir / "docs" / "schema.json"
        with open(schema_file, 'r') as f:
            schema = json.load(f)
        
        default_columns = schema.get('default_columns', [])
        if not default_columns:
            return json.dumps({
                "error": "ConfigurationError",
                "detail": "No default columns configured in schema",
                "action": "Check schema.json for default_columns array"
            })
        
        # Build SELECT clause using default columns
        select_fields = [f'"{col["column_name"]}"' for col in default_columns]
        select_clause = ", ".join(select_fields)
        
        # Build SQL query
        table = schema.get('table', 'Extract.Extract')
        schema_name, table_name = table.split('.') if '.' in table else ('Extract', table)
        
        sql_query = f'''
        SELECT {select_clause}
        FROM "{schema_name}"."{table_name}"
        WHERE "empty_call_dt" BETWEEN '{start_date}' AND '{end_date}'
          AND "icc_cst_ctr_cd" = '{cost_center}'
        ORDER BY "empty_call_dt", "ordr_nbr", "disp_nbr"
        '''
        
        # Execute query
        result = run_sql_query_tool(sql_query, limit=1000)
        
        if not result.get("success"):
            return json.dumps({
                "error": "QueryError",
                "detail": result.get('detail', 'Query execution failed'),
                "query": sql_query
            })
        
        data = result.get('data', [])
        
        # Clean up column names (remove quotes)
        cleaned_data = []
        for record in data:
            cleaned_record = {k.strip('"'): v for k, v in record.items()}
            cleaned_data.append(cleaned_record)
        
        # Prepare response
        output = {
            "success": True,
            "period": {
                "start_date": start_date,
                "end_date": end_date
            },
            "cost_center": cost_center,
            "record_count": len(cleaned_data),
            "columns_returned": len(default_columns),
            "column_list": [col["display_name"] for col in default_columns],
            "orders": cleaned_data
        }
        
        # Save to file for reference
        output_dir = project_root / "outputs"
        output_dir.mkdir(exist_ok=True)
        output_file = output_dir / f"order_details_{cost_center}_{start_date}_{end_date}.json"
        
        try:
            with open(output_file, 'w') as f:
                json.dump(output, f, indent=2, default=str)
            output["saved_to"] = str(output_file)
        except Exception as e:
            print(f"[WARNING] Could not save order details: {e}")
        
        return json.dumps(output, indent=2, default=str)
        
    except Exception as e:
        import traceback
        return json.dumps({
            "error": "UnexpectedError",
            "source": "get_order_details_for_period",
            "detail": str(e),
            "traceback": traceback.format_exc(),
            "action": "Review error details and verify agent configuration"
        })
