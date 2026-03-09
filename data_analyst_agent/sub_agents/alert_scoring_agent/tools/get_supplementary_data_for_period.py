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
Get Supplementary Data For Period tool for alert_scoring_coordinator_agent.
"""

import json
from typing import Any, Optional
from pathlib import Path


async def get_supplementary_data_for_period(
    start_date: str,
    end_date: str,
    dimension_value: str,
    contract: Optional[Any] = None
) -> str:
    """Retrieve detailed supplementary data for a specific time period and dimension target.
    
    This tool pulls detailed granular data to investigate anomalies identified in primary analysis.
    Use this when you need to drill down from aggregate data to understand what specific 
    entities or activities contributed to a finding.
    
    Args:
        start_date: Start date for the period in YYYY-MM-DD format (e.g., "2025-06-01")
        end_date: End date for the period in YYYY-MM-DD format (e.g., "2025-06-30")
        dimension_value: Dimension value to filter by
        contract: Optional DatasetContract to resolve supplementary source configuration
        
    Returns:
        JSON string with detailed records.
    """
    try:
        # Resolve supplementary source from contract if provided
        # For now, we still have some fallback logic for known agents
        project_root = Path(__file__).parent.parent.parent.parent
        
        # Example: if contract defines a supplementary source, we would use it here
        # agent_url = contract.supplementary_sources[0].agent_url if contract else ...
        
        # Fallback to existing Order Dispatch agent if no contract-driven source found
        agent_dir = project_root / "remote_a2a" / "tableau_order_dispatch_revenue_ds_agent"
        
        # Import tools from the resolved agent
        import sys
        agent_tools_path = str(agent_dir)
        if agent_tools_path not in sys.path:
            sys.path.insert(0, agent_tools_path)
        
        try:
            from remote_a2a.tableau_order_dispatch_revenue_ds_agent.tools.data_tools import run_sql_query_tool
            from remote_a2a.tableau_order_dispatch_revenue_ds_agent.shared_libraries import hyper_manager
        except ImportError:
            return json.dumps({
                "error": "SourceNotAvailable",
                "detail": "Could not import supplementary data source tools."
            })
        
        # Initialize Source if needed
        if not hyper_manager.is_dataset_available():
            hyper_manager.extract_hyper_at_startup(agent_dir)
        
        # Load schema
        schema_file = agent_dir / "docs" / "schema.json"
        with open(schema_file, 'r') as f:
            schema = json.load(f)
        
        default_columns = schema.get('default_columns', [])
        select_fields = [f'"{col["column_name"]}"' for col in default_columns]
        select_clause = ", ".join(select_fields)
        
        table = schema.get('table', 'Extract.Extract')
        schema_name, table_name = table.split('.') if '.' in table else ('Extract', table)
        
        # Determine filter column from contract or schema
        filter_col = "icc_cst_ctr_cd" # Fallback
        if contract:
            # Logic to find the matching dimension in the supplementary source
            pass

        sql_query = f'''
        SELECT {select_clause}
        FROM "{schema_name}"."{table_name}"
        WHERE "empty_call_dt" BETWEEN '{start_date}' AND '{end_date}'
          AND "{filter_col}" = '{dimension_value}'
        ORDER BY "empty_call_dt"
        '''
        
        result = run_sql_query_tool(sql_query, limit=1000)
        
        if not result.get("success"):
            return json.dumps({"error": "QueryError", "detail": result.get('detail')})
        
        data = result.get('data', [])
        cleaned_data = [{k.strip('"'): v for k, v in r.items()} for r in data]
        
        output = {
            "success": True,
            "period": {"start_date": start_date, "end_date": end_date},
            "dimension_value": dimension_value,
            "record_count": len(cleaned_data),
            "records": cleaned_data
        }
        
        return json.dumps(output, indent=2, default=str)
        
    except Exception as e:
        import traceback
        return json.dumps({
            "error": "UnexpectedError",
            "detail": str(e),
            "traceback": traceback.format_exc()
        })
