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

"""Date range calculation for data queries."""

from datetime import datetime, timedelta
from typing import Dict


def calculate_date_ranges() -> Dict[str, str]:
    """Calculate date ranges for data queries.
    
    Returns:
        Dict with keys: pl_query_start_date, pl_query_end_date,
        ops_metrics_query_start_date, ops_metrics_query_end_date,
        order_query_start_date, order_query_end_date
    """
    today = datetime.now()
    pl_start = (today - timedelta(days=730)).strftime("%Y-%m-%d")
    order_start = (today - timedelta(days=90)).strftime("%Y-%m-%d")
    current_date = today.strftime("%Y-%m-%d")
    
    return {
        "primary_query_start_date": pl_start,
        "primary_query_end_date": current_date,
        "supplementary_query_start_date": pl_start,
        "supplementary_query_end_date": current_date,
        "detail_query_start_date": order_start,
        "detail_query_end_date": current_date,
    }

