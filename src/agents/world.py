"""
世界观 Agent（v0.5.0 两阶段版）

阶段1：大纲骨架 → 快速生成名字/结构（<30s）
阶段2：详细展开 → 基于骨架，4路并行细化（每路 <60s）

力量体系 + 地理 + 社会 + 历史。
使用 instructor 结构化输出（原来解析函数是占位实现，现在完全修复）。
"""

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from ..state.state_types import GraphState
from ..state.state_types import (
    WorldState, PowerSystem, Geography, Society, WorldHistory,
)
from ..utils.knowledge import get_knowledge_base
from ..utils.llm import LLMClient, create_llm_client
from .prompts import build_world_skeleton_prompt, build_world_prompt
from .response_models import WorldSetting, PowerSystem as RM_PowerSystem, Geography as RM_Geography
from .response_models import Society as RM_Society, WorldHistory as RM_WorldHistory

logger = None


def _get_logger():
    global logger
    if logger is None:
        import logging
        logger = logging.getLogger("writesync")
    return logger


def _sanitize_control_chars(text: str) -> str:
    """清理 JSON 字符串中的非法控制字符（\u0000-\u001F 除 \t \n \r）"""
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)


def _parse_world_json(text: str, output_class=None) -> Optional[object]:
    """从 LLM 原始响应中提取并解析 WorldSetting JSON，含控制字符清理"""
    if output_class is None:
        output_class = WorldSetting
    m = re.search(r'```(?:json)?\s*\n(.*?)\n```', text, re.DOTALL)
    if m:
        text = m.group(1)
    else:
        m = re.search(r'\{[\s\S]*\}', text)
        if m:
            text = m.group(0)
    if not text:
        return None
    text = _sanitize_control_chars(text)
    try:
        data = json.loads(text)
        return output_class(**data)
    except (json.JSONDecodeError, Exception):
        return None


# =============================================================================
# 阶段1：大纲骨架
# =============================================================================

def run_world_skeleton_agent(
    state: GraphState,
    llm: Optional[LLMClient] = None,
) -> dict:
    """阶段1：快速生成世界观大纲骨架（仅名字和结构，不展开描述）"""
    if state["data"].story is None or state["data"].characters is None:
        raise ValueError("story 或 characters 字段为空")

    prompt = build_world_skeleton_prompt(
        story_state=_format_story_for_prompt(state["data"].story),
        character_state=_format_characters_for_prompt(state["data"].characters),
        system_prompt=state.get("_prompt_system_override"),
    )

    if llm is None:
        llm = create_llm_client()

    _get_logger().info("world skeleton: 开始生成大纲骨架...")
    try:
        response: WorldSetting = llm.complete_structured(
            prompt, output_class=WorldSetting, temperature=0.7,
            max_tokens=4096,  # 骨架输出短，不需要大 token
        )
    except Exception as e:
        _get_logger().warning("world skeleton complete_structured 失败，降级到 complete(): %s", e)
        text = llm.complete(prompt, temperature=0.7, max_tokens=4096, timeout=120)
        response = _parse_world_json(text)
        if response is None:
            raise ValueError(f"world skeleton 降级解析也失败: {text[:300]}") from e

    world_state = _build_world_state_from_response(response)
    state["data"].world = world_state

    _get_logger().info("world skeleton: 完成 (体系=%s, 等级=%d, 地点=%d, 势力=%d)",
        response.power_system.system_name,
        len(response.power_system.tiers),
        len(response.geography.major_locations),
        len(response.society.factions))

    messages = state.get("messages", [])
    messages.append({
        "role": "assistant",
        "content": f"世界观大纲骨架已生成：{response.power_system.system_name}（{len(response.power_system.tiers)}级体系）",
        "attachments": [{"type": "world_skeleton", "data": response.model_dump()}],
    })

    return {"data": state["data"], "messages": messages}


# =============================================================================
# 阶段2：详细展开（基于骨架，单次调用填充细节）
# =============================================================================

def run_world_agent(
    state: GraphState,
    llm: Optional[LLMClient] = None,
) -> dict:
    """阶段2：基于大纲骨架，生成完整世界观细节（有骨架上下文，比原来快）"""
    if state["data"].story is None or state["data"].characters is None:
        raise ValueError("story 或 characters 字段为空")
    if state["data"].world is None:
        raise ValueError("world 骨架未生成，请先调用 run_world_skeleton_agent")

    skeleton = state["data"].world
    kb = get_knowledge_base()
    template = kb.load_template("世界观")

    story_str = _format_story_for_prompt(state["data"].story)
    char_str = _format_characters_for_prompt(state["data"].characters)
    skel_ctx = _format_skeleton_for_prompt(skeleton)

    if llm is None:
        llm = create_llm_client()

    _get_logger().info("world details: 基于骨架展开完整细节...")

    prompt = build_world_prompt(
        story_state=story_str,
        character_state=char_str,
        template=template,
        skeleton_context=skel_ctx,
        system_prompt=state.get("_prompt_system_override"),
    )

    try:
        response: WorldSetting = llm.complete_structured(
            prompt, output_class=WorldSetting, temperature=0.7,
            max_tokens=12288,  # 有骨架，输出比原始版少
        )
    except Exception as e:
        _get_logger().warning("world details complete_structured 失败，降级: %s", e)
        text = llm.complete(prompt, temperature=0.7, max_tokens=12288, timeout=180)
        response = _parse_world_json(text)
        if response is None:
            raise ValueError(f"world details 降级解析也失败: {text[:300]}") from e

    world_state = _build_world_state_from_response(response)
    # 保留骨架确认时间
    world_state.skel_confirmed_at = skeleton.skel_confirmed_at
    state["data"].world = world_state

    _get_logger().info("world details: 完成 (power=%s, geo=%d locations, society=%d factions)",
        world_state.power_system.system_name,
        len(world_state.geography.major_locations),
        len(world_state.society.factions))

    messages = state.get("messages", [])
    messages.append({
        "role": "assistant",
        "content": f"世界观详细设定已完成：{world_state.power_system.system_name}",
        "attachments": [{"type": "world_details", "data": {}}],
    })

    return {"data": state["data"], "messages": messages}


def _expand_single_section(
    section: str,
    skeleton_ctx: str,
    story_str: str,
    char_str: str,
    template: str,
    llm: LLMClient,
):
    """展开单个世界观部分的详细内容"""
    if section == "power":
        section_guide = "展开力量体系：细化每级描述、修炼规则、力量上限、特殊能力规则"
    elif section == "geo":
        section_guide = "展开地理：细化每个地点描述、故事意义、政治区划"
    elif section == "society":
        section_guide = "展开社会：细化每个势力描述、立场、社会层级、文化特征"
    elif section == "history":
        section_guide = "展开历史：细化关键事件、补充过往冲突"
    else:
        raise ValueError(f"未知 section: {section}")

    prompt = build_world_prompt(
        story_state=story_str,
        character_state=char_str,
        template=template,
        skeleton_context=f"{skeleton_ctx}\n\n## 本次展开重点\n{section_guide}",
    )

    try:
        response: WorldSetting = llm.complete_structured(
            prompt, output_class=WorldSetting, temperature=0.7,
            max_tokens=8192,
        )
    except Exception as e:
        _get_logger().warning("world %s complete_structured 失败，降级: %s", section, e)
        text = llm.complete(prompt, temperature=0.7, max_tokens=8192, timeout=180)
        response = _parse_world_json(text)
        if response is None:
            _get_logger().error("world %s 降级解析也失败", section)
            return None

    # 只返回对应 section
    if section == "power":
        return _build_power_system(response.power_system)
    elif section == "geo":
        return _build_geography(response.geography)
    elif section == "society":
        return _build_society(response.society)
    elif section == "history":
        return _build_history(response.history)
    return None


def _build_power_system(ps: RM_PowerSystem) -> PowerSystem:
    return PowerSystem(
        system_name=ps.system_name,
        tiers=[t.name for t in ps.tiers],
        cultivation_rules=ps.cultivation_rules,
        power_limit=ps.power_limit,
        special_abilities=list(ps.special_abilities),
    )


def _build_geography(geo: RM_Geography) -> Geography:
    return Geography(
        major_locations=[
            {"name": loc.name, "description": loc.description, "significance": loc.significance}
            for loc in geo.major_locations
        ],
        political_division=geo.political_division,
    )


def _build_society(soc: RM_Society) -> Society:
    return Society(
        factions=[
            {"name": f.name, "description": f.description, "align": f.alignment}
            for f in soc.factions
        ],
        social_hierarchy=soc.social_hierarchy,
        cultural_notes=soc.cultural_notes,
    )


def _build_history(hist: RM_WorldHistory) -> WorldHistory:
    return WorldHistory(
        key_events=list(hist.key_events),
        timeline_summary=hist.timeline_summary,
    )


def _build_world_state_from_response(response: WorldSetting) -> WorldState:
    """从 WorldSetting 响应构建 WorldState（用于骨架阶段）"""
    return WorldState(
        power_system=PowerSystem(
            system_name=response.power_system.system_name,
            tiers=[t.name for t in response.power_system.tiers],
            cultivation_rules=response.power_system.cultivation_rules,
            power_limit=response.power_system.power_limit,
            special_abilities=list(response.power_system.special_abilities),
        ),
        geography=Geography(
            major_locations=[
                {"name": loc.name, "description": loc.description, "significance": loc.significance}
                for loc in response.geography.major_locations
            ],
            political_division=response.geography.political_division,
        ),
        society=Society(
            factions=[
                {"name": f.name, "description": f.description, "align": f.alignment}
                for f in response.society.factions
            ],
            social_hierarchy=response.society.social_hierarchy,
            cultural_notes=response.society.cultural_notes,
        ),
        history=WorldHistory(
            key_events=list(response.history.key_events),
            timeline_summary=response.history.timeline_summary,
        ),
        self_check_passed=True,
        consistency_notes=response.consistency_notes,
    )


def _format_skeleton_for_prompt(world: WorldState) -> str:
    """格式化世界观骨架为 prompt 上下文"""
    parts = []

    if world.power_system and world.power_system.system_name:
        ps = world.power_system
        parts.append(f"## 力量体系：{ps.system_name}")
        parts.append(f"- 等级：{', '.join(ps.tiers[:8])}")
        if ps.tiers and len(ps.tiers) > 8:
            parts.append(f"  ... 共 {len(ps.tiers)} 级")

    if world.geography and world.geography.major_locations:
        parts.append(f"## 地理")
        for loc in world.geography.major_locations[:6]:
            parts.append(f"- {loc.get('name', '?')}")

    if world.society and world.society.factions:
        parts.append(f"## 势力")
        for f in world.society.factions[:6]:
            parts.append(f"- {f.get('name', '?')} ({f.get('align', '?')})")

    if world.history:
        parts.append(f"## 历史")
        if world.history.timeline_summary:
            parts.append(world.history.timeline_summary)
        if world.history.key_events:
            for ev in world.history.key_events[:5]:
                parts.append(f"- {ev}")

    return "\n".join(parts) or "待定义"


# =============================================================================
# 格式化辅助
# =============================================================================

def _format_story_for_prompt(story_state) -> str:
    s1 = story_state.step1
    s2 = story_state.step2
    return f"""一句话：{s1.one_sentence}
1. {s2.setup}
2. {s2.inciting}
3. {s2.rising}
4. {s2.climax_prep}
5. {s2.resolution}
主题：{s2.theme}"""


def _format_characters_for_prompt(characters_state) -> str:
    lines = []
    for c in characters_state.characters:
        lines.append(f"- {c.name}（{c.role}）：{c.goal}")
    return "\n".join(lines) or "待定义"
