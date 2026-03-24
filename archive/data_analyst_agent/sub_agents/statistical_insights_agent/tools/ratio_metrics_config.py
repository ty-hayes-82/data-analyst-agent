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

"""Backward-compatible re-export; implementation lives in ``semantic``."""

from data_analyst_agent.semantic.ratio_metrics_config import (  # noqa: F401
    get_ratio_config_for_metric,
    get_ratio_config_from_contract_derived_kpis,
)
