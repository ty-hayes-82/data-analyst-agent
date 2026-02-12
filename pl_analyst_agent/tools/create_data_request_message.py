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

"""Data request message generation for A2A agents."""

from typing import Dict


def create_data_request_message(
    current_cost_center: str,
    date_ranges: Dict[str, str],
    request_analysis: Dict
) -> str:
    """Create data request message for A2A agents.
    
    This replaces the LLM wrapper agents - we directly create the message
    that A2A agents need to see.
    
    Args:
        current_cost_center: Cost center code (e.g., "067")
        date_ranges: Dict with date range keys
        request_analysis: Dict with gl_accounts and analysis type
    
    Returns:
        Formatted data request message
    """
    gl_accounts = request_analysis.get("gl_accounts", [])
    gl_accounts_str = ", ".join([acc.replace("_", "-") for acc in gl_accounts])
    
    return f"""
[DATA REQUEST FOR COST CENTER {current_cost_center}]

Please retrieve the following data:

1. FINANCIAL DATA (Account Research DS):
   - Cost Center: {current_cost_center}
   - Date Range: {date_ranges['pl_query_start_date']} to {date_ranges['pl_query_end_date']}
   - GL Accounts: {gl_accounts_str}
   - Format: CSV export with columns: period, gl_account, amount, cost_center
   - Tool: Use export_bulk_data_tool for efficiency

2. OPERATIONAL METRICS (Ops Metrics DS):
   - Cost Center: {current_cost_center}
   - Date Range: {date_ranges['ops_metrics_query_start_date']} to {date_ranges['ops_metrics_query_end_date']}
   - Aggregate by: month (from empty_call_dt)
   - Format: CSV export
   - Tool: Use export_bulk_data_tool

3. ORDER DETAILS (conditional - only if needs_order_detail = true):
   - Cost Center: {current_cost_center}
   - Date Range: {date_ranges['order_query_start_date']} to {date_ranges['order_query_end_date']}
   - Format: CSV export with order-level detail
   - Tool: Use export_bulk_data_tool
"""

