"""
GlobalForeshadow — Phase 4A 全书级别伏笔追踪

不同于 chapter-level Foreshadow (state_types.py:247)，GlobalForeshadow 是
跨章节的书级伏笔管理系统，追踪每个伏笔从埋设到回收的完整生命周期。

Features:
  - CRUD for global foreshadows
  - LLM-based extraction from chapter content (60s timeout → keyword fallback)
  - Writer prompt injection for active foreshadows
  - Kanban view support (4 columns: planned/planted/called_back/resolved)
  - Sync with chapter-level Foreshadow in ChapterOutline
"""

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Optional

from pydantic import BaseModel, Field

logger = logging.getLogger("writesync")


# ─────────────────────────────────────────────────────────────
# Data Models
# ─────────────────────────────────────────────────────────────

@dataclass
class GlobalForeshadow:
    """Book-level foreshadow tracking across chapters."""

    id: str = ""                        # auto-generated hash key
    project_id: str = ""                # FK to project
    title: str = ""                     # 伏笔标题（≤20字）
    description: str = ""                # 伏笔描述（≤100字）
    type: str = "plot"                  # "plot" | "character" | "item" | "mystery"
    status: str = "planned"            # "planned" | "planted" | "called_back" | "resolved"
    planted_chapter: int = 0            # 埋设章节
    callback_chapters: list[int] = field(default_factory=list)  # 呼应章节
    resolved_chapter: int = 0           # 回收章节
    urgency: int = 3                    # 紧迫度 1-5
    expected_callback_range: str = ""    # "10-15" 预期回收章节范围
    deadline_chapter: int = 0           # 截止章节

    def __post_init__(self):
        if not self.id:
            import hashlib
            raw = f"{self.project_id}:{self.title}:{self.planted_chapter}"
            self.id = hashlib.md5(raw.encode()).hexdigest()[:12]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "title": self.title,
            "description": self.description,
            "type": self.type,
            "status": self.status,
            "planted_chapter": self.planted_chapter,
            "callback_chapters": self.callback_chapters,
            "resolved_chapter": self.resolved_chapter,
            "urgency": self.urgency,
            "expected_callback_range": self.expected_callback_range,
            "deadline_chapter": self.deadline_chapter,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "GlobalForeshadow":
        return cls(
            id=d.get("id", ""),
            project_id=d.get("project_id", ""),
            title=d.get("title", ""),
            description=d.get("description", ""),
            type=d.get("type", "plot"),
            status=d.get("status", "planned"),
            planted_chapter=d.get("planted_chapter", 0),
            callback_chapters=d.get("callback_chapters", []),
            resolved_chapter=d.get("resolved_chapter", 0),
            urgency=d.get("urgency", 3),
            expected_callback_range=d.get("expected_callback_range", ""),
            deadline_chapter=d.get("deadline_chapter", 0),
        )


# ─────────────────────────────────────────────────────────────
# Pydantic response models for LLM structured output
# ─────────────────────────────────────────────────────────────

class ForeshadowItem(BaseModel):
    title: str = Field(description="伏笔标题（≤20字）")
    description: str = Field(description="伏笔描述（≤100字）")
    type: str = Field(description="类型: plot/character/item/mystery")
    status: str = Field(description="状态: planned/planted/called_back/resolved")
    planted_chapter: int = Field(description="埋设章节编号")
    callback_chapters: list[int] = Field(default_factory=list, description="呼应章节列表")
    resolved_chapter: int = Field(default=0, description="回收章节编号")
    urgency: int = Field(default=3, description="紧迫度 1-5")
    expected_callback_range: str = Field(default="", description="预期回收章节范围")
    deadline_chapter: int = Field(default=0, description="截止章节")


class ForeshadowList(BaseModel):
    foreshadows: list[ForeshadowItem] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────
# ForeshadowManager
# ─────────────────────────────────────────────────────────────

class ForeshadowManager:
    """
    Book-level foreshadow tracker with LLM extraction and prompt injection.

    Stores foreshadows in workspace.context_cache and persists to
    foreshadows.json in the project directory.
    """

    def __init__(self, workspace):
        self._workspace = workspace
        self._state = workspace.raw_state
        self._foreshadows: list[GlobalForeshadow] = []
        self._load_from_cache()

    # ── Lifecycle ─────────────────────────────────────────────

    def _load_from_cache(self):
        """Load foreshadows from context_cache."""
        cached = self._workspace.context_cache.get("global_foreshadows")
        if cached:
            try:
                loaded = json.loads(cached) if isinstance(cached, str) else cached
                self._foreshadows = [GlobalForeshadow.from_dict(f) for f in loaded]
            except Exception:
                pass

    def _persist_to_cache(self):
        """Write foreshadows to context_cache."""
        fs_dicts = [f.to_dict() for f in self._foreshadows]
        self._workspace.context_cache["global_foreshadows"] = json.dumps(
            fs_dicts, ensure_ascii=False
        )

    def _persist_to_disk(self):
        """Write foreshadows to foreshadows.json in project dir."""
        if not hasattr(self._workspace, "_project_dir") or not self._workspace._project_dir:
            return
        from pathlib import Path
        try:
            path = Path(self._workspace._project_dir) / "foreshadows.json"
            data = {
                "foreshadows": [f.to_dict() for f in self._foreshadows],
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.debug("foreshadows disk persist failed: %s", e)

    def save(self):
        """Persist to cache and disk."""
        self._persist_to_cache()
        self._persist_to_disk()

    # ── CRUD ─────────────────────────────────────────────────

    def create(self, fs: GlobalForeshadow):
        """Add a new foreshadow (dedup by ID)."""
        if not any(f.id == fs.id for f in self._foreshadows):
            self._foreshadows.append(fs)
            self.save()
            logger.debug("[foreshadow] created: %s", fs.title)

    def update(self, fs_id: str, **kwargs) -> bool:
        """Update foreshadow fields by ID. Returns True if found."""
        for f in self._foreshadows:
            if f.id == fs_id:
                for key, val in kwargs.items():
                    if hasattr(f, key):
                        setattr(f, key, val)
                self.save()
                logger.debug("[foreshadow] updated: %s fields=%s", fs_id, list(kwargs.keys()))
                return True
        return False

    def delete(self, fs_id: str) -> bool:
        """Delete a foreshadow by ID."""
        for i, f in enumerate(self._foreshadows):
            if f.id == fs_id:
                self._foreshadows.pop(i)
                self.save()
                logger.debug("[foreshadow] deleted: %s", fs_id)
                return True
        return False

    def get(self, fs_id: str) -> Optional[GlobalForeshadow]:
        """Get a single foreshadow by ID."""
        for f in self._foreshadows:
            if f.id == fs_id:
                return f
        return None

    def list_by_project(self, project_id: str = "") -> list[GlobalForeshadow]:
        """Return all foreshadows, optionally filtered by project."""
        if project_id:
            return [f for f in self._foreshadows if f.project_id == project_id]
        return list(self._foreshadows)

    def get_all(self) -> list[GlobalForeshadow]:
        """Return all globally tracked foreshadows."""
        return list(self._foreshadows)

    # ── LLM Extraction ───────────────────────────────────────

    def extract_from_chapter(self, chapter_content: str, chapter_num: int,
                             project_id: str = "", llm=None) -> list[GlobalForeshadow]:
        """
        LLM-based foreshadow extraction from chapter content.
        Uses complete_structured (MD_JSON) with 60s timeout.
        On failure, falls back to keyword scanning.

        Returns list of NEW GlobalForeshadow objects (not yet persisted).
        """
        if not chapter_content:
            return []

        t0 = time.time()

        try:
            new_fs = self._llm_extract(chapter_content, chapter_num, project_id, llm)
            elapsed = (time.time() - t0) * 1000
            logger.info(
                "[foreshadow.extract] ch=%d found=%d method=llm elapsed=%.0fms",
                chapter_num, len(new_fs), elapsed,
            )
            return new_fs
        except Exception as e:
            elapsed = (time.time() - t0) * 1000
            logger.warning(
                "[foreshadow.extract] ch=%d llm_failed=%s elapsed=%.0fms, using keyword scan",
                chapter_num, e, elapsed,
            )
            return self._keyword_extract(chapter_content, chapter_num, project_id)

    def _llm_extract(self, chapter_content: str, chapter_num: int,
                     project_id: str, llm=None) -> list[GlobalForeshadow]:
        """LLM structured output for foreshadow discovery."""
        from ..utils.llm import create_llm_client
        if llm is None:
            llm = create_llm_client()

        snippet = chapter_content[:4000]

        # Include existing foreshadows for status update context
        existing_str = ""
        active = self.get_active_foreshadows(project_id, chapter_num)
        if active:
            items = [f"- [{f.status}] {f.title}: {f.description[:50]}" for f in active[:10]]
            existing_str = "## 已有伏笔（待发现状态变化）\n" + "\n".join(items) + "\n\n"

        prompt = (
            "从以下章节正文中提取伏笔（foreshadow）信息，包括：\n"
            "1. 本章**新埋设**的伏笔\n"
            "2. 已有伏笔的**状态变化**（called_back/resolved）\n\n"
            f"## 第{chapter_num}章正文（前4000字）\n\n{snippet}\n\n"
            f"{existing_str}"
            "## 规则\n"
            "1. type 必须为: plot | character | item | mystery\n"
            "2. status：新伏笔用 planted，已有伏笔的状态变更用 called_back 或 resolved\n"
            "3. planted_chapter 设为本章编号\n"
            "4. urgency: 1=可延后, 3=正常, 5=必须尽快回收\n"
            "5. expected_callback_range: 如 '10-15'\n"
            "6. 若无新伏笔也无状态变化，返回空列表"
        )

        try:
            result = llm.complete_structured(
                prompt, output_class=ForeshadowList,
                temperature=0.3, max_tokens=2048, timeout=60, max_retries=0,
            )
            foreshadows = []
            for item in result.foreshadows:
                foreshadows.append(GlobalForeshadow(
                    project_id=project_id,
                    title=item.title,
                    description=item.description,
                    type=item.type,
                    status=item.status,
                    planted_chapter=item.planted_chapter or chapter_num,
                    callback_chapters=item.callback_chapters,
                    resolved_chapter=item.resolved_chapter,
                    urgency=item.urgency,
                    expected_callback_range=item.expected_callback_range,
                    deadline_chapter=item.deadline_chapter,
                ))
            return foreshadows
        except Exception:
            raise

    def _keyword_extract(self, chapter_content: str, chapter_num: int,
                         project_id: str) -> list[GlobalForeshadow]:
        """
        Keyword fallback: scan for foreshadowing language patterns.
        Matches phrases like "日后", "后来才知道", "此时他还不知道", "这将是".
        """
        foreshadow_patterns = [
            r'(?:日后|后来|不久之后|多年后).{0,20}(?:知道|发现|明白|才|才知)',
            r'(?:此时|当时).{0,10}(?:还|尚且).{0,10}(?:不知道|不知|没意识到|没发现)',
            r'(?:这将是|这会是|这将|这会).{0,20}(?:关键|转折|契机|伏笔)',
            r'(?:隐隐|似乎|好像|仿佛).{0,20}(?:预示|暗示|意味着|表明)',
            r'(?:留下的|残留的|隐藏的).{0,10}(?:线索|痕迹|印记|标记)',
        ]

        foreshadows = []
        seen_titles = {f.title for f in self._foreshadows}

        for pat in foreshadow_patterns:
            for m in re.finditer(pat, chapter_content):
                snippet = m.group(0)
                title = snippet[:20]
                if title in seen_titles:
                    continue
                seen_titles.add(title)

                # Determine type
                if any(w in snippet for w in ("知道", "不知", "意识", "明白")):
                    ftype = "mystery"
                elif any(w in snippet for w in ("物品", "剑", "刀", "宝物", "丹药", "秘籍")):
                    ftype = "item"
                elif any(w in snippet for w in ("日", "年后", "将来")):
                    ftype = "plot"
                else:
                    ftype = "plot"

                foreshadows.append(GlobalForeshadow(
                    project_id=project_id,
                    title=title,
                    description=snippet[:100],
                    type=ftype,
                    status="planted",
                    planted_chapter=chapter_num,
                    urgency=3,
                ))

        logger.info(
            "[foreshadow.keyword] ch=%d found=%d",
            chapter_num, len(foreshadows),
        )
        return foreshadows

    def apply_extraction(self, new_foreshadows: list[GlobalForeshadow],
                         chapter_num: int):
        """
        Merge extracted foreshadows: add new ones, update existing statuses.
        Called after LLM/keyword extraction to persist results.
        """
        existing_by_title = {}
        for f in self._foreshadows:
            if f.title:
                existing_by_title[f.title] = f

        added = 0
        updated = 0

        for new_fs in new_foreshadows:
            existing = existing_by_title.get(new_fs.title)
            if existing:
                # Update existing: track callback/resolve changes
                changed = False
                if new_fs.status == "called_back" and chapter_num not in existing.callback_chapters:
                    existing.callback_chapters.append(chapter_num)
                    existing.status = "called_back"
                    changed = True
                if new_fs.status == "resolved" and existing.resolved_chapter == 0:
                    existing.resolved_chapter = chapter_num
                    existing.status = "resolved"
                    changed = True
                if changed:
                    updated += 1
            else:
                # New foreshadow
                self._foreshadows.append(new_fs)
                added += 1

        if added or updated:
            self.save()
            # Also sync with chapter-level Foreshadow
            self._sync_to_chapter_outline(chapter_num)
            logger.info(
                "[foreshadow.apply] ch=%d added=%d updated=%d total=%d",
                chapter_num, added, updated, len(self._foreshadows),
            )

    def _sync_to_chapter_outline(self, chapter_num: int):
        """Sync planted foreshadows back to ChapterOutline.foreshadows."""
        ws_state = self._state
        if not ws_state.chapter_outline:
            return
        from ..state.state_types import Foreshadow as ChForeshadow
        for ch in ws_state.chapter_outline.chapters:
            if ch.chapter_number == chapter_num:
                existing_ids = {f.content[:30] for f in ch.foreshadows}
                for gf in self._foreshadows:
                    if gf.planted_chapter == chapter_num and gf.status == "planted":
                        content = f"{gf.title}: {gf.description[:50]}"
                        if content[:30] not in existing_ids:
                            ch.foreshadows.append(ChForeshadow(
                                content=content,
                                planted_at=chapter_num,
                                status="planted",
                            ))
                            existing_ids.add(content[:30])

    # ── Writer Prompt Injection ──────────────────────────────

    def get_active_foreshadows(self, project_id: str = "",
                                up_to_chapter: int = 0) -> list[GlobalForeshadow]:
        """Return foreshadows that are active (not resolved) up to the given chapter."""
        result = []
        for f in self._foreshadows:
            if project_id and f.project_id != project_id:
                continue
            if f.status == "resolved":
                continue
            if f.planted_chapter > up_to_chapter:
                continue
            result.append(f)
        # Sort by urgency (high first), then by planted_chapter
        result.sort(key=lambda x: (-x.urgency, x.planted_chapter))
        return result

    def inject_into_writer_prompt(self, project_id: str = "",
                                   up_to_chapter: int = 0,
                                   max_tokens: int = 800) -> str:
        """
        Format active foreshadows as writer prompt injection.
        """
        active = self.get_active_foreshadows(project_id, up_to_chapter)
        if not active:
            return ""

        max_chars = max_tokens * 2
        lines = []
        used = 0

        type_labels = {
            "plot": "情节",
            "character": "角色",
            "item": "物品",
            "mystery": "悬念",
        }
        urgency_marks = {1: "○", 2: "◔", 3: "◑", 4: "◕", 5: "●"}

        for f in active:
            label = type_labels.get(f.type, f.type)
            mark = urgency_marks.get(f.urgency, "◑")
            deadline = f"｜截止Ch{f.deadline_chapter}" if f.deadline_chapter else ""
            line = (
                f"- {mark} [{label}] {f.title}: {f.description[:50]}"
                f" (Ch{f.planted_chapter}埋{deadline})"
            )
            if used + len(line) > max_chars:
                break
            lines.append(line)
            used += len(line)

        if not lines:
            return ""

        count = len(active)
        header = f"## ⚠️ 本章有 {count} 个待呼应伏笔\n"
        return header + "\n".join(lines) + "\n"

    def get_foreshadows_by_status(self, status: str) -> list[GlobalForeshadow]:
        """Get foreshadows filtered by status (for kanban view)."""
        return [f for f in self._foreshadows if f.status == status]

    def get_kanban_data(self) -> dict:
        """Return data for 4-column kanban view."""
        return {
            "planned": [f.to_dict() for f in self.get_foreshadows_by_status("planned")],
            "planted": [f.to_dict() for f in self.get_foreshadows_by_status("planted")],
            "called_back": [f.to_dict() for f in self.get_foreshadows_by_status("called_back")],
            "resolved": [f.to_dict() for f in self.get_foreshadows_by_status("resolved")],
        }


# ─────────────────────────────────────────────────────────────
# Async helper for fire-and-forget extraction
# ─────────────────────────────────────────────────────────────

async def extract_foreshadows_async(mgr: ForeshadowManager, content: str,
                                     chapter_num: int, project_id: str = ""):
    """Fire-and-forget async wrapper for foreshadow extraction."""
    try:
        loop = asyncio.get_running_loop()
        new_fs = await loop.run_in_executor(
            None, mgr.extract_from_chapter, content, chapter_num, project_id
        )
        mgr.apply_extraction(new_fs, chapter_num)
        logger.info(
            "[foreshadow.async] ch=%d extracted=%d (total=%d)",
            chapter_num, len(new_fs), len(mgr.get_all()),
        )
    except Exception as e:
        logger.warning("[foreshadow.async] ch=%d failed: %s", chapter_num, e)
