"""Configuration flags for the hierarchical analysis agent."""

from __future__ import annotations

import os

USE_CODE_INSIGHTS = os.environ.get("USE_CODE_INSIGHTS", "true").lower() == "true"
CROSS_DIMENSION_ANALYSIS = os.environ.get("CROSS_DIMENSION_ANALYSIS", "false").lower() == "true"
INDEPENDENT_LEVEL_ANALYSIS = os.environ.get("INDEPENDENT_LEVEL_ANALYSIS", "false").lower() == "true"
INDEPENDENT_LEVEL_MAX_CARDS = max(1, int(os.environ.get("INDEPENDENT_LEVEL_MAX_CARDS", "5")))
