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
Shared ResolvedDataBundle for passing pre-resolved data to statistical sub-tools
to avoid redundant resolve_data_and_columns calls.
"""

from typing import Any, Dict, Optional
import pandas as pd


def build_resolved_bundle(
    df: pd.DataFrame,
    pivot: pd.DataFrame,
    time_col: str,
    metric_col: str,
    grain_col: str,
    name_col: str,
    ctx: Any,
    names_map: Optional[Dict[Any, Any]] = None,
    monthly_totals: Optional[Dict[str, float]] = None,
    lag_metadata: Optional[Dict[str, Any]] = None,
) -> dict:
    """
    Build a ResolvedDataBundle from pre-resolved data.
    
    Returns a dict that sub-tools can use instead of calling resolve_data_and_columns.
    """
    if names_map is None:
        names_map = dict(zip(df[grain_col], df[name_col]))
    
    return {
        "df": df,
        "pivot": pivot,
        "time_col": time_col,
        "metric_col": metric_col,
        "grain_col": grain_col,
        "name_col": name_col,
        "ctx": ctx,
        "names_map": names_map,
        "monthly_totals": monthly_totals or {},
        "lag_metadata": lag_metadata,
    }
