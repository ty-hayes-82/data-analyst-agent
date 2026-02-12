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

from __future__ import annotations

import os
from typing import Any

import yaml


def _load_agent_models_config() -> dict[str, Any]:
  """Loads the agent models configuration from the YAML file."""
  config_path = os.path.join(os.path.dirname(__file__), "agent_models.yaml")
  with open(config_path, "r", encoding="utf-8") as f:
    return yaml.safe_load(f)


def get_agent_model(agent_name: str) -> str:
  """Gets the model for a given agent from the configuration.

  Args:
    agent_name: The name of the agent.

  Returns:
    The model name for the agent.
  """
  config = _load_agent_models_config()
  agent_config = config.get("agents", {}).get(agent_name)
  if agent_config and "tier" in agent_config:
    tier = agent_config["tier"]
    return config["model_tiers"][tier]["model"]

  default_tier = config["default_tier"]
  return config["model_tiers"][default_tier]["model"]


def get_test_config() -> dict[str, Any]:
  """Gets the test configuration settings.

  Returns:
    Dictionary containing test configuration.
  """
  config = _load_agent_models_config()
  return config.get("test_config", {})

