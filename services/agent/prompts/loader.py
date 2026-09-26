# ============================================
# services/agent/prompts/loader.py
# ============================================
"""
Prompt loading utility.
Reads markdown templates from the prompts directory and formats them with variables.
"""

from pathlib import Path
from typing import Any

PROMPT_DIR = Path(__file__).parent


def load_prompt(name: str, **kwargs: Any) -> str:
    """
    Load a prompt template and inject variables.

    Args:
        name: Name of the prompt file (without .md extension).
        **kwargs: Variables to format into the template.

    Returns:
        Formatted prompt string.
    """
    path = PROMPT_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")

    template = path.read_text(encoding="utf-8")
    if not kwargs:
        return template
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError, ValueError):
        # Literal JSON braces in a prompt must never crash agent startup.
        # Fall back to the raw template (variables like {today} stay visible
        # but the agent keeps working).
        import logging

        logging.getLogger(__name__).warning(
            "Prompt '%s' has unescaped braces; serving it without formatting.", name
        )
        return template
