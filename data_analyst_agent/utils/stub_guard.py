"""Helpers to detect and gate stubbed LLM outputs."""

from __future__ import annotations

import json
import os
from typing import Any

from .env_utils import parse_bool_env

_STUB_MARKERS = (
    "# stub report",
    "stub action with specificity",
    "stub narrative (llm disabled)",
    "stub executive summary",
    "stub variance narrative",
)


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.lower()
    try:
        serialized = json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        serialized = str(value)
    return serialized.lower()


def contains_stub_content(value: Any) -> bool:
    """Return True when the payload includes known stub placeholders."""
    text = _normalize_text(value)
    if not text:
        return False
    return any(marker in text for marker in _STUB_MARKERS)


def stub_outputs_allowed() -> bool:
    """Whether stubbed outputs are explicitly permitted via env flag."""
    return parse_bool_env(os.environ.get("DATA_ANALYST_ALLOW_STUB_OUTPUTS"))
