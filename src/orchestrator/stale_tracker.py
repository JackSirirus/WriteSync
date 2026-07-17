"""编辑后的依赖追踪 — 标记下游产出为待审"""

import logging

logger = logging.getLogger("writesync")

DEPENDENCY_MAP: dict[str, list[str]] = {
    "story":      ["character", "world", "outline", "writer"],
    "character":  ["outline", "writer"],
    "world":      ["outline", "writer"],
    "outline":    ["writer"],
    "writer":     ["proofreader"],
}


def mark_stale(workspace, edited_agent: str):
    """编辑确认后自动标记下游依赖（使用 raw_state dataclass）"""
    downstream = DEPENDENCY_MAP.get(edited_agent, [])
    if not downstream:
        return

    state = workspace.raw_state
    for target in downstream:
        if target not in state.stale_markers:
            state.stale_markers[target] = []
        if edited_agent not in state.stale_markers[target]:
            state.stale_markers[target].append(edited_agent)
    workspace.save()
    logger.info(f"stale: marked {downstream} as stale due to {edited_agent} edit")


def clear_stale(workspace, agent: str):
    """Agent 被重新确认后清除其 stale 标记"""
    state = workspace.raw_state
    if agent in state.stale_markers:
        state.stale_markers.pop(agent, None)
        workspace.save()
        logger.info(f"stale: cleared stale markers for {agent}")


def get_stale_info(workspace) -> dict:
    """获取当前 stale 状态，供 Dashboard 和前端使用"""
    return workspace.raw_state.stale_markers
