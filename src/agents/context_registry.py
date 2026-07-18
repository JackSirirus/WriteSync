"""
Context Source Registry — 上下文来源注册表

Declarative registry of context sources that replaces the hardcoded step-by-step
context extraction in context.py. Sources are registered with priority, scope,
max_chars, and builder functions. assemble_context() iterates sources by priority
and builds the final context string within a character budget.

Usage:
    from .context_registry import assemble_context, CONTEXT_SOURCES, ContextSource
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from ..state.state_types import WriteSyncState

logger = logging.getLogger("writesync")


# ============================================================================
# ContextSource — declarative context source definition
# ============================================================================

@dataclass
class ContextSource:
    """A single context source registered in the declarative registry.

    Attributes:
        name: Unique identifier for this source (e.g. "character_snapshot").
        builder_fn: Callable that extracts formatted text from state.
            Signature: (data: WriteSyncState, chapter_num: int) -> str
        priority: Injection order (lower = higher priority, injected earlier).
        scope: When this source applies.
            - "planning": chapter_num == 0 only
            - "writing": chapter_num > 0 only
            - "all": always included
        requires_llm: Whether the builder needs LLM calls (informational).
        max_chars: Maximum characters for this source's output (header excluded).
        section_title: Display title used as the section header (e.g. "当前角色状态").
    """
    name: str
    builder_fn: Callable[[WriteSyncState, int], str]
    priority: int
    scope: str  # "planning" | "writing" | "all"
    requires_llm: bool = False
    max_chars: int = 300
    section_title: str = ""


# ============================================================================
# Builder functions — each extracts & formats one DynamicContext field
# ============================================================================

def _build_character_snapshot(data: WriteSyncState, chapter_num: int) -> str:
    """Extract character snapshot from DynamicContext."""
    ctx = data.dynamic_context
    if not ctx or not ctx.character_snapshot:
        return ""
    return ctx.character_snapshot


def _build_recent_chapters(data: WriteSyncState, chapter_num: int) -> str:
    """Extract recent chapters summary from DynamicContext."""
    ctx = data.dynamic_context
    if not ctx or not ctx.recent_chapters_summary:
        return ""
    return ctx.recent_chapters_summary


def _build_continuity_envelope(data: WriteSyncState, chapter_num: int) -> str:
    """Extract and format continuity envelope from DynamicContext."""
    ctx = data.dynamic_context
    if not ctx or not ctx.continuity_envelope:
        return ""
    env = ctx.continuity_envelope
    env_lines = []
    if env.get("handoff"):
        env_lines.append(f"[上章结束状态] {env['handoff']}")
    if env.get("protected"):
        env_lines.append(f"[保护元素·不可变更] {env['protected']}")
    if env.get("plan_delta"):
        env_lines.append(f"[本章计划调整] {env['plan_delta']}")
    return "\n".join(env_lines) if env_lines else ""


def _build_unresolved_foreshadows(data: WriteSyncState, chapter_num: int) -> str:
    """Extract unresolved foreshadows from DynamicContext."""
    ctx = data.dynamic_context
    if not ctx or not ctx.unresolved_foreshadows:
        return ""
    return "\n".join(f"- {f}" for f in ctx.unresolved_foreshadows[:5])


def _build_foreshadow_deadline(data: WriteSyncState, chapter_num: int) -> str:
    """Extract foreshadow deadlines from DynamicContext."""
    ctx = data.dynamic_context
    if not ctx or not ctx.foreshadow_deadline:
        return ""
    return "\n".join(
        f"- Ch{k}: {v}" for k, v in list(ctx.foreshadow_deadline.items())[:3]
    )


def _build_consistency_notes(data: WriteSyncState, chapter_num: int) -> str:
    """Extract world consistency notes from DynamicContext."""
    ctx = data.dynamic_context
    if not ctx or not ctx.world_consistency_notes:
        return ""
    return ctx.world_consistency_notes


def _build_pacing_state(data: WriteSyncState, chapter_num: int) -> str:
    """Extract pacing state from DynamicContext."""
    ctx = data.dynamic_context
    if not ctx or not ctx.pacing_state:
        return ""
    return ctx.pacing_state


# ============================================================================
# Registry
# ============================================================================

CONTEXT_SOURCES: Dict[str, ContextSource] = {
    "character_snapshot": ContextSource(
        name="character_snapshot",
        builder_fn=_build_character_snapshot,
        priority=1,
        scope="all",
        requires_llm=False,
        max_chars=300,
        section_title="当前角色状态",
    ),
    "recent_chapters": ContextSource(
        name="recent_chapters",
        builder_fn=_build_recent_chapters,
        priority=2,
        scope="writing",
        requires_llm=False,
        max_chars=200,
        section_title="前章回顾",
    ),
    "continuity_envelope": ContextSource(
        name="continuity_envelope",
        builder_fn=_build_continuity_envelope,
        priority=3,
        scope="writing",
        requires_llm=False,
        max_chars=150,
        section_title="章节交接",
    ),
    "unresolved_foreshadows": ContextSource(
        name="unresolved_foreshadows",
        builder_fn=_build_unresolved_foreshadows,
        priority=4,
        scope="all",
        requires_llm=False,
        max_chars=100,
        section_title="未收伏笔",
    ),
    "foreshadow_deadline": ContextSource(
        name="foreshadow_deadline",
        builder_fn=_build_foreshadow_deadline,
        priority=5,
        scope="writing",
        requires_llm=False,
        max_chars=80,
        section_title="待处理提醒",
    ),
    "consistency_notes": ContextSource(
        name="consistency_notes",
        builder_fn=_build_consistency_notes,
        priority=6,
        scope="writing",
        requires_llm=False,
        max_chars=100,
        section_title="一致性注意",
    ),
    "pacing_state": ContextSource(
        name="pacing_state",
        builder_fn=_build_pacing_state,
        priority=7,
        scope="writing",
        requires_llm=False,
        max_chars=80,
        section_title="节奏状态",
    ),
}


# ============================================================================
# assemble_context — main entry point
# ============================================================================

def assemble_context(
    state,
    chapter_num: int = 0,
    budget: int = 800,
    sources: Optional[Dict[str, ContextSource]] = None,
) -> str:
    """Assemble a context string from registered sources, ordered by priority.

    Iterates over applicable context sources (filtered by scope based on
    chapter_num), invokes each builder function, and concatenates the results
    into a formatted string capped at the given character budget.

    Args:
        state: Either a GraphState dict (with "data" key pointing to
            WriteSyncState) or a WriteSyncState instance directly.
        chapter_num: Current chapter number. 0 = planning phase,
            >0 = writing phase. Determines which sources are applicable.
        budget: Maximum character budget for the assembled output (default 800).
        sources: Optional override of the source registry.
            Defaults to CONTEXT_SOURCES.

    Returns:
        Assembled context string with sections separated by double newlines,
        matching the format of the current build_writing_context() output.
        Returns empty string if state has no DynamicContext.
    """
    t0 = time.time()

    # Extract WriteSyncState from dict or direct object
    data = state.get("data") if isinstance(state, dict) else state
    if not isinstance(data, WriteSyncState):
        logger.warning("[context_registry] invalid state type: %s", type(data))
        return ""

    if sources is None:
        sources = CONTEXT_SOURCES

    # Determine applicable scope based on chapter_num
    if chapter_num > 0:
        allowed_scopes = {"writing", "all"}
    else:
        allowed_scopes = {"planning", "all"}

    # Filter and sort by priority (lower = higher priority)
    applicable = [
        src for src in sources.values()
        if src.scope in allowed_scopes
    ]
    applicable.sort(key=lambda s: s.priority)

    # Assemble within budget
    parts: List[str] = []
    remaining = budget

    for src in applicable:
        # Budget exhausted — skip remaining sources
        if remaining <= 30:
            break

        # Build source text
        try:
            text = src.builder_fn(data, chapter_num)
        except Exception:
            logger.debug(
                "[context_registry] builder failed for %s", src.name, exc_info=True
            )
            continue

        if not text:
            continue

        # Truncate to source max_chars and remaining budget
        max_for_source = min(src.max_chars, remaining)
        text = text[:max_for_source]

        section = f"## {src.section_title}\n{text}"
        parts.append(section)
        # Estimate overhead: the section text + separator
        remaining -= len(text) + 20

    result = "\n\n".join(parts)
    elapsed = (time.time() - t0) * 1000
    logger.debug(
        "[context_registry] chapter=%d budget=%d output_len=%d sources=%d elapsed=%.1fms",
        chapter_num, budget, len(result), len(parts), elapsed,
    )
    return result


# ============================================================================
# Backward-compatible aliases (Phase 7 registry interface)
# ============================================================================

# Alias for __init__.py import compatibility
ContextSourceDef = ContextSource


def get_source(name: str) -> Optional[ContextSource]:
    """Get a context source definition by name (backward-compatible wrapper)."""
    return CONTEXT_SOURCES.get(name)


def list_sources() -> Dict[str, ContextSource]:
    """Return all registered context sources (backward-compatible wrapper)."""
    return dict(CONTEXT_SOURCES)


def list_sources_by_scope(scope: str) -> List[Tuple[str, ContextSource]]:
    """Filter context sources by scope, sorted by priority (backward-compatible wrapper)."""
    items = [(k, v) for k, v in CONTEXT_SOURCES.items() if v.scope == scope]
    items.sort(key=lambda x: x[1].priority)
    return items
