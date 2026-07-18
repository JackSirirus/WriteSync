"""
Agent Registry — 功能完整的 Agent 注册表（Phase 7+）

作为 Agent 调度的唯一真实来源：
- 注册所有 7 个 Agent 的元数据（适配函数、阶段、模型偏好、超时等）
- call_agent() 统一分发，替代 adapters.AGENT_MAP 的手工 dispatch
- 查询 API：get_agent(), list_agents(), agents_for_phase()
- 可扩展：add_agent() / register_agent() 支持运行时注册新 Agent

用法：
    from .agent_registry import call_agent, get_agent, list_agents, agents_for_phase
    from .agent_registry import AGENT_REGISTRY, AgentDef, register_agent
"""

import logging
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from .models import AgentResult

logger = logging.getLogger("writesync")


@dataclass
class AgentDef:
    """单个 Agent 的完整注册信息"""
    adapter_fn: Callable                                     # 适配器函数引用
    allowed_phases: List[str] = field(default_factory=list)  # 允许运行的阶段
    model_preference: str = "flash"                          # "pro" | "flash"
    requires_confirmation: bool = True                       # 是否需要用户确认
    timeout: int = 90                                        # 默认超时（秒）
    description: str = ""                                    # 简要说明
    has_stages: bool = False                                 # 是否有内部多阶段（story/world）


# ── 构建注册表（延迟导入 adapter 函数，模块级一次性） ──
def _build_registry() -> Dict[str, AgentDef]:
    """构建 Agent 注册表。延迟导入适配器函数避免循环依赖。"""
    from .adapters import (
        adapt_story_agent,
        adapt_character_agent,
        adapt_world_agent,
        adapt_outline_agent,
        adapt_writer_agent,
        adapt_proofreader_agent,
        adapt_novel_review_agent,
    )
    return {
        "story": AgentDef(
            adapter_fn=adapt_story_agent,
            allowed_phases=["new", "topic_selection", "planning"],
            model_preference="pro",
            requires_confirmation=True,
            timeout=90,
            description="故事核心策划（选题+五句话扩展）",
            has_stages=True,
        ),
        "character": AgentDef(
            adapter_fn=adapt_character_agent,
            allowed_phases=["planning"],
            model_preference="flash",
            requires_confirmation=True,
            timeout=90,
            description="角色设定",
            has_stages=False,
        ),
        "world": AgentDef(
            adapter_fn=adapt_world_agent,
            allowed_phases=["planning"],
            model_preference="flash",
            requires_confirmation=True,
            timeout=90,
            description="世界观构建（大纲骨架+详细展开）",
            has_stages=True,
        ),
        "outline": AgentDef(
            adapter_fn=adapt_outline_agent,
            allowed_phases=["planning"],
            model_preference="flash",
            requires_confirmation=True,
            timeout=90,
            description="章纲规划",
            has_stages=False,
        ),
        "writer": AgentDef(
            adapter_fn=adapt_writer_agent,
            allowed_phases=["writing_chapters"],
            model_preference="flash",
            requires_confirmation=True,
            timeout=90,
            description="章节正文写作",
            has_stages=False,
        ),
        "proofreader": AgentDef(
            adapter_fn=adapt_proofreader_agent,
            allowed_phases=["writing_chapters"],
            model_preference="flash",
            requires_confirmation=False,
            timeout=90,
            description="校对润色",
            has_stages=False,
        ),
        "novel_review": AgentDef(
            adapter_fn=adapt_novel_review_agent,
            allowed_phases=["review"],
            model_preference="pro",
            requires_confirmation=True,
            timeout=90,
            description="全书审查",
            has_stages=False,
        ),
    }


AGENT_REGISTRY: Dict[str, AgentDef] = _build_registry()


# =============================================================================
# 查询 API
# =============================================================================

def get_agent(name: str) -> Optional[AgentDef]:
    """按名称获取 Agent 定义。返回 None 若未注册。"""
    return AGENT_REGISTRY.get(name)


def list_agents() -> Dict[str, AgentDef]:
    """返回所有已注册 Agent 的完整字典（浅拷贝）。"""
    return dict(AGENT_REGISTRY)


def agents_for_phase(phase: str) -> Dict[str, AgentDef]:
    """返回允许在指定阶段运行的所有 Agent。

    Args:
        phase: 阶段名称（"new", "topic_selection", "planning", "writing_chapters", "review"）

    Returns:
        {agent_name: AgentDef} 过滤后的字典
    """
    return {
        name: agent_def
        for name, agent_def in AGENT_REGISTRY.items()
        if phase in agent_def.allowed_phases
    }


# =============================================================================
# 注册 API
# =============================================================================

def add_agent(name: str, agent_def: AgentDef) -> None:
    """注册一个新的 Agent 定义（程序化扩展入口）。

    Args:
        name: Agent 名称（用于路由查找的键）
        agent_def: AgentDef 实例

    Raises:
        ValueError: 名称已存在
    """
    if name in AGENT_REGISTRY:
        raise ValueError(f"Agent '{name}' 已注册")
    AGENT_REGISTRY[name] = agent_def


# register_agent 是 add_agent 的语义别名
register_agent = add_agent


# =============================================================================
# 分发 API
# =============================================================================

def call_agent(workspace, agent_name: str, instruction: str = "",
               chapter_num: int = 0, llm=None) -> AgentResult:
    """通过注册表统一分发 Agent 调用。

    替代 adapters.AGENT_MAP 的手工 dispatch，逻辑完全一致：
    - writer / proofreader 传入 chapter_num
    - 其他 Agent 不传 chapter_num

    Args:
        workspace: Workspace 实例
        agent_name: Agent 名称（"story", "character", "world", "outline",
                   "writer", "proofreader", "novel_review"）
        instruction: 传给 Agent 的自然语言指令
        chapter_num: 章节号（仅 writer/proofreader 使用）
        llm: LLM 客户端（可选）

    Returns:
        AgentResult 包含执行结果或错误信息
    """
    agent_def = AGENT_REGISTRY.get(agent_name)
    if agent_def is None:
        return AgentResult(agent=agent_name, error=f"未知 Agent: {agent_name}")

    try:
        # writer / proofreader 需要 chapter_num 参数
        if agent_name in ("writer", "proofreader"):
            return agent_def.adapter_fn(
                workspace,
                instruction=instruction,
                chapter_num=chapter_num,
                llm=llm,
            )
        return agent_def.adapter_fn(
            workspace,
            instruction=instruction,
            llm=llm,
        )
    except Exception as e:
        logger.exception("agent_registry call_agent('%s') 失败", agent_name)
        return AgentResult(agent=agent_name, error=str(e))
