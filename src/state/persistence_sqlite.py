"""
WriteSync SQLite Persistence Layer (Phase 5)

Provides:
- WAL mode SQLite storage for projects, chapters, characters, facts
- Schema management (versioned migrations)
- Table registry from PROJECT_TABLES
- Periodic vacuum maintenance

Part of the JSON→SQLite migration: dual-write transition (Migration Step 1).
"""

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("writesync")

SCHEMA_VERSION = 1

PROJECT_TABLES: dict[str, dict[str, Any]] = {
    "projects": {
        "sql": """CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            platform TEXT DEFAULT '',
            created_at TEXT DEFAULT '',
            updated_at TEXT DEFAULT '',
            status TEXT DEFAULT 'drafting',
            full_state TEXT NOT NULL
        )""",
        "exportable": True,
        "cascade_delete": ["chapters", "facts"],
    },
    "chapters": {
        "sql": """CREATE TABLE IF NOT EXISTS chapters (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            chapter_number INTEGER NOT NULL,
            draft_content TEXT DEFAULT '',
            final_content TEXT DEFAULT '',
            word_count INTEGER DEFAULT 0,
            stage TEXT DEFAULT 'draft',
            confirmed_at TEXT DEFAULT '',
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        )""",
        "exportable": True,
    },
    "facts": {
        "sql": """CREATE TABLE IF NOT EXISTS facts (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            content TEXT NOT NULL,
            category TEXT DEFAULT 'plot',
            valid_from_ch INTEGER NOT NULL,
            valid_to_ch INTEGER,
            status TEXT DEFAULT 'candidate',
            source_chapter INTEGER DEFAULT 0,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        )""",
        "exportable": True,
    },
    "snapshots": {
        "sql": """CREATE TABLE IF NOT EXISTS snapshots (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            state_json TEXT NOT NULL,
            chapter_count INTEGER DEFAULT 0,
            word_count INTEGER DEFAULT 0,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        )""",
        "exportable": True,
    },
    # ── Phase 7: extended table registry ──
    "global_foreshadows": {
        "sql": """CREATE TABLE IF NOT EXISTS global_foreshadows (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            foreshadow_text TEXT NOT NULL,
            status TEXT DEFAULT 'planted',
            planted_in_ch INTEGER NOT NULL,
            resolved_in_ch INTEGER,
            due_chapter INTEGER,
            priority INTEGER DEFAULT 0,
            created_at TEXT DEFAULT '',
            resolved_at TEXT DEFAULT '',
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        )""",
        "exportable": True,
        "cascade_delete": [],
    },
    "character_states": {
        "sql": """CREATE TABLE IF NOT EXISTS character_states (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            character_name TEXT NOT NULL,
            chapter_snapshot TEXT NOT NULL,
            chapter_number INTEGER NOT NULL,
            arc_progress TEXT DEFAULT '',
            physical_state TEXT DEFAULT '',
            emotional_state TEXT DEFAULT '',
            relationship_changes TEXT DEFAULT '',
            updated_at TEXT DEFAULT '',
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        )""",
        "exportable": True,
        "cascade_delete": [],
    },
    "item_transactions": {
        "sql": """CREATE TABLE IF NOT EXISTS item_transactions (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            item_name TEXT NOT NULL,
            transaction_type TEXT DEFAULT 'acquire',
            from_character TEXT DEFAULT '',
            to_character TEXT DEFAULT '',
            chapter_number INTEGER NOT NULL,
            description TEXT DEFAULT '',
            created_at TEXT DEFAULT '',
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        )""",
        "exportable": True,
        "cascade_delete": [],
    },
    "writing_rules": {
        "sql": """CREATE TABLE IF NOT EXISTS writing_rules (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            rule_name TEXT NOT NULL,
            rule_content TEXT NOT NULL,
            category TEXT DEFAULT 'global',
            priority INTEGER DEFAULT 5,
            is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT '',
            updated_at TEXT DEFAULT '',
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        )""",
        "exportable": True,
        "cascade_delete": [],
    },
    "reference_materials": {
        "sql": """CREATE TABLE IF NOT EXISTS reference_materials (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            title TEXT NOT NULL,
            content_type TEXT DEFAULT 'text',
            source TEXT DEFAULT '',
            file_path TEXT DEFAULT '',
            tags TEXT DEFAULT '',
            created_at TEXT DEFAULT '',
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        )""",
        "exportable": True,
        "cascade_delete": [],
    },
    "usage_records": {
        "sql": """CREATE TABLE IF NOT EXISTS usage_records (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            agent_name TEXT NOT NULL,
            model_name TEXT DEFAULT '',
            prompt_tokens INTEGER DEFAULT 0,
            completion_tokens INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            cost_usd REAL DEFAULT 0.0,
            duration_ms INTEGER DEFAULT 0,
            status TEXT DEFAULT 'success',
            created_at TEXT DEFAULT '',
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        )""",
        "exportable": True,
        "cascade_delete": [],
    },
}


class SQLitePersistence:
    """SQLite persistence backend with WAL mode and schema management.

    Usage:
        db = SQLitePersistence("projects/writesync.db")
        db.init_db()                             # create tables on first use
        db.save_project("abc123", state_dict)     # upsert full state
        data = db.load_project("abc123")          # returns dict or None
    """

    def __init__(self, db_path: str):
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None

    # ------------------------------------------------------------------
    # connection lifecycle
    # ------------------------------------------------------------------

    def _ensure_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self._db_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA busy_timeout=5000")
        return self._conn

    def close(self) -> None:
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    # ------------------------------------------------------------------
    # schema
    # ------------------------------------------------------------------

    def init_db(self) -> None:
        """Create all tables defined in PROJECT_TABLES if they don't exist."""
        conn = self._ensure_conn()
        for table_name, table_def in PROJECT_TABLES.items():
            conn.execute(table_def["sql"])
        conn.commit()
        # Record schema version
        conn.execute(
            "CREATE TABLE IF NOT EXISTS _schema_version (version INTEGER PRIMARY KEY)"
        )
        conn.execute(
            "INSERT OR REPLACE INTO _schema_version (version) VALUES (?)",
            (SCHEMA_VERSION,),
        )
        conn.commit()
        logger.info("SQLite DB initialised at %s (schema v%d)", self._db_path, SCHEMA_VERSION)

    def get_schema_version(self) -> int:
        conn = self._ensure_conn()
        row = conn.execute("SELECT version FROM _schema_version LIMIT 1").fetchone()
        return row["version"] if row else 0

    # ------------------------------------------------------------------
    # project CRUD
    # ------------------------------------------------------------------

    def save_project(self, project_id: str, state_dict: dict) -> None:
        """Persist a complete WriteSyncState as both a JSON blob and normalised rows."""
        conn = self._ensure_conn()
        now = datetime.now(timezone.utc).isoformat()

        # Upsert project row
        name = state_dict.get("metadata", {}).get("name", "") if isinstance(state_dict.get("metadata"), dict) else ""
        platform = state_dict.get("metadata", {}).get("platform", "") if isinstance(state_dict.get("metadata"), dict) else ""
        status = state_dict.get("metadata", {}).get("status", "drafting") if isinstance(state_dict.get("metadata"), dict) else "drafting"

        conn.execute(
            """INSERT INTO projects (id, name, platform, created_at, updated_at, status, full_state)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 name=excluded.name,
                 platform=excluded.platform,
                 updated_at=excluded.updated_at,
                 status=excluded.status,
                 full_state=excluded.full_state""",
            (project_id, name, platform, now, now, status,
             json.dumps(state_dict, ensure_ascii=False, default=str)),
        )

        # Extract and save chapters from drafts
        drafts = state_dict.get("drafts") or {}
        chapters_dict = drafts.get("chapters") if isinstance(drafts, dict) else {}
        for ch_num_str, ch_data in chapters_dict.items():
            try:
                ch_num = int(ch_num_str)
            except (ValueError, TypeError):
                continue
            if not isinstance(ch_data, dict):
                continue
            ch_id = f"{project_id}_ch{ch_num:03d}"
            draft_content = ""
            final_content = ""
            if ch_data.get("draft") and isinstance(ch_data["draft"], dict):
                draft_content = ch_data["draft"].get("content", "")
            if ch_data.get("final") and isinstance(ch_data["final"], dict):
                final_content = ch_data["final"].get("content", "")
            word_count = ch_data.get("word_count", 0) or 0
            stage = ch_data.get("stage", "draft") or "draft"
            confirmed_at = ""  # chapters don't have individual confirmed_at in current schema
            conn.execute(
                """INSERT INTO chapters (id, project_id, chapter_number, draft_content, final_content,
                                         word_count, stage, confirmed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                     draft_content=excluded.draft_content,
                     final_content=excluded.final_content,
                     word_count=excluded.word_count,
                     stage=excluded.stage,
                     confirmed_at=excluded.confirmed_at""",
                (ch_id, project_id, ch_num, draft_content, final_content,
                 word_count, stage, confirmed_at),
            )

        # Extract and save characters as facts
        characters = state_dict.get("characters")
        if characters and isinstance(characters, dict):
            chars_list = characters.get("characters") or []
            if isinstance(chars_list, list):
                for c in chars_list:
                    if not isinstance(c, dict):
                        continue
                    c_name = c.get("name", "unknown")
                    fact_id = str(uuid.uuid4())[:12]
                    # Build a rich fact string for the character
                    parts = [f"角色:{c_name}"]
                    if c.get("role"):
                        parts.append(f"身份:{c.get('role')}")
                    if c.get("personality"):
                        parts.append(f"性格:{c.get('personality')}")
                    if c.get("goal"):
                        parts.append(f"目标:{c.get('goal')}")
                    if c.get("background"):
                        parts.append(f"背景:{c.get('background')}")
                    content = " | ".join(parts)
                    conn.execute(
                        """INSERT INTO facts (id, project_id, content, category, valid_from_ch,
                                             valid_to_ch, status, source_chapter)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (fact_id, project_id, content, "character", 1, None, "confirmed", 0),
                    )

        # Extract world facts
        world = state_dict.get("world")
        if world and isinstance(world, dict):
            ps = world.get("power_system") or {}
            if isinstance(ps, dict) and ps.get("system_name"):
                fact_id = str(uuid.uuid4())[:12]
                content = f"力量体系:{ps.get('system_name')}"
                if ps.get("tiers"):
                    content += f" | 等级: {', '.join(ps['tiers']) if isinstance(ps['tiers'], list) else ps['tiers']}"
                conn.execute(
                    """INSERT INTO facts (id, project_id, content, category, valid_from_ch,
                                         valid_to_ch, status, source_chapter)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (fact_id, project_id, content, "world", 1, None, "confirmed", 0),
                )

        conn.commit()

    def load_project(self, project_id: str) -> Optional[dict]:
        """Load a project's full state from SQLite. Returns None if not found."""
        conn = self._ensure_conn()
        row = conn.execute(
            "SELECT full_state FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if not row:
            return None
        try:
            return json.loads(row["full_state"])
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning("Corrupt SQLite state for project %s: %s", project_id, e)
            return None

    def delete_project(self, project_id: str) -> bool:
        """Delete a project and its cascaded rows."""
        conn = self._ensure_conn()
        cursor = conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        conn.commit()
        return cursor.rowcount > 0

    def list_projects(self) -> list[dict]:
        """List all projects with metadata (no full_state)."""
        conn = self._ensure_conn()
        rows = conn.execute(
            "SELECT id, name, platform, created_at, updated_at, status FROM projects ORDER BY updated_at DESC"
        ).fetchall()
        result = []
        for row in rows:
            info = dict(row)
            # count chapters
            ch_count = conn.execute(
                "SELECT COUNT(*) as cnt FROM chapters WHERE project_id = ?", (info["id"],)
            ).fetchone()
            info["chapter_count"] = ch_count["cnt"] if ch_count else 0
            result.append(info)
        return result

    # ------------------------------------------------------------------
    # chapter CRUD
    # ------------------------------------------------------------------

    def save_chapter(
        self, project_id: str, chapter_num: int,
        draft: str, final: str, word_count: int = 0,
    ) -> None:
        conn = self._ensure_conn()
        ch_id = f"{project_id}_ch{chapter_num:03d}"
        conn.execute(
            """INSERT INTO chapters (id, project_id, chapter_number, draft_content,
                                     final_content, word_count)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 draft_content=excluded.draft_content,
                 final_content=excluded.final_content,
                 word_count=excluded.word_count""",
            (ch_id, project_id, chapter_num, draft, final, word_count),
        )
        conn.commit()

    def get_chapters(self, project_id: str) -> list[dict]:
        conn = self._ensure_conn()
        rows = conn.execute(
            "SELECT * FROM chapters WHERE project_id = ? ORDER BY chapter_number",
            (project_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # fact CRUD
    # ------------------------------------------------------------------

    def save_fact(self, project_id: str, fact: dict) -> None:
        conn = self._ensure_conn()
        fact_id = fact.get("id") or str(uuid.uuid4())[:12]
        conn.execute(
            """INSERT INTO facts (id, project_id, content, category, valid_from_ch,
                                  valid_to_ch, status, source_chapter)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 content=excluded.content,
                 category=excluded.category,
                 valid_from_ch=excluded.valid_from_ch,
                 valid_to_ch=excluded.valid_to_ch,
                 status=excluded.status,
                 source_chapter=excluded.source_chapter""",
            (
                fact_id, project_id,
                fact.get("content", ""), fact.get("category", "plot"),
                fact.get("valid_from_ch", 1), fact.get("valid_to_ch"),
                fact.get("status", "candidate"), fact.get("source_chapter", 0),
            ),
        )
        conn.commit()

    def get_facts(self, project_id: str, up_to_chapter: Optional[int] = None) -> list[dict]:
        conn = self._ensure_conn()
        if up_to_chapter is not None:
            rows = conn.execute(
                """SELECT * FROM facts WHERE project_id = ?
                   AND valid_from_ch <= ? AND (valid_to_ch IS NULL OR valid_to_ch >= ?)
                   ORDER BY valid_from_ch""",
                (project_id, up_to_chapter, up_to_chapter),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM facts WHERE project_id = ? ORDER BY valid_from_ch",
                (project_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # maintenance
    # ------------------------------------------------------------------

    def vacuum(self) -> None:
        """Periodic maintenance: run VACUUM to reclaim space."""
        conn = self._ensure_conn()
        conn.execute("VACUUM")
        logger.info("SQLite VACUUM completed for %s", self._db_path)

    # ------------------------------------------------------------------
    # snapshot CRUD (raw — higher-level management is in snapshot.py)
    # ------------------------------------------------------------------

    def save_snapshot(self, project_id: str, name: str,
                      state_json: str, chapter_count: int = 0,
                      word_count: int = 0) -> str:
        conn = self._ensure_conn()
        snap_id = str(uuid.uuid4())[:12]
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """INSERT INTO snapshots (id, project_id, name, created_at,
                                      state_json, chapter_count, word_count)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (snap_id, project_id, name, now, state_json, chapter_count, word_count),
        )
        conn.commit()
        logger.info("Snapshot %s created for project %s", snap_id, project_id)
        return snap_id

    def get_snapshots(self, project_id: str) -> list[dict]:
        conn = self._ensure_conn()
        rows = conn.execute(
            "SELECT * FROM snapshots WHERE project_id = ? ORDER BY created_at DESC",
            (project_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_snapshot(self, snapshot_id: str) -> Optional[dict]:
        conn = self._ensure_conn()
        row = conn.execute(
            "SELECT * FROM snapshots WHERE id = ?", (snapshot_id,)
        ).fetchone()
        return dict(row) if row else None

    def delete_snapshot(self, snapshot_id: str) -> bool:
        conn = self._ensure_conn()
        cursor = conn.execute("DELETE FROM snapshots WHERE id = ?", (snapshot_id,))
        conn.commit()
        return cursor.rowcount > 0
