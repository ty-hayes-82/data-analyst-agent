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

"""Cost center parsing utilities."""

import json
import re
from typing import List, Union


def parse_cost_centers(raw_output: Union[str, List]) -> List[str]:
    """Parse cost center JSON string into list.
    
    Args:
        raw_output: JSON string like '["067", "385"]' or with markdown, or already a list
    
    Returns:
        List of cost center strings
    """
    if isinstance(raw_output, list):
        return [str(cc).strip() for cc in raw_output]
    
    # Remove markdown code blocks
    raw_str = str(raw_output)
    raw_str = re.sub(r'```json\s*', '', raw_str)
    raw_str = re.sub(r'```\s*', '', raw_str)
    
    try:
        cost_centers = json.loads(raw_str.strip())
        if not isinstance(cost_centers, list):
            cost_centers = [str(cost_centers)]
    except json.JSONDecodeError:
        cost_centers = []
    
    return [str(cc).strip() for cc in cost_centers]

