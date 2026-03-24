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
# WITHOUT WARRANTIES OR ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Hierarchy Variance Ranker Agent exports."""

from typing import Any

__all__ = ["root_agent"]


def __getattr__(name: str) -> Any:
    if name == "root_agent":
        from .agent import root_agent as _root_agent

        return _root_agent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
