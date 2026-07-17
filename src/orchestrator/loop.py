"""
Orchestrator 主循环 — 异步生成器，yield SSE 事件

流程：
1. thinking → 主Agent决策 → agent_call → 子Agent执行
2. 若需要确认 → confirm → 等待用户响应 → 回到主Agent
3. 若全书完成 → done → 等待用户确认 → 结束
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import AsyncGenerator, Optional

from ..utils.llm import LLMClient, create_llm_client
from ..state.state_types import get_pleasure_density_target, StoryState, StoryCore, StoryArc
from .models import (
    SSEEvent, SSEEventType, OrchestratorDecision, AgentResult,
    Dashboard, AgentName,
)
from .workspace import Workspace
from .adapters import call_agent
from .stale_tracker import mark_stale, clear_stale
from .decision import (
    decide_next_action,
    generate_hook_matrix,
    generate_pleasure_curve,
    validate_hook_matrix,
    validate_pleasure_curve,
    auto_degrade_hook_matrix,
    auto_degrade_pleasure_curve,
)

logger = logging.getLogger("writesync")


class OrchestratorSession:
    """
    编排器会话 — 管理一段写作会话的完整生命周期。

    用法（CLI 模式）：
        session = OrchestratorSession(workspace)
        async for event in session.run():
            print(event)
            if event.type == "confirm":
                session.user_respond(approved=True, feedback="")
            elif event.type == "done":
                session.user_respond(approved=True)
    """

    def __init__(self, workspace: Workspace, llm: Optional[LLMClient] = None):
        self.workspace = workspace
        # 编排器决策使用 pro 模型（高质量决策），子Agent 使用 flash（快速生成）
        if llm is None:
            self.llm = create_llm_client(model="deepseek-v4-pro")
        else:
            self.llm = llm

        # 暂停/恢复
        self._pause = asyncio.Event()
        self._user_response: Optional[dict] = None
        self._running = False

        # 统计
        self.step_count = 0
        self.started_at = ""
        self.finished_at = ""
        self._current_chapter_num: int = 0  # 追踪当前处理的章节号（用于确认标记）

    # =========================================================================
    # 用户交互
    # =========================================================================

    def user_respond(self, approved: bool, feedback: str = "",
                     scope: str = "all", edited_content=None,
                     selected_action: str = ""):
        """用户响应确认/完成事件"""
        self._user_response = {
            "approved": approved,
            "feedback": feedback,
            "scope": scope,
            "edited_content": edited_content,
            "selected_action": selected_action,
        }
        self._pause.set()

    async def _wait_for_user(self) -> dict:
        """暂停循环，等待用户响应"""
        self._pause.clear()
        # 防止竞态：用户响应可能在 _pause.clear() 前已到达
        if self._user_response is not None:
            resp = self._user_response
            self._user_response = None
            return resp
        await self._pause.wait()
        resp = self._user_response or {"approved": False, "feedback": ""}
        self._user_response = None
        return resp

    async def _wait_for_suggestion_response(self, timeout: float = 30.0) -> dict:
        """v0.5.0 Suggestion Mode: 等待用户对备选方案的选择（30s 超时自动放行）

        超时或无 selected_action 时，返回的 dict 中 selected_action 为空字符串，
        调用方应继续使用主建议。
        """
        self._pause.clear()
        if self._user_response is not None:
            resp = self._user_response
            self._user_response = None
            return resp
        try:
            await asyncio.wait_for(self._pause.wait(), timeout=timeout)
            resp = self._user_response or {"approved": False, "feedback": "", "selected_action": ""}
        except asyncio.TimeoutError:
            logger.info("建议等待超时 (%.0fs)，自动执行主建议", timeout)
            resp = {"approved": True, "feedback": "", "selected_action": ""}
        self._user_response = None
        return resp

    def _has_user_response(self) -> bool:
        """检查是否有待处理的用户响应"""
        return self._user_response is not None

    # =========================================================================
    # 主循环
    # =========================================================================

    async def run(self) -> AsyncGenerator[SSEEvent, None]:
        self._running = True
        self.step_count = 0
        self.started_at = datetime.now(timezone.utc).isoformat()

        try:
            while self._running:
                self.step_count += 1
                logger.info("--- Orchestrator step %d ---", self.step_count)

                # 1. thinking 事件
                yield SSEEvent(type="thinking", data={"step": self.step_count})

                # 2. 主Agent决策（注入 v0.4.0 上下文）
                dashboard = self.workspace.get_dashboard()
                l1_context = self.workspace.get_l1_context_for_prompt()
                seed_idea = self.workspace.get_seed_idea()
                platform = self.workspace.get_platform_profile()
                # 钩子/爽点统计
                hook_stats = self._compute_hook_stats()
                pleasure_stats = self._compute_pleasure_stats()
                # 黄金三章判断
                written = self.workspace.get_written_chapters()
                next_ch = (max(written) + 1) if written else 1
                golden_three = self.workspace.is_golden_three_chapter(next_ch)

                decision = await asyncio.to_thread(
                    decide_next_action,
                    dashboard=dashboard,
                    history=self.workspace.history,
                    feedbacks=self.workspace.feedbacks,
                    l1_context=l1_context,
                    seed_idea=seed_idea,
                    llm=self.llm,
                    platform_profile=platform,
                    golden_three=golden_three,
                    hook_stats=hook_stats,
                    pleasure_stats=pleasure_stats,
                )
                self.workspace.log_decision(decision)

                logger.info("决策: action=%s agent=%s reason=%s",
                            decision.action, decision.agent, decision.reason)

                # 3. 处理 done
                if decision.action == "done":
                    yield SSEEvent(type="done", data={
                        "reason": decision.reason,
                        "dashboard": dashboard.__dict__,
                    })
                    response = await self._wait_for_user()
                    if response.get("approved"):
                        self.finished_at = datetime.now(timezone.utc).isoformat()
                        break
                    else:
                        if response.get("feedback"):
                            self.workspace.add_feedback("orchestrator", response["feedback"])
                        continue

                # v0.5.0 Orchestrator Suggestion Mode: 主决策后、执行子Agent前提供备选方案
                # 仅在 LLM 提供了 options 时触发；30s 超时自动放行（保持原有执行流）
                if decision.options:
                    valid_option_actions = {
                        o.get("action") for o in decision.options
                        if isinstance(o, dict) and o.get("action")
                    }
                    yield SSEEvent(type="suggestion", data={
                        "primary": decision.agent,
                        "reasoning": decision.reason,
                        "options": decision.options,
                    })
                    sugg_resp = await self._wait_for_suggestion_response(timeout=30.0)
                    selected = sugg_resp.get("selected_action", "")
                    if selected and selected != decision.agent:
                        if selected in valid_option_actions:
                            logger.info(
                                "Suggestion Mode: 用户切换 %s → %s",
                                decision.agent, selected,
                            )
                            decision.agent = selected
                        else:
                            logger.warning(
                                "Suggestion Mode: 用户选择了未知 action=%s，回退到主建议 %s",
                                selected, decision.agent,
                            )

                # 4. 调用子Agent
                logger.info("调用子Agent: %s, instruction: %s", decision.agent, decision.instruction)

                # 主Agent请求 L2 上下文
                l2_context = ""
                if decision.request_context:
                    l2_context = self.workspace.get_l2_context(decision.request_context)
                    if l2_context:
                        logger.info("注入 L2 上下文 (%d 字符): %s",
                                    len(l2_context), decision.request_context)

                yield SSEEvent(type="agent_call", data={
                    "agent": decision.agent,
                    "instruction": decision.instruction,
                })

                chapter_num = self._extract_chapter_num(decision.instruction)
                # 记录当前章节号，供 _mark_confirmed 使用
                if decision.agent in ("writer", "proofreader"):
                    self._current_chapter_num = chapter_num

                result = await asyncio.to_thread(
                    call_agent,
                    workspace=self.workspace,
                    agent_name=decision.agent,
                    instruction=decision.instruction,
                    chapter_num=chapter_num,
                    # 不传 llm：子 Agent 自行创建 deepseek-v4-flash 客户端
                    # 编排器决策用 pro，子 Agent 生成用 flash（READM/架构详设约定）
                )
                self.workspace.log_agent_result(result)

                if result.error:
                    logger.error("子Agent %s 失败: %s", decision.agent, result.error)
                    yield SSEEvent(type="error", data={
                        "message": result.error,
                        "agent": decision.agent,
                    })
                    continue

                # 5. 刷新 L1 上下文缓存 + 保存状态
                self.workspace.build_context_cache()
                self.workspace.save()

                # 6. workspace_update 事件
                ws_event_data = {
                    "agent": decision.agent,
                    "data": result.content,
                    "summary": result.summary,
                }
                yield SSEEvent(type="workspace_update", data=ws_event_data)

                # v0.4.0: auxiliary_check 事件
                if decision.agent == "writer" and "auxiliary_checks" in result.content:
                    ac_data = result.content.get("auxiliary_checks", [])
                    yield SSEEvent(type="auxiliary_check", data={
                        "chapter_num": result.content.get("chapter_num", 0),
                        "checks": ac_data,
                    })

                # 7. confirm 事件（如果需要确认）
                if result.requires_confirmation:
                    dashboard = self.workspace.get_dashboard()
                    yield SSEEvent(type="confirm", data={
                        "agent": result.agent,
                        "content": result.content,
                        "dashboard": dashboard.__dict__,
                        "chapter_num": chapter_num if chapter_num > 0 else None,
                    })

                    # 等待用户确认
                    response = await self._wait_for_user()

                    # 先应用用户编辑
                    if response.get("edited_content"):
                        self._apply_edits(result.agent, response["edited_content"], chapter_num)
                        mark_stale(self.workspace, result.agent)
                        self._request_fact_revalidation(result.agent, chapter_num)

                    if response.get("feedback"):
                        self.workspace.add_feedback(result.agent, response["feedback"])

                    if response.get("approved"):
                        self._mark_confirmed(result.agent)
                        # v0.5.0: 卷切换检测 — 当前卷章节全部确认后发射 volume_change
                        if self._check_volume_transition():
                            new_vol = self.workspace.get_current_volume()
                            yield SSEEvent(type="volume_change", data={
                                "from_volume": new_vol.index - 1 if new_vol else 0,
                                "to_volume": new_vol.index if new_vol else 1,
                                "total_volumes": len(self.workspace.raw_state.volumes),
                            })

                # 8. 继续循环
                await asyncio.sleep(0)

        except Exception as e:
            logger.exception("Orchestrator 异常")
            yield SSEEvent(type="error", data={"message": str(e)})
        finally:
            self._running = False

    # =========================================================================
    # 辅助方法
    # =========================================================================

    def _check_volume_transition(self) -> bool:
        """检查是否当前卷所有章节已确认 → 应切换到下一卷"""
        ws_state = self.workspace.raw_state
        if not ws_state.volumes or len(ws_state.volumes) <= 1:
            return False
        vol = self.workspace.get_current_volume()
        if not vol or not vol.chapter_indices:
            return False
        # 检查当前卷所有章节是否都已确认
        written = self.workspace.get_written_chapters()
        for ch_idx in vol.chapter_indices:
            ch_num = ch_idx + 1  # chapter_indices 是 0-based
            if ch_num not in written:
                return False
        # 当前卷完成 → 切换到下一卷
        next_idx = vol.index  # vol.index 是 1-based，下一卷 = index + 1
        if next_idx < len(ws_state.volumes):
            ws_state.metadata.current_volume = next_idx + 1  # 切到下一卷
            logger.info("卷切换: %d → %d", vol.index, next_idx + 1)
            return True
        return False

    def _extract_chapter_num(self, instruction: str) -> int:
        """从指令中提取章节号"""
        import re
        if not instruction:
            return 0
        # 匹配 "第X章" 或 "chapter X" 或 "ch X"
        patterns = [
            r'第\s*(\d+)\s*章',
            r'chapter\s*(\d+)',
            r'ch[.]?\s*(\d+)',
            r'#(\d+)',
        ]
        for pat in patterns:
            m = re.search(pat, instruction, re.IGNORECASE)
            if m:
                return int(m.group(1))
        return 0

    def _find_selected_topic(self):
        """从 feedbacks 中找到用户选择的选题，返回 TopicSuggestion 或 None"""
        ws_state = self.workspace.raw_state
        if not ws_state.topic or not ws_state.topic.suggestions:
            return None
        suggestions = ws_state.topic.suggestions

        # 1. 从 feedbacks 中匹配选题标题（最近优先）
        for fb in reversed(self.workspace.feedbacks):
            if fb.get("agent") == "story":
                # 修复: feedback 键名是 "feedback" 不是 "text"
                feedback = (fb.get("feedback") or fb.get("text") or "").strip()
                if not feedback:
                    continue
                for idx, s in enumerate(suggestions):
                    if s.title in feedback or feedback in s.title:
                        ws_state.topic.selected = idx
                        return s

        # 2. 若 TopicState.selected 已明确
        if 0 <= ws_state.topic.selected < len(suggestions):
            return suggestions[ws_state.topic.selected]

        # 3. 降级：取第一条建议
        if suggestions:
            ws_state.topic.selected = 0
            return suggestions[0]

        return None

    def _apply_edits(self, agent: str, edits: dict, chapter_num: int = 0):
        """将用户编辑的内容直接写入 workspace state"""
        state = self.workspace.raw_state

        if agent == "story":
            story = state.story
            if not story:
                return
            if "one_sentence" in edits:
                story.step1.one_sentence = edits["one_sentence"]
            if "tag" in edits:
                story.step1.tag = edits["tag"]
            if story.step2:
                for field in ["setup", "inciting", "rising", "climax_prep", "resolution", "theme", "moral"]:
                    if field in edits:
                        setattr(story.step2, field, edits[field])

        elif agent == "character":
            if "characters" in edits and state.characters:
                new_list = edits["characters"]
                for i, ch_data in enumerate(new_list):
                    if i < len(state.characters.characters):
                        card = state.characters.characters[i]
                        for key in ["name", "role", "personality", "goal"]:
                            if key in ch_data:
                                setattr(card, key, ch_data[key])

        elif agent == "world":
            world = state.world
            if not world:
                return
            if "power_system" in edits and world.power_system:
                world.power_system.system_name = edits["power_system"]
            if "tiers" in edits and world.power_system:
                tiers_val = edits["tiers"]
                if isinstance(tiers_val, str):
                    world.power_system.tiers = [t.strip() for t in tiers_val.split(",") if t.strip()]
                else:
                    world.power_system.tiers = tiers_val
            if "locations" in edits and world.geography:
                locs = edits["locations"]
                if isinstance(locs, str):
                    locs = [l.strip() for l in locs.split(",") if l.strip()]
                if locs and isinstance(locs[0], dict):
                    world.geography.major_locations = locs
                else:
                    world.geography.major_locations = [
                        {"name": loc, "description": "", "significance": ""}
                        if isinstance(loc, str) else loc
                        for loc in locs
                    ]
            if "factions" in edits and world.society:
                facs = edits["factions"]
                if isinstance(facs, str):
                    facs = [f.strip() for f in facs.split(",") if f.strip()]
                if facs and isinstance(facs[0], dict):
                    world.society.factions = facs
                else:
                    world.society.factions = [
                        {"name": fac, "description": "", "align": ""}
                        if isinstance(fac, str) else fac
                        for fac in facs
                    ]

        elif agent == "outline":
            outline = state.chapter_outline
            if not outline:
                return
            if "chapters" in edits:
                for i, ch_data in enumerate(edits["chapters"]):
                    if i < len(outline.chapters):
                        ch = outline.chapters[i]
                        if "title" in ch_data:
                            ch.chapter_title = ch_data["title"]
                        if "core_event" in ch_data:
                            ch.core_event = ch_data["core_event"]
            if "total_chapters" in edits:
                outline.total_chapters = edits["total_chapters"]

        elif agent == "writer":
            ch = state.drafts.chapters.get(chapter_num)
            if ch and ch.draft:
                if "content" in edits:
                    ch.draft.content = edits["content"]

        elif agent == "proofreader":
            ch = state.drafts.chapters.get(chapter_num)
            if ch and ch.final:
                if "content" in edits:
                    ch.final.content = edits["content"]

        self.workspace.save()

    def _request_fact_revalidation(self, agent: str, chapter_num: int):
        """Phase 3: 编辑确认后触发异步事实提取 + 上下文更新。

        Uses fire-and-forget pattern to avoid blocking the orchestration loop.
        Fact extraction via LLM + regex fallback runs in background.
        """
        if agent in ("writer", "proofreader") and chapter_num > 0:
            try:
                from src.agents.fact_ledger import FactLedger, extract_facts_async
                ledger = FactLedger(self.workspace)
                ch = self.workspace.raw_state.drafts.chapters.get(chapter_num)
                if ch and ch.draft and ch.draft.content:
                    content = ch.draft.content
                    # Fire-and-forget: extract facts asynchronously
                    loop = asyncio.get_event_loop()
                    loop.create_task(extract_facts_async(ledger, content, chapter_num))
                    logger.info(
                        "[fact_revalidate] scheduled async extraction for ch=%d agent=%s",
                        chapter_num, agent,
                    )
            except Exception as e:
                logger.warning("[fact_revalidate] failed to schedule: %s", e)

    def _mark_confirmed(self, agent_name: str):
        """标记确认时间，更新章节状态"""
        now = datetime.now(timezone.utc).isoformat()
        ws_state = self.workspace.raw_state

        if agent_name == "story":
            # Stage 1: 选题确认 → 从选中选题创建 StoryState
            if ws_state.story is None:
                selected = self._find_selected_topic()
                if selected is not None:
                    ws_state.story = StoryState(
                        step1=StoryCore(
                            one_sentence=selected.core_selling_point or selected.title,
                            tag=selected.genre,
                        ),
                        step2=StoryArc(setup="", inciting="", rising="", climax_prep="", resolution="", theme=""),
                        confirmed_at=now,
                    )
                    logger.info("从选题创建 StoryState: %s", selected.title)
                    self.workspace.save()
                    return
            if ws_state.story:
                ws_state.story.confirmed_at = now
        elif agent_name == "character":
            if ws_state.characters:
                ws_state.characters.confirmed_at = now
        elif agent_name == "world":
            if ws_state.world:
                if ws_state.world.skel_confirmed_at is None:
                    # 第一次确认：标记大纲骨架已确认
                    ws_state.world.skel_confirmed_at = now
                    logger.info("世界观大纲骨架已确认")
                else:
                    # 第二次确认：标记完整细节已确认
                    ws_state.world.confirmed_at = now
                    logger.info("世界观详细设定已确认")
        elif agent_name == "outline":
            if ws_state.chapter_outline:
                ws_state.chapter_outline.confirmed_at = now
        elif agent_name == "writer":
            # 标记章节草稿为已确认（用户确认初稿）
            ch_num = self._current_chapter_num
            if ch_num > 0 and ch_num in ws_state.drafts.chapters:
                cd = ws_state.drafts.chapters[ch_num]
                cd.stage = "final"
                cd.updated_at = now
                logger.info("第%d章初稿已确认（stage=final）", ch_num)
        elif agent_name == "proofreader":
            # 校对自动确认（proofreader 不触发 confirm，但保留处理）
            ch_num = self._current_chapter_num
            if ch_num > 0 and ch_num in ws_state.drafts.chapters:
                cd = ws_state.drafts.chapters[ch_num]
                cd.stage = "final"
                cd.updated_at = now
        elif agent_name == "novel_review":
            if ws_state.novel_review:
                ws_state.novel_review.confirmed_at = now

        # v0.4.0: 章纲确认后生成钩子矩阵和爽点曲线
        if agent_name == "outline":
            self._generate_hook_matrix()
            self._generate_pleasure_curve()

        # Phase 3: 章节确认后提取事实 + 连续性信封
        if agent_name in ("writer", "proofreader"):
            ch_num = self._current_chapter_num
            if ch_num > 0:
                self._extract_chapter_memory(ch_num)

        # 清除 stale 标记
        clear_stale(self.workspace, agent_name)

        self.workspace.save()

    def _generate_hook_matrix(self):
        vol = self.workspace.get_current_volume()
        if not vol:
            return
        platform = self.workspace.get_platform_profile()
        ch_count = len(vol.chapter_indices)
        if ch_count <= 0:
            return
        is_v1 = vol.index == 1
        for attempt in range(3):
            hooks = generate_hook_matrix(ch_count, is_volume_one=is_v1,
                                         hook_strength_min=platform.hook_strength_min,
                                         golden_three_boost=platform.golden_three_boost == "极度强化")
            errors = validate_hook_matrix(hooks, ch_count, is_v1, platform.hook_strength_min)
            if not errors:
                vol.hook_matrix = hooks
                vol.auto_degraded = False
                logger.info("钩子矩阵生成成功 (%d章, %d hooks)", ch_count, len(hooks))
                return
            logger.warning("钩子矩阵校验失败 (attempt %d/3): %s", attempt + 1, errors)
        # 降级
        vol.hook_matrix = auto_degrade_hook_matrix(ch_count, platform.hook_strength_min)
        vol.auto_degraded = True
        logger.warning("钩子矩阵已降级 (自动生成)")

    def _generate_pleasure_curve(self):
        vol = self.workspace.get_current_volume()
        if not vol:
            return
        platform = self.workspace.get_platform_profile()
        ch_count = len(vol.chapter_indices)
        if ch_count <= 0:
            return
        density = get_pleasure_density_target(platform)
        for attempt in range(3):
            curve = generate_pleasure_curve(ch_count, density, is_volume_one=vol.index == 1)
            errors = validate_pleasure_curve(curve, ch_count)
            if not errors:
                vol.pleasure_curve = curve
                logger.info("爽点曲线生成成功 (%d章)", len(curve))
                return
            logger.warning("爽点曲线校验失败 (attempt %d/3): %s", attempt + 1, errors)
        vol.pleasure_curve = auto_degrade_pleasure_curve(ch_count)
        logger.warning("爽点曲线已降级 (自动生成)")

    def _compute_hook_stats(self) -> dict:
        vol = self.workspace.get_current_volume()
        if not vol or not vol.hook_matrix:
            return {}
        total = len(vol.hook_matrix)
        landed = sum(1 for h in vol.hook_matrix if h.content)
        type_count = {}
        for h in vol.hook_matrix:
            type_count[h.hook_type] = type_count.get(h.hook_type, 0) + 1
        return {
            "rate": landed / max(total, 1),
            "distribution": ", ".join(f"{t}:{c}" for t, c in type_count.items()),
        }

    def _compute_pleasure_stats(self) -> dict:
        vol = self.workspace.get_current_volume()
        if not vol or not vol.pleasure_curve:
            return {}
        platform = self.workspace.get_platform_profile()
        target = get_pleasure_density_target(platform)
        # 简单估算
        actual = sum(c.word_ratio_target for c in vol.pleasure_curve) / max(len(vol.pleasure_curve), 1)
        return {
            "density": actual,
            "target": target,
        }

    def _extract_chapter_memory(self, chapter_num: int):
        """Phase 3: Extract facts + continuity envelope after chapter confirmation.

        Gets chapter content from state.drafts, calls FactLedger.extract_facts()
        and FactLedger.extract_envelope(), updates context cache, and saves workspace.
        Uses fire-and-forget to avoid blocking the orchestration loop.
        """
        try:
            from src.agents.fact_ledger import (
                FactLedger, extract_facts_async, extract_envelope_async,
            )
            from src.agents.context import update_dynamic_context

            ws_state = self.workspace.raw_state
            cd = ws_state.drafts.chapters.get(chapter_num)
            if not cd:
                return

            content = ""
            if cd.final and cd.final.content:
                content = cd.final.content
            elif cd.draft and cd.draft.content:
                content = cd.draft.content

            if not content:
                return

            # Build outline text for envelope extraction
            outline_text = ""
            if ws_state.chapter_outline:
                for ch in ws_state.chapter_outline.chapters:
                    if ch.chapter_number == chapter_num:
                        outline_text = (
                            f"第{ch.chapter_number}章 {ch.chapter_title}: "
                            f"{ch.core_event}. {ch.character_states}"
                        )
                        break

            # Update dynamic context (existing pipeline)
            update_dynamic_context(
                {"data": ws_state}, chapter_num, skip_llm=False
            )

            # Fire-and-forget: extract facts + envelope asynchronously
            ledger = FactLedger(self.workspace)
            loop = asyncio.get_event_loop()

            # Extract facts
            loop.create_task(extract_facts_async(ledger, content, chapter_num))

            # Extract continuity envelope
            loop.create_task(
                extract_envelope_async(
                    self.workspace, content, outline_text, chapter_num, ledger
                )
            )

            # Phase 4A: Foreshadow extraction
            try:
                from src.agents.foreshadow import ForeshadowManager, extract_foreshadows_async
                fmgr = ForeshadowManager(self.workspace)
                pid = ws_state.metadata.project_id
                loop.create_task(extract_foreshadows_async(fmgr, content, chapter_num, pid))
                logger.info("[chapter_memory] ch=%d scheduled foreshadow extraction", chapter_num)
            except Exception as e:
                logger.warning("[chapter_memory] foreshadow extraction failed to schedule: %s", e)

            # Phase 4A: State table extraction
            try:
                from src.agents.state_table import StateTable, extract_states_async
                stable = StateTable(self.workspace)
                pid = ws_state.metadata.project_id
                loop.create_task(extract_states_async(stable, content, chapter_num, pid))
                logger.info("[chapter_memory] ch=%d scheduled state_table extraction", chapter_num)
            except Exception as e:
                logger.warning("[chapter_memory] state_table extraction failed to schedule: %s", e)

            # Phase 4A: Item ledger extraction
            try:
                from src.agents.item_ledger import ItemLedger, extract_items_async
                iledger = ItemLedger(self.workspace)
                loop.create_task(extract_items_async(iledger, content, chapter_num))
                logger.info("[chapter_memory] ch=%d scheduled item_ledger extraction", chapter_num)
            except Exception as e:
                logger.warning("[chapter_memory] item_ledger extraction failed to schedule: %s", e)

            # Phase 6: Timeline extraction
            try:
                from src.agents.timeline import TimelineManager, extract_timeline_async
                pid = ws_state.metadata.project_id
                tmgr = TimelineManager(pid)
                loop.create_task(extract_timeline_async(tmgr, content, chapter_num))
                logger.info("[chapter_memory] ch=%d scheduled timeline extraction", chapter_num)
            except Exception as e:
                logger.warning("[chapter_memory] timeline extraction failed to schedule: %s", e)

            # Rebuild context cache
            self.workspace.build_context_cache()
            self.workspace.save()

            logger.info(
                "[chapter_memory] ch=%d scheduled fact+envelope+foreshadow+state+item extraction, "
                "content_len=%d outline_len=%d",
                chapter_num, len(content), len(outline_text),
            )
        except Exception as e:
            logger.warning("[chapter_memory] ch=%d failed: %s", chapter_num, e)

    def is_running(self) -> bool:
        return self._running

    def stop(self):
        self._running = False
        self._pause.set()
