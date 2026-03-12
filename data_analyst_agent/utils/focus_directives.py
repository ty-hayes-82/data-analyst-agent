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


def parse_focus_directives(state: StateLike) -> list[str]:
    """Extract and normalize focus mode directives from session state.
    
    Reads analysis_focus from state and normalizes it to a list of non-empty
    strings. Handles string, list, tuple, or None inputs.
    
    Args:
        state: Session state dict-like object or None. Expects 'analysis_focus' key.
    
    Returns:
        list[str]: Normalized list of focus mode strings. Empty list if none found.
    
    Example:
        >>> state = {"analysis_focus": "recent_weekly_trends,seasonality"}
        >>> parse_focus_directives(state)
        ['recent_weekly_trends', 'seasonality']
        
        >>> state = {"analysis_focus": ["recent_monthly_trends"]}
        >>> parse_focus_directives(state)
        ['recent_monthly_trends']
    
    Note:
        - Trims whitespace from each directive
        - Filters out empty strings
        - Returns empty list if state is None or missing analysis_focus key
    """
    return get_focus_modes(state)


def get_focus_modes(state: StateLike) -> list[str]:
    """Return analysis_focus as a normalized list of non-empty strings.
    
    (Internal implementation for parse_focus_directives)
    """
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
    """Append focus directives to an LLM instruction prompt when present.
    
    This function dynamically augments agent prompts with user-provided focus
    directives (analysis_focus and custom_focus from session state). It formats
    them into a FOCUS_DIRECTIVES block and appends to the base instruction.
    
    Used by: PlannerAgent, NarrativeAgent, and other LLM agents to incorporate
    user focus preferences into their prompts.
    
    Args:
        base_instruction: Original agent instruction string (e.g., PLANNER_INSTRUCTION).
        state: Session state dict-like object containing:
            - analysis_focus: List/string of focus modes (e.g., ["recent_weekly_trends"])
            - custom_focus: Free-text custom focus directive
        suffix: Optional additional text to append after focus block (default None).
    
    Returns:
        str: Augmented instruction with focus directives appended.
            If no focus directives present, returns base_instruction unchanged.
    
    Format:
        {base_instruction}
        
        FOCUS_DIRECTIVES:
        Focus modes to prioritize: recent_weekly_trends, seasonality
        Custom directive: Focus on revenue drivers in Retail LOB
        {suffix}
    
    Example:
        >>> state = {
        ...     "analysis_focus": ["recent_weekly_trends"],
        ...     "custom_focus": "Compare Retail vs Wholesale LOBs"
        ... }
        >>> base = "You are a planner agent. Select analysis methods."
        >>> augmented = augment_instruction(base, state)
        >>> print(augmented)
        >>> # You are a planner agent. Select analysis methods.
        >>> # 
        >>> # FOCUS_DIRECTIVES:
        >>> # Focus modes to prioritize: recent_weekly_trends
        >>> # Custom directive: Compare Retail vs Wholesale LOBs
    
    Note:
        - Returns base_instruction unchanged if state is None or empty
        - focus_block() handles formatting of the FOCUS_DIRECTIVES section
        - suffix is appended on a new line if provided
    """
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
    """Extract focus directives as a single text blob for keyword matching.
    
    Combines analysis_focus modes and custom_focus text into a single space-separated
    string. Used by PlannerAgent for keyword-based agent selection refinement.
    
    Args:
        state: Session state dict-like object containing:
            - analysis_focus: List/string of focus modes
            - custom_focus: Free-text custom focus directive
    
    Returns:
        str: Space-separated concatenation of all focus text.
            Empty string if no focus directives present.
    
    Example:
        >>> state = {
        ...     "analysis_focus": ["seasonality", "anomalies"],
        ...     "custom_focus": "drill into Retail performance"
        ... }
        >>> focus_search_text(state)
        'seasonality anomalies drill into Retail performance'
        
        >>> # Used by planner for keyword matching:
        >>> text = focus_search_text(state)
        >>> if "seasonality" in text.lower():
        ...     # Add SeasonalDecompositionAgent to plan
    
    Note:
        - Trims and joins all focus text with spaces
        - Returns empty string if state is None or has no focus directives
        - Used by refine_plan() in planner_agent for keyword-based agent routing
    """
    modes = get_focus_modes(state)
    custom = get_custom_focus(state)
    return " ".join([*modes, custom]).strip()
