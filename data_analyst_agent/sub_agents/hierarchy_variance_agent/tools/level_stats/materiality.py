"""Materiality helpers for hierarchy variance level stats."""
from __future__ import annotations

from typing import Tuple, Any

from config.materiality_loader import (
    get_thresholds_for_category,  # noqa: F401 (re-export for legacy callers)
    get_global_defaults,
)


def get_materiality_thresholds(ctx: Any) -> Tuple[float, float]:
    """Return the (pct, dollar) materiality thresholds for the current context."""
    pct_threshold = 5.0
    dollar_threshold = 50000.0

    if ctx and ctx.contract:
        materiality = getattr(ctx.contract, "materiality", {}) or {}
        pct_threshold = materiality.get("variance_pct", pct_threshold)
        dollar_threshold = materiality.get("variance_absolute", dollar_threshold)
    else:
        try:
            defaults = get_global_defaults()
            pct_threshold = defaults.get("variance_pct", pct_threshold)
            dollar_threshold = defaults.get("variance_dollar", dollar_threshold)
        except Exception:
            # Defaults loader is best-effort; fall back to constants when unavailable.
            pass

    return pct_threshold, dollar_threshold
