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
Environment variable utility functions.
"""

from __future__ import annotations
from typing import Optional


def parse_bool_env(value: Optional[str]) -> bool:
    """
    Parse a string value into a boolean.
    Accepts truthy values like '1', 'true', 'yes', 'on' (case-insensitive).
    """
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}
