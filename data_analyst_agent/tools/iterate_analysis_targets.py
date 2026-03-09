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

"""Analysis target iteration tool for loop control."""

from typing import Dict, Any, Tuple, Optional


def iterate_analysis_targets(
    extracted_targets: list, 
    loop_state: Optional[Dict[str, Any]] = None,
    target_label: str = "Analysis Target"
) -> Tuple[Optional[str], Dict[str, Any], bool]:
    """Iterate through analysis targets for loop control.
    
    Args:
        extracted_targets: List of target strings
        loop_state: Current loop state dict (contains target_index)
        target_label: Label for the target (e.g. "Metric")
        
    Returns:
        Tuple of (current_target, updated_loop_state, is_complete)
        - current_target: The next target to process (None if done)
        - updated_loop_state: Updated loop state dict
        - is_complete: True if all targets have been processed
    """
    if loop_state is None:
        loop_state = {}
    
    index = loop_state.get("target_index", 0)
    
    # Check if we're done
    if index >= len(extracted_targets):
        print(f"\n{'='*80}")
        print(f"[Iterator] All {len(extracted_targets)} {target_label.lower()}s processed successfully!")
        print(f"{'='*80}\n")
        return None, loop_state, True
    
    # Get current target and increment index for next iteration
    current_target = extracted_targets[index]
    loop_state["target_index"] = index + 1
    
    print(f"\n{'='*80}")
    print(f"[{target_label} {index + 1}/{len(extracted_targets)}] Starting analysis for {target_label.lower()}: {current_target}")
    print(f"{'='*80}\n")
    
    return current_target, loop_state, False
