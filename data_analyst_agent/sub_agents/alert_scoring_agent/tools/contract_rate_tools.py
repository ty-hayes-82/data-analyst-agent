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
Contract Rate Tools for Alert Scoring Coordinator Agent.
Fetches major shippers and their AS400 contract rates.
"""

import json
import sys
import re
from pathlib import Path


async def process_shippers_and_get_rates(
    shippers_json: str,
    analysis_target: str,
    market_share_threshold: float = 5.0
) -> str:
    """Process top shippers data and get AS400 contract rates for major shippers.
    
    This function:
    1. Parses the JSON response from tableau_order_dispatch_revenue_ds_agent
    2. Filters for shippers with >threshold% market share
    3. Queries AS400 for contract rates for each major shipper
    
    Args:
        shippers_json: JSON string from tableau_order_dispatch_revenue_ds_agent with top shippers data
        analysis_target: Target ID (e.g., "497", "067")
        market_share_threshold: Minimum market share % to include (default: 5.0)
        
    Returns:
        JSON string with major shippers and their contract rates
    """
    try:
        project_root = Path(__file__).parent.parent.parent
        
        # Parse the shippers data from tableau agent
        print(f"[INFO] Parsing top shippers data for target {analysis_target}...")
        
        # The input might be a string or already parsed JSON
        if isinstance(shippers_json, str):
            # Try to extract JSON from markdown code blocks if present
            json_match = re.search(r'```json\s*(\{.*?\})\s*```', shippers_json, re.DOTALL)
            if json_match:
                shippers_json = json_match.group(1)
            
            try:
                shippers_data = json.loads(shippers_json)
            except json.JSONDecodeError as e:
                return json.dumps({
                    "success": False,
                    "error_message": f"Failed to parse shippers JSON: {str(e)}"
                })
        else:
            shippers_data = shippers_json
        
        # Extract top shippers list from the data
        # The tableau agent might return data in different formats, so we need to handle multiple cases
        top_shippers = []
        
        # Case 1: Direct array of shippers
        if isinstance(shippers_data, list):
            top_shippers = shippers_data
        # Case 2: Object with 'top_shippers' key (from get_top_entities_by_metric tool)
        elif isinstance(shippers_data, dict) and 'top_shippers' in shippers_data:
            top_shippers = shippers_data.get('top_shippers', [])
        # Case 3: SQL query result format with 'data' key
        elif isinstance(shippers_data, dict) and 'data' in shippers_data:
            top_shippers = shippers_data.get('data', [])
        # Case 4: Extract from any 'results' key
        elif isinstance(shippers_data, dict) and 'results' in shippers_data:
            top_shippers = shippers_data.get('results', [])
        else:
            return json.dumps({
                "success": False,
                "error_message": f"Unexpected shippers data format. Keys: {list(shippers_data.keys()) if isinstance(shippers_data, dict) else 'not a dict'}"
            })
        
        if not top_shippers:
            return json.dumps({
                "success": True,
                "dimension_value": analysis_target,
                "market_share_threshold": market_share_threshold,
                "major_shippers": [],
                "total_major_shippers": 0,
                "message": "No shippers data found"
            })
        
        print(f"[INFO] Found {len(top_shippers)} total shippers")
        
        # Calculate total miles across all shippers to compute market share if not already provided
        total_miles = 0
        for shipper in top_shippers:
            # Handle different field name variations
            miles = (shipper.get('total_loaded_miles', 0) or 
                    shipper.get('loaded_miles', 0) or 
                    shipper.get('miles', 0) or 0)
            total_miles += float(miles)
        
        # Filter shippers with >threshold% market share
        major_shippers = []
        for shipper in top_shippers:
            # Get miles
            miles = (shipper.get('total_loaded_miles', 0) or 
                    shipper.get('loaded_miles', 0) or 
                    shipper.get('miles', 0) or 0)
            miles = float(miles)
            
            # Calculate market share if not provided
            if 'percent_of_total_miles' in shipper:
                market_share = float(shipper.get('percent_of_total_miles', 0))
            elif total_miles > 0:
                market_share = (miles / total_miles) * 100
            else:
                market_share = 0
            
            if market_share >= market_share_threshold:
                # Normalize shipper data
                normalized_shipper = {
                    'shipper_code': str(shipper.get('shipper_code', '') or shipper.get('shpr_cd', '')),
                    'shipper_name': str(shipper.get('shipper_name', '') or shipper.get('shpr_nm', '')),
                    'total_loaded_miles': miles,
                    'total_revenue': float(shipper.get('total_revenue', 0) or shipper.get('revenue', 0) or 0),
                    'order_count': int(shipper.get('order_count', 0) or shipper.get('orders', 0) or 0),
                    'percent_of_total_miles': market_share
                }
                major_shippers.append(normalized_shipper)
        
        print(f"[INFO] Found {len(major_shippers)} shippers with >{market_share_threshold}% market share")
        
        if not major_shippers:
            return json.dumps({
                "success": True,
                "dimension_value": analysis_target,
                "market_share_threshold": market_share_threshold,
                "major_shippers": [],
                "total_major_shippers": 0,
                "message": f"No shippers found with >{market_share_threshold}% market share"
            })
        
        # Query AS400 contract rates for each major shipper
        print(f"[INFO] Querying AS400 contract rates for {len(major_shippers)} shippers...")
        
        # Import AS400 agent function
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))
        
        from remote_a2a.as400_contract_accessorial_rates_agent.agent import check_contract_accessorial_rates
        
        results = []
        for shipper in major_shippers:
            shipper_code = shipper.get("shipper_code", "")
            shipper_name = shipper.get("shipper_name", "")
            market_share = shipper.get("percent_of_total_miles", 0)
            
            print(f"[INFO]   Querying rates for {shipper_code} ({shipper_name}) - {market_share:.1f}% market share...")
            
            try:
                # Query AS400 for this shipper's contract rates
                rates_result = await check_contract_accessorial_rates(shipper_code)
                rates_data = json.loads(rates_result)
                
                # Compile shipper info with their contract rates
                shipper_info = {
                    "shipper_code": shipper_code,
                    "shipper_name": shipper_name,
                    "market_share_percent": market_share,
                    "total_loaded_miles": shipper.get("total_loaded_miles", 0),
                    "total_revenue": shipper.get("total_revenue", 0),
                    "order_count": shipper.get("order_count", 0),
                    "avg_revenue_per_order": shipper.get("total_revenue", 0) / shipper.get("order_count", 1) if shipper.get("order_count", 0) > 0 else 0,
                    "contract_rates": {
                        "success": not rates_data.get("error"),
                        "total_rates": rates_data.get("total_records", 0) if not rates_data.get("error") else 0,
                        "rates": rates_data.get("results", []) if not rates_data.get("error") else [],
                        "error": rates_data.get("error") if rates_data.get("error") else None
                    }
                }
                
                results.append(shipper_info)
                
                if rates_data.get("error"):
                    print(f"[WARNING]   No contract rates found for {shipper_code}: {rates_data.get('detail')}")
                else:
                    print(f"[INFO]   Found {rates_data.get('total_records', 0)} active contract rates for {shipper_code}")
                    
            except Exception as e:
                print(f"[ERROR]   Failed to get rates for {shipper_code}: {str(e)}")
                shipper_info = {
                    "shipper_code": shipper_code,
                    "shipper_name": shipper_name,
                    "market_share_percent": market_share,
                    "total_loaded_miles": shipper.get("total_loaded_miles", 0),
                    "total_revenue": shipper.get("total_revenue", 0),
                    "order_count": shipper.get("order_count", 0),
                    "avg_revenue_per_order": 0,
                    "contract_rates": {
                        "success": False,
                        "total_rates": 0,
                        "rates": [],
                        "error": f"Exception: {str(e)}"
                    }
                }
                results.append(shipper_info)
        
        # Create summary
        total_rates_found = sum(s["contract_rates"]["total_rates"] for s in results)
        shippers_with_rates = sum(1 for s in results if s["contract_rates"]["total_rates"] > 0)
        
        response = {
            "success": True,
            "dimension_value": analysis_target,
            "market_share_threshold": market_share_threshold,
            "total_major_shippers": len(results),
            "shippers_with_contract_rates": shippers_with_rates,
            "total_contract_rates_found": total_rates_found,
            "major_shippers": results
        }
        
        # Save to file
        output_dir = project_root / "outputs"
        output_dir.mkdir(exist_ok=True)
        output_file = output_dir / f"major_shippers_with_rates_{analysis_target}.json"
        
        try:
            with open(output_file, 'w') as f:
                json.dump(response, f, indent=2)
            print(f"[INFO] Major shippers with contract rates saved to: {output_file}")
        except Exception as e:
            print(f"[WARNING] Could not save results: {e}")
        
        return json.dumps(response, indent=2)
        
    except Exception as e:
        import traceback
        return json.dumps({
            "success": False,
            "error_message": f"Unexpected error: {str(e)}\n{traceback.format_exc()}"
        })


async def get_major_shippers_with_contract_rates(
    start_date: str,
    end_date: str,
    analysis_target: str,
    market_share_threshold: float = 5.0
) -> str:
    """Get major shippers (>5% market share) and their AS400 contract rates.
    
    This is a two-step process:
    1. Query Order Dispatch Revenue DS to get top shippers by miles
    2. For shippers with >threshold% market share, query AS400 for contract rates
    
    Args:
        start_date: Start date for the period in YYYY-MM-DD format (e.g., "2025-06-01")
        end_date: End date for the period in YYYY-MM-DD format (e.g., "2025-06-30")
        analysis_target: Target ID to filter by (e.g., "497", "094")
        market_share_threshold: Minimum market share % to include (default: 5.0)
        
    Returns:
        JSON string with shipper information and their contract rates
    """
    try:
        project_root = Path(__file__).parent.parent.parent
        
        # Step 1: Get top shippers by miles
        print(f"[INFO] Step 1: Getting top shippers for target {analysis_target}...")
        shippers_result = await get_top_entities_by_metric(
            start_date=start_date,
            end_date=end_date,
            analysis_target=analysis_target,
            top_n=50  # Get top 50 to ensure we capture all >5% shippers
        )
        
        shippers_data = json.loads(shippers_result)
        
        if not shippers_data.get("success"):
            return json.dumps({
                "success": False,
                "error_message": f"Failed to get top shippers: {shippers_data.get('error_message')}"
            })
        
        # Step 2: Filter shippers with >threshold% market share
        major_shippers = [
            s for s in shippers_data.get("top_shippers", [])
            if s.get("percent_of_total_miles", 0) >= market_share_threshold
        ]
        
        print(f"[INFO] Found {len(major_shippers)} shippers with >{market_share_threshold}% market share")
        
        if not major_shippers:
            return json.dumps({
                "success": True,
                "dimension_value": analysis_target,
                "period_start": start_date,
                "period_end": end_date,
                "market_share_threshold": market_share_threshold,
                "major_shippers": [],
                "total_major_shippers": 0,
                "message": f"No shippers found with >{market_share_threshold}% market share"
            })
        
        # Step 3: Query AS400 contract rates for each major shipper
        print(f"[INFO] Step 2: Querying AS400 contract rates for {len(major_shippers)} shippers...")
        
        # Import AS400 agent function
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))
        
        from remote_a2a.as400_contract_accessorial_rates_agent.agent import check_contract_accessorial_rates
        
        results = []
        for shipper in major_shippers:
            shipper_code = shipper.get("shipper_code", "")
            shipper_name = shipper.get("shipper_name", "")
            market_share = shipper.get("percent_of_total_miles", 0)
            
            print(f"[INFO]   Querying rates for {shipper_code} ({shipper_name}) - {market_share:.1f}% market share...")
            
            try:
                # Query AS400 for this shipper's contract rates
                rates_result = await check_contract_accessorial_rates(shipper_code)
                rates_data = json.loads(rates_result)
                
                # Compile shipper info with their contract rates
                shipper_info = {
                    "shipper_code": shipper_code,
                    "shipper_name": shipper_name,
                    "market_share_percent": market_share,
                    "total_loaded_miles": shipper.get("total_loaded_miles", 0),
                    "total_revenue": shipper.get("total_revenue", 0),
                    "order_count": shipper.get("order_count", 0),
                    "avg_revenue_per_order": shipper.get("avg_revenue_per_order", 0),
                    "contract_rates": {
                        "success": not rates_data.get("error"),
                        "total_rates": rates_data.get("total_records", 0) if not rates_data.get("error") else 0,
                        "rates": rates_data.get("results", []) if not rates_data.get("error") else [],
                        "error": rates_data.get("error") if rates_data.get("error") else None
                    }
                }
                
                results.append(shipper_info)
                
                if rates_data.get("error"):
                    print(f"[WARNING]   No contract rates found for {shipper_code}: {rates_data.get('detail')}")
                else:
                    print(f"[INFO]   Found {rates_data.get('total_records', 0)} active contract rates for {shipper_code}")
                    
            except Exception as e:
                print(f"[ERROR]   Failed to get rates for {shipper_code}: {str(e)}")
                shipper_info = {
                    "shipper_code": shipper_code,
                    "shipper_name": shipper_name,
                    "market_share_percent": market_share,
                    "total_loaded_miles": shipper.get("total_loaded_miles", 0),
                    "total_revenue": shipper.get("total_revenue", 0),
                    "order_count": shipper.get("order_count", 0),
                    "avg_revenue_per_order": shipper.get("avg_revenue_per_order", 0),
                    "contract_rates": {
                        "success": False,
                        "total_rates": 0,
                        "rates": [],
                        "error": f"Exception: {str(e)}"
                    }
                }
                results.append(shipper_info)
        
        # Create summary
        total_rates_found = sum(s["contract_rates"]["total_rates"] for s in results)
        shippers_with_rates = sum(1 for s in results if s["contract_rates"]["total_rates"] > 0)
        
        response = {
            "success": True,
            "dimension_value": analysis_target,
            "period_start": start_date,
            "period_end": end_date,
            "market_share_threshold": market_share_threshold,
            "total_major_shippers": len(results),
            "shippers_with_contract_rates": shippers_with_rates,
            "total_contract_rates_found": total_rates_found,
            "major_shippers": results
        }
        
        # Save to file
        output_dir = project_root / "outputs"
        output_dir.mkdir(exist_ok=True)
        output_file = output_dir / f"major_shippers_with_rates_{analysis_target}_{start_date}_{end_date}.json"
        
        try:
            with open(output_file, 'w') as f:
                json.dump(response, f, indent=2)
            print(f"[INFO] Major shippers with contract rates saved to: {output_file}")
        except Exception as e:
            print(f"[WARNING] Could not save results: {e}")
        
        return json.dumps(response, indent=2)
        
    except Exception as e:
        import traceback
        return json.dumps({
            "success": False,
            "error_message": f"Unexpected error: {str(e)}\n{traceback.format_exc()}"
        })

