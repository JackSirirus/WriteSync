"""
JSON Complete Backup Export (Phase 5)

Export the entire project state as a structured JSON file suitable for
backup, archival, or migration.

Usage:
    from src.utils.export_json import export_full_backup
    export_full_backup(ws_state, "my_backup.json")
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from ..state.state_types import WriteSyncState

logger = logging.getLogger("writesync")

_BACKUP_VERSION = "0.5.0"


def export_full_backup(state: WriteSyncState, output_path: str = "") -> str:
    """Export complete project state as a structured JSON backup.

    The backup includes:
    - Metadata (version, exported_at, project_id)
    - Full serialized WriteSyncState
    - Summary statistics (chapter/word counts)

    Args:
        state: WriteSyncState to export
        output_path: Target file path (auto-generated if empty)

    Returns:
        The output file path
    """
    if not output_path:
        name = state.metadata.name or "novel"
        output_path = f"{name}_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    # Serialize the full state using the same logic as PersistenceManager
    from ..state.persistence import PersistenceManager

    def _serialize_state(obj: object) -> object:
        """Serialize a WriteSyncState dataclass tree to JSON-compatible dicts."""
        if obj is None:
            return None
        if isinstance(obj, list):
            return [_serialize_state(v) for v in obj]
        if isinstance(obj, dict):
            return {str(k): _serialize_state(v) for k, v in obj.items()}
        from enum import Enum
        if isinstance(obj, Enum):
            return obj.value
        if hasattr(obj, "__dataclass_fields__"):
            result = {}
            for field_name in obj.__dataclass_fields__:
                value = getattr(obj, field_name)
                result[field_name] = _serialize_state(value)
            return result
        if isinstance(obj, (str, int, float, bool)):
            return obj
        return str(obj)

    state_dict = _serialize_state(state) if state else {}
    chapter_count = 0
    word_count = 0
    if state.drafts and state.drafts.chapters:
        chapter_count = len(state.drafts.chapters)
        word_count = sum(cd.word_count or 0 for cd in state.drafts.chapters.values())

    chapters_outlined = 0
    if state.chapter_outline:
        chapters_outlined = state.chapter_outline.total_chapters

    backup = {
        "format": "writesync_full_backup",
        "version": _BACKUP_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "project_id": state.metadata.project_id,
        "project_name": state.metadata.name,
        "platform": state.metadata.platform,
        "summary": {
            "chapter_count": chapter_count,
            "word_count": word_count,
            "chapters_outlined": chapters_outlined,
            "status": state.metadata.status.value if hasattr(state.metadata.status, "value") else str(state.metadata.status),
            "created_at": state.metadata.created_at,
            "updated_at": state.metadata.updated_at,
        },
        "state": state_dict,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(backup, f, ensure_ascii=False, indent=2, default=str)

    file_size = Path(output_path).stat().st_size
    logger.info("JSON backup exported: %s (%.1f KB)", output_path, file_size / 1024)

    return output_path
