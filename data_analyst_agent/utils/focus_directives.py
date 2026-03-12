from __future__ import annotations

from typing import Any, Mapping, Sequence

StateLike = Mapping[str, Any] | None


def _normalize_sequence(value: Any) -> list[str]:
    """Normalize focus modes from strings/lists/tuples."""
    if value is None:
        return []
    if isinstance(value, str):
        candidates: Sequence[Any] = [value]
    elif isinstance(value, Sequence):
        candidates = value
    else:
        candidates = [value]
    normalized: list[str] = []
    for item in candidates:
        text = str(item).strip()
        if not text:
            continue
        normalized.append(text)
    return normalized


def get_focus_modes(state: StateLike) -> list[str]:
    """Return analysis_focus as a normalized list of non-empty strings."""
    if not state:
        return []
    return _normalize_sequence(state.get("analysis_focus"))


def get_custom_focus(state: StateLike) -> str:
    """Return sanitized custom_focus text (single line)."""
    if not state:
        return ""
    raw = state.get("custom_focus")
    if raw is None:
        return ""
    text = str(raw).strip()
    if not text:
        return ""
    # Collapse internal whitespace/newlines to single spaces.
    parts = text.split()
    return " ".join(parts).strip()


def focus_lines(state: StateLike, *, include_labels: bool = True) -> list[str]:
    """Return formatted focus directive lines for prompts."""
    modes = get_focus_modes(state)
    custom = get_custom_focus(state)
    if not modes and not custom:
        return []

    lines: list[str] = []
    if modes:
        label = "Focus modes to prioritize" if include_labels else ""
        value = ", ".join(modes)
        lines.append(f"{label}: {value}" if label else value)
    if custom:
        label = "Custom directive" if include_labels else ""
        lines.append(f"{label}: {custom}" if label else custom)
    return lines


def focus_block(state: StateLike, *, header: str = "FOCUS_DIRECTIVES", include_labels: bool = True) -> str:
    """Return a formatted block suitable for appending to instructions."""
    lines = focus_lines(state, include_labels=include_labels)
    if not lines:
        return ""
    line_text = "\n".join(lines)
    return f"{header}:\n{line_text}"


def augment_instruction(base_instruction: str, state: StateLike, *, suffix: str | None = None) -> str:
    """Append focus directives to an instruction string when present."""
    block = focus_block(state)
    if not block:
        return base_instruction
    suffix_text = f"\n{suffix}" if suffix else ""
    return f"{base_instruction}\n\n{block}{suffix_text}"


def focus_payload(state: StateLike) -> dict[str, Any]:
    """Return structured payload for downstream JSON prompts."""
    return {
        "modes": get_focus_modes(state),
        "custom_directive": get_custom_focus(state),
    }


def focus_search_text(state: StateLike) -> str:
    """Return free-form text blob for keyword routing/refinement."""
    modes = get_focus_modes(state)
    custom = get_custom_focus(state)
    return " ".join([*modes, custom]).strip()
