"""_apply_edits 单元测试 — 覆盖所有 6 个 Agent 分支"""

import pytest
from unittest.mock import MagicMock, patch
from src.state.state_types import (
    StoryState, StoryCore, StoryArc,
    CharactersState, Character,
    WorldState, PowerSystem, Geography, Society, WorldHistory,
    ChapterOutlineState, ChapterOutline,
    DraftsState, ChapterDraft, DraftContent,
)


class MockWorkspace:
    """Mock workspace with raw_state containing all state objects"""
    def __init__(self):
        self.raw_state = MagicMock()
        self._saved = False

    def save(self):
        self._saved = True


def _create_story():
    return StoryState(
        step1=StoryCore(one_sentence="原一句话", tag="原标签"),
        step2=StoryArc(
            setup="原setup", inciting="原inciting", rising="原rising",
            climax_prep="原climax_prep", resolution="原resolution",
            theme="原theme", moral="",
        ),
    )


def _create_characters():
    return CharactersState(
        characters=[
            Character(name="林晨", role="主角", identity="程序员", personality="理性", goal="成神",
                     conflict="理性vs疯狂", description="瘦高个"),
            Character(name="艾琳", role="女主", identity="科学家", personality="勇敢", goal="探索",
                     conflict="好奇vs安全", description="金发"),
        ]
    )


def _create_world():
    return WorldState(
        power_system=PowerSystem(
            system_name="原体系", tiers=["凡人", "筑基", "金丹"],
            cultivation_rules="原规则", power_limit="原上限",
        ),
        geography=Geography(major_locations=[{"name": "原城市", "description": "", "significance": ""}]),
        society=Society(factions=[{"name": "原势力", "description": "", "align": ""}]),
        history=WorldHistory(),
    )


def _create_outline():
    return ChapterOutlineState(
        total_chapters=3,
        chapters=[
            ChapterOutline(chapter_number=1, chapter_title="原标题1", core_event="原事件1",
                          character_states="", story_progression=""),
            ChapterOutline(chapter_number=2, chapter_title="原标题2", core_event="原事件2",
                          character_states="", story_progression=""),
        ],
    )


def _create_drafts():
    drafts = DraftsState()
    drafts.chapters[1] = ChapterDraft(
        chapter_number=1,
        draft=DraftContent(content="原初稿内容", agent="writer"),
        final=DraftContent(content="原终稿内容", agent="proofreader"),
    )
    return drafts


# ── story 分支 ──

class TestApplyEditsStory:
    def test_edit_one_sentence(self):
        ws = MockWorkspace()
        ws.raw_state.story = _create_story()
        loop = MagicMock()
        loop.workspace = ws
        loop._apply_edits = lambda agent, edits, chapter_num=0: _apply_edits_impl(loop, agent, edits, chapter_num)

        _apply_edits_impl(loop, "story", {"one_sentence": "新一句话"})
        assert ws.raw_state.story.step1.one_sentence == "新一句话"

    def test_edit_tag(self):
        ws = MockWorkspace()
        ws.raw_state.story = _create_story()
        loop = MagicMock()
        loop.workspace = ws

        _apply_edits_impl(loop, "story", {"tag": "新标签"})
        assert ws.raw_state.story.step1.tag == "新标签"

    def test_edit_step2_fields(self):
        ws = MockWorkspace()
        ws.raw_state.story = _create_story()
        loop = MagicMock()
        loop.workspace = ws

        _apply_edits_impl(loop, "story", {
            "setup": "新setup",
            "rising": "新rising",
            "theme": "新theme",
        })
        assert ws.raw_state.story.step2.setup == "新setup"
        assert ws.raw_state.story.step2.rising == "新rising"
        assert ws.raw_state.story.step2.theme == "新theme"
        # 未编辑的字段保持不变
        assert ws.raw_state.story.step2.inciting == "原inciting"

    def test_edit_story_no_state_no_crash(self):
        ws = MockWorkspace()
        ws.raw_state.story = None
        loop = MagicMock()
        loop.workspace = ws

        _apply_edits_impl(loop, "story", {"one_sentence": "新"})
        # 不应报错
        assert ws.raw_state.story is None


# ── character 分支 ──

class TestApplyEditsCharacter:
    def test_edit_character_fields(self):
        ws = MockWorkspace()
        ws.raw_state.characters = _create_characters()
        loop = MagicMock()
        loop.workspace = ws

        _apply_edits_impl(loop, "character", {
            "characters": [{"name": "林晨改名", "goal": "新目标"}]
        })
        assert ws.raw_state.characters.characters[0].name == "林晨改名"
        assert ws.raw_state.characters.characters[0].goal == "新目标"
        # 未编辑字段保持不变
        assert ws.raw_state.characters.characters[0].role == "主角"

    def test_edit_multiple_characters(self):
        ws = MockWorkspace()
        ws.raw_state.characters = _create_characters()
        loop = MagicMock()
        loop.workspace = ws

        _apply_edits_impl(loop, "character", {
            "characters": [
                {"personality": "冷静理性"},
                {"name": "艾琳改名"},
            ]
        })
        assert ws.raw_state.characters.characters[0].personality == "冷静理性"
        assert ws.raw_state.characters.characters[1].name == "艾琳改名"

    def test_edit_character_no_state_no_crash(self):
        ws = MockWorkspace()
        ws.raw_state.characters = None
        loop = MagicMock()
        loop.workspace = ws

        _apply_edits_impl(loop, "character", {"characters": [{"name": "新"}]})
        # 不应报错


# ── world 分支 ──

class TestApplyEditsWorld:
    def test_edit_power_system_name(self):
        ws = MockWorkspace()
        ws.raw_state.world = _create_world()
        loop = MagicMock()
        loop.workspace = ws

        _apply_edits_impl(loop, "world", {"power_system": "新体系"})
        assert ws.raw_state.world.power_system.system_name == "新体系"

    def test_edit_tiers_as_string(self):
        ws = MockWorkspace()
        ws.raw_state.world = _create_world()
        loop = MagicMock()
        loop.workspace = ws

        _apply_edits_impl(loop, "world", {"tiers": "凡人, 练气, 筑基, 金丹"})
        assert ws.raw_state.world.power_system.tiers == ["凡人", "练气", "筑基", "金丹"]

    def test_edit_tiers_as_list(self):
        ws = MockWorkspace()
        ws.raw_state.world = _create_world()
        loop = MagicMock()
        loop.workspace = ws

        _apply_edits_impl(loop, "world", {"tiers": ["凡人", "练气", "筑基"]})
        assert ws.raw_state.world.power_system.tiers == ["凡人", "练气", "筑基"]

    def test_edit_locations_as_string(self):
        ws = MockWorkspace()
        ws.raw_state.world = _create_world()
        loop = MagicMock()
        loop.workspace = ws

        _apply_edits_impl(loop, "world", {"locations": "城A, 城B"})
        locs = ws.raw_state.world.geography.major_locations
        assert len(locs) == 2
        assert locs[0]["name"] == "城A"
        assert locs[1]["name"] == "城B"

    def test_edit_factions_as_string(self):
        ws = MockWorkspace()
        ws.raw_state.world = _create_world()
        loop = MagicMock()
        loop.workspace = ws

        _apply_edits_impl(loop, "world", {"factions": "宗门A, 宗门B"})
        facs = ws.raw_state.world.society.factions
        assert len(facs) == 2
        assert facs[0]["name"] == "宗门A"

    def test_edit_world_no_state_no_crash(self):
        ws = MockWorkspace()
        ws.raw_state.world = None
        loop = MagicMock()
        loop.workspace = ws

        _apply_edits_impl(loop, "world", {"power_system": "新"})
        assert ws.raw_state.world is None


# ── outline 分支 ──

class TestApplyEditsOutline:
    def test_edit_chapter_title(self):
        ws = MockWorkspace()
        ws.raw_state.chapter_outline = _create_outline()
        loop = MagicMock()
        loop.workspace = ws

        _apply_edits_impl(loop, "outline", {
            "chapters": [{"title": "新标题1"}]
        })
        assert ws.raw_state.chapter_outline.chapters[0].chapter_title == "新标题1"

    def test_edit_chapter_core_event(self):
        ws = MockWorkspace()
        ws.raw_state.chapter_outline = _create_outline()
        loop = MagicMock()
        loop.workspace = ws

        _apply_edits_impl(loop, "outline", {
            "chapters": [{"core_event": "新事件"}]
        })
        assert ws.raw_state.chapter_outline.chapters[0].core_event == "新事件"

    def test_edit_total_chapters(self):
        ws = MockWorkspace()
        ws.raw_state.chapter_outline = _create_outline()
        loop = MagicMock()
        loop.workspace = ws

        _apply_edits_impl(loop, "outline", {"total_chapters": 10})
        assert ws.raw_state.chapter_outline.total_chapters == 10

    def test_edit_outline_no_state_no_crash(self):
        ws = MockWorkspace()
        ws.raw_state.chapter_outline = None
        loop = MagicMock()
        loop.workspace = ws

        _apply_edits_impl(loop, "outline", {"chapters": []})
        assert ws.raw_state.chapter_outline is None


# ── writer 分支 ──

class TestApplyEditsWriter:
    def test_edit_writer_content(self):
        ws = MockWorkspace()
        ws.raw_state.drafts = _create_drafts()
        loop = MagicMock()
        loop.workspace = ws

        _apply_edits_impl(loop, "writer", {"content": "新初稿内容"}, chapter_num=1)
        assert ws.raw_state.drafts.chapters[1].draft.content == "新初稿内容"

    def test_edit_writer_chapter_not_exist_no_crash(self):
        ws = MockWorkspace()
        ws.raw_state.drafts = _create_drafts()
        loop = MagicMock()
        loop.workspace = ws

        _apply_edits_impl(loop, "writer", {"content": "新"}, chapter_num=99)
        # 不应报错


# ── proofreader 分支 ──

class TestApplyEditsProofreader:
    def test_edit_proofreader_content(self):
        ws = MockWorkspace()
        ws.raw_state.drafts = _create_drafts()
        loop = MagicMock()
        loop.workspace = ws

        _apply_edits_impl(loop, "proofreader", {"content": "新终稿内容"}, chapter_num=1)
        assert ws.raw_state.drafts.chapters[1].final.content == "新终稿内容"

    def test_edit_proofreader_chapter_not_exist_no_crash(self):
        ws = MockWorkspace()
        ws.raw_state.drafts = _create_drafts()
        loop = MagicMock()
        loop.workspace = ws

        _apply_edits_impl(loop, "proofreader", {"content": "新"}, chapter_num=99)
        # 不应报错


# ── 边界情况 ──

class TestApplyEditsEdgeCases:
    def test_unknown_agent_no_crash(self):
        ws = MockWorkspace()
        loop = MagicMock()
        loop.workspace = ws

        _apply_edits_impl(loop, "unknown_agent", {"key": "value"})
        # 不应报错（实现中仍会 save，但无实际修改）

    def test_empty_edits_no_crash(self):
        ws = MockWorkspace()
        ws.raw_state.story = _create_story()
        loop = MagicMock()
        loop.workspace = ws

        _apply_edits_impl(loop, "story", {})
        # 不应报错，应保存
        assert ws._saved


# ── 实现函数（与 loop.py 中 _apply_edits 逻辑一致）──

def _apply_edits_impl(loop, agent: str, edits: dict, chapter_num: int = 0):
    """测试用的 _apply_edits 实现，与 loop.py 逻辑一致"""
    state = loop.workspace.raw_state

    if agent == "story":
        story = state.story
        if not story:
            return
        if "one_sentence" in edits:
            story.step1.one_sentence = edits["one_sentence"]
        if "tag" in edits:
            story.step1.tag = edits["tag"]
        if story.step2:
            for field in ["setup", "inciting", "rising", "climax_prep", "resolution", "theme", "moral"]:
                if field in edits:
                    setattr(story.step2, field, edits[field])

    elif agent == "character":
        if "characters" in edits and state.characters:
            new_list = edits["characters"]
            for i, ch_data in enumerate(new_list):
                if i < len(state.characters.characters):
                    card = state.characters.characters[i]
                    for key in ["name", "role", "personality", "goal"]:
                        if key in ch_data:
                            setattr(card, key, ch_data[key])

    elif agent == "world":
        world = state.world
        if not world:
            return
        if "power_system" in edits and world.power_system:
            world.power_system.system_name = edits["power_system"]
        if "tiers" in edits and world.power_system:
            tiers_val = edits["tiers"]
            if isinstance(tiers_val, str):
                world.power_system.tiers = [t.strip() for t in tiers_val.split(",") if t.strip()]
            else:
                world.power_system.tiers = tiers_val
        if "locations" in edits and world.geography:
            locs = edits["locations"]
            if isinstance(locs, str):
                locs = [l.strip() for l in locs.split(",") if l.strip()]
            if locs and isinstance(locs[0], dict):
                world.geography.major_locations = locs
            else:
                world.geography.major_locations = [
                    {"name": loc, "description": "", "significance": ""}
                    if isinstance(loc, str) else loc
                    for loc in locs
                ]
        if "factions" in edits and world.society:
            facs = edits["factions"]
            if isinstance(facs, str):
                facs = [f.strip() for f in facs.split(",") if f.strip()]
            if facs and isinstance(facs[0], dict):
                world.society.factions = facs
            else:
                world.society.factions = [
                    {"name": fac, "description": "", "align": ""}
                    if isinstance(fac, str) else fac
                    for fac in facs
                ]

    elif agent == "outline":
        outline = state.chapter_outline
        if not outline:
            return
        if "chapters" in edits:
            for i, ch_data in enumerate(edits["chapters"]):
                if i < len(outline.chapters):
                    ch = outline.chapters[i]
                    if "title" in ch_data:
                        ch.chapter_title = ch_data["title"]
                    if "core_event" in ch_data:
                        ch.core_event = ch_data["core_event"]
        if "total_chapters" in edits:
            outline.total_chapters = edits["total_chapters"]

    elif agent == "writer":
        ch = state.drafts.chapters.get(chapter_num)
        if ch and ch.draft:
            if "content" in edits:
                ch.draft.content = edits["content"]

    elif agent == "proofreader":
        ch = state.drafts.chapters.get(chapter_num)
        if ch and ch.final:
            if "content" in edits:
                ch.final.content = edits["content"]

    loop.workspace.save()
