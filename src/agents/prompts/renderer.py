"""
PromptTemplate — {{placeholder}} variable substitution engine.

Usage:
    template = PromptTemplate("You are a {{genre}} writer. Tone: {{tone}}")
    rendered, _ = template.render({"genre": "仙侠", "tone": "修炼升级"})
    # "You are a 仙侠 writer. Tone: 修炼升级"
"""

import re
from typing import Optional


# Regex: matches {{var_name}} with optional whitespace around var_name
_PLACEHOLDER_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")


class PromptTemplate:
    """
    A template with {{placeholder}} variables for system and user prompts.

    Uses regex substitution — ignores whitespace inside braces so
    {{genre}}, {{ genre }}, {{  genre  }} all match the "genre" key.
    """

    def __init__(self, system_template: str, user_template: str = ""):
        self._system = system_template
        self._user = user_template

    @property
    def system_template(self) -> str:
        return self._system

    @property
    def user_template(self) -> str:
        return self._user

    def render(self, context: dict) -> tuple[str, str]:
        """Substitute {{var}} placeholders with values from context dict.
        Returns (rendered_system, rendered_user).
        Missing keys are left as-is (no substitution).
        """
        system = _PLACEHOLDER_RE.sub(
            lambda m: str(context.get(m.group(1), m.group(0))),
            self._system,
        )
        user = ""
        if self._user:
            user = _PLACEHOLDER_RE.sub(
                lambda m: str(context.get(m.group(1), m.group(0))),
                self._user,
            )
        return system, user

    def render_system(self, context: dict) -> str:
        """Convenience: render just the system template."""
        system, _ = self.render(context)
        return system

    @classmethod
    def from_string(cls, system_template: str, user_template: str = "") -> "PromptTemplate":
        """Create from raw string templates."""
        return cls(system_template, user_template)

    def extract_variables(self) -> set[str]:
        """Return all {{var}} names found in the template."""
        system_vars = set(_PLACEHOLDER_RE.findall(self._system))
        user_vars = set(_PLACEHOLDER_RE.findall(self._user))
        return system_vars | user_vars


def render_prompt(template_text: str, context: dict) -> str:
    """Quick one-shot render without creating a PromptTemplate object."""
    return _PLACEHOLDER_RE.sub(
        lambda m: str(context.get(m.group(1), m.group(0))),
        template_text,
    )
