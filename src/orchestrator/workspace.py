"""
Workspace — v0.3.0 工作空间状态管理

封装 WriteSyncState，提供：
- schema_version 追踪（v1→v2 迁移）
- L0 仪表盘
- L1 上下文缓存（角色/世界观/章纲/章节摘要）
- L2 按需深度上下文
- L3 调试日志（orchestrator_log.jsonl）
- 会话历史与反馈
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..state.state_types import (
    WriteSyncState,
    ProjectMetadata,
    TopicState,
    StoryState,
    StoryCore,
    CharactersState,
    WorldState,
    ChapterOutlineState,
    DraftsState,
    DraftContent,
    ChapterDraft,
    NovelReviewState,
    WorkflowState,
    VersionState,
    StepName,
    ProjectStatus,
    Character,
    HookCard,
    PleasurePointCard,
    PlatformProfile,
    VolumeState,
    get_platform_profile,
    get_pleasure_density_target,
)
from ..state.persistence import PersistenceManager
from .models import Dashboard, Progress

logger = logging.getLogger("writesync")

CURRENT_SCHEMA_VERSION = 3


class Workspace:
    """v0.3.0 工作空间，包装 WriteSyncState 并提供新接口"""

    def __init__(self, ws_state: WriteSyncState, project_dir: str = "",
                 schema_version: Optional[int] = None):
        self._state = ws_state
        self._project_dir = project_dir

        # schema_version 检测
        if schema_version is not None:
            self._schema_version = schema_version
        elif project_dir and (Path(project_dir) / "schema_version.json").exists():
            self._schema_version = self._detect_schema_version()
        elif project_dir:
            self._schema_version = 1  # 旧项目无文件 = v1
        else:
            self._schema_version = CURRENT_SCHEMA_VERSION

        if not self._state.metadata.project_id:
            raise ValueError("WriteSyncState 缺少 project_id")

        # 会话历史
        self.history: list[dict] = []
        self.feedbacks: list[dict] = []
        self._history_max = 100

        # L1 上下文缓存
        self.context_cache: dict = {
            "characters_summary": "",
            "world_summary": "",
            "outline_summary": "",
            "last_chapter_summary": "",
            "chapters_summaries": {},   # {ch_num: summary}
            "updated_at": "",
        }

        # prompt_overrides: agent_name → custom_system_prompt 持久化
        self.prompt_overrides: dict = {}
        # genre_pack_name: 当前项目使用的题材包
        self.genre_pack_name: str = "default"

        # 从磁盘恢复
        self._load_context_cache()
        self._load_prompt_overrides()
        self._load_session_log()
        self._load_session_data()

    # =========================================================================
    # Schema 版本
    # =========================================================================

    @property
    def schema_version(self) -> int:
        return self._schema_version

    @schema_version.setter
    def schema_version(self, v: int):
        self._schema_version = v

    def needs_migration(self) -> bool:
        return self._schema_version < CURRENT_SCHEMA_VERSION

    def migrate(self) -> list[str]:
        """执行 v1→v2→v3 迁移，返回变更日志"""
        changes = []
        v = self.schema_version

        if v < 2:
            changes.append("v1→v2: 初始化 context_cache")
            self.context_cache = {
                "characters_summary": "",
                "world_summary": "",
                "outline_summary": "",
                "last_chapter_summary": "",
                "chapters_summaries": {},
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            self.schema_version = 2
            self._save_context_cache()
            self._save_schema_version()

        if self.schema_version < 3:
            changes.append("v2→v3: 初始化分卷 + 平台策略")
            s = self._state
            # 创建虚拟卷（所有已有章节合并为第一卷）
            if not s.volumes:
                ch_count = 0
                if s.chapter_outline:
                    ch_count = s.chapter_outline.total_chapters or len(s.chapter_outline.chapters)
                vol = VolumeState(
                    index=1,
                    one_sentence=s.story.step1.one_sentence if s.story else "",
                    chapter_indices=list(range(ch_count)),
                    status="writing" if ch_count > 0 else "planning",
                )
                s.volumes = [vol]
                s.current_volume_index = 0
            # 平台策略推断
            if s.platform_profile is None:
                platform_name = s.metadata.platform or "起点"
                s.platform_profile = get_platform_profile(platform_name)
            self.schema_version = 3
            self._save_schema_version()

        return changes

    def _save_schema_version(self):
        if not self._project_dir:
            return
        try:
            sc = {"schema_version": self._schema_version}
            with open(Path(self._project_dir) / "schema_version.json", "w", encoding="utf-8") as f:
                json.dump(sc, f, ensure_ascii=False)
        except Exception as e:
            logger.debug("schema_version 保存失败: %s", e)

    def _detect_schema_version(self) -> int:
        if not self._project_dir:
            return CURRENT_SCHEMA_VERSION
        sc_path = Path(self._project_dir) / "schema_version.json"
        if not sc_path.exists():
            return 1
        try:
            sc = json.loads(sc_path.read_text(encoding="utf-8"))
            return sc.get("schema_version", 1)
        except Exception:
            return 1

    # =========================================================================
    # 基础属性
    # =========================================================================

    @property
    def project_id(self) -> str:
        return self._state.metadata.project_id

    @property
    def project_name(self) -> str:
        return self._state.metadata.name

    @property
    def platform(self) -> str:
        return self._state.metadata.platform

    @property
    def raw_state(self) -> WriteSyncState:
        return self._state

    # =========================================================================
    # 仪表盘（L0）
    # =========================================================================

    def get_dashboard(self) -> Dashboard:
        """构建 L0 仪表盘"""
        s = self._state
        completed: list[str] = []
        pending: str = ""

        if s.story and s.story.confirmed_at:
            completed.append("story")
        if s.characters and s.characters.confirmed_at:
            completed.append("character")
        if s.world and s.world.skel_confirmed_at:
            completed.append("world_skeleton")
        if s.world and s.world.confirmed_at:
            completed.append("world")
        if s.chapter_outline and s.chapter_outline.confirmed_at:
            completed.append("outline")

        total = 0
        written = 0
        proofread_count = 0
        confirmed_count = 0
        if s.chapter_outline:
            total = s.chapter_outline.total_chapters or len(s.chapter_outline.chapters)
            written = len(s.chapter_outline.written_chapters)
        if s.drafts and s.drafts.chapters:
            for cd in s.drafts.chapters.values():
                if cd.final:
                    proofread_count += 1
                if cd.stage == "final":
                    confirmed_count += 1

        phase = "idle"
        if confirmed_count >= total and total > 0 and s.novel_review:
            phase = "review"
        elif written > 0:
            phase = "writing_chapters"
        elif "outline" in completed:
            phase = "writing_chapters"
        elif "story" in completed:
            phase = "planning"
        elif s.topic and s.topic.suggestions:
            phase = "topic_selection"
        else:
            phase = "new"

        last_fb = ""
        if self.feedbacks:
            last_fb = self.feedbacks[-1].get("feedback", "")[:200]

        # v0.4.0: 钩子落地率 / 爽点密度 / 自动降级标记
        vol = self.get_current_volume()
        hook_landing_rate = 0.0
        pleasure_density = 0.0
        auto_degraded = False
        if vol and vol.hook_matrix:
            total_hooks = len(vol.hook_matrix)
            landed = sum(1 for h in vol.hook_matrix if h.content)
            hook_landing_rate = landed / max(total_hooks, 1)
        if vol and vol.pleasure_curve:
            pleasure_density = sum(c.word_ratio_target for c in vol.pleasure_curve) / max(len(vol.pleasure_curve), 1)
        if vol:
            auto_degraded = vol.auto_degraded

        return Dashboard(
            phase=phase,
            completed_agents=completed,
            pending_confirm=pending,
            last_user_feedback=last_fb,
            progress=Progress(
                total_chapters=total,
                written=written,
                proofread=proofread_count,
                confirmed=confirmed_count,
                total_volumes=len(self._state.volumes),
                current_volume=self._state.current_volume_index + 1,
            ),
            updated_at=datetime.now(timezone.utc).isoformat(),
            platform=self.platform,
            golden_three_active=self.is_golden_three_chapter(
                max(self.get_written_chapters()) if self.get_written_chapters() else 1
            ),
            orchestrator_mode=(
                "planning" if not self.has_outline() else
                "reviewing" if self.is_all_written() else "orchestrating"
            ),
            hook_landing_rate=hook_landing_rate,
            pleasure_density=pleasure_density,
            auto_degraded=auto_degraded,
            stale_markers=s.stale_markers,
        )

    # =========================================================================
    # 状态查询
    # =========================================================================

    def has_story(self) -> bool:
        s = self._state.story
        return s is not None and bool(s.step1.one_sentence)

    def has_characters(self) -> bool:
        c = self._state.characters
        return c is not None and len(c.characters) > 0

    def has_world(self) -> bool:
        return self._state.world is not None

    def has_world_skeleton(self) -> bool:
        """世界观大纲骨架是否已生成（阶段1完成）"""
        w = self._state.world
        return w is not None and bool(w.power_system.system_name)

    def has_outline(self) -> bool:
        o = self._state.chapter_outline
        return o is not None and len(o.chapters) > 0

    def has_drafts(self) -> bool:
        return bool(self._state.drafts.chapters)

    def get_total_chapters(self) -> int:
        if self._state.chapter_outline:
            return self._state.chapter_outline.total_chapters or len(self._state.chapter_outline.chapters)
        return 0

    def get_written_chapters(self) -> list[int]:
        if self._state.chapter_outline:
            return list(self._state.chapter_outline.written_chapters)
        return []

    def get_draft_chapters(self) -> dict[int, "ChapterDraft"]:
        return dict(self._state.drafts.chapters)

    def is_all_written(self) -> bool:
        total = self.get_total_chapters()
        return total > 0 and len(self.get_written_chapters()) >= total

    def is_all_proofread(self) -> bool:
        total = self.get_total_chapters()
        if total <= 0:
            return False
        for ch_num in range(1, total + 1):
            if ch_num not in self._state.drafts.chapters:
                return False
            cd = self._state.drafts.chapters[ch_num]
            if not cd.final:
                return False
        return True

    def has_review(self) -> bool:
        return self._state.novel_review is not None

    def is_story_confirmed(self) -> bool:
        return self._state.story is not None and self._state.story.confirmed_at is not None

    def is_characters_confirmed(self) -> bool:
        return self._state.characters is not None and self._state.characters.confirmed_at is not None

    def is_world_confirmed(self) -> bool:
        w = self._state.world
        return w is not None and w.confirmed_at is not None

    def is_world_skeleton_confirmed(self) -> bool:
        """世界观大纲骨架是否已确认（阶段1完成）"""
        w = self._state.world
        return w is not None and w.skel_confirmed_at is not None

    def is_outline_confirmed(self) -> bool:
        return self._state.chapter_outline is not None and self._state.chapter_outline.confirmed_at is not None

    # =========================================================================
    # v0.4.0 分卷操作
    # =========================================================================

    def get_current_volume(self) -> Optional[VolumeState]:
        vols = self._state.volumes
        idx = self._state.current_volume_index
        if vols and 0 <= idx < len(vols):
            return vols[idx]
        return None

    def get_volume_count(self) -> int:
        return len(self._state.volumes)

    def get_volume_chapter_range(self, vol_idx: int = -1) -> tuple[int, int]:
        vol = self.get_current_volume() if vol_idx < 0 else (
            self._state.volumes[vol_idx] if 0 <= vol_idx < len(self._state.volumes) else None
        )
        if vol and vol.chapter_indices:
            return (vol.chapter_indices[0], vol.chapter_indices[-1])
        return (0, 0)

    def is_golden_three_chapter(self, ch_num: int) -> bool:
        vol = self.get_current_volume()
        if not vol or vol.index != 1:
            return False
        ch_range = self.get_volume_chapter_range()
        relative_ch = ch_num - ch_range[0]
        return 1 <= relative_ch <= 3

    def get_hook_card(self, ch_num: int) -> Optional[HookCard]:
        vol = self.get_current_volume()
        if not vol or not vol.hook_matrix:
            return None
        ch_range = self.get_volume_chapter_range()
        rel_idx = ch_num - ch_range[0]
        for card in vol.hook_matrix:
            if card.chapter_index == rel_idx:
                return card
        return None

    def get_pleasure_card(self, ch_num: int) -> Optional[PleasurePointCard]:
        vol = self.get_current_volume()
        if not vol or not vol.pleasure_curve:
            return None
        ch_range = self.get_volume_chapter_range()
        rel_idx = ch_num - ch_range[0]
        for card in vol.pleasure_curve:
            if card.chapter_index == rel_idx:
                return card
        return None

    def get_platform_profile(self) -> PlatformProfile:
        if self._state.platform_profile:
            return self._state.platform_profile
        return get_platform_profile(self._state.metadata.platform or "起点")

    # =========================================================================
    # 用户种子想法
    # =========================================================================

    def set_seed_idea(self, idea: str):
        if self._state.topic is None:
            now = datetime.now(timezone.utc).isoformat()
            self._state.topic = TopicState(
                user_original_idea=idea,
                suggestions=[],
                selected=-1,
                confirmed_at=None,
            )
            self._state.metadata.updated_at = now
        else:
            self._state.topic.user_original_idea = idea

    def get_seed_idea(self) -> str:
        if self._state.topic:
            return self._state.topic.user_original_idea
        return ""

    # =========================================================================
    # Prompt Overrides（用户自定义系统提示词 + 题材包）
    # =========================================================================

    def save_prompt_override(self, agent_name: str, custom_prompt: str):
        """保存某个 Agent 的自定义系统提示词。存到 prompts.json。"""
        self.prompt_overrides[agent_name] = custom_prompt
        self._save_prompt_overrides()

    def get_prompt_override(self, agent_name: str) -> str:
        """获取某个 Agent 的自定义系统提示词（不存在返回空字符串）。"""
        return self.prompt_overrides.get(agent_name, "")

    def remove_prompt_override(self, agent_name: str):
        """移除某个 Agent 的自定义系统提示词。"""
        self.prompt_overrides.pop(agent_name, None)
        self._save_prompt_overrides()

    def get_all_prompt_overrides(self) -> dict:
        """返回所有自定义提示词（agent_name → custom_prompt）。"""
        return dict(self.prompt_overrides)

    def set_genre_pack(self, pack_name: str):
        """设置当前项目使用的题材包（如 xianxia/urban/mystery/default）。"""
        self.genre_pack_name = pack_name
        self._save_prompt_overrides()

    def get_genre_pack(self) -> str:
        """获取当前项目使用的题材包名称。"""
        return self.genre_pack_name

    def get_prompt_context(self) -> dict:
        """
        构建 PromptManager 所需的渲染上下文。
        合并：题材包变量 + 用户自定义提示词 + 项目元数据。
        """
        context = {
            "genre": self._state.metadata.platform or "通用",
            "era": "任意",
            "power_system": "任意",
            "tone": "中性",
        }
        # 题材包变量由 PromptManager 从 JSON 加载
        # 用户覆盖的提示词在 get_system_prompt 中合并
        return context

    def _save_prompt_overrides(self):
        """持久化 prompt_overrides 到 prompts.json。"""
        if not self._project_dir:
            return
        try:
            data = {
                "genre_pack": self.genre_pack_name,
                "overrides": self.prompt_overrides,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            path = Path(self._project_dir) / "prompts.json"
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.debug("prompt_overrides 保存失败: %s", e)

    def _load_prompt_overrides(self):
        """从 prompts.json 恢复 prompt_overrides。"""
        if not self._project_dir:
            return
        path = Path(self._project_dir) / "prompts.json"
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self.genre_pack_name = data.get("genre_pack", "default")
            self.prompt_overrides = data.get("overrides", {})
        except Exception as e:
            logger.debug("prompt_overrides 加载失败: %s", e)

    # =========================================================================
    # L1 上下文缓存
    # =========================================================================

    def build_context_cache(self, use_llm: bool = False, llm_client=None):
        """构建/刷新 L1 上下文缓存（≤800 字摘要）"""
        s = self._state
        now = datetime.now(timezone.utc).isoformat()

        # 角色摘要
        if s.characters and s.characters.characters:
            chars = s.characters.characters
            lines = [f"角色({len(chars)}人):"]
            for c in chars[:8]:
                lines.append(f"  {c.name}({c.role}): {c.personality} | 目标:{c.goal}")
            if len(chars) > 8:
                lines.append(f"  ...及其他{len(chars)-8}人")
            self.context_cache["characters_summary"] = "\n".join(lines)[:800]

        # 世界观摘要
        if s.world:
            w = s.world
            parts = [f"力量体系: {w.power_system.system_name}"]
            if w.power_system.tiers:
                parts.append(f"等级: {' > '.join(w.power_system.tiers[:8])}")
            if w.geography and w.geography.major_locations:
                locs = [l.get("name", "?") for l in w.geography.major_locations[:5]]
                parts.append(f"主要地点: {', '.join(locs)}")
            self.context_cache["world_summary"] = "；".join(parts)[:800]

        # 章纲摘要
        if s.chapter_outline and s.chapter_outline.chapters:
            co = s.chapter_outline
            total = co.total_chapters or len(co.chapters)
            lines = [f"章纲: 共{total}章"]
            for ch in co.chapters[:5]:
                lines.append(f"  Ch{ch.chapter_number} {ch.chapter_title}: {ch.core_event[:60]}")
            if len(co.chapters) > 5:
                lines.append(f"  ...及其他{len(co.chapters)-5}章")
            self.context_cache["outline_summary"] = "\n".join(lines)[:800]

        # 最近章节摘要
        drafts = s.drafts.chapters
        if drafts:
            last_num = max(drafts.keys())
            cd = drafts[last_num]
            if cd.draft and cd.draft.content:
                self.context_cache["last_chapter_summary"] = (
                    f"第{last_num}章({cd.word_count}字): {cd.draft.content[:500]}..."
                )

        self.context_cache["updated_at"] = now
        self._save_context_cache()

    def _save_context_cache(self):
        if not self._project_dir:
            return
        try:
            cache_path = Path(self._project_dir) / "context_cache.json"
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(self.context_cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.debug("context_cache 保存失败: %s", e)

    def _load_context_cache(self):
        if not self._project_dir:
            return
        cache_path = Path(self._project_dir) / "context_cache.json"
        if not cache_path.exists():
            return
        try:
            loaded = json.loads(cache_path.read_text(encoding="utf-8"))
            self.context_cache.update(loaded)
        except Exception as e:
            logger.debug("context_cache 加载失败: %s", e)

    def get_l1_summary(self, key: str) -> str:
        """获取 L1 摘要字段"""
        return self.context_cache.get(key, "")

    def get_l1_context_for_prompt(self) -> str:
        """获取用于注入 Agent prompt 的 L1 上下文文本"""
        parts = []
        for key, label in [
            ("characters_summary", "角色摘要"),
            ("world_summary", "世界观摘要"),
            ("outline_summary", "章纲摘要"),
            ("last_chapter_summary", "最近章节"),
        ]:
            val = self.context_cache.get(key, "")
            if val:
                parts.append(f"## {label}\n{val}")
        return "\n\n".join(parts) if parts else ""

    # =========================================================================
    # L2 按需深度上下文
    # =========================================================================

    def get_l2_context(self, requests: list[str]) -> str:
        """
        按需获取 L2 深度上下文。
        requests: ["characters_full", "world_full", "outline_full", "drafts_full"]
        """
        parts = []
        s = self._state

        for req in requests:
            if req == "characters_full" and s.characters and s.characters.characters:
                lines = ["## 完整角色卡"]
                for c in s.characters.characters:
                    lines.append(f"\n### {c.name} ({c.role})")
                    lines.append(f"身份: {c.identity}")
                    lines.append(f"性格: {c.personality}")
                    lines.append(f"目标: {c.goal}")
                    lines.append(f"冲突: {c.conflict}")
                    if c.background:
                        lines.append(f"背景: {c.background[:200]}")
                    if c.arc:
                        lines.append(f"弧线: {c.arc.start_state} → {c.arc.end_state}")
                    if c.relationships:
                        rels = [f"{r.target_name}({r.relation_type})" for r in c.relationships[:5]]
                        lines.append(f"关系: {', '.join(rels)}")
                parts.append("\n".join(lines))

            elif req == "world_full" and s.world:
                w = s.world
                lines = ["## 完整世界观"]
                lines.append(f"\n### 力量体系: {w.power_system.system_name}")
                lines.append(f"等级: {', '.join(w.power_system.tiers) if w.power_system.tiers else '无'}")
                lines.append(f"修炼规则: {w.power_system.cultivation_rules}")
                lines.append(f"力量上限: {w.power_system.power_limit}")
                if w.power_system.special_abilities:
                    lines.append(f"特殊能力: {', '.join(w.power_system.special_abilities)}")
                if w.geography:
                    lines.append(f"\n### 地理")
                    for loc in w.geography.major_locations[:10]:
                        lines.append(f"- {loc.get('name', '?')}: {loc.get('description', '')}")
                if w.society and w.society.factions:
                    lines.append(f"\n### 社会/势力")
                    for fac in w.society.factions[:10]:
                        lines.append(f"- {fac.get('name', '?')}: {fac.get('description', '')}")
                if w.history and w.history.key_events:
                    lines.append(f"\n### 历史事件")
                    for ev in w.history.key_events[:10]:
                        lines.append(f"- {ev}")
                parts.append("\n".join(lines))

            elif req == "outline_full" and s.chapter_outline:
                co = s.chapter_outline
                lines = [f"## 完整章纲 (共{co.total_chapters}章)"]
                for ch in co.chapters:
                    lines.append(f"\n### 第{ch.chapter_number}章: {ch.chapter_title}")
                    lines.append(f"核心事件: {ch.core_event}")
                    lines.append(f"人物状态: {ch.character_states}")
                    lines.append(f"故事推进: {ch.story_progression}")
                    if ch.hook_at_end:
                        lines.append(f"结尾钩子: {ch.hook_at_end}")
                    if ch.scenes:
                        lines.append("场景:")
                        for sc in ch.scenes[:5]:
                            lines.append(f"  - {sc.scene_id}: {sc.location} | {sc.purpose}")
                if co.global_foreshadows:
                    lines.append(f"\n### 伏笔追踪")
                    for fs in co.global_foreshadows[:10]:
                        lines.append(f"- [{fs.status}] Ch{fs.planted_at}→{fs.payoff_chapter}: {fs.content[:80]}")
                parts.append("\n".join(lines))

            elif req == "drafts_full" and s.drafts.chapters:
                lines = ["## 已写章节全文"]
                for ch_num in sorted(s.drafts.chapters.keys()):
                    cd = s.drafts.chapters[ch_num]
                    text = ""
                    if cd.final:
                        text = cd.final.content
                    elif cd.draft:
                        text = cd.draft.content
                    if text:
                        lines.append(f"\n### 第{ch_num}章 ({cd.word_count}字)")
                        lines.append(text[:3000])

        return "\n\n".join(parts) if parts else ""

    # =========================================================================
    # 会话历史
    # =========================================================================

    def log_decision(self, decision):
        self.history.append({
            "step": len(self.history) + 1,
            "action": decision.action,
            "agent": decision.agent,
            "reason": decision.reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        if len(self.history) > self._history_max:
            self.history = self.history[-self._history_max:]
        self._append_orchestrator_log("decision", decision)

    def log_agent_result(self, result):
        self.history.append({
            "step": len(self.history) + 1,
            "action": "agent_done",
            "agent": result.agent,
            "requires_confirmation": result.requires_confirmation,
            "summary": result.summary,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        if len(self.history) > self._history_max:
            self.history = self.history[-self._history_max:]
        self._append_orchestrator_log("agent_result", result)

    def add_feedback(self, agent: str, feedback: str):
        self.feedbacks.append({
            "step": len(self.history),
            "agent": agent,
            "feedback": feedback,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def _save_session_data(self):
        """持久化会话数据（历史 + 反馈）"""
        if not self._project_dir:
            return
        try:
            data = {
                "feedbacks": self.feedbacks,
                "history": self.history[-self._history_max:],
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            path = Path(self._project_dir) / "session_data.json"
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.debug("session_data 保存失败: %s", e)

    def _load_session_data(self):
        """从磁盘恢复会话数据"""
        if not self._project_dir:
            return
        path = Path(self._project_dir) / "session_data.json"
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if "feedbacks" in data and data["feedbacks"]:
                self.feedbacks = data["feedbacks"]
                # 清理旧版纯数字 feedback（选题索引误存入的残留数据）
                self.feedbacks = [fb for fb in self.feedbacks
                    if not (isinstance(fb.get("feedback"), str) and fb["feedback"].strip().isdigit() and len(fb["feedback"].strip()) < 3)]
            if "history" in data and data["history"]:
                existing = {h.get("step"): h for h in self.history}
                for h in data["history"]:
                    existing[h.get("step")] = h
                self.history = list(existing.values())[-self._history_max:]
        except Exception as e:
            logger.debug("session_data 加载失败: %s", e)

    # =========================================================================
    # L3 调试日志
    # =========================================================================

    def _append_orchestrator_log(self, event_type: str, obj):
        if not self._project_dir:
            return
        log_path = Path(self._project_dir) / "orchestrator_log.jsonl"
        try:
            serializable = obj.__dict__ if hasattr(obj, '__dict__') else str(obj)
            record = {
                "type": event_type,
                "data": serializable,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except Exception as e:
            logger.debug("orchestrator_log 写入失败: %s", e)

    def _load_session_log(self):
        if not self._project_dir:
            return
        log_path = Path(self._project_dir) / "orchestrator_log.jsonl"
        if not log_path.exists():
            return
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        self.history.append(record.get("data", record))
                    except json.JSONDecodeError:
                        pass
            self.history = self.history[-self._history_max:]
        except Exception as e:
            logger.debug("会话日志加载失败: %s", e)

    def get_orchestrator_log_path(self) -> Optional[Path]:
        if self._project_dir:
            return Path(self._project_dir) / "orchestrator_log.jsonl"
        return None

    def read_orchestrator_log(self) -> list[dict]:
        if not self._project_dir:
            return []
        log_path = Path(self._project_dir) / "orchestrator_log.jsonl"
        records = []
        if not log_path.exists():
            return records
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            records.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
        except Exception:
            pass
        return records

    # =========================================================================
    # 持久化
    # =========================================================================

    def save(self, pm: Optional[PersistenceManager] = None):
        if pm is None:
            pm = PersistenceManager()
        self._state.metadata.updated_at = datetime.now(timezone.utc).isoformat()
        pm.save_project(self._state)
        self._save_context_cache()
        self._save_prompt_overrides()
        self._save_schema_version()
        self._save_session_data()

    def to_dict(self) -> dict:
        s = self._state
        return {
            "id": s.metadata.project_id,
            "name": s.metadata.name,
            "platform": s.metadata.platform,
            "created_at": s.metadata.created_at,
            "updated_at": s.metadata.updated_at,
            "schema_version": self.schema_version,
            "dashboard": self.get_dashboard().__dict__,
            "context_cache": self.context_cache,
            "volume_count": len(s.volumes),
            "current_volume": s.current_volume_index + 1,
            "genre_pack": self.genre_pack_name,
            "prompt_overrides_count": len(self.prompt_overrides),
        }

    # =========================================================================
    # 工厂方法
    # =========================================================================

    @classmethod
    def create(cls, name: str, platform: str = "", seed_idea: str = "",
               projects_dir: str = "projects") -> "Workspace":
        pm = PersistenceManager(projects_dir)
        ws_state = pm.create_project(name, platform)
        workspace = cls(ws_state, str(Path(projects_dir) / ws_state.metadata.project_id),
                        schema_version=CURRENT_SCHEMA_VERSION)
        if seed_idea:
            workspace.set_seed_idea(seed_idea)
        # v0.4.0: 新项目初始化默认卷和平台策略
        if not ws_state.volumes:
            ws_state.volumes = [VolumeState(index=1, status="planning")]
            ws_state.current_volume_index = 0
        if ws_state.platform_profile is None:
            ws_state.platform_profile = get_platform_profile(platform or "起点")
        workspace._save_schema_version()
        return workspace

    @classmethod
    def load(cls, project_id: str, projects_dir: str = "projects",
             auto_migrate: bool = True) -> Optional["Workspace"]:
        pm = PersistenceManager(projects_dir)
        ws_state = pm.load_project(project_id)
        if ws_state is None:
            return None

        project_dir = str(Path(projects_dir) / project_id)
        workspace = cls(ws_state, project_dir)  # 自动检测 schema_version

        # 自动迁移
        if auto_migrate and workspace.needs_migration():
            changes = workspace.migrate()
            logger.info("项目 %s 迁移完成: %s", project_id, changes)

        return workspace


def init_workspace(name: str, platform: str = "", seed_idea: str = "",
                   projects_dir: str = "projects") -> Workspace:
    return Workspace.create(name, platform, seed_idea, projects_dir)


def load_workspace(project_id: str, projects_dir: str = "projects",
                   auto_migrate: bool = True) -> Optional[Workspace]:
    return Workspace.load(project_id, projects_dir, auto_migrate)
