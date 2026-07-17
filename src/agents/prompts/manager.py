"""
PromptManager — orchestrates template loading, genre packs, and user overrides.

Usage:
    pm = PromptManager()
    prompt = pm.get_system_prompt("character", genre_pack="xianxia")
    # Returns rendered system prompt with 仙侠 genre vars substituted
"""

import json
import logging
from pathlib import Path
from typing import Optional

from .renderer import PromptTemplate

logger = logging.getLogger("writesync")

# Package directory for template resolution
_PKG_DIR = Path(__file__).parent

# Map agent names to template files
_AGENT_TEMPLATES = {
    "story": "story.md",
    "character": "character.md",
    "world": "world.md",
    "outline": "outline.md",
    "writer": "writer.md",
    "proofreader": "proofreader.md",
    "novel_review": "novel_review.md",
}

# Canonical agent name normalization (aliases → canonical)
_AGENT_ALIASES = {
    "novel_review": "novel_review",
    "review": "novel_review",
    "editor": "novel_review",
}


class PromptManager:
    """Manages prompt templates, genre packs, and user overrides."""

    def __init__(self, templates_dir: Optional[str] = None):
        if templates_dir:
            self._templates_dir = Path(templates_dir)
        else:
            self._templates_dir = _PKG_DIR / "system"

        self._genre_packs_dir = _PKG_DIR / "genre_packs"
        self._template_cache: dict[str, PromptTemplate] = {}
        self._genre_cache: dict[str, dict] = {}

    # ── Agent name normalization ──────────────────────────────

    def _canonical_name(self, agent_name: str) -> str:
        """Normalize agent name to canonical form."""
        name = agent_name.lower().strip()
        return _AGENT_ALIASES.get(name, name)

    # ── Template loading ──────────────────────────────────────

    def _load_template(self, agent_name: str) -> PromptTemplate:
        """Load and cache a template file for the given agent."""
        canonical = self._canonical_name(agent_name)
        if canonical in self._template_cache:
            return self._template_cache[canonical]

        filename = _AGENT_TEMPLATES.get(canonical)
        if filename is None:
            # Fallback: try loading from disk directly
            filename = f"{canonical}.md"

        filepath = self._templates_dir / filename
        if not filepath.exists():
            raise FileNotFoundError(
                f"Template not found for agent '{agent_name}' "
                f"(canonical: '{canonical}', path: {filepath})"
            )

        text = filepath.read_text(encoding="utf-8")
        template = PromptTemplate(text)
        self._template_cache[canonical] = template
        return template

    # ── Genre pack loading ────────────────────────────────────

    def _load_genre_pack(self, name: str) -> dict:
        """Load and cache a genre pack JSON file."""
        if name in self._genre_cache:
            return self._genre_cache[name]

        filepath = self._genre_packs_dir / f"{name}.json"
        if not filepath.exists():
            logger.warning("Genre pack '%s' not found, using default", name)
            return self._load_genre_pack("default")

        try:
            data = json.loads(filepath.read_text(encoding="utf-8"))
            self._genre_cache[name] = data
            return data
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load genre pack '%s': %s, using default", name, e)
            return self._load_genre_pack("default")

    def get_genre_pack(self, name: str) -> dict:
        """Return the genre pack dict for the given name."""
        return dict(self._load_genre_pack(name))

    def list_genre_packs(self) -> list[str]:
        """List available genre pack names (without .json extension)."""
        packs = []
        if self._genre_packs_dir.exists():
            for f in sorted(self._genre_packs_dir.glob("*.json")):
                packs.append(f.stem)
        return packs or ["default"]

    # ── Prompt rendering with overrides ───────────────────────

    def get_system_prompt(
        self,
        agent_name: str,
        genre_pack: str = "default",
        user_overrides: Optional[dict] = None,
    ) -> str:
        """
        Get the rendered system prompt for an agent.

        Pipeline:
        1. Load the agent's template file
        2. Load the genre pack variables
        3. Merge user_overrides on top of genre pack
        4. Render template with merged context

        Args:
            agent_name: e.g. "story", "character", "writer"
            genre_pack: genre pack name (default: "default")
            user_overrides: additional/override variables from workspace

        Returns:
            Rendered system prompt string
        """
        template = self._load_template(agent_name)
        context = self._load_genre_pack(genre_pack)

        # Merge user overrides (user values take priority)
        if user_overrides:
            context = {**context, **user_overrides}

        return template.render_system(context)

    def get_full_prompt(
        self,
        agent_name: str,
        task_prompt: str,
        genre_pack: str = "default",
        user_overrides: Optional[dict] = None,
    ) -> str:
        """
        Convenience: get system prompt concatenated with task prompt.

        This mirrors the pattern in src/agents/prompts.py where
        SYSTEM_PROMPT is prepended to task-specific instructions.
        """
        system = self.get_system_prompt(agent_name, genre_pack, user_overrides)
        return f"{system}\n\n{task_prompt}"

    def get_context_for_agent(self, agent_name: str, genre_pack: str = "default") -> dict:
        """Return the merged context dict (genre + no overrides)."""
        return dict(self._load_genre_pack(genre_pack))

    # ── Template listing ──────────────────────────────────────

    def list_agents(self) -> list[str]:
        """List all agent names that have templates."""
        return sorted(_AGENT_TEMPLATES.keys())

    def get_template_raw(self, agent_name: str) -> str:
        """Return the raw (unrendered) template text for inspection."""
        template = self._load_template(agent_name)
        return template.system_template
