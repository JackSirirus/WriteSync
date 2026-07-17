"""
数据模型：Orchestrator 决策、Agent 结果、工作空间、SSE 事件
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class SSEEventType(str, Enum):
    THINKING = "thinking"
    AGENT_CALL = "agent_call"
    CONFIRM = "confirm"
    DONE = "done"
    WORKSPACE_UPDATE = "workspace_update"
    ERROR = "error"
    # v0.4.0 新增
    AUXILIARY_CHECK = "auxiliary_check"     # 辅助检查清单
    VOLUME_CHANGE = "volume_change"         # 卷切换
    REPLAN_NEEDED = "replan_needed"         # 提示需重新规划
    # v0.5.0 新增
    SUGGESTION = "suggestion"               # 编排器备选方案建议


class AgentName(str, Enum):
    STORY = "story"
    CHARACTER = "character"
    WORLD = "world"
    OUTLINE = "outline"
    WRITER = "writer"
    PROOFREADER = "proofreader"
    NOVEL_REVIEW = "novel_review"


class OrchestratorMode(str, Enum):
    PLANNING = "planning"       # 全书初始化 / 进入新卷
    ORCHESTRATING = "orchestrating"  # 卷内逐章写作
    REVIEWING = "reviewing"     # 卷末 / 全书审查


@dataclass
class OrchestratorDecision:
    action: str = ""           # "call_agent" | "done"
    agent: str = ""            # AgentName 值（主决策：最高置信度选项）
    instruction: str = ""      # 传给子Agent的自然语言指令
    request_context: list[str] = field(default_factory=list)
    reason: str = ""           # 决策理由
    # v0.5.0 Orchestrator Suggestion Mode: 备选方案列表
    # 每项: {"action": agent_name, "reasoning": str, "confidence": float 0.0-1.0}
    # 主决策 (agent/reason) = options 中 confidence 最高的项
    # LLM 失败或未提供时为空 list (向后兼容)
    options: list[dict] = field(default_factory=list)


@dataclass
class AgentResult:
    agent: str
    content: dict = field(default_factory=dict)
    requires_confirmation: bool = False
    summary: str = ""           # L1 摘要
    error: str = ""
    editable: Optional[dict] = None


@dataclass
class Progress:
    total_chapters: int = 0
    written: int = 0
    proofread: int = 0
    confirmed: int = 0
    # v0.4.0 分卷
    total_volumes: int = 0
    current_volume: int = 1


@dataclass
class Dashboard:
    phase: str = ""
    completed_agents: list[str] = field(default_factory=list)
    pending_confirm: str = ""
    last_user_feedback: str = ""
    progress: Progress = field(default_factory=Progress)
    updated_at: str = ""
    # v0.4.0 新字段
    orchestrator_mode: str = ""           # "planning" | "orchestrating" | "reviewing"
    platform: str = ""
    golden_three_active: bool = False    # Ch1-3 约束是否生效
    hook_landing_rate: float = 0.0       # 钩子落地率
    pleasure_density: float = 0.0        # 当前爽点密度
    auto_degraded: bool = False          # 钩子矩阵是否已降级
    stale_markers: dict = field(default_factory=dict)


@dataclass
class SSEEvent:
    type: str                  # SSEEventType 值
    data: dict = field(default_factory=dict)
