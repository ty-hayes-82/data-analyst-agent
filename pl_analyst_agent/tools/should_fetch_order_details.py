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

"""Determine if order details should be fetched based on request analysis."""

from typing import Any, Dict


def should_fetch_order_details(request_analysis: Any) -> bool:
    """Check if order details should be fetched based on request type.
    
    Args:
        request_analysis: The request analysis output (could be string or dict)
        
    Returns:
        True if order details should be fetched, False otherwise
    """
    # Convert to string for checking
    analysis_str = str(request_analysis).lower() if request_analysis else ""
    
    # Check for contract validation indicators
    needs_order_details = (
        "contract" in analysis_str or
        "billing" in analysis_str or
        "recovery" in analysis_str or
        "needs_order_detail" in analysis_str
    )
    
    if needs_order_details:
        print("[Conditional Logic] Contract validation requested - will fetch order details")
    else:
        print("[Conditional Logic] No contract validation needed - will skip order details")
    
    return needs_order_details

