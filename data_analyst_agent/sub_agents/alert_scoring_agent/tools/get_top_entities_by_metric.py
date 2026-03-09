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
Get Top Shippers By Miles tool for alert_scoring_coordinator_agent.
"""

import json
from typing import Any
from pathlib import Path
from .models import TopShipper, TopShippersByMilesResponse


async def get_top_entities_by_metric(
    start_date: str,
    end_date: str,
    analysis_target: str,
    top_n: int = 10
) -> str:
    """Get top shippers ranked by total loaded miles for a specific period and analysis target.
    
    Returns a Pydantic-structured response with detailed shipper metrics including:
    - Shipper code and name
    - Total loaded miles (primary ranking metric)
    - Total revenue
    - Order count
    - Average revenue per order
    - Percentage of total miles
    
    Args:
        start_date: Start date for the period in YYYY-MM-DD format (e.g., "2025-06-01")
        end_date: End date for the period in YYYY-MM-DD format (e.g., "2025-06-30")
        analysis_target: Target ID to filter by (e.g., "497", "094" or metric name)
        top_n: Number of top shippers to return (default: 10)
        
    Returns:
        JSON string with TopShippersByMilesResponse structure
        
    Example:
        # Get top 10 shippers for June 2025 at target 497
        get_top_entities_by_metric("2025-06-01", "2025-06-30", "497", top_n=10)
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
            from remote_a2a.tableau_order_dispatch_revenue_ds_agent.tools.data_tools import run_sql_query_tool
            from remote_a2a.tableau_order_dispatch_revenue_ds_agent.shared_libraries import hyper_manager
        except ImportError as import_err:
            response = TopShippersByMilesResponse(
                success=False,
                period_start=start_date,
                period_end=end_date,
                analysis_target=analysis_target,
                total_miles=0.0,
                total_revenue=0.0,
                total_orders=0,
                top_shippers=[],
                error_message=f"Import error: {str(import_err)}"
            )
            return response.model_dump_json(indent=2)
        
        # Initialize Hyper connection if not already done
        if not hyper_manager.is_dataset_available():
            hyper_manager.extract_hyper_at_startup(agent_dir)
        
        # Load schema
        schema_file = agent_dir / "docs" / "schema.json"
        with open(schema_file, 'r') as f:
            schema = json.load(f)
        
        table = schema.get('table', 'Extract.Extract')
        schema_name, table_name = table.split('.') if '.' in table else ('Extract', table)
        
        # SQL query to get top shippers by miles with aggregate metrics
        sql_query = f'''
        SELECT 
            "shpr_cd" as shipper_code,
            "shpr_nm" as shipper_name,
            SUM("loaded_miles") as total_loaded_miles,
            SUM("ttl_amt") as total_revenue,
            COUNT(*) as order_count
        FROM "{schema_name}"."{table_name}"
        WHERE "empty_call_dt" BETWEEN '{start_date}' AND '{end_date}'
          AND "icc_cst_ctr_cd" = '{analysis_target}'
        GROUP BY "shpr_cd", "shpr_nm"
        ORDER BY total_loaded_miles DESC
        LIMIT {top_n}
        '''
        
        # Execute query
        result = run_sql_query_tool(sql_query, limit=top_n)
        
        if not result.get("success"):
            response = TopShippersByMilesResponse(
                success=False,
                period_start=start_date,
                period_end=end_date,
                analysis_target=analysis_target,
                total_miles=0.0,
                total_revenue=0.0,
                total_orders=0,
                top_shippers=[],
                error_message=result.get('detail', 'Query execution failed')
            )
            return response.model_dump_json(indent=2)
        
        data = result.get('data', [])
        
        # Clean up column names
        cleaned_data = []
        for record in data:
            cleaned_record = {k.strip('"'): v for k, v in record.items()}
            cleaned_data.append(cleaned_record)
        
        # Calculate grand totals
        total_miles = sum(float(row.get('total_loaded_miles', 0) or 0) for row in cleaned_data)
        total_revenue = sum(float(row.get('total_revenue', 0) or 0) for row in cleaned_data)
        total_orders = sum(int(row.get('order_count', 0) or 0) for row in cleaned_data)
        
        # Build top shippers list
        top_shippers = []
        for row in cleaned_data:
            shipper_miles = float(row.get('total_loaded_miles', 0) or 0)
            shipper_revenue = float(row.get('total_revenue', 0) or 0)
            shipper_orders = int(row.get('order_count', 0) or 0)
            
            top_shipper = TopShipper(
                shipper_code=str(row.get('shipper_code', '')),
                shipper_name=str(row.get('shipper_name', '')),
                total_loaded_miles=shipper_miles,
                total_revenue=shipper_revenue,
                order_count=shipper_orders,
                avg_revenue_per_order=shipper_revenue / shipper_orders if shipper_orders > 0 else 0.0,
                percent_of_total_miles=(shipper_miles / total_miles * 100) if total_miles > 0 else 0.0
            )
            top_shippers.append(top_shipper)
        
        # Create structured response
        response = TopShippersByMilesResponse(
            success=True,
            period_start=start_date,
            period_end=end_date,
            analysis_target=analysis_target,
            total_miles=total_miles,
            total_revenue=total_revenue,
            total_orders=total_orders,
            top_shippers=top_shippers
        )
        
        # Save to file for reference
        output_dir = project_root / "outputs"
        output_dir.mkdir(exist_ok=True)
        output_file = output_dir / f"top_shippers_{analysis_target}_{start_date}_{end_date}.json"
        
        try:
            with open(output_file, 'w') as f:
                f.write(response.model_dump_json(indent=2))
            print(f"[INFO] Top shippers saved to: {output_file}")
        except Exception as e:
            print(f"[WARNING] Could not save top shippers: {e}")
        
        return response.model_dump_json(indent=2)
        
    except Exception as e:
        import traceback
        response = TopShippersByMilesResponse(
            success=False,
            period_start=start_date,
            period_end=end_date,
            analysis_target=analysis_target,
            total_miles=0.0,
            total_revenue=0.0,
            total_orders=0,
            top_shippers=[],
            error_message=f"Unexpected error: {str(e)}\n{traceback.format_exc()}"
        )
        return response.model_dump_json(indent=2)
