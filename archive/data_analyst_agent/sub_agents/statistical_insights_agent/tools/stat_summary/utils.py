"""Utilities shared across the statistical summary helpers."""

from __future__ import annotations

import numpy as np


def json_default(value):
    """JSON serializer that handles NumPy scalar types."""
    if isinstance(value, np.generic):
        return value.item()
    return str(value)
