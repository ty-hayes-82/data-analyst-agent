from pathlib import Path


def load_dataset_specific_append() -> str:
    """Load optional dataset-specific prompt fragment from config/datasets/<active>/executive_brief_append.txt.

    Add dataset-specific context (industry, metrics, domain guidance) without modifying the base prompt.
    Returns empty string if the file does not exist. The content is inserted at {dataset_specific_append}.
    """
    try:
        from config.dataset_resolver import get_dataset_path_optional
        path = get_dataset_path_optional("executive_brief_append.txt")
        if path and path.exists():
            return "\n\n" + path.read_text(encoding="utf-8", errors="replace").strip()
    except Exception:
        pass
    return ""


def load_prompt_variant(name: str) -> str:
    """Load prompt variant by name (Spec 031). 'default' returns empty append; others load from config/prompts/executive_brief/.

    Variants are appended to the base EXECUTIVE_BRIEF_INSTRUCTION. Use with --prompt-variant in regenerate script.
    """
    if not name or name.lower() == "default":
        return ""
    try:
        config_dir = Path(__file__).resolve().parent.parent.parent.parent / "config" / "prompts" / "executive_brief"
        path = config_dir / f"{name.lower().replace(' ', '_')}.txt"
        if path.exists():
            return "\n\n" + path.read_text(encoding="utf-8", errors="replace").strip()
    except Exception:
        pass
    return ""


SCOPED_BRIEF_PREAMBLE = """

SCOPE RESTRICTION: This brief covers the {scope_level_name} scope: **{scope_entity}** only.
All insights, numbers, and entities mentioned must be specific to the {scope_entity} {scope_level_name}.
Do NOT reference entities from other {scope_level_name}s unless explicitly comparing against the network total."""


def _load_executive_brief_instruction() -> str:
    """Load the executive brief instruction template.

    Style selection via EXECUTIVE_BRIEF_STYLE env var:
    - "ceo" -> config/prompts/executive_brief_ceo.md (CEO weekly format)
    - default -> config/prompts/executive_brief.md (standard format)
    """
    import os
    style = os.environ.get("EXECUTIVE_BRIEF_STYLE", "default").lower()
    project_root = Path(__file__).resolve().parent.parent.parent.parent

    if style == "ceo":
        ceo_path = project_root / "config" / "prompts" / "executive_brief_ceo.md"
        if ceo_path.exists():
            print("[BRIEF] Using CEO brief style")
            return ceo_path.read_text(encoding="utf-8").strip()
        print("[BRIEF] Warning: CEO prompt not found, falling back to default")

    try:
        path = project_root / "config" / "prompts" / "executive_brief.md"
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
    except Exception as e:
        print(f"[BRIEF] Warning: Failed to load executive brief instruction: {e}")

    # Fallback to hardcoded string if file missing
    return "You are an Executive Analyst. Synthesize individual metric reports into a brief."

EXECUTIVE_BRIEF_INSTRUCTION = _load_executive_brief_instruction()


def is_ceo_style() -> bool:
    """Check if CEO brief style is active."""
    import os
    return os.environ.get("EXECUTIVE_BRIEF_STYLE", "").lower() == "ceo"


def load_standard_executive_brief_instruction() -> str:
    """Load the standard (non-CEO) brief instruction for entity-scoped briefs.

    Scoped briefs always use the Executive Summary / Key Findings JSON contract even when
    the network brief uses CEO hybrid; the CEO prompt would mismatch validation.
    """
    project_root = Path(__file__).resolve().parent.parent.parent.parent
    path = project_root / "config" / "prompts" / "executive_brief.md"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    return "You are an Executive Analyst. Synthesize metric analyses into a brief JSON."


def get_ceo_section_contract(temporal_grain: str = "weekly") -> list:
    """Return CEO section contract with grain-appropriate outlook title."""
    grain = (temporal_grain or "weekly").lower()
    outlook_title = {
        "monthly": "Next-month outlook",
        "yearly": "Next-quarter outlook",
        "daily": "Next-day outlook",
    }.get(grain, "Next-week outlook")
    return [
        {"title": "What moved the business", "mode": "insights"},
        {"title": "Trend status", "mode": "insights"},
        {"title": "Where it came from", "mode": "insights"},
        {"title": "Why it matters", "mode": "content"},
        {"title": outlook_title, "mode": "content"},
        {"title": "Leadership focus", "mode": "insights"},
    ]

# Default for backward compatibility
CEO_SECTION_CONTRACT = get_ceo_section_contract("weekly")

