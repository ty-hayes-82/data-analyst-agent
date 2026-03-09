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
Get Monthly Aggregates By Cost Center tool for alert_scoring_coordinator_agent.
"""

import json
from typing import Any, List
from pathlib import Path
from .models import MonthlyAggregate, MonthlyAggregatesResponse


async def get_period_aggregates_by_dimension(
    start_date: str,
    end_date: str,
    analysis_targets: List[str]
) -> str:
    """Get monthly aggregate metrics (miles, stops, revenue) by analysis target.
    
    Returns a Pydantic-structured response with monthly breakdowns including:
    - Total loaded/empty/order miles
    - Total stops (stop_count)
    - Total revenue (overall and by type: LH, Fuel, Accessorial)
    - Order count and average revenue per order
    
    This function is designed to run in parallel with data pulls
    to provide operational context alongside financial data.
    
    Args:
        start_date: Start date for the period in YYYY-MM-DD format (e.g., "2023-01-01")
        end_date: End date for the period in YYYY-MM-DD format (e.g., "2025-12-31")
        analysis_targets: List of target IDs to include (e.g., ["497", "094", "289"])
        
    Returns:
        JSON string with MonthlyAggregatesResponse structure
        
    Example:
        # Get monthly aggregates for multiple targets over 24 months
        get_period_aggregates_by_dimension(
            "2023-06-01", 
            "2025-05-31", 
            ["497", "094", "289"]
        )
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
            response = MonthlyAggregatesResponse(
                success=False,
                period_start=start_date,
                period_end=end_date,
                analysis_targets=analysis_targets,
                monthly_data=[],
                grand_totals={},
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
        
        # Build analysis target filter
        analysis_target_list = "', '".join(analysis_targets)
        
        # SQL query for monthly aggregates
        # Use empty_call_dt for month grouping to match analysis
        # DATE_TRUNC is supported in Hyper for date aggregation
        sql_query = f'''
        SELECT 
            CAST(YEAR("empty_call_dt") AS VARCHAR) || '-' || 
            LPAD(CAST(MONTH("empty_call_dt") AS VARCHAR), 2, '0') as month,
            "icc_cst_ctr_cd" as analysis_target,
            "icc_cst_ctr_nm" as target_name,
            SUM("loaded_miles") as total_loaded_miles,
            SUM("empty_miles") as total_empty_miles,
            SUM("ordr_miles") as total_order_miles,
            SUM("stop_count") as total_stops,
            SUM("ttl_amt") as total_revenue,
            SUM("lh_amt") as total_lh_revenue,
            SUM("fuel_srchrg_amt") as total_fuel_revenue,
            SUM("acsrl_amt") as total_accessorial_revenue,
            COUNT(*) as order_count
        FROM "{schema_name}"."{table_name}"
        WHERE "empty_call_dt" BETWEEN '{start_date}' AND '{end_date}'
          AND "icc_cst_ctr_cd" IN ('{analysis_target_list}')
        GROUP BY month, "icc_cst_ctr_cd", "icc_cst_ctr_nm"
        ORDER BY month, "icc_cst_ctr_cd"
        '''
        
        # Execute query
        result = run_sql_query_tool(sql_query, limit=10000)  # Higher limit for monthly data
        
        if not result.get("success"):
            response = MonthlyAggregatesResponse(
                success=False,
                period_start=start_date,
                period_end=end_date,
                analysis_targets=analysis_targets,
                monthly_data=[],
                grand_totals={},
                error_message=result.get('detail', 'Query execution failed')
            )
            return response.model_dump_json(indent=2)
        
        data = result.get('data', [])
        
        # Clean up column names
        cleaned_data = []
        for record in data:
            cleaned_record = {k.strip('"'): v for k, v in record.items()}
            cleaned_data.append(cleaned_record)
        
        # Build monthly aggregates list
        monthly_data = []
        for row in cleaned_data:
            order_count = int(row.get('order_count', 0) or 0)
            total_revenue = float(row.get('total_revenue', 0) or 0)
            
            monthly_agg = MonthlyAggregate(
                month=str(row.get('month', '')),
                analysis_target=str(row.get('analysis_target', '')),
                target_name=str(row.get('target_name', '')),
                total_loaded_miles=float(row.get('total_loaded_miles', 0) or 0),
                total_empty_miles=float(row.get('total_empty_miles', 0) or 0),
                total_order_miles=float(row.get('total_order_miles', 0) or 0),
                total_stops=int(row.get('total_stops', 0) or 0),
                total_revenue=total_revenue,
                total_lh_revenue=float(row.get('total_lh_revenue', 0) or 0),
                total_fuel_revenue=float(row.get('total_fuel_revenue', 0) or 0),
                total_accessorial_revenue=float(row.get('total_accessorial_revenue', 0) or 0),
                order_count=order_count,
                avg_revenue_per_order=total_revenue / order_count if order_count > 0 else 0.0
            )
            monthly_data.append(monthly_agg)
        
        # Calculate grand totals
        grand_totals = {
            "total_loaded_miles": sum(m.total_loaded_miles for m in monthly_data),
            "total_empty_miles": sum(m.total_empty_miles for m in monthly_data),
            "total_order_miles": sum(m.total_order_miles for m in monthly_data),
            "total_stops": sum(m.total_stops for m in monthly_data),
            "total_revenue": sum(m.total_revenue for m in monthly_data),
            "total_lh_revenue": sum(m.total_lh_revenue for m in monthly_data),
            "total_fuel_revenue": sum(m.total_fuel_revenue for m in monthly_data),
            "total_accessorial_revenue": sum(m.total_accessorial_revenue for m in monthly_data),
            "total_orders": sum(m.order_count for m in monthly_data),
            "months_covered": len(set(m.month for m in monthly_data)),
            "targets_covered": len(set(m.analysis_target for m in monthly_data))
        }
        
        # Create structured response
        response = MonthlyAggregatesResponse(
            success=True,
            period_start=start_date,
            period_end=end_date,
            analysis_targets=analysis_targets,
            monthly_data=monthly_data,
            grand_totals=grand_totals
        )
        
        # Save to file for reference
        output_dir = project_root / "outputs"
        output_dir.mkdir(exist_ok=True)
        target_str = "_".join(analysis_targets[:3])  # Use first 3 targets in filename
        output_file = output_dir / f"monthly_aggregates_{target_str}_{start_date}_{end_date}.json"
        
        try:
            with open(output_file, 'w') as f:
                f.write(response.model_dump_json(indent=2))
            print(f"[INFO] Monthly aggregates saved to: {output_file}")
        except Exception as e:
            print(f"[WARNING] Could not save monthly aggregates: {e}")
        
        return response.model_dump_json(indent=2)
        
    except Exception as e:
        import traceback
        response = MonthlyAggregatesResponse(
            success=False,
            period_start=start_date,
            period_end=end_date,
            analysis_targets=analysis_targets,
            monthly_data=[],
            grand_totals={},
            error_message=f"Unexpected error: {str(e)}\n{traceback.format_exc()}"
        )
        return response.model_dump_json(indent=2)
