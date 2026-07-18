"""
Reference Library — Phase 6 参考资料模块

ReferenceMaterial dataclass + ReferenceManager with:
- CRUD for reference materials
- search(query) → filter by title/tags/content
- inject_relevant(tags, max_tokens=500) → find and format relevant refs for agent context
"""

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger("writesync")


# ─────────────────────────────────────────────────────────────
# Data Models
# ─────────────────────────────────────────────────────────────

@dataclass
class ReferenceMaterial:
    """参考资料条目"""

    id: str = ""                          # auto-generated hash key
    project_id: str = ""
    title: str = ""                       # 资料标题
    content: str = ""                     # 资料内容
    ref_type: str = "note"               # "setting" | "character" | "plot" | "research" | "note"
    tags: list[str] = field(default_factory=list)   # 标签列表
    source_url: str = ""                  # 资料来源 URL（可选）
    created_at: str = ""                  # ISO timestamp

    def __post_init__(self):
        if not self.id:
            raw = f"{self.project_id}:{self.title}:{time.time()}"
            self.id = hashlib.md5(raw.encode()).hexdigest()[:12]
        if not self.created_at:
            self.created_at = time.strftime("%Y-%m-%dT%H:%M:%S")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "title": self.title,
            "content": self.content,
            "ref_type": self.ref_type,
            "tags": self.tags,
            "source_url": self.source_url,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ReferenceMaterial":
        return cls(
            id=d.get("id", ""),
            project_id=d.get("project_id", ""),
            title=d.get("title", ""),
            content=d.get("content", ""),
            ref_type=d.get("ref_type", "note"),
            tags=d.get("tags", []),
            source_url=d.get("source_url", ""),
            created_at=d.get("created_at", ""),
        )


# ─────────────────────────────────────────────────────────────
# Storage Helpers
# ─────────────────────────────────────────────────────────────

def _get_refs_path(project_id: str) -> Path:
    base = Path("projects") / project_id
    base.mkdir(parents=True, exist_ok=True)
    return base / "references.json"


def _load_refs(project_id: str) -> list[ReferenceMaterial]:
    fpath = _get_refs_path(project_id)
    if not fpath.exists():
        return []
    try:
        with open(fpath, "r", encoding="utf-8") as f:
            data = json.loads(f.read())
        return [ReferenceMaterial.from_dict(d) for d in data]
    except Exception as e:
        logger.warning("Failed to load references for %s: %s", project_id, e)
        return []


def _save_refs(project_id: str, refs: list[ReferenceMaterial]):
    fpath = _get_refs_path(project_id)
    try:
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump([r.to_dict() for r in refs], f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("Failed to save references for %s: %s", project_id, e)


# ─────────────────────────────────────────────────────────────
# Manager
# ─────────────────────────────────────────────────────────────

class ReferenceManager:
    """管理项目参考资料库。"""

    def __init__(self, project_id: str):
        self.project_id = project_id
        self._refs: list[ReferenceMaterial] = _load_refs(project_id)

    def _save(self):
        _save_refs(self.project_id, self._refs)

    # ── CRUD ──

    def create(self, ref: ReferenceMaterial) -> ReferenceMaterial:
        ref.project_id = self.project_id
        if not ref.id or ref.id in {r.id for r in self._refs}:
            raw = f"{self.project_id}:{ref.title}:{time.time()}"
            ref.id = hashlib.md5(raw.encode()).hexdigest()[:12]
        if not ref.created_at:
            ref.created_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        self._refs.append(ref)
        self._save()
        logger.info("Reference created: %s type=%s tags=%s", ref.id, ref.ref_type, ref.tags)
        return ref

    def update(self, ref_id: str, **kwargs) -> bool:
        for r in self._refs:
            if r.id == ref_id:
                for key, val in kwargs.items():
                    if hasattr(r, key):
                        setattr(r, key, val)
                self._save()
                return True
        return False

    def delete(self, ref_id: str) -> bool:
        before = len(self._refs)
        self._refs = [r for r in self._refs if r.id != ref_id]
        if len(self._refs) < before:
            self._save()
            return True
        return False

    def get_all(self) -> list[ReferenceMaterial]:
        return list(self._refs)

    def get_by_type(self, ref_type: str) -> list[ReferenceMaterial]:
        return [r for r in self._refs if r.ref_type == ref_type]

    # ── Search ──

    def search(self, query: str) -> list[ReferenceMaterial]:
        """Search references by title, tags, and content."""
        if not query:
            return self.get_all()
        q = query.lower()
        results = []
        for r in self._refs:
            if q in r.title.lower():
                results.append(r)
            elif any(q in tag.lower() for tag in r.tags):
                results.append(r)
            elif q in r.content.lower():
                results.append(r)
        return results

    # ── Inject into context ──

    def inject_relevant(self, tags: list[str], max_tokens: int = 500) -> str:
        """Find references matching any of the given tags and format for agent context.
        Returns a formatted string suitable for injecting into LLM prompts.
        """
        if not tags or not self._refs:
            return ""

        matched = []
        for r in self._refs:
            if any(tag.lower() in (r_tag.lower() for r_tag in r.tags) for tag in tags):
                matched.append(r)

        if not matched:
            return ""

        # Format with token budget (rough estimate: 1 char ≈ 0.5 tokens for Chinese)
        char_budget = max_tokens * 2
        lines = ["【参考资料】"]
        used = 0

        for r in matched:
            entry = f"- [{r.ref_type}] {r.title}"
            if r.content:
                snippet = r.content[:200]
                entry += f": {snippet}"
            entry_chars = len(entry)
            if used + entry_chars > char_budget:
                break
            lines.append(entry)
            used += entry_chars

        if len(lines) == 1:
            return ""
        return '\n'.join(lines)
