"""
test_export.py — 导出功能测试

测试 export_to_markdown/export_to_txt 的输出内容.
"""
import os
from datetime import datetime, timezone
from src.state.state_types import (
    WriteSyncState, StoryState, StoryCore, StoryArc,
    CharactersState, Character, WorldState, PowerSystem,
    ChapterOutlineState, ChapterOutline, DraftsState, ChapterDraft, DraftContent,
    TopicState, TopicSuggestion, PlatformFit,
)
from src.state.persistence import PersistenceManager
from src.utils.export import export_to_markdown, export_to_txt


def _make_complete_state(name="测试导出项目") -> WriteSyncState:
    now = datetime.now(timezone.utc).isoformat()
    pm = PersistenceManager()
    ws_state = pm.create_project(name, "起点")

    ws_state.topic = TopicState(
        user_original_idea="末世觉醒",
        suggestions=[
            TopicSuggestion(title="末世觉醒", genre="末世", sub_genre="修真",
                            core_selling_point="少年觉醒操控金属的能力",
                            target_audience="", competitive_analysis="",
                            platform_fit=PlatformFit(heat_level="热", difficulty="中等", reader_preference="高"),
                            inspiration_source=""),
        ],
        selected=0, confirmed_at=None,
    )
    ws_state.story = StoryState(
        step1=StoryCore(one_sentence="一个少年在末世中崛起的故事", tag="末世"),
        step2=StoryArc(setup="末世降临", inciting="发现阴谋", rising="建立势力", climax_prep="面对BOSS", resolution="建立新秩序", theme="不放弃希望"),
        confirmed_at=now,
    )
    ws_state.characters = CharactersState(
        characters=[
            Character(name="林风", role="主角", personality="坚韧果敢", goal="保护重要的人",
                      conflict="面对同伴背叛", identity="觉醒者", background="孤儿院出身", description="黑色短发"),
            Character(name="苏瑶", role="女主", personality="温柔聪慧", goal="辅助林风",
                      conflict="家族立场矛盾", identity="研究员", background="科学世家", description="长发披肩"),
        ],
        confirmed_at=now,
    )
    ws_state.world = WorldState(
        power_system=PowerSystem(system_name="觉醒之力",
                                 tiers=["F级", "E级", "D级", "C级", "B级", "A级", "S级"],
                                 cultivation_rules="击杀变异生物吸收晶核升级",
                                 power_limit="S级可操控元素",
                                 special_abilities=["金属操控", "空间折叠"]),
        geography={"major_locations": []}, society={"factions": []},
        history={"key_events": []}, confirmed_at=now,
    )
    ws_state.chapter_outline = ChapterOutlineState(
        total_chapters=3,
        chapters=[
            ChapterOutline(chapter_number=1, chapter_title="末世降临", core_event="主角觉醒", character_states="", story_progression=""),
            ChapterOutline(chapter_number=2, chapter_title="初次战斗", core_event="首战告捷", character_states="", story_progression=""),
            ChapterOutline(chapter_number=3, chapter_title="基地危机", core_event="危机降临", character_states="", story_progression=""),
        ],
        written_chapters=[1, 2, 3], confirmed_at=now,
    )
    ch1 = ChapterDraft(chapter_number=1,
                       draft=DraftContent(content="林风正在教室里打瞌睡。窗外突然暗了下来。", agent="writer", timestamp=now),
                       final=DraftContent(content="林风正在教室里打瞌睡。窗外突然暗了，一声爆炸。", agent="proofreader", timestamp=now),
                       word_count=3000, stage="final", written_at=now, updated_at=now)
    ch2 = ChapterDraft(chapter_number=2,
                       draft=DraftContent(content="林风握紧手中的铁棍。", agent="writer", timestamp=now),
                       final=DraftContent(content="林风握紧手中的铁棍，冲了上去。", agent="proofreader", timestamp=now),
                       word_count=3500, stage="final", written_at=now, updated_at=now)
    ch3 = ChapterDraft(chapter_number=3,
                       draft=DraftContent(content="基地外出现了几个黑衣人。", agent="writer", timestamp=now),
                       final=DraftContent(content="基地外出现了几个黑衣人，胸口印着诡异符号。", agent="proofreader", timestamp=now),
                       word_count=4000, stage="final", written_at=now, updated_at=now)
    ws_state.drafts = DraftsState(chapters={1: ch1, 2: ch2, 3: ch3})
    return ws_state


class TestExport:
    def test_export_md_contains_keywords(self, tmp_path):
        """完整状态 → MD 导出含关键内容"""
        ws_state = _make_complete_state()
        output = os.path.join(str(tmp_path), "test.md")
        result_path = export_to_markdown(ws_state, output)
        content = open(result_path, encoding="utf-8").read()
        assert "林风" in content
        assert "苏瑶" in content
        assert "觉醒之力" in content
        assert "末世降临" in content
        assert "林风正在教室里打瞌睡" in content

    def test_export_empty_state_no_crash(self, tmp_path):
        """空项目导出不崩溃"""
        pm = PersistenceManager()
        ws_state = pm.create_project("空项目", "起点")
        output = os.path.join(str(tmp_path), "empty.md")
        result_path = export_to_markdown(ws_state, output)
        content = open(result_path, encoding="utf-8").read()
        assert isinstance(content, str)
        assert len(content) > 0

    def test_export_story_only(self, tmp_path):
        """仅有故事 → 导出包含故事"""
        pm = PersistenceManager()
        ws_state = pm.create_project("故事项目", "起点")
        now = datetime.now(timezone.utc).isoformat()
        ws_state.story = StoryState(
            step1=StoryCore(one_sentence="一个简单的故事", tag=""),
            step2=StoryArc(setup="", inciting="", rising="", climax_prep="", resolution="", theme=""),
            confirmed_at=now,
        )
        output = os.path.join(str(tmp_path), "story.md")
        result_path = export_to_markdown(ws_state, output)
        content = open(result_path, encoding="utf-8").read()
        assert "一个简单的故事" in content

    def test_export_missing_world_ok(self, tmp_path):
        """缺少世界观 → 导出不崩溃，角色仍存在"""
        ws_state = _make_complete_state()
        ws_state.world = None
        output = os.path.join(str(tmp_path), "no_world.md")
        result_path = export_to_markdown(ws_state, output)
        content = open(result_path, encoding="utf-8").read()
        assert "林风" in content

    def test_export_to_txt(self, tmp_path):
        """TXT 导出仅含正文"""
        ws_state = _make_complete_state()
        output = os.path.join(str(tmp_path), "test.txt")
        result_path = export_to_txt(ws_state, output)
        content = open(result_path, encoding="utf-8").read()
        assert "林风正在教室里打瞌睡" in content

    def test_export_no_drafts_ok(self, tmp_path):
        """无正文 → TXT 导出不崩溃"""
        pm = PersistenceManager()
        ws_state = pm.create_project("空", "起点")
        output = os.path.join(str(tmp_path), "empty.txt")
        result_path = export_to_txt(ws_state, output)
        content = open(result_path, encoding="utf-8").read()
        assert isinstance(content, str)
