"""
Timeline — Phase 6 故事年表模块

TimelineEvent dataclass + TimelineManager with:
- CRUD for timeline events
- LLM-based auto_extract from chapter content (60s timeout → regex fallback)
- get_timeline(project_id) sorted by story_time
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger("writesync")


# ─────────────────────────────────────────────────────────────
# Data Models
# ─────────────────────────────────────────────────────────────

@dataclass
class TimelineEvent:
    """故事年表中的单个事件"""

    id: str = ""                          # auto-generated hash key
    project_id: str = ""
    description: str = ""                  # 事件描述
    chapter_num: int = 0                  # 所在章节
    story_time: str = ""                   # 故事内时间，如 "第3天" "盛夏" "三年前"
    event_type: str = "plot"              # "plot" | "character" | "world"
    created_at: str = ""                  # ISO timestamp

    def __post_init__(self):
        if not self.id:
            raw = f"{self.project_id}:{self.description}:{self.chapter_num}:{self.story_time}"
            self.id = hashlib.md5(raw.encode()).hexdigest()[:12]
        if not self.created_at:
            self.created_at = time.strftime("%Y-%m-%dT%H:%M:%S")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "description": self.description,
            "chapter_num": self.chapter_num,
            "story_time": self.story_time,
            "event_type": self.event_type,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TimelineEvent":
        return cls(
            id=d.get("id", ""),
            project_id=d.get("project_id", ""),
            description=d.get("description", ""),
            chapter_num=d.get("chapter_num", 0),
            story_time=d.get("story_time", ""),
            event_type=d.get("event_type", "plot"),
            created_at=d.get("created_at", ""),
        )


# ─────────────────────────────────────────────────────────────
# Storage Helpers
# ─────────────────────────────────────────────────────────────

def _get_timeline_path(project_id: str) -> Path:
    """Get the JSON file path for a project's timeline data."""
    from pathlib import Path as _Path
    base = _Path("projects") / project_id
    base.mkdir(parents=True, exist_ok=True)
    return base / "timeline.json"


def _load_events(project_id: str) -> list[TimelineEvent]:
    """Load timeline events from JSON file."""
    fpath = _get_timeline_path(project_id)
    if not fpath.exists():
        return []
    try:
        with open(fpath, "r", encoding="utf-8") as f:
            data = json.loads(f.read())
        return [TimelineEvent.from_dict(d) for d in data]
    except Exception as e:
        logger.warning("Failed to load timeline for %s: %s", project_id, e)
        return []


def _save_events(project_id: str, events: list[TimelineEvent]):
    """Save timeline events to JSON file."""
    fpath = _get_timeline_path(project_id)
    try:
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump([e.to_dict() for e in events], f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("Failed to save timeline for %s: %s", project_id, e)


# ─────────────────────────────────────────────────────────────
# Manager
# ─────────────────────────────────────────────────────────────

class TimelineManager:
    """管理项目的故事年表。"""

    def __init__(self, project_id: str):
        self.project_id = project_id
        self._events: list[TimelineEvent] = _load_events(project_id)

    def _save(self):
        _save_events(self.project_id, self._events)

    # ── CRUD ──

    def create(self, event: TimelineEvent) -> TimelineEvent:
        event.project_id = self.project_id
        if not event.id or event.id in {e.id for e in self._events}:
            # force new id
            raw = f"{self.project_id}:{event.description}:{event.chapter_num}:{event.story_time}:{time.time()}"
            event.id = hashlib.md5(raw.encode()).hexdigest()[:12]
        if not event.created_at:
            event.created_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        self._events.append(event)
        self._save()
        logger.info("Timeline event created: %s ch=%d type=%s", event.id, event.chapter_num, event.event_type)
        return event

    def update(self, event_id: str, **kwargs) -> bool:
        for e in self._events:
            if e.id == event_id:
                for key, val in kwargs.items():
                    if hasattr(e, key):
                        setattr(e, key, val)
                self._save()
                return True
        return False

    def delete(self, event_id: str) -> bool:
        before = len(self._events)
        self._events = [e for e in self._events if e.id != event_id]
        if len(self._events) < before:
            self._save()
            return True
        return False

    def get_all(self) -> list[TimelineEvent]:
        return list(self._events)

    def get_timeline(self) -> list[TimelineEvent]:
        """Return events sorted by story_time (natural sort)."""
        def _sort_key(ev: TimelineEvent) -> tuple:
            st = ev.story_time or ""
            # Try to extract numeric prefix for natural sorting
            m = re.match(r'第?\s*(\d+)', st)
            if m:
                return (1, int(m.group(1)), st)
            return (0, 0, st)
        return sorted(self._events, key=_sort_key)

    # ── LLM Extraction ──

    def auto_extract(self, chapter_content: str, chapter_num: int) -> list[TimelineEvent]:
        """Fire LLM to extract timeline events from chapter content.
        Falls back to regex extraction on timeout/failure.
        """
        if not chapter_content or len(chapter_content) < 50:
            return []

        snippet = chapter_content[:3000]  # limit context for LLM

        try:
            from ..utils.llm import create_llm_client
            llm = create_llm_client(model="deepseek-v4-flash")
            prompt = f"""你是一位故事编辑。从以下章节内容中提取时间线事件。
每个事件包含：description（简短描述≤30字）、story_time（故事内时间，如"第3天"、"盛夏"、"三年前"、"深夜"）、event_type（plot/character/world之一）。

章节内容：
{snippet}

请以 JSON 数组格式输出，例如：
[{{"description": "主角进入秘境", "story_time": "第三日下午", "event_type": "plot"}}]

只输出 JSON 数组，不要包含其他内容。若无时间相关事件，输出空数组 []。"""

            import json as _json
            result = llm.complete(prompt, timeout=60, max_tokens=1024)

            # Try to extract JSON from response
            events_data = _json.loads(result) if result else []
            if not isinstance(events_data, list):
                events_data = []

            new_events = []
            for item in events_data:
                if isinstance(item, dict) and item.get("description"):
                    ev = TimelineEvent(
                        project_id=self.project_id,
                        description=item.get("description", ""),
                        chapter_num=chapter_num,
                        story_time=item.get("story_time", f"第{chapter_num}章"),
                        event_type=item.get("event_type", "plot"),
                    )
                    new_events.append(ev)

            if new_events:
                self._events.extend(new_events)
                self._save()
                logger.info("Timeline auto_extract: LLM extracted %d events for ch=%d", len(new_events), chapter_num)
                return new_events

        except Exception as e:
            logger.warning("Timeline LLM extraction failed for ch=%d: %s, falling back to regex", chapter_num, e)

        # Regex fallback
        return self._regex_extract(chapter_content, chapter_num)

    def _regex_extract(self, chapter_content: str, chapter_num: int) -> list[TimelineEvent]:
        """Regex-based fallback: detect time markers in text."""
        time_patterns = [
            (r'第\s*([一二三四五六七八九十百千\d]+)\s*天', '第\\1天'),
            (r'第\s*(\d+)\s*日', '第\\1日'),
            (r'(清晨|上午|中午|下午|傍晚|黄昏|深夜|凌晨|午夜)', '\\1'),
            (r'(\d+)\s*年前', '\\1年前'),
            (r'(\d+)\s*年后', '\\1年后'),
            (r'(\d+)\s*天后', '\\1天后'),
            (r'(三个月后|半年后|一年后)', '\\1'),
            (r'(第二天|次日|翌日)', '\\1'),
            (r'(春|夏|秋|冬)(天|季)', '\\1\\2'),
            (r'(正月|二月|三月|腊月)', '\\1'),
        ]

        found_times = set()
        new_events = []
        for pattern, _ in time_patterns:
            for m in re.finditer(pattern, chapter_content):
                tm = m.group(0)
                if tm in found_times:
                    continue
                found_times.add(tm)
                # Get context (30 chars around)
                start = max(0, m.start() - 15)
                end = min(len(chapter_content), m.end() + 20)
                ctx = chapter_content[start:end].replace('\n', ' ').strip()

                ev = TimelineEvent(
                    project_id=self.project_id,
                    description=ctx[:50],
                    chapter_num=chapter_num,
                    story_time=tm,
                    event_type="plot",
                )
                new_events.append(ev)

        if new_events:
            self._events.extend(new_events)
            self._save()
            logger.info("Timeline regex_extract: found %d events for ch=%d", len(new_events), chapter_num)

        return new_events


async def extract_timeline_async(mgr: TimelineManager, content: str, chapter_num: int):
    """Fire-and-forget async wrapper for timeline extraction."""
    try:
        await asyncio.to_thread(mgr.auto_extract, content, chapter_num)
    except Exception as e:
        logger.warning("[timeline] async extraction failed ch=%d: %s", chapter_num, e)
