"""stale_tracker 单元测试 — 标记/清除/查询逻辑"""

import pytest
from unittest.mock import MagicMock, PropertyMock
from src.orchestrator.stale_tracker import mark_stale, clear_stale, get_stale_info, DEPENDENCY_MAP


class MockWorkspace:
    """Mock workspace with raw_state.stale_markers"""
    def __init__(self):
        self.raw_state = MagicMock()
        self.raw_state.stale_markers = {}
        self._saved = False

    def save(self):
        self._saved = True


# ── DEPENDENCY_MAP 验证 ──

class TestDependencyMap:
    def test_story_depends_on_all_writing_agents(self):
        deps = DEPENDENCY_MAP["story"]
        assert "character" in deps
        assert "world" in deps
        assert "outline" in deps
        assert "writer" in deps

    def test_character_depends_on_outline_and_writer(self):
        deps = DEPENDENCY_MAP["character"]
        assert "outline" in deps
        assert "writer" in deps
        assert "proofreader" not in deps

    def test_world_depends_on_outline_and_writer(self):
        deps = DEPENDENCY_MAP["world"]
        assert "outline" in deps
        assert "writer" in deps

    def test_outline_depends_on_writer_only(self):
        deps = DEPENDENCY_MAP["outline"]
        assert deps == ["writer"]

    def test_writer_depends_on_proofreader_only(self):
        deps = DEPENDENCY_MAP["writer"]
        assert deps == ["proofreader"]

    def test_proofreader_has_no_downstream(self):
        deps = DEPENDENCY_MAP.get("proofreader", [])
        assert deps == []


# ── mark_stale 测试 ──

class TestMarkStale:
    def test_mark_stale_story(self):
        ws = MockWorkspace()
        mark_stale(ws, "story")
        markers = ws.raw_state.stale_markers
        assert "character" in markers
        assert "world" in markers
        assert "outline" in markers
        assert "writer" in markers
        assert markers["character"] == ["story"]
        assert ws._saved

    def test_mark_stale_character(self):
        ws = MockWorkspace()
        mark_stale(ws, "character")
        markers = ws.raw_state.stale_markers
        assert "outline" in markers
        assert "writer" in markers
        assert "character" not in markers
        assert markers["outline"] == ["character"]

    def test_mark_stale_world(self):
        ws = MockWorkspace()
        mark_stale(ws, "world")
        markers = ws.raw_state.stale_markers
        assert "outline" in markers
        assert "writer" in markers
        assert markers["outline"] == ["world"]

    def test_mark_stale_outline(self):
        ws = MockWorkspace()
        mark_stale(ws, "outline")
        markers = ws.raw_state.stale_markers
        assert "writer" in markers
        assert markers["writer"] == ["outline"]

    def test_mark_stale_writer(self):
        ws = MockWorkspace()
        mark_stale(ws, "writer")
        markers = ws.raw_state.stale_markers
        assert "proofreader" in markers
        assert markers["proofreader"] == ["writer"]

    def test_mark_stale_proofreader_no_effect(self):
        ws = MockWorkspace()
        mark_stale(ws, "proofreader")
        assert ws.raw_state.stale_markers == {}

    def test_mark_stale_no_duplicate(self):
        ws = MockWorkspace()
        mark_stale(ws, "story")
        mark_stale(ws, "story")  # 重复标记
        markers = ws.raw_state.stale_markers
        assert markers["character"] == ["story"]  # 不应重复追加

    def test_mark_stale_accumulates_multiple_sources(self):
        ws = MockWorkspace()
        mark_stale(ws, "story")
        mark_stale(ws, "character")
        # outline 应同时被 story 和 character 标记
        assert set(ws.raw_state.stale_markers["outline"]) == {"story", "character"}
        # writer 应同时被 story 和 character 标记
        assert set(ws.raw_state.stale_markers["writer"]) == {"story", "character"}


# ── clear_stale 测试 ──

class TestClearStale:
    def test_clear_stale_removes_entry(self):
        ws = MockWorkspace()
        mark_stale(ws, "story")
        assert "character" in ws.raw_state.stale_markers
        clear_stale(ws, "character")
        assert "character" not in ws.raw_state.stale_markers

    def test_clear_stale_nonexistent_no_error(self):
        ws = MockWorkspace()
        clear_stale(ws, "nonexistent")  # 不应报错

    def test_clear_stale_only_removes_target(self):
        ws = MockWorkspace()
        mark_stale(ws, "story")
        clear_stale(ws, "character")
        # 其他标记应保留
        assert "outline" in ws.raw_state.stale_markers
        assert "writer" in ws.raw_state.stale_markers


# ── get_stale_info 测试 ──

class TestGetStaleInfo:
    def test_get_stale_info_returns_markers(self):
        ws = MockWorkspace()
        mark_stale(ws, "story")
        info = get_stale_info(ws)
        assert info == ws.raw_state.stale_markers

    def test_get_stale_info_empty_when_no_edits(self):
        ws = MockWorkspace()
        info = get_stale_info(ws)
        assert info == {}
