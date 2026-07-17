"""
Agent Registry — 代码级 Agent 注册表（Phase 7）

只读的文档与运行时查询注册中心。
记录所有注册 Agent 的模块路径、适用阶段、模型偏好、确认需求。
运行时路由仍由 adapters.AGENT_MAP 处理，本注册表不改变任何执行行为。

用法：
    from .agent_registry import get_agent, list_agents, AGENT_REGISTRY
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class AgentDef:
    """单个 Agent 的注册信息"""
    module: str                            # Agent 实现模块路径
    allowed_phases: List[str] = field(default_factory=list)   # 允许运行的阶段
    model_preference: str = "flash"        # "pro" | "flash"
    requires_confirmation: bool = True     # 是否需要对用户确认
    description: str = ""                  # 简要说明


AGENT_REGISTRY: dict[str, AgentDef] = {
    "story": AgentDef(
        module="src.agents.story",
        allowed_phases=["new", "planning"],
        model_preference="pro",
        requires_confirmation=True,
        description="故事核心策划",
    ),
    "character": AgentDef(
        module="src.agents.character",
        allowed_phases=["planning"],
        model_preference="flash",
        requires_confirmation=True,
        description="角色设定",
    ),
    "world": AgentDef(
        module="src.agents.world",
        allowed_phases=["planning"],
        model_preference="flash",
        requires_confirmation=True,
        description="世界观构建",
    ),
    "outline": AgentDef(
        module="src.agents.outline",
        allowed_phases=["planning"],
        model_preference="flash",
        requires_confirmation=True,
        description="章纲规划",
    ),
    "writer": AgentDef(
        module="src.agents.writer",
        allowed_phases=["writing_chapters"],
        model_preference="flash",
        requires_confirmation=True,
        description="章节正文写作",
    ),
    "proofreader": AgentDef(
        module="src.agents.proofreader",
        allowed_phases=["writing_chapters"],
        model_preference="flash",
        requires_confirmation=False,
        description="校对润色",
    ),
    "novel_review": AgentDef(
        module="src.agents.novel_editor",
        allowed_phases=["review"],
        model_preference="pro",
        requires_confirmation=True,
        description="全书审查",
    ),
}


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


def get_agent(name: str) -> Optional[AgentDef]:
    """按名称获取 Agent 定义。返回 None 若未注册。"""
    return AGENT_REGISTRY.get(name)


def list_agents() -> dict[str, AgentDef]:
    """返回所有已注册 Agent 的完整字典。"""
    return dict(AGENT_REGISTRY)
