"""
StateTable — Phase 4A 角色状态快照追踪

逐章记录角色的位置、状态、健康、关系和持有物品变化，
提供角色时间线查询和 LLM 驱动状态提取。

Architecture:
  StateTable stores character states via workspace.context_cache
  and persists to state_table.json in the project directory.
"""

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field

logger = logging.getLogger("writesync")


# ─────────────────────────────────────────────────────────────
# Data Models
# ─────────────────────────────────────────────────────────────

@dataclass
class CharacterState:
    """Per-character state snapshot at a specific chapter."""

    character_id: str = ""               # auto-generated
    character_name: str = ""             # matching Character.name
    project_id: str = ""
    current_location: str = ""            # 当前位置
    current_status: str = ""              # 当前状态（战斗中/静养/旅途...）
    health_state: str = ""                # 健康状态（完好/轻伤/重伤/濒死...）
    relationship_status: dict = field(default_factory=dict)  # {char_name: relation_desc}
    held_items: list[str] = field(default_factory=list)      # 持有的物品
    last_updated_chapter: int = 0         # 最后更新章节
    last_updated_at: str = ""             # ISO timestamp

    def __post_init__(self):
        if not self.character_id:
            import hashlib
            raw = f"{self.project_id}:{self.character_name}"
            self.character_id = hashlib.md5(raw.encode()).hexdigest()[:12]
        if not self.last_updated_at:
            self.last_updated_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            "character_id": self.character_id,
            "character_name": self.character_name,
            "project_id": self.project_id,
            "current_location": self.current_location,
            "current_status": self.current_status,
            "health_state": self.health_state,
            "relationship_status": self.relationship_status,
            "held_items": self.held_items,
            "last_updated_chapter": self.last_updated_chapter,
            "last_updated_at": self.last_updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CharacterState":
        return cls(
            character_id=d.get("character_id", ""),
            character_name=d.get("character_name", ""),
            project_id=d.get("project_id", ""),
            current_location=d.get("current_location", ""),
            current_status=d.get("current_status", ""),
            health_state=d.get("health_state", ""),
            relationship_status=d.get("relationship_status", {}),
            held_items=d.get("held_items", []),
            last_updated_chapter=d.get("last_updated_chapter", 0),
            last_updated_at=d.get("last_updated_at", ""),
        )


# ─────────────────────────────────────────────────────────────
# Pydantic response models for LLM structured output
# ─────────────────────────────────────────────────────────────

class CharStateChange(BaseModel):
    character_name: str = Field(description="角色名称")
    current_location: str = Field(default="", description="当前位置")
    current_status: str = Field(default="", description="当前状态")
    health_state: str = Field(default="", description="健康状态")
    relationship_changes: dict = Field(default_factory=dict, description="关系变化 {name: desc}")
    held_items: list[str] = Field(default_factory=list, description="持有物品")


class CharStateList(BaseModel):
    changes: list[CharStateChange] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────
# StateTable
# ─────────────────────────────────────────────────────────────

class StateTable:
    """
    Character state tracker with per-chapter snapshots and timeline queries.
    """

    def __init__(self, workspace):
        self._workspace = workspace
        self._state = workspace.raw_state
        self._states: list[CharacterState] = []
        self._timeline: list[CharacterState] = []  # all snapshots
        self._load_from_cache()

    # ── Lifecycle ─────────────────────────────────────────────

    def _load_from_cache(self):
        """Load states from context_cache."""
        cached = self._workspace.context_cache.get("state_table")
        if cached:
            try:
                loaded = json.loads(cached) if isinstance(cached, str) else cached
                self._states = [CharacterState.from_dict(s) for s in loaded]
            except Exception:
                pass
        tl = self._workspace.context_cache.get("state_timeline")
        if tl:
            try:
                loaded = json.loads(tl) if isinstance(tl, str) else tl
                self._timeline = [CharacterState.from_dict(s) for s in loaded]
            except Exception:
                pass

    def _persist_to_cache(self):
        """Write states to context_cache."""
        self._workspace.context_cache["state_table"] = json.dumps(
            [s.to_dict() for s in self._states], ensure_ascii=False
        )
        self._workspace.context_cache["state_timeline"] = json.dumps(
            [s.to_dict() for s in self._timeline], ensure_ascii=False
        )

    def _persist_to_disk(self):
        """Write to state_table.json in project dir."""
        if not hasattr(self._workspace, "_project_dir") or not self._workspace._project_dir:
            return
        from pathlib import Path
        try:
            path = Path(self._workspace._project_dir) / "state_table.json"
            data = {
                "states": [s.to_dict() for s in self._states],
                "timeline": [s.to_dict() for s in self._timeline],
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.debug("state_table disk persist failed: %s", e)

    def save(self):
        """Persist to cache and disk."""
        self._persist_to_cache()
        self._persist_to_disk()

    # ── CRUD ─────────────────────────────────────────────────

    def get_state(self, character_id: str) -> Optional[CharacterState]:
        """Get current state for a character."""
        for s in self._states:
            if s.character_id == character_id:
                return s
        return None

    def get_state_by_name(self, name: str) -> Optional[CharacterState]:
        """Get current state by character name."""
        for s in self._states:
            if s.character_name == name:
                return s
        return None

    def upsert_state(self, cs: CharacterState):
        """Insert or update a character state."""
        for i, s in enumerate(self._states):
            if s.character_id == cs.character_id:
                # Archive old state to timeline
                old = CharacterState(
                    character_id=s.character_id,
                    character_name=s.character_name,
                    project_id=s.project_id,
                    current_location=s.current_location,
                    current_status=s.current_status,
                    health_state=s.health_state,
                    relationship_status=dict(s.relationship_status),
                    held_items=list(s.held_items),
                    last_updated_chapter=s.last_updated_chapter,
                    last_updated_at=s.last_updated_at,
                )
                self._timeline.append(old)
                # Update
                self._states[i] = cs
                self.save()
                return
        # New character
        self._states.append(cs)
        self.save()

    def delete_state(self, character_id: str) -> bool:
        """Remove a character state."""
        for i, s in enumerate(self._states):
            if s.character_id == character_id:
                self._states.pop(i)
                self.save()
                return True
        return False

    def list_states(self, project_id: str = "") -> list[CharacterState]:
        """List all current character states."""
        if project_id:
            return [s for s in self._states if s.project_id == project_id]
        return list(self._states)

    def get_character_timeline(self, character_id: str) -> list[CharacterState]:
        """Get all state snapshots for a character (current + historical)."""
        timeline = [s for s in self._timeline if s.character_id == character_id]
        current = self.get_state(character_id)
        if current:
            timeline.append(current)
        timeline.sort(key=lambda x: x.last_updated_chapter)
        return timeline

    # ── LLM Extraction ───────────────────────────────────────

    def extract_from_chapter(self, chapter_content: str, chapter_num: int,
                             project_id: str = "", llm=None) -> list[CharacterState]:
        """
        LLM-based character state extraction.
        Uses complete_structured (MD_JSON) with 60s timeout.
        On failure, falls back to regex scanning.

        Returns list of CharacterState objects (not yet persisted).
        """
        if not chapter_content:
            return []

        t0 = time.time()

        try:
            new_states = self._llm_extract(chapter_content, chapter_num, project_id, llm)
            elapsed = (time.time() - t0) * 1000
            logger.info(
                "[state_table.extract] ch=%d states=%d method=llm elapsed=%.0fms",
                chapter_num, len(new_states), elapsed,
            )
            return new_states
        except Exception as e:
            elapsed = (time.time() - t0) * 1000
            logger.warning(
                "[state_table.extract] ch=%d llm_failed=%s elapsed=%.0fms, using regex",
                chapter_num, e, elapsed,
            )
            return self._regex_extract(chapter_content, chapter_num, project_id)

    def _llm_extract(self, chapter_content: str, chapter_num: int,
                     project_id: str, llm=None) -> list[CharacterState]:
        """LLM structured output for state extraction."""
        from ..utils.llm import create_llm_client
        if llm is None:
            llm = create_llm_client()

        snippet = chapter_content[:4000]

        # Get known character names for reference
        char_names = ""
        ws_state = self._state
        if ws_state.characters and ws_state.characters.characters:
            names = [c.name for c in ws_state.characters.characters]
            char_names = "已知角色: " + ", ".join(names) + "\n"

        prompt = (
            "从以下章节正文中提取角色状态变化。只输出状态**发生了变化**的角色。\n\n"
            f"## 第{chapter_num}章正文（前4000字）\n\n{snippet}\n\n"
            f"{char_names}"
            "## 规则\n"
            "1. 只提取本章中有变化的角色（位置/状态/健康/关系/物品变化）\n"
            "2. current_location: 角色结尾所在的地点\n"
            "3. current_status: 战斗中/静养/旅途/修炼/被囚/逃窜/潜伏...\n"
            "4. health_state: 完好/轻伤/重伤/濒死/昏迷/中毒...\n"
            "5. relationship_changes: {角色名: 关系变化简述}\n"
            "6. held_items: 角色获得/持有的关键物品列表\n"
            "7. 若没有角色发生状态变化，返回空列表"
        )

        try:
            result = llm.complete_structured(
                prompt, output_class=CharStateList,
                temperature=0.3, max_tokens=2048, timeout=60, max_retries=0,
            )
            states = []
            for item in result.changes:
                states.append(CharacterState(
                    character_name=item.character_name,
                    project_id=project_id,
                    current_location=item.current_location,
                    current_status=item.current_status,
                    health_state=item.health_state,
                    relationship_status=item.relationship_changes,
                    held_items=item.held_items,
                    last_updated_chapter=chapter_num,
                ))
            return states
        except Exception:
            raise

    def _regex_extract(self, chapter_content: str, chapter_num: int,
                       project_id: str) -> list[CharacterState]:
        """
        Regex fallback: scan for character names + status keywords.
        """
        states = []
        # Pattern: character name + location/status keywords
        loc_pattern = re.compile(
            r'([\u4e00-\u9fff]{2,4})(?:来到|抵达|进入|离开|在|回到|返回)([\u4e00-\u9fff]{2,10}(?:城|国|宗|门|派|山|谷|林|海|界|域|殿|阁|楼|塔|洞|府|院|市|镇|村|中|内|外|里|上|下))'
        )
        health_pattern = re.compile(
            r'([\u4e00-\u9fff]{2,4})(?:受伤|重伤|轻伤|中毒|昏迷|晕倒|恢复|痊愈|治愈)'
        )
        status_pattern = re.compile(
            r'([\u4e00-\u9fff]{2,4})(?:在修炼|在战斗|闭关|逃窜|潜伏|被囚|疗伤|静养|赶路|布阵)'
        )

        seen_names = set()

        # Extract location changes
        for m in loc_pattern.finditer(chapter_content):
            name = m.group(1)
            loc = m.group(2)
            if name not in seen_names:
                seen_names.add(name)
                states.append(CharacterState(
                    character_name=name,
                    project_id=project_id,
                    current_location=loc,
                    last_updated_chapter=chapter_num,
                ))

        # Extract health changes
        for m in health_pattern.finditer(chapter_content):
            name = m.group(1)
            health_kw = m.group(2)
            if name in seen_names:
                for s in states:
                    if s.character_name == name and not s.health_state:
                        s.health_state = health_kw
                        break

        # Extract status changes
        for m in status_pattern.finditer(chapter_content):
            name = m.group(1)
            status_kw = m.group(2)
            if name in seen_names:
                for s in states:
                    if s.character_name == name and not s.current_status:
                        s.current_status = status_kw
                        break

        logger.info(
            "[state_table.regex] ch=%d states=%d",
            chapter_num, len(states),
        )
        return states

    def apply_extraction(self, states: list[CharacterState], chapter_num: int):
        """Merge extracted states into the table."""
        updated = 0
        for cs in states:
            if not cs.character_name:
                continue
            existing = self.get_state_by_name(cs.character_name)
            if existing:
                # Merge: only overwrite non-empty fields
                changed = False
                for field in ("current_location", "current_status", "health_state"):
                    new_val = getattr(cs, field, "")
                    if new_val and getattr(existing, field) != new_val:
                        setattr(existing, field, new_val)
                        changed = True
                if cs.relationship_status:
                    existing.relationship_status.update(cs.relationship_status)
                    changed = True
                if cs.held_items:
                    for item in cs.held_items:
                        if item not in existing.held_items:
                            existing.held_items.append(item)
                            changed = True
                if changed:
                    existing.last_updated_chapter = chapter_num
                    existing.last_updated_at = datetime.now(timezone.utc).isoformat()
                    updated += 1
            else:
                self.upsert_state(cs)
                updated += 1

        if updated:
            self.save()
            logger.info(
                "[state_table.apply] ch=%d updated=%d total=%d",
                chapter_num, updated, len(self._states),
            )

    # ── Context Injection ────────────────────────────────────

    def inject_into_writer_prompt(self, project_id: str = "",
                                   max_tokens: int = 500) -> str:
        """Format current character states for writer prompt."""
        states = self.list_states(project_id)
        if not states:
            return ""

        max_chars = max_tokens * 2
        lines = []
        used = 0

        for s in states:
            parts = [s.character_name]
            if s.current_location:
                parts.append(f"📍{s.current_location}")
            if s.current_status:
                parts.append(f"📌{s.current_status}")
            if s.health_state:
                parts.append(f"❤️{s.health_state}")
            if s.held_items:
                parts.append(f"🎒{','.join(s.held_items[:3])}")

            line = " | ".join(parts)
            if used + len(line) > max_chars:
                break
            lines.append(line)
            used += len(line)

        if not lines:
            return ""

        header = "## B1 角色状态快照（State Table）\n"
        return header + "\n".join(f"- {l}" for l in lines) + "\n"


# ─────────────────────────────────────────────────────────────
# Async helper
# ─────────────────────────────────────────────────────────────

async def extract_states_async(table: StateTable, content: str,
                                chapter_num: int, project_id: str = ""):
    """Fire-and-forget async wrapper for state extraction."""
    try:
        loop = asyncio.get_running_loop()
        new_states = await loop.run_in_executor(
            None, table.extract_from_chapter, content, chapter_num, project_id
        )
        table.apply_extraction(new_states, chapter_num)
        logger.info(
            "[state_table.async] ch=%d extracted=%d (total=%d)",
            chapter_num, len(new_states), len(table.list_states()),
        )
    except Exception as e:
        logger.warning("[state_table.async] ch=%d failed: %s", chapter_num, e)
