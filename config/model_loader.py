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

# Module-level override path. Set via set_config_override() or MODEL_CONFIG_PATH env var.
_config_override_path: str | None = None


def set_config_override(path: str) -> None:
  """Override the agent models config file path for all subsequent calls.

  Useful for benchmark runs that need to swap model configs without modifying
  the production agent_models.yaml. The path is resolved to an absolute path.

  Args:
    path: Absolute or relative path to an alternative agent_models YAML file.
  """
  global _config_override_path
  _config_override_path = os.path.abspath(path)


def clear_config_override() -> None:
  """Clear any programmatic config override, reverting to the default file
  (or MODEL_CONFIG_PATH env var if set)."""
  global _config_override_path
  _config_override_path = None


def _load_agent_models_config() -> dict[str, Any]:
  """Loads the agent models configuration from the YAML file.

  Resolution order:
  1. Programmatic override set via set_config_override()
  2. MODEL_CONFIG_PATH environment variable
  3. Default config/agent_models.yaml alongside this file
  """
  global _config_override_path
  config_path = (
    _config_override_path
    or os.environ.get("MODEL_CONFIG_PATH")
    or os.path.join(os.path.dirname(__file__), "agent_models.yaml")
  )
  with open(config_path, "r", encoding="utf-8") as f:
    return yaml.safe_load(f)


def _get_tier_for_agent(agent_name: str) -> dict[str, Any]:
  """Gets the full tier config dict for a given agent.

  Args:
    agent_name: The name of the agent.

  Returns:
    The tier configuration dict (contains 'model', 'thinking_level', etc.).
  """
  config = _load_agent_models_config()
  agent_config = config.get("agents", {}).get(agent_name)
  if agent_config and "tier" in agent_config:
    tier = agent_config["tier"]
    return config["model_tiers"][tier]

  default_tier = config["default_tier"]
  return config["model_tiers"][default_tier]


def get_agent_model(agent_name: str) -> str:
  """Gets the model for a given agent from the configuration.

  Args:
    agent_name: The name of the agent.

  Returns:
    The model name for the agent.
  """
  return _get_tier_for_agent(agent_name)["model"]


def get_agent_thinking_level(agent_name: str) -> str:
  """Gets the thinking level for a given agent from the configuration.

  Thinking levels control how much internal reasoning Gemini 3.0 Flash
  performs: 'minimal', 'low', 'medium', or 'high'.

  Args:
    agent_name: The name of the agent.

  Returns:
    The thinking level string (defaults to 'medium' if not configured).
  """
  tier_config = _get_tier_for_agent(agent_name)
  return tier_config.get("thinking_level", "medium")


def get_agent_thinking_config(agent_name: str):
  """Gets a ThinkingConfig object for a given agent.

  Returns a google.genai.types.ThinkingConfig appropriate for the agent's
  tier and model. Returns None for models that do not support thinking.

  Model families handled:
    gemini-2.5-flash-lite  — no thinking support
    gemini-2.5-flash       — thinking_budget_tokens (integer budget)
    gemini-2.5-pro         — include_thoughts + optional budget
    gemini-3.x-flash       — thinking_budget_tokens (same as 2.5-flash)
    gemini-3.x-pro         — include_thoughts + optional budget
    gemini-3.0-flash       — thinking_level string (legacy)

  Args:
    agent_name: The name of the agent.

  Returns:
    A ThinkingConfig instance, or None if the model does not support thinking.
  """
  tier_config = _get_tier_for_agent(agent_name)
  model = tier_config.get("model", "")
  level = tier_config.get("thinking_level")
  budget = tier_config.get("thinking_budget")

  if not model:
    return None

  from google.genai import types

  # --- Models with NO thinking support ---
  # Must be checked before broader substring matches below.
  _NO_THINKING = ("flash-lite", "gemini-2.0-flash", "embedding")
  if any(s in model for s in _NO_THINKING):
    return None

  # --- gemini-2.5-flash: thinking_budget (int) ---
  if "gemini-2.5-flash" in model:
    if budget is not None:
      try:
        return types.ThinkingConfig(thinking_budget=budget)
      except Exception:
        return None
    return None  # no explicit budget — use model default (no ThinkingConfig sent)

  # --- gemini-2.5-pro: include_thoughts + optional budget ---
  if "gemini-2.5-pro" in model:
    try:
      if budget:
        return types.ThinkingConfig(include_thoughts=True, thinking_budget=budget)
      return types.ThinkingConfig(include_thoughts=True)
    except Exception:
      return None

  # --- gemini-3.x flash: thinking_budget (same API as 2.5-flash) ---
  if "gemini-3" in model and "flash" in model:
    if budget is not None:
      try:
        return types.ThinkingConfig(thinking_budget=budget)
      except Exception:
        return None
    return None

  # --- gemini-3.x pro: include_thoughts + optional budget ---
  if "gemini-3" in model and "pro" in model:
    try:
      if budget:
        return types.ThinkingConfig(include_thoughts=True, thinking_budget=budget)
      return types.ThinkingConfig(include_thoughts=True)
    except Exception:
      return None

  # --- Fallback: thinking_level string (older model families) ---
  if not level:
    return None
  if budget and level == "high":
    try:
      return types.ThinkingConfig(include_thoughts=True, thinking_budget=budget)
    except Exception:
      pass
  try:
    return types.ThinkingConfig(thinking_level=level)
  except Exception:
    return None


def get_test_config() -> dict[str, Any]:
  """Gets the test configuration settings.

  Returns:
    Dictionary containing test configuration.
  """
  config = _load_agent_models_config()
  return config.get("test_config", {})

