"""
AgentAdapter — 现有 Agent 的包装层

将 7 个活跃 Agent 接入新架构，不改 Agent 内部逻辑。
每个 Adapter 负责：
1. 从 Workspace 提取所需数据，构建 GraphState
2. 调用原始 Agent 函数
3. 将返回结果包装为 AgentResult
4. 生成 L1 摘要
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from ..utils.llm import LLMClient, create_llm_client
from ..state.state_types import GraphState
from ..state.state_types import (
    WriteSyncState,
    TopicState,
    StoryState,
    StoryCore,
    Character,
    AuxiliaryCheckItem,
    WorldState,
    PowerSystem,
    Geography,
    Society,
    WorldHistory,
)

from ..agents.topic import run_topic_agent
from ..agents.planning import run_planning_agent
from ..agents.character import run_character_agent
from ..agents.world import run_world_agent, run_world_skeleton_agent
from ..agents.outline import run_outline_agent
from ..agents.writer import run_writer_agent
from ..agents.proofreader import run_proofreader_agent
from ..agents.novel_editor import run_novel_review_agent
from ..agents.prompts.manager import PromptManager

from .models import AgentResult

logger = logging.getLogger("writesync")

# Singleton PromptManager for template rendering
_prompt_manager: Optional[PromptManager] = None


def _get_prompt_manager() -> PromptManager:
    global _prompt_manager
    if _prompt_manager is None:
        _prompt_manager = PromptManager()
    return _prompt_manager


def _make_graph_state(ws_state: WriteSyncState, pending_feedback: str = "") -> GraphState:
    return GraphState(
        data=ws_state,
        messages=[],
        pending_step=None,
        user_note=None,
        pending_feedback=pending_feedback,
    )


def _inject_prompt_override(gs: GraphState, workspace, agent_name: str):
    """
    Inject the rendered system prompt into GraphState via _prompt_system_override.

    Uses PromptManager to render the agent's template with the workspace's
    genre pack and any user prompt overrides.
    """
    pm = _get_prompt_manager()
    genre_pack = workspace.genre_pack_name
    overrides = workspace.prompt_overrides.get(agent_name)
    # Build context: genre pack variables + per-agent user override
    user_overrides = {}
    if overrides:
        user_overrides = {"_custom_prompt": overrides}
    try:
        rendered = pm.get_system_prompt(agent_name, genre_pack, user_overrides)
        gs["_prompt_system_override"] = rendered
    except Exception as e:
        logger.debug("PromptManager render failed for %s: %s", agent_name, e)


def _get_llm(llm: Optional[LLMClient] = None) -> LLMClient:
    if llm is None:
        return create_llm_client()
    return llm


def _build_story_summary(ws_state: WriteSyncState) -> str:
    s = ws_state.story
    if s is None:
        return ""
    parts = []
    if s.step1.one_sentence:
        parts.append(f"一句话：{s.step1.one_sentence}")
    if s.step2 and s.step2.setup:
        parts.append(f"五句话：{s.step2.setup[:100]}...")
    return "\n".join(parts)


def _build_character_summary(ws_state: WriteSyncState) -> str:
    c = ws_state.characters
    if c is None or not c.characters:
        return ""
    names = [ch.name for ch in c.characters]
    return f"角色({len(names)}人)：{', '.join(names[:8])}"


def _build_world_summary(ws_state: WriteSyncState) -> str:
    w = ws_state.world
    if w is None:
        return ""
    return f"世界观：{w.power_system.system_name}"


def _build_outline_summary(ws_state: WriteSyncState) -> str:
    co = ws_state.chapter_outline
    if co is None:
        return ""
    return f"章纲：共{co.total_chapters}章"


def _build_chapter_summary(ws_state: WriteSyncState, ch_num: int) -> str:
    drafts = ws_state.drafts
    if ch_num not in drafts.chapters:
        return ""
    cd = drafts.chapters[ch_num]
    return f"第{ch_num}章：{cd.word_count}字"


# =============================================================================
# Story Agent (选题 + 策划)
# =============================================================================

def adapt_story_agent(workspace, instruction: str = "",
                      llm: Optional[LLMClient] = None) -> AgentResult:
    """
    Story Agent 适配器。
    两阶段：
    - 阶段1：尚无一句话 → 生成选题建议
    - 阶段2：已有一句话 → 生成五句话扩展
    """
    llm = _get_llm(llm)
    ws_state = workspace.raw_state

    if not workspace.has_story():
        return _story_stage1_generate_topics(workspace, instruction, llm)
    else:
        return _story_stage2_generate_expansion(workspace, instruction, llm)


def _story_stage1_generate_topics(workspace, instruction: str,
                                   llm: LLMClient) -> AgentResult:
    """阶段1：生成选题建议"""
    ws_state = workspace.raw_state

    if ws_state.topic is None:
        seed = workspace.get_seed_idea() or instruction or "一个精彩的故事"
        ws_state.topic = TopicState(
            user_original_idea=seed,
            suggestions=[],
            selected=-1,
            confirmed_at=None,
        )
        ws_state.metadata.updated_at = datetime.now(timezone.utc).isoformat()

    gs = _make_graph_state(ws_state)
    _inject_prompt_override(gs, workspace, "story")
    try:
        result_dict = run_topic_agent(gs, llm)
        if "data" in result_dict:
            pass
        topics = []
        if ws_state.topic and ws_state.topic.suggestions:
            for t in ws_state.topic.suggestions:
                topics.append({
                    "title": t.title,
                    "genre": t.genre,
                    "sub_genre": t.sub_genre,
                    "core_selling_point": t.core_selling_point,
                })
        # 修复: 选题列表为空时不触发确认，返回错误让 orchestrator 重试
        if not topics:
            return AgentResult(
                agent="story",
                error="选题生成失败：LLM 未返回有效选题建议",
            )
        return AgentResult(
            agent="story",
            content={"stage": "topics", "topics": topics},
            requires_confirmation=True,
            summary=f"选题建议：{topics[0]['title'] if topics else ''}",
        )
    except Exception as e:
        logger.exception("story_agent stage1 失败")
        return AgentResult(agent="story", error=str(e))


def _story_stage2_generate_expansion(workspace, instruction: str,
                                      llm: LLMClient) -> AgentResult:
    """阶段2：基于一句话生成五句话扩展"""
    ws_state = workspace.raw_state
    gs = _make_graph_state(ws_state, pending_feedback=instruction if instruction else "")
    _inject_prompt_override(gs, workspace, "story")

    try:
        result_dict = run_planning_agent(gs, llm)
        story = ws_state.story
        if story is None or not story.step2.setup:
            return AgentResult(agent="story", error="策划扩展生成失败", requires_confirmation=True)

        return AgentResult(
            agent="story",
            content={
                "stage": "expansion",
                "one_sentence": story.step1.one_sentence,
                "tag": story.step1.tag,
                "expansion": {
                    "setup": story.step2.setup,
                    "inciting": story.step2.inciting,
                    "rising": story.step2.rising,
                    "climax_prep": story.step2.climax_prep,
                    "resolution": story.step2.resolution,
                    "theme": story.step2.theme,
                },
            },
            requires_confirmation=True,
            summary=_build_story_summary(ws_state),
            editable={
                "mode": "form",
                "fields": [
                    {"key": "one_sentence", "label": "一句话核心", "type": "text", "current": story.step1.one_sentence if story and story.step1 else ""},
                    {"key": "tag", "label": "类型标签", "type": "text", "current": story.step1.tag if story and story.step1 else ""},
                    {"key": "setup", "label": "背景设定", "type": "textarea", "current": story.step2.setup if story and story.step2 else ""},
                    {"key": "inciting", "label": "第一转折点", "type": "textarea", "current": story.step2.inciting if story and story.step2 else ""},
                    {"key": "rising", "label": "中点", "type": "textarea", "current": story.step2.rising if story and story.step2 else ""},
                    {"key": "climax_prep", "label": "第二转折点", "type": "textarea", "current": story.step2.climax_prep if story and story.step2 else ""},
                    {"key": "resolution", "label": "结局", "type": "textarea", "current": story.step2.resolution if story and story.step2 else ""},
                    {"key": "theme", "label": "核心主题", "type": "text", "current": story.step2.theme if story and story.step2 else ""},
                    {"key": "moral", "label": "道德寓意", "type": "text", "current": story.step2.moral if story and story.step2 else ""},
                ],
                "preview_required": False,
            },
        )
    except Exception as e:
        logger.exception("story_agent stage2 失败")
        return AgentResult(agent="story", error=str(e))


# =============================================================================
# Character Agent
# =============================================================================

def adapt_character_agent(workspace, instruction: str = "",
                           llm: Optional[LLMClient] = None) -> AgentResult:
    llm = _get_llm(llm)
    ws_state = workspace.raw_state
    gs = _make_graph_state(ws_state, pending_feedback=instruction if instruction else "")
    _inject_prompt_override(gs, workspace, "character")

    try:
        result_dict = run_character_agent(gs, llm)
        chars = ws_state.characters
        char_list = []
        if chars and chars.characters:
            for c in chars.characters:
                char_list.append({
                    "name": c.name,
                    "role": c.role,
                    "personality": c.personality,
                    "goal": c.goal,
                })

        return AgentResult(
            agent="character",
            content={"characters": char_list},
            requires_confirmation=True,
            summary=_build_character_summary(ws_state),
            editable={
                "mode": "form",
                "fields": [
                    {"key": "characters", "label": "角色列表", "type": "form", "current": char_list},
                ],
                "preview_required": False,
            },
        )
    except Exception as e:
        logger.exception("character_agent 失败")
        return AgentResult(agent="character", error=str(e))


# =============================================================================
# World Agent（两阶段：大纲骨架 → 详细展开）
# =============================================================================

def adapt_world_agent(workspace, instruction: str = "",
                       llm: Optional[LLMClient] = None) -> AgentResult:
    """
    World Agent 适配器。
    两阶段（参照 story agent 模式）：
    - 阶段1：无大纲骨架 → 快速生成世界观大纲骨架（只出名字/结构）
    - 阶段2：已有大纲骨架 → 4路并行展开完整细节
    """
    llm = _get_llm(llm)
    ws_state = workspace.raw_state

    # 向后兼容：旧项目（confirmed_at 已设置但 skel_confirmed_at 未设置）
    if (ws_state.world is not None
        and ws_state.world.confirmed_at is not None
        and ws_state.world.skel_confirmed_at is None):
        ws_state.world.skel_confirmed_at = ws_state.world.confirmed_at
        logger.info("world: 旧项目已确认，跳过骨架阶段，直接标记 skel_confirmed_at")

    skel_confirmed = (
        ws_state.world is not None
        and ws_state.world.power_system.system_name
        and ws_state.world.skel_confirmed_at is not None
    )

    if not skel_confirmed:
        return _world_stage1_skeleton(workspace, instruction, llm)
    else:
        return _world_stage2_details(workspace, instruction, llm)


def _world_stage1_skeleton(workspace, instruction: str,
                             llm: LLMClient) -> AgentResult:
    """阶段1：生成世界观大纲骨架（快速，<30s）"""
    ws_state = workspace.raw_state
    gs = _make_graph_state(ws_state)
    _inject_prompt_override(gs, workspace, "world")

    try:
        result_dict = run_world_skeleton_agent(gs, llm)
        w = ws_state.world
        skel_data = {}
        if w:
            skel_data = {
                "stage": "skeleton",
                "power_system": w.power_system.system_name if w.power_system else "",
                "tiers": w.power_system.tiers if w.power_system else [],
                "tier_count": len(w.power_system.tiers) if w.power_system else 0,
                "location_count": len(w.geography.major_locations) if w.geography else 0,
                "faction_count": len(w.society.factions) if w.society else 0,
                "locations": [loc.get("name", "") for loc in (w.geography.major_locations if w.geography else [])],
                "factions": [f.get("name", "") for f in (w.society.factions if w.society else [])],
                "timeline": w.history.timeline_summary if w.history else "",
            }

        return AgentResult(
            agent="world",
            content=skel_data,
            requires_confirmation=True,
            summary=f"世界观大纲：{w.power_system.system_name if w and w.power_system else ''}",
            editable={
                "mode": "form",
                "fields": [
                    {"key": "power_system", "label": "力量体系", "type": "text", "current": skel_data.get("power_system", "")},
                    {"key": "tiers", "label": "等级", "type": "text", "current": ", ".join(skel_data.get("tiers", []))},
                    {"key": "locations", "label": "地点", "type": "textarea", "current": ", ".join(skel_data.get("locations", []))},
                    {"key": "factions", "label": "势力", "type": "textarea", "current": ", ".join(skel_data.get("factions", []))},
                ],
                "preview_required": False,
            },
        )
    except Exception as e:
        logger.exception("world_agent stage1 (skeleton) 失败")
        return AgentResult(agent="world", error=str(e))


def _world_stage2_details(workspace, instruction: str,
                            llm: LLMClient) -> AgentResult:
    """阶段2：基于大纲骨架，4路并行展开完整世界观细节"""
    ws_state = workspace.raw_state
    gs = _make_graph_state(ws_state)
    _inject_prompt_override(gs, workspace, "world")

    try:
        result_dict = run_world_agent(gs, llm)
        w = ws_state.world
        world_data = {
            "stage": "details",
            "power_system": w.power_system.system_name if w.power_system else "",
            "tiers": w.power_system.tiers if w.power_system else [],
            "locations": [
                {"name": loc.get("name", ""), "description": loc.get("description", "")[:80]}
                for loc in (w.geography.major_locations if w.geography else [])
            ],
            "factions": [
                {"name": f.get("name", ""), "align": f.get("align", ""), "description": f.get("description", "")[:80]}
                for f in (w.society.factions if w.society else [])
            ],
        }

        return AgentResult(
            agent="world",
            content=world_data,
            requires_confirmation=True,
            summary=_build_world_summary(ws_state),
            editable={
                "mode": "form",
                "fields": [
                    {"key": "power_system", "label": "力量体系", "type": "text", "current": w.power_system.system_name if w and w.power_system else ""},
                    {"key": "tiers", "label": "等级", "type": "textarea", "current": ", ".join(w.power_system.tiers) if w and w.power_system else ""},
                    {"key": "locations", "label": "地点列表", "type": "textarea", "current": ""},
                    {"key": "factions", "label": "势力列表", "type": "textarea", "current": ""},
                ],
                "preview_required": False,
            },
        )
    except Exception as e:
        logger.exception("world_agent stage2 (details) 失败")
        return AgentResult(agent="world", error=str(e))


# =============================================================================
# Outline Agent
# =============================================================================

def adapt_outline_agent(workspace, instruction: str = "",
                         llm: Optional[LLMClient] = None) -> AgentResult:
    llm = _get_llm(llm)
    ws_state = workspace.raw_state
    gs = _make_graph_state(ws_state)

    # ── 降级：world 未确认时注入最小占位 world 防止 outline agent 崩溃 ──
    if gs["data"].world is None:
        logger.warning("world 未确认但允许 outline 继续（降级：注入最小占位 world）")
        gs["data"].world = WorldState(
            power_system=PowerSystem(system_name="待补充", tiers=[], cultivation_rules="", power_limit=""),
            geography=Geography(major_locations=[]),
            society=Society(factions=[]),
            history=WorldHistory(key_events=[]),
        )

    _inject_prompt_override(gs, workspace, "outline")

    try:
        result_dict = run_outline_agent(gs, llm)
        co = ws_state.chapter_outline
        chapters = []
        if co and co.chapters:
            for ch in co.chapters:
                chapters.append({
                    "num": ch.chapter_number,
                    "title": ch.chapter_title,
                    "core_event": ch.core_event,
                })

        return AgentResult(
            agent="outline",
            content={"total_chapters": co.total_chapters if co else 0, "chapters": chapters},
            requires_confirmation=True,
            summary=_build_outline_summary(ws_state),
            editable={
                "mode": "form",
                "fields": [
                    {"key": "chapters", "label": "章纲列表", "type": "form", "current": chapters},
                ],
                "preview_required": False,
            },
        )
    except Exception as e:
        logger.exception("outline_agent 失败")
        return AgentResult(agent="outline", error=str(e))


# =============================================================================
# Writer Agent
# =============================================================================

def adapt_writer_agent(workspace, instruction: str = "",
                        chapter_num: int = 0, llm: Optional[LLMClient] = None) -> AgentResult:
    llm = _get_llm(llm)
    ws_state = workspace.raw_state

    if chapter_num <= 0:
        written = workspace.get_written_chapters()
        if ws_state.chapter_outline and ws_state.chapter_outline.chapters:
            all_nums = [ch.chapter_number for ch in ws_state.chapter_outline.chapters]
            for n in all_nums:
                if n not in written:
                    chapter_num = n
                    break
        if chapter_num <= 0:
            return AgentResult(agent="writer", error="无法确定要写的章节号")

    # v0.4.0: 组装 enhanced instruction（钩子+爽点+平台+黄金三章）
    enhanced = _build_writer_enhanced_instruction(workspace, chapter_num, instruction)
    gs = _make_graph_state(ws_state, pending_feedback=enhanced)
    golden_three = workspace.is_golden_three_chapter(chapter_num)
    platform = workspace.get_platform_profile()

    # 在 GraphState 的额外字段中注入平台和黄金三章信息供 writer agent 使用
    gs["_v04_platform_profile"] = platform.__dict__
    gs["_v04_golden_three"] = golden_three
    gs["_v04_chapter_num"] = chapter_num
    _inject_prompt_override(gs, workspace, "writer")

    try:
        result_dict = run_writer_agent(gs, chapter_num, llm)
        cd = ws_state.drafts.chapters.get(chapter_num)
        draft_text = ""
        word_count = 0
        if cd and cd.draft:
            draft_text = cd.draft.content[:500]
            word_count = cd.word_count

        # v0.4.0: 生成辅助检查清单
        checks = run_auxiliary_checks(draft_text, golden_three, platform, chapter_num)

        # 获取完整草稿文本用于 editable 面板
        full_draft = cd.draft.content if cd and cd.draft else draft_text

        return AgentResult(
            agent="writer",
            content={
                "chapter_num": chapter_num,
                "content": draft_text,
                "word_count": word_count,
                "stage": "draft",
                "auxiliary_checks": [c.__dict__ for c in checks],
                "golden_three_active": golden_three,
            },
            requires_confirmation=True,
            summary=f"第{chapter_num}章初稿：{word_count}字",
            editable={
                "mode": "richtext",
                "fields": [
                    {"key": "content", "label": "正文", "type": "richtext", "current": full_draft},
                ],
                "preview_required": True,
            },
        )
    except Exception as e:
        logger.exception("writer_agent 失败")
        return AgentResult(agent="writer", error=str(e))


def _build_writer_enhanced_instruction(workspace, ch_num: int, base_instruction: str) -> str:
    parts = []
    # 0. 原有指令
    if base_instruction:
        parts.append(base_instruction)
    # 1. 钩子卡片
    hook = workspace.get_hook_card(ch_num)
    if hook:
        parts.append(f"\n## 本章钩子要求\n"
                     f"- 类型：{hook.hook_type}\n"
                     f"- 强度：{'★' * hook.strength}\n"
                     f"- 钩子内容：{hook.content or '请自行设计'}\n"
                     f"- 衔接：第{hook.connect_chapter}章开头\n"
                     f"- **要求：章末最后一句话必须是钩子落地句**")
    # 2. 爽点卡片
    pleasure = workspace.get_pleasure_card(ch_num)
    if pleasure:
        parts.append(f"\n## 本章爽点要求\n"
                     f"- 类型：{pleasure.pp_type}\n"
                     f"- 强度：{'★' * pleasure.strength}\n"
                     f"- 场景：{pleasure.description or '请自行设计'}\n"
                     f"- 建议字数占比：{pleasure.word_ratio_target:.0%}")
    # 3. 平台风格
    platform = workspace.get_platform_profile()
    if platform:
        parts.append(f"\n## 平台风格约束（{platform.platform}）\n"
                     f"- 文风：{platform.style_requirement}\n"
                     f"- 开篇策略：{platform.suppress_tolerance}容忍度压制主角")
        if platform.system_panel_preference == "强烈推荐":
            parts.append("- 建议：适当使用系统面板/数值反馈")
        elif platform.system_panel_preference == "不推荐":
            parts.append("- 注意：避免系统面板/数值流写法")
    # 4. 黄金三章
    if workspace.is_golden_three_chapter(ch_num):
        rel_ch = ch_num - workspace.get_volume_chapter_range()[0] + 1
        parts.append(f"\n## ⚠ 黄金三章模式（当前为第{rel_ch}章）")
        parts.append("- 30字内进入冲突/悬念，禁止环境描写开头")
        parts.append("- 200字内完成主角身份+处境+特殊性展示")
        if rel_ch == 1:
            parts.append("- Ch1必须暗示或展现金手指的存在")
            parts.append("- 必须包含1个微爽点")
        elif rel_ch == 2:
            parts.append("- 必须包含1个小爽点（明显反击/收获）")
        elif rel_ch == 3:
            parts.append("- 必须是第一个中爽点（爆发式）")
            parts.append("- 章末钩子揭示更大的世界观/阴谋，锁定追读")
        parts.append("- 对话占比 ≥ 50%")
        parts.append("- 主角被压制时长 ≤ 全章 15%")
        parts.append(f"- 钩子强度 ≥ ★★★★")

    return "\n".join(parts) if parts else base_instruction


# =============================================================================
# Proofreader Agent
# =============================================================================

def adapt_proofreader_agent(workspace, instruction: str = "",
                             chapter_num: int = 0,
                             llm: Optional[LLMClient] = None) -> AgentResult:
    llm = _get_llm(llm)
    ws_state = workspace.raw_state
    gs = _make_graph_state(ws_state)
    _inject_prompt_override(gs, workspace, "proofreader")

    if chapter_num <= 0:
        drafts = ws_state.drafts.chapters
        for n in sorted(drafts.keys()):
            cd = drafts[n]
            if cd.draft and not cd.final:
                chapter_num = n
                break
        if chapter_num <= 0 and drafts:
            chapter_num = max(drafts.keys())

    if chapter_num <= 0:
        return AgentResult(agent="proofreader", error="无可用章节校对")

    try:
        result_dict = run_proofreader_agent(gs, chapter_num, llm)
        cd = ws_state.drafts.chapters.get(chapter_num)
        proofread_text = ""
        if cd and cd.final:
            proofread_text = cd.final.content[:500]

        return AgentResult(
            agent="proofreader",
            content={
                "chapter_num": chapter_num,
                "proofread_content": proofread_text,
                "stage": "proofread",
            },
            requires_confirmation=False,
            summary=f"第{chapter_num}章校对完成",
        )
    except Exception as e:
        logger.exception("proofreader_agent 失败")
        return AgentResult(agent="proofreader", error=str(e))


# =============================================================================
# Novel Review Agent
# =============================================================================

def adapt_novel_review_agent(workspace, instruction: str = "",
                              llm: Optional[LLMClient] = None) -> AgentResult:
    llm = _get_llm(llm)
    ws_state = workspace.raw_state
    gs = _make_graph_state(ws_state)
    _inject_prompt_override(gs, workspace, "novel_review")

    try:
        result_dict = run_novel_review_agent(gs, llm)
        nr = ws_state.novel_review
        review_data = {}
        if nr:
            review_data = {
                "structural_issues": nr.structural_issues,
                "pacing_assessment": nr.pacing_assessment,
                "character_arc_consistency": nr.character_arc_consistency,
                "recommendations": nr.recommendations,
                "passed": nr.passed,
            }

        return AgentResult(
            agent="novel_review",
            content=review_data,
            requires_confirmation=True,
            summary=f"全书审查：{'通过' if (nr and nr.passed) else '需修改'}",
            editable={
                "mode": "form",
                "fields": [
                    {"key": "passed", "label": "是否通过", "type": "text", "current": str(result_dict.get("passed", True)) if result_dict else "True"},
                    {"key": "recommendations", "label": "建议", "type": "textarea", "current": ""},
                ],
                "preview_required": False,
            },
        )
    except Exception as e:
        logger.exception("novel_review_agent 失败")
        return AgentResult(agent="novel_review", error=str(e))


# =============================================================================
# AgentAdapter 统一入口
# =============================================================================

AGENT_MAP = {
    "story": adapt_story_agent,
    "character": adapt_character_agent,
    "world": adapt_world_agent,
    "outline": adapt_outline_agent,
    "writer": adapt_writer_agent,
    "proofreader": adapt_proofreader_agent,
    "novel_review": adapt_novel_review_agent,
}


def call_agent(workspace, agent_name: str, instruction: str = "",
               chapter_num: int = 0, llm: Optional[LLMClient] = None) -> AgentResult:
    adapter = AGENT_MAP.get(agent_name)
    if adapter is None:
        return AgentResult(agent=agent_name, error=f"未知 Agent: {agent_name}")

    if agent_name in ("writer", "proofreader"):
        return adapter(workspace, instruction=instruction, chapter_num=chapter_num, llm=llm)
    return adapter(workspace, instruction=instruction, llm=llm)


# =============================================================================
# v0.4.0 辅助检查（纯规则，不调 LLM）
# =============================================================================

POISON_KEYWORDS = [
    "送女", "绿帽", "跪舔", "圣母", "舔狗", "无故被辱", "戴绿帽",
    "跪地求饶", "无脑倒贴", "洗白反派",
]

HOOK_KEYWORDS = {
    "悬念": ["究竟", "难道", "秘密", "真相", "谜底", "隐藏", "不为人知", "黑石", "心跳", "浮现"],
    "冲突": ["宣布", "废黜", "挑战", "对抗", "对决", "宣战", "背叛", "翻脸"],
    "期待": ["即将", "浮现", "开启", "传承", "机缘", "突破", "征兆", "预示"],
    "危机": ["坍塌", "苏醒", "围攻", "追杀", "濒死", "陷阱", "绝境", "深渊", "末日"],
    "反转": ["陷阱", "夺舍", "反杀", "伪装", "真实身份", "竟是", "原来"],
    "情感": ["泪水", "拥抱", "重逢", "离别", "感动", "温暖", "心碎"],
}

PP_KEYWORDS = {
    "打脸": ["打脸", "震惊", "不可思议", "目瞪口呆", "嘲讽", "瞧不起", "亮明身份"],
    "突破升级": ["突破", "晋级", "领悟", "突破瓶颈", "冲关", "渡劫", "升阶"],
    "收获获得": ["获得", "得到", "收获", "捡到", "传承", "宝物", "秘籍"],
    "复仇": ["报仇", "复仇", "血债", "偿还", "清算"],
    "逆袭反转": ["反转", "反杀", "绝境", "逆袭", "翻盘", "扮猪吃虎"],
}


def run_auxiliary_checks(draft_text: str, golden_three: bool = False,
                         platform_profile=None, ch_num: int = 0) -> list[AuxiliaryCheckItem]:
    checks = []
    if not draft_text:
        return checks

    # 1. 钩子落地检查（末段关键词匹配）
    last_paragraph = _get_last_paragraph(draft_text)
    has_hook = False
    for cat, keywords in HOOK_KEYWORDS.items():
        for kw in keywords:
            if kw in last_paragraph:
                has_hook = True
                break
        if has_hook:
            break
    checks.append(AuxiliaryCheckItem(
        name="钩子落地",
        status="pass" if has_hook else "warn",
        detail="末段检测到钩子信号" if has_hook else "末段未检测到明显钩子信号",
    ))

    # 2. 爽点密度（关键词匹配估算）
    pp_chars = 0
    for cat, keywords in PP_KEYWORDS.items():
        for kw in keywords:
            if kw in draft_text:
                pp_chars += draft_text.count(kw) * 50  # 粗略估算每个关键词周围50字
    total_chars = len(draft_text.replace(" ", "").replace("\n", ""))
    pp_rate = min(pp_chars / max(total_chars, 1), 1.0)
    target = 0.12
    if platform_profile and hasattr(platform_profile, 'pleasure_density'):
        from ..state.state_types import get_pleasure_density_target
        target = get_pleasure_density_target(platform_profile)
    checks.append(AuxiliaryCheckItem(
        name="爽点密度",
        status="pass" if pp_rate >= target * 0.7 else "warn",
        detail=f"估算 {pp_rate:.0%}，预设 {target:.0%}",
    ))

    # 3. 毒点扫描
    lines = draft_text.split("\n")
    poison_hits = []
    for i, line in enumerate(lines, 1):
        for kw in POISON_KEYWORDS:
            if kw in line:
                poison_hits.append((i, kw))
    checks.append(AuxiliaryCheckItem(
        name="毒点扫描",
        status="warn" if poison_hits else "pass",
        detail=f"检测到 {', '.join(f'L{p}:{k}' for p, k in poison_hits)}" if poison_hits else "未检测到毒点",
        position=poison_hits[0][0] if poison_hits else 0,
    ))

    # 4. 字数范围
    char_count = len(draft_text.replace(" ", "").replace("\n", ""))
    in_range = 2000 <= char_count <= 6000
    checks.append(AuxiliaryCheckItem(
        name="字数范围",
        status="pass" if in_range else "warn",
        detail=f"{char_count} 字（建议 3000-5000）",
    ))

    # 5. 黄金三章专项
    if golden_three:
        golden_warnings = []
        first_100 = draft_text[:100]
        # 检查是否环境描写开头（场景类词汇密集）
        env_count = sum(1 for w in ["天空", "大地", "阳光", "微风", "树林", "城市", "街道"] if w in first_100)
        if env_count >= 3:
            golden_warnings.append("开头环境描写词过多，建议从冲突/悬念切入")
        checks.append(AuxiliaryCheckItem(
            name="黄金三章",
            status="warn" if golden_warnings else "pass",
            detail="; ".join(golden_warnings) if golden_warnings else "黄金三章约束满足",
        ))

    return checks


def _get_last_paragraph(text: str) -> str:
    lines = text.rstrip().split("\n")
    last = ""
    for line in reversed(lines):
        stripped = line.strip()
        if stripped:
            last = stripped + last
        if len(last) > 200:
            break
    return last[-200:] if last else ""
