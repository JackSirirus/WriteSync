"""
WriteSync ProjectSnapshot System (Phase 5)

Distinct from VersionSnapshot (state_types.py) which tracks code versions.
ProjectSnapshot captures user-project state at a point in time.

Usage:
    db = SQLitePersistence("projects/writesync.db")
    sm = SnapshotManager(db)
    snap_id = sm.create_auto_snapshot("abc123", state_dict)
    sm.list_snapshots("abc123")
    sm.restore_snapshot("abc123", snap_id)
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from .persistence_sqlite import SQLitePersistence

logger = logging.getLogger("writesync")


@dataclass
class ProjectSnapshot:
    """A point-in-time snapshot of a user project.

    Uses the name 'ProjectSnapshot' to avoid collision with the existing
    VersionSnapshot (state_types.py) which tracks internal versioning.
    """
    id: str                     # UUID (short)
    project_id: str
    name: str                   # User-given name or "auto-{timestamp}"
    created_at: str             # ISO timestamp
    state_json: str             # Full JSON dump of WriteSyncState
    chapter_count: int = 0
    word_count: int = 0


class SnapshotManager:
    """Manages ProjectSnapshot lifecycle via SQLitePersistence."""

    def __init__(self, db: SQLitePersistence):
        self._db = db

    # ------------------------------------------------------------------
    # create
    # ------------------------------------------------------------------

    def create_auto_snapshot(self, project_id: str, state_dict: dict) -> str:
        """Create an auto-named snapshot (e.g., auto-2026-07-13T09:30:00)."""
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        name = f"auto-{ts}"
        return self._create(project_id, name, state_dict)

    def create_manual_snapshot(self, project_id: str, name: str,
                               state_dict: dict) -> str:
        """Create a user-named snapshot."""
        if not name.strip():
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
            name = f"snapshot-{ts}"
        return self._create(project_id, name, state_dict)

    def _create(self, project_id: str, name: str, state_dict: dict) -> str:
        state_json = json.dumps(state_dict, ensure_ascii=False, default=str)

        # calculate chapter_count and word_count from state
        chapter_count = 0
        word_count = 0
        drafts = state_dict.get("drafts") or {}
        if isinstance(drafts, dict):
            chapters = drafts.get("chapters") or {}
            if isinstance(chapters, dict):
                chapter_count = len(chapters)
                for ch_data in chapters.values():
                    if isinstance(ch_data, dict):
                        word_count += ch_data.get("word_count", 0) or 0
        # also check chapter_outline
        co = state_dict.get("chapter_outline") or {}
        if isinstance(co, dict):
            if chapter_count == 0 and co.get("total_chapters"):
                chapter_count = co["total_chapters"]

        snap_id = self._db.save_snapshot(
            project_id, name, state_json,
            chapter_count=chapter_count, word_count=word_count,
        )
        logger.info("ProjectSnapshot created: %s (project=%s, ch=%d, wc=%d)",
                    snap_id, project_id, chapter_count, word_count)
        return snap_id

    # ------------------------------------------------------------------
    # list / get
    # ------------------------------------------------------------------

    def list_snapshots(self, project_id: str) -> list[ProjectSnapshot]:
        """List all snapshots for a project, newest first."""
        rows = self._db.get_snapshots(project_id)
        return [
            ProjectSnapshot(
                id=r["id"],
                project_id=r["project_id"],
                name=r["name"],
                created_at=r["created_at"],
                state_json=r["state_json"],
                chapter_count=r.get("chapter_count", 0),
                word_count=r.get("word_count", 0),
            )
            for r in rows
        ]

    def get_snapshot(self, snapshot_id: str) -> Optional[ProjectSnapshot]:
        """Get a single snapshot by ID."""
        row = self._db.get_snapshot(snapshot_id)
        if not row:
            return None
        return ProjectSnapshot(
            id=row["id"],
            project_id=row["project_id"],
            name=row["name"],
            created_at=row["created_at"],
            state_json=row["state_json"],
            chapter_count=row.get("chapter_count", 0),
            word_count=row.get("word_count", 0),
        )

    # ------------------------------------------------------------------
    # restore / delete
    # ------------------------------------------------------------------

    def restore_snapshot(self, project_id: str, snapshot_id: str) -> Optional[dict]:
        """Restore a snapshot: return the state dict so caller can reload."""
        row = self._db.get_snapshot(snapshot_id)
        if not row or row["project_id"] != project_id:
            return None
        try:
            return json.loads(row["state_json"])
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning("Corrupt snapshot %s: %s", snapshot_id, e)
            return None

    def delete_snapshot(self, snapshot_id: str) -> bool:
        """Delete a snapshot. Returns True if deleted."""
        return self._db.delete_snapshot(snapshot_id)
