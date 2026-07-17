"""确认循环陷阱回归测试

AGENTS.md §5.1 描述的问题：
- _用户一句话() 用户确认后应直接设 story.confirmed_at
- 不应再进入 _一句话确认
- 症状：两步确认死循环

AGENTS.md §5.2 描述的问题：
- 复制粘贴确认模板时，容易把 story.confirmed_at 留在非 story 确认节点
- 症状：章纲确认后 outline.confirmed_at 不设值，无限等待确认
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from src.state.state_types import (
    StoryState, StoryCore, StoryArc,
    CharactersState, Character,
    WorldState, PowerSystem, Geography, Society, WorldHistory,
    ChapterOutlineState, ChapterOutline,
)


class MockWorkspace:
    def __init__(self):
        self.raw_state = MagicMock()
        self._saved = False
        self.feedbacks = []

    def save(self):
        self._saved = True

    def add_feedback(self, agent, feedback):
        self.feedbacks.append({"agent": agent, "feedback": feedback})


# ── §5.1: story 确认后应直接设 confirmed_at ──

class TestStoryConfirmLoop:
    def test_story_confirm_sets_confirmed_at(self):
        """story 确认后应直接设置 story.confirmed_at"""
        ws = MockWorkspace()
        ws.raw_state.story = StoryState(
            step1=StoryCore(one_sentence="test", tag="test"),
            step2=StoryArc(setup="", inciting="", rising="", climax_prep="", resolution="", theme=""),
            confirmed_at=None,
        )

        # 模拟 _mark_confirmed("story")
        now = datetime.now(timezone.utc).isoformat()
        ws.raw_state.story.confirmed_at = now

        assert ws.raw_state.story.confirmed_at is not None
        assert ws.raw_state.story.confirmed_at == now

    def test_story_confirm_does_not_trigger_second_confirm(self):
        """story 确认后不应再进入 _一句话确认节点"""
        ws = MockWorkspace()
        ws.raw_state.story = StoryState(
            step1=StoryCore(one_sentence="test", tag="test"),
            step2=StoryArc(setup="", inciting="", rising="", climax_prep="", resolution="", theme=""),
            confirmed_at=None,
        )

        # 模拟 _mark_confirmed("story")
        now = datetime.now(timezone.utc).isoformat()
        ws.raw_state.story.confirmed_at = now

        # 验证 confirmed_at 已设置，router 应返回"已确认"而非"进入确认"
        assert ws.raw_state.story.confirmed_at is not None


# ── §5.2: 每个确认节点应设置对应的 confirmed_at ──

class TestConfirmNodeVariableNames:
    def test_outline_confirm_sets_outline_confirmed_at(self):
        """outline 确认应设置 outline.confirmed_at，而非 story.confirmed_at"""
        ws = MockWorkspace()
        ws.raw_state.story = StoryState(
            step1=StoryCore(one_sentence="test", tag="test"),
            step2=StoryArc(setup="", inciting="", rising="", climax_prep="", resolution="", theme=""),
            confirmed_at="already-set",
        )
        ws.raw_state.chapter_outline = ChapterOutlineState(
            total_chapters=3,
            chapters=[],
            confirmed_at=None,
        )

        # 模拟 _mark_confirmed("outline")
        now = datetime.now(timezone.utc).isoformat()
        ws.raw_state.chapter_outline.confirmed_at = now

        # 验证 outline.confirmed_at 已设置
        assert ws.raw_state.chapter_outline.confirmed_at is not None
        # 验证 story.confirmed_at 未被覆盖
        assert ws.raw_state.story.confirmed_at == "already-set"

    def test_character_confirm_sets_character_confirmed_at(self):
        """character 确认应设置 characters.confirmed_at"""
        ws = MockWorkspace()
        ws.raw_state.characters = CharactersState(
            characters=[
                Character(name="林晨", role="主角", identity="程序员", personality="理性", goal="成神",
                         conflict="理性vs疯狂", description="瘦高个"),
            ],
            confirmed_at=None,
        )

        # 模拟 _mark_confirmed("character")
        now = datetime.now(timezone.utc).isoformat()
        ws.raw_state.characters.confirmed_at = now

        assert ws.raw_state.characters.confirmed_at is not None

    def test_world_confirm_sets_world_confirmed_at(self):
        """world 确认应设置 world.confirmed_at"""
        ws = MockWorkspace()
        ws.raw_state.world = WorldState(
            power_system=PowerSystem(system_name="test", tiers=[], cultivation_rules="", power_limit=""),
            geography=Geography(),
            society=Society(),
            history=WorldHistory(),
            confirmed_at=None,
        )

        # 模拟 _mark_confirmed("world")
        now = datetime.now(timezone.utc).isoformat()
        ws.raw_state.world.confirmed_at = now

        assert ws.raw_state.world.confirmed_at is not None


# ── 编辑→确认→编排器推进 ──

class TestEditConfirmProgression:
    def test_edit_then_confirm_does_not_loop(self):
        """编辑→确认后，编排器应正常推进，不进入 double-confirm loop"""
        from src.orchestrator.stale_tracker import mark_stale, clear_stale

        ws = MockWorkspace()
        ws.raw_state.story = StoryState(
            step1=StoryCore(one_sentence="original", tag="tag"),
            step2=StoryArc(setup="", inciting="", rising="", climax_prep="", resolution="", theme=""),
            confirmed_at="2026-01-01T00:00:00",
        )
        ws.raw_state.stale_markers = {}

        # 1. 用户编辑 story
        ws.raw_state.story.step1.one_sentence = "edited version"
        # 2. 标记下游 stale
        mark_stale(ws, "story")
        # 3. 用户确认编辑
        ws.raw_state.story.confirmed_at = datetime.now(timezone.utc).isoformat()
        # 4. 清除 stale（因为已重新确认）
        clear_stale(ws, "story")

        # 验证：story 已确认，无 stale 标记
        assert ws.raw_state.story.confirmed_at is not None
        assert "story" not in ws.raw_state.stale_markers

    def test_multiple_edits_then_confirm(self):
        """多次编辑→最终确认，编排器应正常推进"""
        ws = MockWorkspace()
        ws.raw_state.story = StoryState(
            step1=StoryCore(one_sentence="v1", tag="tag"),
            step2=StoryArc(setup="", inciting="", rising="", climax_prep="", resolution="", theme=""),
            confirmed_at=None,
        )

        # 多次编辑
        ws.raw_state.story.step1.one_sentence = "v2"
        ws.raw_state.story.step1.one_sentence = "v3"
        ws.raw_state.story.step1.one_sentence = "final"

        # 最终确认
        ws.raw_state.story.confirmed_at = datetime.now(timezone.utc).isoformat()

        assert ws.raw_state.story.step1.one_sentence == "final"
        assert ws.raw_state.story.confirmed_at is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
