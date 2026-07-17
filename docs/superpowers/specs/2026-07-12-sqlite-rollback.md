# SQLite Migration Rollback Plan

**Created**: 2026-07-12  
**Context**: Phase 5 SQLite persistence upgrade adds dual-write (JSON + SQLite) as
Migration Step 1. JSON remains primary by default. This document describes how to
roll back if SQLite causes issues.

---

## Current State (Migration Step 1)

- `_use_sqlite_primary = False` (default)
- Every `save_project()` writes to **both** JSON files AND SQLite
- `load_project()` reads from **JSON only** (safe, no SQLite dependency for reads)
- SQLite write failures are caught and logged — they **never** prevent JSON saves

---

## Rollback Procedure

### Step 1: Disable SQLite Primary Mode

Verify `_use_sqlite_primary` is `False` in `src/state/persistence.py`:

```python
self._use_sqlite_primary = False  # line ~55
```

If it was ever changed to `True`, revert it back to `False`.

### Step 2: Verify JSON Files Are Intact

```bash
# List all project directories
Get-ChildItem projects\ -Directory | ForEach-Object { $_.Name }

# Check a specific project's metadata.json exists
cat projects\<project_id>\metadata.json
```

### Step 3: Delete SQLite Database

```bash
# Rename (safer) or delete
Rename-Item projects\writesync.db writesync.db.bak
# Or: Remove-Item projects\writesync.db
```

### Step 4: Restart the Application

```bash
# Web UI
uvicorn src.web.app:app --reload

# CLI
python -m src.cli
```

### Step 5: Verify JSON-Only Mode Works

```bash
# Run persistence tests
python -m pytest tests/test_persistence.py -v

# Verify project listing works
curl http://localhost:8000/api/projects
```

---

## Emergency Rollback (Quick)

If SQLite is causing startup errors:

1. Delete or rename `projects/writesync.db`
2. Restart the application
3. The `SQLitePersistence.init_db()` call will re-create the DB but won't
   auto-migrate existing JSON data (migration is opt-in via `/api/migrate`)

---

## Data Safety

- **JSON files are NEVER deleted** during Migration Step 1
- SQLite writes are additive — they don't modify JSON files
- Even with `_use_sqlite_primary = True`, JSON writes still happen in parallel
- The migration script (`migrate_to_sqlite.py`) only reads JSON, never deletes

---

## Recovery After Rollback

To re-enable SQLite after fixing issues:

1. Ensure `projects/writesync.db` exists (it will auto-create on startup)
2. Run migration: `python -m src.state.migrate_to_sqlite`
3. Or trigger via API: `POST /api/migrate`

---

## When to Roll Back

Consider rollback if:
- SQLite write errors appear frequently in logs
- Disk space is critically low (SQLite adds ~2x storage)
- Performance degradation observed (WAL mode should prevent this)
- SQLite file corruption detected
