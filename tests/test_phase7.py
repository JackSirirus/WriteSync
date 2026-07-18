"""
Phase 7 — 架构固化：三注册表 + 架构 lint

Tests for:
- Agent Registry (call_agent, get_agent, list_agents, agents_for_phase)
- Context Source Registry (assemble_context, get_source, list_sources)
- TableRegistry (CRUD, import/export, cascade_delete)
- Architecture Linter (run_lint, LintViolation)
"""
import sqlite3
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# ── Agent Registry ──────────────────────────────────────────────────────

from src.orchestrator.agent_registry import (
    AGENT_REGISTRY,
    AgentDef,
    call_agent,
    get_agent,
    list_agents,
    agents_for_phase,
    add_agent,
)

# ── Context Source Registry ─────────────────────────────────────────────

from src.agents.context_registry import (
    CONTEXT_SOURCES,
    ContextSource,
    assemble_context,
    get_source,
    list_sources,
    list_sources_by_scope,
)

# ── TableRegistry ───────────────────────────────────────────────────────

from src.state.persistence_sqlite import TableRegistry

# ── Architecture Linter ────────────────────────────────────────────────

# Import directly (no subprocess — Windows env crashes on subprocess.run)
import sys
_scripts_dir = str(Path(__file__).resolve().parent.parent / "scripts")
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)
from arch_lint import run_lint, LintViolation


# ============================================================================
# Agent Registry Tests
# ============================================================================

class TestAgentRegistry:
    """Tests for the declarative agent registry."""

    def test_all_seven_agents_registered(self):
        """Exactly 7 agents should be registered."""
        assert len(list_agents()) == 7

    def test_known_agent_names(self):
        """The registry must contain all known agent names."""
        expected = {"story", "character", "world", "outline", "writer", "proofreader", "novel_review"}
        assert set(list_agents().keys()) == expected

    def test_get_agent_returns_def(self):
        """get_agent() returns AgentDef for valid name, None for invalid."""
        assert isinstance(get_agent("writer"), AgentDef)
        assert get_agent("nonexistent") is None

    def test_agents_for_phase_writing(self):
        """agents_for_phase('writing_chapters') includes writer and proofreader."""
        names = list(agents_for_phase("writing_chapters").keys())
        assert "writer" in names
        assert "proofreader" in names
        assert "story" not in names

    def test_agents_for_phase_planning(self):
        """agents_for_phase('planning') includes character, world, outline."""
        names = list(agents_for_phase("planning").keys())
        assert "character" in names
        assert "world" in names
        assert "outline" in names

    def test_agent_def_fields(self):
        """AgentDef must have required metadata fields."""
        a = get_agent("story")
        assert a is not None
        assert hasattr(a, "adapter_fn")
        assert hasattr(a, "allowed_phases")
        assert hasattr(a, "model_preference")
        assert hasattr(a, "timeout")
        assert a.model_preference in ("pro", "flash")
        assert a.timeout > 0

    def test_add_agent_raises_on_duplicate(self):
        """add_agent() raises ValueError for existing name."""
        with pytest.raises(ValueError, match="已注册"):
            add_agent("writer", AgentDef(
                adapter_fn=lambda *a, **kw: None,
                allowed_phases=[], model_preference="flash", timeout=30,
            ))

    def test_add_agent_new_name(self):
        """add_agent() registers a new agent successfully."""
        dummy = AgentDef(
            adapter_fn=lambda *a, **kw: None,
            allowed_phases=["test"], model_preference="flash", timeout=30,
            description="test agent",
        )
        add_agent("test_dummy_7", dummy)
        try:
            assert get_agent("test_dummy_7") is dummy
        finally:
            AGENT_REGISTRY.pop("test_dummy_7", None)

    def test_call_agent_dispatches(self):
        """call_agent() invokes the adapter function with correct args."""
        mock_fn = MagicMock(return_value=MagicMock(agent="writer"))
        with patch.dict(AGENT_REGISTRY, {
            "writer": AgentDef(
                adapter_fn=mock_fn, allowed_phases=["writing_chapters"],
                model_preference="flash", timeout=30,
            )
        }):
            result = call_agent(None, "writer", instruction="write", chapter_num=1)
            mock_fn.assert_called_once()
            assert result.agent == "writer"

    def test_call_agent_invalid_name_returns_error(self):
        """call_agent with unknown name returns AgentResult with error."""
        result = call_agent(None, "nonexistent")
        assert result.error is not None
        assert "nonexistent" in result.error


# ============================================================================
# Context Source Registry Tests
# ============================================================================

# Helper to build a minimal WriteSyncState without hitting metadata requirement
def _make_state(**dynamic_ctx_kwargs):
    """Build a WriteSyncState with minimal metadata for testing."""
    from src.state.state_types import WriteSyncState, ProjectMetadata, DynamicContext
    meta = ProjectMetadata(project_id="test", name="test")
    dc = DynamicContext(**dynamic_ctx_kwargs) if dynamic_ctx_kwargs else None
    return WriteSyncState(metadata=meta, dynamic_context=dc)


class TestContextRegistry:
    """Tests for the declarative context source registry."""

    def test_seven_sources_registered(self):
        """Exactly 7 context sources should be registered."""
        assert len(CONTEXT_SOURCES) == 7

    def test_source_names(self):
        """Registered source names must match expected set."""
        expected = {
            "character_snapshot", "recent_chapters", "continuity_envelope",
            "unresolved_foreshadows", "foreshadow_deadline",
            "consistency_notes", "pacing_state",
        }
        assert set(CONTEXT_SOURCES.keys()) == expected

    def test_source_fields(self):
        """Each ContextSource must have name, builder_fn, priority, scope."""
        for src in CONTEXT_SOURCES.values():
            assert isinstance(src, ContextSource)
            assert callable(src.builder_fn)
            assert src.priority > 0
            assert src.scope in ("planning", "writing", "all")

    def test_get_source(self):
        """get_source() returns ContextSource or None."""
        s = get_source("character_snapshot")
        assert isinstance(s, ContextSource)
        assert get_source("no_such_source") is None

    def test_list_sources_by_scope(self):
        """Filtering by scope returns only matching sources."""
        planning = list_sources_by_scope("planning")
        for name, src in planning:
            assert src.scope == "planning"
        writing = list_sources_by_scope("writing")
        for name, src in writing:
            assert src.scope == "writing"

    def test_assemble_context_empty_state(self):
        """assemble_context with empty state returns empty string."""
        state = _make_state()
        result = assemble_context(state, chapter_num=0, budget=800)
        assert result == ""

    def test_assemble_context_with_data(self):
        """assemble_context with populated state returns formatted sections."""
        state = _make_state(
            character_snapshot="张三：男，28岁，性格温和",
            recent_chapters_summary="前三章讲了...",
            continuity_envelope={"handoff": "上章结束于雨夜"},
            unresolved_foreshadows=["伏笔A", "伏笔B"],
        )
        result = assemble_context(state, chapter_num=2, budget=800)
        assert "张三" in result
        assert "伏笔A" in result

    def test_assemble_context_budget_limit(self):
        """Output should respect the budget cap."""
        state = _make_state(
            character_snapshot="A" * 500,
            recent_chapters_summary="B" * 500,
            unresolved_foreshadows=["C" * 100] * 10,
        )
        result = assemble_context(state, chapter_num=1, budget=200)
        assert len(result) <= 400  # headers add ~20 chars per section

    def test_assemble_context_dict_state(self):
        """assemble_context accepts dict wrapper with 'data' key."""
        state = _make_state(character_snapshot="测试角色")
        result = assemble_context({"data": state}, chapter_num=1, budget=800)
        assert "测试角色" in result


# ============================================================================
# TableRegistry Tests
# ============================================================================

class TestTableRegistry:
    """Tests for the data table registry wrapping PROJECT_TABLES."""

    def _make_registry(self) -> TableRegistry:
        """Build a minimal registry with projects + chapters."""
        reg = TableRegistry({})
        reg.register_table(
            "projects",
            sql='CREATE TABLE projects (id TEXT PRIMARY KEY, name TEXT, created_at TEXT)',
            exportable=True,
            cascade_delete=["chapters"],
        )
        reg.register_table(
            "chapters",
            sql='CREATE TABLE chapters (id TEXT PRIMARY KEY, project_id TEXT, content TEXT)',
            exportable=True,
        )
        return reg

    def test_table_names(self):
        """table_names() returns registered table names."""
        reg = self._make_registry()
        names = reg.table_names()
        assert "projects" in names
        assert "chapters" in names

    def test_create_all(self):
        """create_all() creates tables in SQLite."""
        reg = self._make_registry()
        conn = sqlite3.connect(":memory:")
        reg.create_all(conn)
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        assert "projects" in tables
        assert "chapters" in tables
        conn.close()

    def test_insert_and_get_rows(self):
        """Insert rows and retrieve them as dicts."""
        reg = self._make_registry()
        conn = sqlite3.connect(":memory:")
        reg.create_all(conn)
        reg.insert_row(conn, "projects", {"id": "p1", "name": "Test", "created_at": "2026-01-01"})
        rows = reg.get_rows(conn, "projects")
        assert len(rows) == 1
        assert rows[0]["name"] == "Test"
        conn.close()

    def test_update_row(self):
        """Update a row by primary key."""
        reg = self._make_registry()
        conn = sqlite3.connect(":memory:")
        reg.create_all(conn)
        reg.insert_row(conn, "projects", {"id": "p1", "name": "Old", "created_at": "2026-01-01"})
        reg.update_row(conn, "projects", "p1", {"name": "New"})
        rows = reg.get_rows(conn, "projects", where="id = ?", params=("p1",))
        assert rows[0]["name"] == "New"
        conn.close()

    def test_delete_row(self):
        """Delete a row by primary key."""
        reg = self._make_registry()
        conn = sqlite3.connect(":memory:")
        reg.create_all(conn)
        reg.insert_row(conn, "projects", {"id": "p1", "name": "Test", "created_at": "2026-01-01"})
        reg.delete_row(conn, "projects", "p1")
        rows = reg.get_rows(conn, "projects")
        assert len(rows) == 0
        conn.close()

    def test_export_import_table(self):
        """Export then import preserves data."""
        reg = self._make_registry()
        conn = sqlite3.connect(":memory:")
        reg.create_all(conn)
        reg.insert_row(conn, "projects", {"id": "p1", "name": "Test", "created_at": "2026-01-01"})
        exported = reg.export_table(conn, "projects")
        assert len(exported) == 1
        assert exported[0]["name"] == "Test"
        # Clear and reimport
        reg.delete_row(conn, "projects", "p1")
        reg.import_table(conn, "projects", exported)
        rows = reg.get_rows(conn, "projects")
        assert len(rows) == 1
        assert rows[0]["name"] == "Test"
        conn.close()

    def test_cascade_delete(self):
        """Cascade delete removes children when parent is deleted."""
        reg = self._make_registry()
        conn = sqlite3.connect(":memory:")
        reg.create_all(conn)
        reg.insert_row(conn, "projects", {"id": "p1", "name": "Test", "created_at": "2026-01-01"})
        reg.insert_row(conn, "chapters", {"id": "c1", "project_id": "p1", "content": "hello"})
        reg.insert_row(conn, "chapters", {"id": "c2", "project_id": "p1", "content": "world"})
        reg.cascade_delete(conn, "projects", "p1")
        assert len(reg.get_rows(conn, "projects")) == 0
        assert len(reg.get_rows(conn, "chapters")) == 0
        conn.close()


# ============================================================================
# Architecture Linter Tests
# ============================================================================

class TestArchLint:
    """Tests for the architecture linter (direct import, no subprocess)."""

    def test_run_lint_returns_list(self):
        """run_lint() should return a list of LintViolation."""
        violations = run_lint()
        assert isinstance(violations, list)

    def test_violation_dataclass_fields(self):
        """LintViolation must have file, line, rule, message fields."""
        v = LintViolation(file="src/test.py", line=42, rule="NO_DIRECT_FILE_IO", message="test")
        assert v.file == "src/test.py"
        assert v.line == 42
        assert v.rule == "NO_DIRECT_FILE_IO"
        assert v.message == "test"

    def test_lint_finds_known_violations(self):
        """The linter should find NO_DIRECT_FILE_IO violations in existing code."""
        violations = run_lint()
        rules_found = {v.rule for v in violations}
        # Existing codebase has known violations
        assert "NO_DIRECT_FILE_IO" in rules_found

    def test_lint_excludes_persistence_layer(self):
        """persistence.py and persistence_sqlite.py should be excluded from NO_DIRECT_FILE_IO."""
        violations = run_lint()
        io_violations = [v for v in violations if v.rule == "NO_DIRECT_FILE_IO"]
        for v in io_violations:
            assert "persistence.py" not in v.file
            assert "persistence_sqlite.py" not in v.file

    def test_lint_result_has_file_paths(self):
        """Every violation should have a valid-looking file path."""
        violations = run_lint()
        for v in violations:
            assert v.file.startswith("src/") or v.file.startswith("scripts/")
