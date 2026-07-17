"""
SQLite Migration Script (Phase 5)

One-time migration: export all existing JSON projects to SQLite.
Run from CLI or via the /api/migrate endpoint.

Usage:
    python -m src.state.migrate_to_sqlite
    python -m src.state.migrate_to_sqlite --projects-dir projects --db-path projects/writesync.db
"""

import argparse
import logging
import os
import sys

# ensure project root on path
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
os.environ["LANGGRAPH_STRICT_MSGPACK"] = "false"

from src.state.persistence import PersistenceManager

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger("writesync")


def migrate_all(projects_dir: str = "projects", db_path: str = "projects/writesync.db") -> dict:
    """Migrate all existing JSON projects to SQLite.

    Returns:
        {"total": int, "migrated": int, "skipped": int, "errors": list[str]}
    """
    result = {"total": 0, "migrated": 0, "skipped": 0, "errors": []}

    pm = PersistenceManager(projects_dir=projects_dir, db_path=db_path)
    projects = pm.list_projects()
    result["total"] = len(projects)

    if not projects:
        logger.info("No projects found in %s — nothing to migrate.", projects_dir)
        return result

    for p in projects:
        pid = p["project_id"]
        name = p.get("name", pid)
        try:
            state = pm.load_project(pid)
            if state is None:
                result["skipped"] += 1
                result["errors"].append(f"{pid}: load failed (corrupt JSON)")
                logger.warning("SKIP %s (%s): could not load from JSON", name, pid)
                continue

            # Force SQLite write
            pm._save_sqlite(state)
            logger.info("MIGRATED %s (%s)", name, pid)
            result["migrated"] += 1
        except Exception as e:
            result["errors"].append(f"{pid}: {e}")
            logger.error("ERROR %s (%s): %s", name, pid, e)

    # Verify consistency
    logger.info("Migration phase complete. Verifying consistency...")
    for p in projects:
        pid = p["project_id"]
        try:
            report = pm.verify_dual_write_consistency(pid)
            if not report["consistent"]:
                logger.warning("  MISMATCH %s: %s", pid, report["diffs"])
                result["errors"].append(f"{pid}: dual-write mismatch: {report['diffs']}")
        except Exception as e:
            logger.warning("  VERIFY ERROR %s: %s", pid, e)

    logger.info("Migration complete: %d/%d projects migrated.", result["migrated"], result["total"])
    return result


def main():
    parser = argparse.ArgumentParser(description="Migrate JSON projects to SQLite")
    parser.add_argument("--projects-dir", default="projects", help="Projects directory")
    parser.add_argument("--db-path", default="projects/writesync.db", help="SQLite DB path")
    args = parser.parse_args()

    result = migrate_all(args.projects_dir, args.db_path)
    print(f"\nDone: {result['migrated']}/{result['total']} migrated, "
          f"{result['skipped']} skipped, {len(result['errors'])} errors.")
    if result["errors"]:
        print("Errors:")
        for e in result["errors"]:
            print(f"  - {e}")


if __name__ == "__main__":
    main()
