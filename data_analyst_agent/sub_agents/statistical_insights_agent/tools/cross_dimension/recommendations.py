"""Recommendation builder for cross-dimension analysis."""
from __future__ import annotations

from typing import List


def build_recommendation(
    aux_name: str,
    explains: bool,
    interaction: bool,
    n_drags: int,
    n_boosts: int,
    patterns: List[dict],
    trends: List[dict],
) -> str:
    if not explains and not interaction:
        return f"{aux_name} does not significantly explain variance. No action needed."

    parts = []
    if explains:
        parts.append(f"{aux_name} is a significant secondary driver")
    if interaction:
        parts.append("specific combinations with the hierarchy dimension matter")
    if n_drags:
        top_drag = patterns[0]["auxiliary_value"] if patterns else "unknown"
        parts.append(f"{n_drags} cross-cutting drag(s) detected (top: {top_drag})")
    if trends:
        parts.append(f"{len(trends)} diverging trend(s)")

    return ". ".join(parts) + "."
