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

"""Determine if supplementary data should be fetched based on request analysis."""

from typing import Any, Dict, Optional


def should_fetch_supplementary_data(request_analysis: Any, contract: Optional[Any] = None) -> bool:
    """Check if supplementary or detail data should be fetched.
    
    Args:
        request_analysis: The request analysis output (could be string or dict)
        contract: Optional DatasetContract to check for supplementary sources
        
    Returns:
        True if supplementary data should be fetched, False otherwise
    """
    import json
    
    # Check if the contract explicitly mandates supplementary data for certain analysis types
    if contract and hasattr(contract, 'policies') and hasattr(contract.policies, 'supplementary_data_trigger'):
        analysis_type = None
        if isinstance(request_analysis, dict):
            analysis_type = request_analysis.get("analysis_type")
        elif isinstance(request_analysis, str):
            try:
                data = json.loads(request_analysis)
                analysis_type = data.get("analysis_type")
            except:
                pass
        
        if analysis_type and analysis_type in contract.policies.supplementary_data_trigger:
            print(f"[Conditional Logic] Contract policy triggers supplementary data for analysis type '{analysis_type}'")
            return True

    # 1. Handle dictionary
    if isinstance(request_analysis, dict):
        # Check explicit flag
        if request_analysis.get("needs_supplementary_data") is True or request_analysis.get("needs_order_detail") is True:
            print("[Conditional Logic] Explicitly requested supplementary data")
            return True
            
        analysis_str = json.dumps(request_analysis).lower()
    else:
        # Convert to string for checking
        analysis_str = str(request_analysis).lower() if request_analysis else ""
    
    # 2. Try to parse as JSON if it's a string
    try:
        data = json.loads(analysis_str)
        if isinstance(data, dict):
            if data.get("needs_supplementary_data") is True or data.get("needs_order_detail") is True:
                print("[Conditional Logic] Explicitly requested supplementary data (parsed JSON)")
                return True
    except:
        pass

    # 3. Fallback to keyword check
    # These keywords are generic indicators that detail-level investigation is needed
    keywords = ["detailed validation", "data validation", "anomaly detection", "root cause", "drill down", "leakage"]
    needs_supplementary = any(kw in analysis_str for kw in keywords)
    
    if needs_supplementary:
        print("[Conditional Logic] Keywords suggest supplementary data needed")
    else:
        print("[Conditional Logic] No supplementary data needed")
    
    return needs_supplementary
