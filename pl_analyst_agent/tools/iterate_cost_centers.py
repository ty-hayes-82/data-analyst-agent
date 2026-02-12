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

"""Cost center iteration tool for loop control."""

from typing import Dict, Any, Tuple, Optional


def iterate_cost_centers(
    extracted_cost_centers: list, 
    loop_state: Optional[Dict[str, Any]] = None
) -> Tuple[Optional[str], Dict[str, Any], bool]:
    """Iterate through cost centers for loop control.
    
    Args:
        extracted_cost_centers: List of cost center strings
        loop_state: Current loop state dict (contains cost_center_index)
        
    Returns:
        Tuple of (current_cost_center, updated_loop_state, is_complete)
        - current_cost_center: The next cost center to process (None if done)
        - updated_loop_state: Updated loop state dict
        - is_complete: True if all cost centers have been processed
    """
    if loop_state is None:
        loop_state = {}
    
    index = loop_state.get("cost_center_index", 0)
    
    # Check if we're done
    if index >= len(extracted_cost_centers):
        print(f"\n{'='*80}")
        print(f"[Iterator] All {len(extracted_cost_centers)} cost centers processed successfully!")
        print(f"{'='*80}\n")
        return None, loop_state, True
    
    # Get current cost center and increment index for next iteration
    current_cc = extracted_cost_centers[index]
    loop_state["cost_center_index"] = index + 1
    
    print(f"\n{'='*80}")
    print(f"[Cost Center {index + 1}/{len(extracted_cost_centers)}] Starting analysis for cost center: {current_cc}")
    print(f"{'='*80}\n")
    
    return current_cc, loop_state, False

