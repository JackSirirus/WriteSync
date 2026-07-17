"""
WriteSync 持久化层

三层持久化策略：
1. LangGraph Checkpoint — 程序级，崩溃后恢复
2. 结构化 JSON 文件 — 用户可见，版本管理
3. 草稿独立文件 — 最高保护，文字不丢失

Phase 5: JSON + SQLite 双写过渡（Migration Step 1）
- JSON 仍然是主存储（_use_sqlite_primary=False）
- 每次保存同时写入 SQLite（双写）
- 可通过 enable_sqlite_primary() 切换到 SQLite 优先
"""

import json
import logging
import uuid
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, get_origin, get_args

from .state_types import (
    WriteSyncState,
    ProjectMetadata,
    StepName,
    ProjectStatus,
    TopicState,
    StoryState,
    CharactersState,
    WorldState,
    OutlineState,
    ChapterOutlineState,
    DraftsState,
    WorkflowState,
    VersionState,
    NovelReviewState,
    DynamicContext,
    ChapterDraft,
)
from .persistence_sqlite import SQLitePersistence

logger = logging.getLogger("writesync")


class PersistenceManager:
    """
    持久化管理器

    负责：
    - State 的序列化/反序列化（JSON 文件 + SQLite 双写）
    - 项目目录管理
    - 版本快照管理
    - 草稿文件的独立存储

    Phase 5 双写模式：
    - _use_sqlite_primary=False: JSON 主，SQLite 副（Migration Step 1 默认）
    - _use_sqlite_primary=True:  SQLite 主，JSON 副（Migration Step 2）
    """

    def __init__(self, projects_dir: str = "projects", db_path: str = ""):
        self.projects_dir = Path(projects_dir)
        self.projects_dir.mkdir(exist_ok=True)

        # Phase 5: SQLite 双写
        if not db_path:
            db_path = str(self.projects_dir / "writesync.db")
        self._db_path = db_path
        self._db = SQLitePersistence(db_path)
        try:
            self._db.init_db()
        except Exception as e:
            logger.warning("SQLite init failed (non-fatal, JSON-only mode): %s", e)

        # Migration Step 1: dual-write, JSON primary
        self._use_sqlite_primary = False

    def close(self) -> None:
        """Close the SQLite connection and release file locks.

        Call this before deleting the database file or the projects directory.
        JSON persistence is unaffected by close().
        """
        try:
            self._db.close()
        except Exception as e:
            logger.debug("Error closing SQLite: %s", e)

    # =========================================================================
    # 项目管理
    # =========================================================================

    def create_project(self, name: str, platform: str) -> WriteSyncState:
        """创建新项目，初始化 State"""
        project_id = str(uuid.uuid4())[:8]
        now = datetime.now().isoformat()

        metadata = ProjectMetadata(
            project_id=project_id,
            name=name,
            platform=platform,
            created_at=now,
            updated_at=now,
            current_step=StepName.TOPIC,
            status=ProjectStatus.DRAFTING,
        )

        workflow = WorkflowState(
            current_step=StepName.TOPIC,
            completed_steps=[],
            pending_confirmation=False,
            last_saved=now,
            version=1,
        )

        state = WriteSyncState(
            metadata=metadata,
            workflow=workflow,
            drafts=DraftsState(),
            versions=VersionState(),
        )

        self.save_project(state)
        return state

    def load_project(self, project_id: str) -> WriteSyncState | None:
        """从文件加载项目。SQLite 优先模式时先尝试 SQLite，回退到 JSON。"""
        # Phase 5: SQLite primary path
        if self._use_sqlite_primary:
            try:
                data = self._db.load_project(project_id)
                if data:
                    project_dir = self.projects_dir / project_id
                    return self._deserialize_state(data, project_dir)
            except Exception as e:
                logger.warning("SQLite load failed for %s, falling back to JSON: %s",
                               project_id, e)

        # JSON path (primary or fallback)
        return self._load_json(project_id)

    def save_project(self, state: WriteSyncState) -> None:
        """保存项目到文件（JSON + SQLite 双写）"""
        project_dir = self.projects_dir / state.metadata.project_id
        project_dir.mkdir(exist_ok=True)

        state.metadata.updated_at = datetime.now().isoformat()
        state.workflow.last_saved = datetime.now().isoformat()

        self._save_state_file(project_dir, "topic", state.topic)
        self._save_state_file(project_dir, "story", state.story)
        self._save_state_file(project_dir, "outline", state.outline)
        self._save_state_file(project_dir, "characters", state.characters)
        self._save_state_file(project_dir, "world", state.world)
        self._save_state_file(project_dir, "chapter_outline", state.chapter_outline)
        self._save_state_file(project_dir, "workflow", state.workflow)
        self._save_state_file(project_dir, "versions", state.versions)
        self._save_state_file(project_dir, "novel_review", state.novel_review)

        metadata_path = project_dir / "metadata.json"
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(self._serialize(state.metadata), f, ensure_ascii=False, indent=2)

        self._save_drafts(project_dir, state.drafts)

        # Phase 5: dual-write to SQLite
        try:
            self._save_sqlite(state)
        except Exception as e:
            logger.warning("SQLite dual-write failed for %s (JSON intact): %s",
                           state.metadata.project_id, e)

    def list_projects(self) -> list[dict]:
        """列出所有项目（含丰富摘要信息）"""
        projects = []
        for project_dir in self.projects_dir.iterdir():
            if project_dir.is_dir():
                metadata_path = project_dir / "metadata.json"
                if not metadata_path.exists():
                    continue
                with open(metadata_path, "r", encoding="utf-8") as f:
                    m = json.load(f)
                info = {
                    "project_id": m["project_id"],
                    "name": m["name"],
                    "platform": m.get("platform", ""),
                    "status": m.get("status", ""),
                    "updated_at": m.get("updated_at", ""),
                    "current_stage": "",
                    "progress_pct": 0,
                    "total_chapters": 0,
                    "written_chapters": 0,
                    "word_count": 0,
                    "story_sentence": "",
                }
                # 读取 workflow.json 获取当前步骤
                wf_path = project_dir / "workflow.json"
                if wf_path.exists():
                    try:
                        wf = json.loads(wf_path.read_text(encoding="utf-8"))
                        info["current_stage"] = wf.get("current_step", "")
                    except Exception:
                        pass
                # 读取 chapter_outline.json 获取章节进度
                co_path = project_dir / "chapter_outline.json"
                if co_path.exists():
                    try:
                        co = json.loads(co_path.read_text(encoding="utf-8"))
                        info["total_chapters"] = co.get("total_chapters", 0)
                        info["written_chapters"] = len(co.get("written_chapters", []))
                        info["progress_pct"] = round(
                            info["written_chapters"] / info["total_chapters"] * 100
                        ) if info["total_chapters"] > 0 else 0
                    except Exception:
                        pass
                # 读取 story.json 获取一句话
                story_path = project_dir / "story.json"
                if story_path.exists():
                    try:
                        s = json.loads(story_path.read_text(encoding="utf-8"))
                        step1 = s.get("step1", {})
                        info["story_sentence"] = (step1.get("one_sentence") or "")[:60]
                    except Exception:
                        pass
                # 统计总字数（遍历 drafts/ 目录）
                drafts_dir = project_dir / "drafts"
                if drafts_dir.exists():
                    try:
                        total_wc = 0
                        for df in drafts_dir.glob("chapter_*.json"):
                            try:
                                d = json.loads(df.read_text(encoding="utf-8"))
                                total_wc += d.get("word_count", 0) or 0
                            except Exception:
                                pass
                        info["word_count"] = total_wc
                    except Exception:
                        pass
                projects.append(info)
        return projects

    def delete_project(self, project_id: str) -> bool:
        """删除项目（JSON + SQLite）"""
        import shutil
        project_dir = self.projects_dir / project_id
        ok = False
        if project_dir.exists():
            shutil.rmtree(project_dir)
            ok = True
        # Phase 5: also remove from SQLite
        try:
            self._db.delete_project(project_id)
            ok = True
        except Exception as e:
            logger.warning("SQLite delete failed for %s: %s", project_id, e)
        return ok

    # =========================================================================
    # Phase 5: SQLite 双写管理
    # =========================================================================

    def enable_sqlite_primary(self) -> None:
        """Migration Step 2: switch to SQLite as primary read source."""
        self._use_sqlite_primary = True
        logger.info("SQLite primary mode ENABLED (db=%s)", self._db_path)

    def disable_sqlite(self) -> None:
        """Rollback: switch back to JSON primary."""
        self._use_sqlite_primary = False
        logger.info("SQLite primary mode DISABLED — JSON is primary")

    def verify_dual_write_consistency(self, project_id: str) -> dict:
        """Compare JSON vs SQLite for a project, return diff report.

        Returns:
            {"consistent": bool, "json_exists": bool, "sqlite_exists": bool,
             "json_keys": int, "sqlite_keys": int, "diffs": list[str]}
        """
        result = {
            "consistent": True, "json_exists": False, "sqlite_exists": False,
            "json_keys": 0, "sqlite_keys": 0, "diffs": [],
        }

        # JSON check
        project_dir = self.projects_dir / project_id
        metadata_path = project_dir / "metadata.json"
        if metadata_path.exists():
            result["json_exists"] = True
            with open(metadata_path, "r", encoding="utf-8") as f:
                json_data = json.load(f)
            result["json_keys"] = len(json_data)

        # SQLite check
        try:
            sqlite_data = self._db.load_project(project_id)
            if sqlite_data:
                result["sqlite_exists"] = True
                result["sqlite_keys"] = len(sqlite_data)
        except Exception as e:
            result["diffs"].append(f"sqlite_read_error: {e}")
            result["consistent"] = False
            return result

        if not result["json_exists"] and not result["sqlite_exists"]:
            result["consistent"] = True
            return result

        if result["json_exists"] and not result["sqlite_exists"]:
            result["diffs"].append("missing_in_sqlite")
            result["consistent"] = False
        elif not result["json_exists"] and result["sqlite_exists"]:
            result["diffs"].append("missing_in_json")
            result["consistent"] = False
        elif result["json_exists"] and result["sqlite_exists"]:
            # Compare top-level keys
            json_keys = set(json_data.keys()) if isinstance(json_data, dict) else set()
            sqlite_keys = set(sqlite_data.keys()) if isinstance(sqlite_data, dict) else set()
            if json_keys != sqlite_keys:
                missing_in_sqlite = json_keys - sqlite_keys
                missing_in_json = sqlite_keys - json_keys
                if missing_in_sqlite:
                    result["diffs"].append(f"keys_missing_in_sqlite: {sorted(missing_in_sqlite)}")
                if missing_in_json:
                    result["diffs"].append(f"keys_missing_in_json: {sorted(missing_in_json)}")
                result["consistent"] = False

        return result

    def _save_sqlite(self, state: WriteSyncState) -> None:
        """Serialize state and write to SQLite."""
        state_dict = self._serialize(state)
        self._db.save_project(state.metadata.project_id, state_dict)

    def _load_json(self, project_id: str) -> WriteSyncState | None:
        """Load project from JSON files (original path)."""
        project_dir = self.projects_dir / project_id
        metadata_path = project_dir / "metadata.json"

        if not metadata_path.exists():
            return None

        with open(metadata_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        return self._deserialize_state(data, project_dir)

    # =========================================================================
    # 版本快照
    # =========================================================================

    def create_snapshot(self, state: WriteSyncState, step: StepName, user_note: str = "") -> int:
        """创建版本快照"""
        version_num = state.versions.current_version + 1
        snapshot = {
            "metadata": self._serialize(state.metadata),
            "topic": self._serialize(state.topic) if state.topic else None,
            "story": self._serialize(state.story) if state.story else None,
            "outline": self._serialize(state.outline) if state.outline else None,
            "characters": self._serialize(state.characters) if state.characters else None,
            "world": self._serialize(state.world) if state.world else None,
            "chapter_outline": self._serialize(state.chapter_outline) if state.chapter_outline else None,
        }

        from .state_types import VersionSnapshot
        snapshot_obj = VersionSnapshot(
            version=version_num,
            step=step,
            timestamp=datetime.now().isoformat(),
            snapshot=snapshot,
            user_note=user_note if user_note else None,
        )
        state.versions.snapshots.append(snapshot_obj)
        state.versions.current_version = version_num
        return version_num

    def rollback_to_version(self, state: WriteSyncState, version: int) -> bool:
        """回滚到指定版本"""
        for snap in state.versions.snapshots:
            if snap.version == version:
                s = snap.snapshot
                state.metadata = self._reconstruct(s["metadata"], ProjectMetadata)
                state.topic = self._reconstruct(s["topic"], TopicState) if s.get("topic") else None
                state.story = self._reconstruct(s["story"], StoryState) if s.get("story") else None
                state.outline = self._reconstruct(s["outline"], OutlineState) if s.get("outline") else None
                state.characters = self._reconstruct(s["characters"], CharactersState) if s.get("characters") else None
                state.world = self._reconstruct(s["world"], WorldState) if s.get("world") else None
                state.chapter_outline = self._reconstruct(s["chapter_outline"], ChapterOutlineState) if s.get("chapter_outline") else None
                return True
        return False

    # =========================================================================
    # 序列化 / 反序列化
    # =========================================================================

    def _serialize(self, obj: Any) -> Any:
        """将对象序列化为 JSON 兼容的 dict"""
        if obj is None:
            return None
        if isinstance(obj, list):
            return [self._serialize(v) for v in obj]
        if isinstance(obj, dict):
            return {k: self._serialize(v) for k, v in obj.items()}
        if hasattr(obj, "__dataclass_fields__"):
            result = {}
            for field_name in obj.__dataclass_fields__:
                value = getattr(obj, field_name)
                result[field_name] = self._serialize(value)
            return result
        if isinstance(obj, Enum):
            return obj.value
        if isinstance(obj, (str, int, float, bool)):
            return obj
        return str(obj)

    def _reconstruct(self, data: Any, cls: Any) -> Any:
        """从 dict 反序列化回 dataclass"""
        if data is None:
            return None

        origin = get_origin(cls)

        # Optional[X] = Union[X, None]
        if origin is not None:
            args = get_args(cls)
            for arg in args:
                if arg is type(None):
                    continue
                if arg is ...:
                    continue
                if isinstance(data, list):
                    return [self._reconstruct(d, arg) for d in data]
                return self._reconstruct(data, arg)
            return data

        # list[...] 类型
        if origin is list:
            args = get_args(cls)
            elem_type = args[0] if args else Any
            if isinstance(data, list):
                return [self._reconstruct(d, elem_type) for d in data]
            return data

        # dict 类型
        if origin is dict:
            return data

        # Enum
        if isinstance(cls, type) and issubclass(cls, Enum):
            return cls(data)

        # dataclass
        if hasattr(cls, "__dataclass_fields__"):
            kwargs = {}
            for field_name, field_info in cls.__dataclass_fields__.items():
                if field_name in data:
                    kwargs[field_name] = self._reconstruct(
                        data[field_name], field_info.type
                    )
            return cls(**kwargs)

        return data

    # =========================================================================
    # 内部方法
    # =========================================================================

    def _save_state_file(self, project_dir: Path, name: str, data: Any) -> None:
        """保存单个 State 文件"""
        if data is None:
            return
        path = project_dir / f"{name}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._serialize(data), f, ensure_ascii=False, indent=2)

    def _save_drafts(self, project_dir: Path, drafts: DraftsState) -> None:
        """保存草稿文件"""
        drafts_dir = project_dir / "drafts"
        drafts_dir.mkdir(exist_ok=True)

        for chapter_num, draft in drafts.chapters.items():
            draft_path = drafts_dir / f"chapter_{chapter_num:03d}.json"
            with open(draft_path, "w", encoding="utf-8") as f:
                json.dump(self._serialize(draft), f, ensure_ascii=False, indent=2)

    def _deserialize_state(self, data: dict, project_dir: Path) -> WriteSyncState:
        """从文件数据反序列化 State"""
        def load(name: str, cls):
            p = project_dir / f"{name}.json"
            if p.exists():
                with open(p, "r", encoding="utf-8") as f:
                    return self._reconstruct(json.load(f), cls)
            return None

        metadata = self._reconstruct(data, ProjectMetadata)
        workflow = load("workflow", WorkflowState)
        versions = load("versions", VersionState)

        drafts = DraftsState()
        drafts_dir = project_dir / "drafts"
        if drafts_dir.exists():
            for draft_file in drafts_dir.glob("chapter_*.json"):
                with open(draft_file, "r", encoding="utf-8") as f:
                    draft = self._reconstruct(json.load(f), ChapterDraft)
                    drafts.chapters[draft.chapter_number] = draft

        state = WriteSyncState(
            metadata=metadata,
            workflow=workflow,
            drafts=drafts,
            versions=versions,
        )
        state.topic = load("topic", TopicState)
        state.story = load("story", StoryState)
        state.outline = load("outline", OutlineState)
        state.characters = load("characters", CharactersState)
        state.world = load("world", WorldState)
        state.chapter_outline = load("chapter_outline", ChapterOutlineState)
        state.novel_review = load("novel_review", NovelReviewState)

        # 加载动态上下文 (context.json — 若不存在则初始化为空)
        ctx_path = project_dir / "context.json"
        if ctx_path.exists():
            try:
                state.dynamic_context = _safe_load_context(ctx_path)
            except Exception:
                state.dynamic_context = DynamicContext()
        else:
            state.dynamic_context = DynamicContext()

        return state


def _safe_load_context(path: Path):
    """从 JSON 加载 DynamicContext，处理 dict[int,*] key 转换。"""
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw = _fix_dict_keys(raw)
    valid_fields = {f.name for f in DynamicContext.__dataclass_fields__.values()}
    filtered = {k: v for k, v in raw.items() if k in valid_fields}
    return DynamicContext(**filtered)


def _fix_dict_keys(data: dict) -> dict:
    """将 JSON 字符串 key 转回 int key (chapter_word_counts, foreshadow_deadline)。"""
    for int_key_field in ("chapter_word_counts", "foreshadow_deadline"):
        if int_key_field in data and isinstance(data[int_key_field], dict):
            data[int_key_field] = {
                int(k): v for k, v in data[int_key_field].items()
            }
    return data
