"""
Prompt Template System — Phase 1.2

Provides:
- PromptTemplate renderer with {{placeholder}} variable substitution
- Per-agent system prompt templates (system/*.md)
- Genre packs for preset variable values (genre_packs/*.json)
- PromptManager for orchestrated prompt rendering
"""

# Re-export all builder functions for backward compatibility
from .builder import (
    SYSTEM_PROMPT,
    build_topic_prompt,
    build_topic_check_prompt,
    build_planning_prompt,
    build_character_prompt,
    build_world_skeleton_prompt,
    build_world_prompt,
    build_outline_prompt,
    build_writer_prompt,
    build_writer_prompt_v04,
    build_step_plan_prompt,
    build_step_segment_prompt,
    build_step_assemble_prompt,
    GOLDEN_THREE_CH1_TEMPLATE,
    GOLDEN_THREE_CH2_TEMPLATE,
    GOLDEN_THREE_CH3_TEMPLATE,
    build_writer_check_prompt,
    build_editor_prompt,
    build_rhythm_prompt,
    build_proofreader_prompt,
    build_expansion_prompt,
    build_narrative_synopsis_prompt,
    build_novel_review_prompt,
)

from .renderer import PromptTemplate, render_prompt
from .manager import PromptManager

__all__ = [
    "SYSTEM_PROMPT",
    "build_topic_prompt",
    "build_topic_check_prompt",
    "build_planning_prompt",
    "build_character_prompt",
    "build_world_skeleton_prompt",
    "build_world_prompt",
    "build_outline_prompt",
    "build_writer_prompt",
    "build_writer_prompt_v04",
    "build_step_plan_prompt",
    "build_step_segment_prompt",
    "build_step_assemble_prompt",
    "build_writer_check_prompt",
    "build_editor_prompt",
    "build_rhythm_prompt",
    "build_proofreader_prompt",
    "build_expansion_prompt",
    "build_narrative_synopsis_prompt",
    "build_novel_review_prompt",
    "PromptTemplate",
    "render_prompt",
    "PromptManager",
]
