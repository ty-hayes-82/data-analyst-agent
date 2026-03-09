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
    """Load the executive brief instruction template from config/prompts/executive_brief.md."""
    try:
        # Resolve path relative to project root
        project_root = Path(__file__).resolve().parent.parent.parent.parent
        path = project_root / "config" / "prompts" / "executive_brief.md"
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
    except Exception as e:
        print(f"[BRIEF] Warning: Failed to load executive brief instruction: {e}")
    
    # Fallback to hardcoded string if file missing
    return "You are an Executive Analyst. Synthesize individual metric reports into a brief."

EXECUTIVE_BRIEF_INSTRUCTION = _load_executive_brief_instruction()

