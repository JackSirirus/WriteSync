"""WriteSync Agents 模块"""

from .topic import run_topic_agent
from .topic_check import run_topic_check_agent
from .planning import run_planning_agent
from .character import run_character_agent
from .world import run_world_agent, run_world_skeleton_agent
from .outline import run_outline_agent
from .writer import run_writer_agent
from .writer_check import run_writer_check_agent
from .proofreader import run_proofreader_agent
from .expansion import run_expansion_agent
from .narrative import run_narrative_agent
from .novel_editor import run_novel_review_agent
from .context import (
    update_dynamic_context,
    build_writing_context,
    persist_context,
)
from .writing_rules import WritingRules, WritingRulesManager
from .inspire import inspire
from .context_registry import (
    CONTEXT_SOURCES,
    ContextSourceDef,
    get_source,
    list_sources,
    list_sources_by_scope,
)

__all__ = [
    "run_topic_agent",
    "run_topic_check_agent",
    "run_planning_agent",
    "run_character_agent",
    "run_world_agent",
    "run_world_skeleton_agent",
    "run_outline_agent",
    "run_writer_agent",
    "run_writer_check_agent",
    "run_proofreader_agent",
    "run_expansion_agent",
    "run_narrative_agent",
    "run_novel_review_agent",
    "update_dynamic_context",
    "build_writing_context",
    "persist_context",
    "WritingRules",
    "WritingRulesManager",
    "inspire",
    # Phase 7: context source registry
    "CONTEXT_SOURCES",
    "ContextSourceDef",
    "get_source",
    "list_sources",
    "list_sources_by_scope",
]
