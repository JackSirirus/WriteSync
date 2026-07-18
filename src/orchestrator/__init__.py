"""WriteSync Orchestrator — 主Agent + 子Agent 架构核心模块"""

from .models import (
    OrchestratorDecision,
    AgentResult,
    Dashboard,
    Progress,
    SSEEvent,
    SSEEventType,
    AgentName,
)
from .workspace import Workspace, init_workspace, load_workspace
from .decision import decide_next_action
from .loop import OrchestratorSession
from .agent_registry import (
    AGENT_REGISTRY,
    AgentDef,
    add_agent,
    get_agent,
    list_agents,
    agents_for_phase,
    register_agent,
    call_agent,
)

__all__ = [
    "OrchestratorDecision",
    "AgentResult",
    "Dashboard",
    "Progress",
    "SSEEvent",
    "SSEEventType",
    "AgentName",
    "Workspace",
    "init_workspace",
    "load_workspace",
    "call_agent",
    "decide_next_action",
    "OrchestratorSession",
    # Agent registry (source of truth for agent dispatch)
    "AGENT_REGISTRY",
    "AgentDef",
    "add_agent",
    "get_agent",
    "list_agents",
    "agents_for_phase",
    "register_agent",
]
