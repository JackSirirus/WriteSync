"""
Context Source Registry — 上下文来源注册表（Phase 7）

记录所有动态上下文来源的构建器名称、作用域、优先级与说明。
供 ContextBudget 系统与文档生成使用，不改变运行时的上下文构建逻辑。

用法：
    from .context_registry import get_source, list_sources, CONTEXT_SOURCES
"""

from dataclasses import dataclass, field
from typing import List, Literal, Optional


ScopeType = Literal["global", "project", "chapter"]


@dataclass
class ContextSourceDef:
    """单个上下文来源的注册信息"""
    builder: str                   # 构建器函数名（src/agents/context.py 中）
    scope: ScopeType               # 作用域：global / project / chapter
    priority: int                  # 注入优先级（越小越靠前）
    description: str = ""          # 简要说明


CONTEXT_SOURCES: dict[str, ContextSourceDef] = {
    "project_info": ContextSourceDef(
        builder="build_project_context",
        scope="global",
        priority=1,
        description="项目基本信息",
    ),
    "characters": ContextSourceDef(
        builder="build_character_context",
        scope="project",
        priority=2,
        description="角色设定",
    ),
    "world_lore": ContextSourceDef(
        builder="build_world_context",
        scope="project",
        priority=3,
        description="世界观设定",
    ),
    "chapter_outline": ContextSourceDef(
        builder="build_outline_context",
        scope="chapter",
        priority=4,
        description="当前章纲",
    ),
    "continuity_envelope": ContextSourceDef(
        builder="build_envelope_context",
        scope="chapter",
        priority=5,
        description="上章交接状态",
    ),
    "active_facts": ContextSourceDef(
        builder="build_fact_context",
        scope="project",
        priority=6,
        description="已确认事实",
    ),
    "foreshadows": ContextSourceDef(
        builder="build_foreshadow_context",
        scope="project",
        priority=7,
        description="待呼应伏笔",
    ),
    "style_profile": ContextSourceDef(
        builder="build_style_context",
        scope="project",
        priority=8,
        description="文风特征",
    ),
    "writing_rules": ContextSourceDef(
        builder="build_rules_context",
        scope="project",
        priority=9,
        description="创作规则",
    ),
}


def get_source(name: str) -> Optional[ContextSourceDef]:
    """按名称获取上下文来源定义。返回 None 若未注册。"""
    return CONTEXT_SOURCES.get(name)


def list_sources() -> dict[str, ContextSourceDef]:
    """返回所有已注册上下文来源的完整字典。"""
    return dict(CONTEXT_SOURCES)


def list_sources_by_scope(scope: ScopeType) -> list[tuple[str, ContextSourceDef]]:
    """按作用域过滤上下文来源，按优先级排序。"""
    items = [(k, v) for k, v in CONTEXT_SOURCES.items() if v.scope == scope]
    items.sort(key=lambda x: x[1].priority)
    return items
