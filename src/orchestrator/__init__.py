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
from .adapters import call_agent
from .decision import decide_next_action
from .loop import OrchestratorSession
from .agent_registry import (
    AGENT_REGISTRY,
    AgentDef,
    add_agent,
    get_agent,
    list_agents,
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
    # Phase 7: agent registry
    "AGENT_REGISTRY",
    "AgentDef",
    "add_agent",
    "get_agent",
    "list_agents",
]
