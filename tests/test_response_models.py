"""
测试：Pydantic response models 序列化/反序列化
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ['LANGGRAPH_STRICT_MSGPACK'] = 'false'

from src.agents.response_models import (
    TopicList, TopicSuggestion, PlatformFit,
    TopicCheckReport, TopicEvaluation,
    StorySummary, StoryCore, StoryArc,
    CharacterList, CharacterCard, CharacterRelation, CharacterArc,
    WorldSetting, PowerSystem, PowerTier, Geography, MajorLocation,
    Society, Faction, WorldHistory,
    ChapterOutlineList, ChapterOutline, ActOutline, SceneBeat, Foreshadow,
    ChapterDraftContent, DraftReviewNotes, ProofreadReport,
)


def test_topic_list():
    data = TopicList(suggestions=[
        TopicSuggestion(
            title="修仙逆袭", genre="仙侠", sub_genre="修仙升级",
            core_selling_point="凡人逆袭成仙",
            target_audience="男18-35",
            competitive_analysis="修仙题材竞争激烈",
            platform_fit=PlatformFit(heat_level="热门", difficulty="红海", reader_preference="高"),
            estimated_risk="题材老套",
        ),
    ])
    d = data.model_dump()
    assert len(d["suggestions"]) == 1
    assert d["suggestions"][0]["title"] == "修仙逆袭"
    print("  PASS: test_topic_list")


def test_story_summary():
    data = StorySummary(
        step1=StoryCore(one_sentence="少年逆天改命", tag="热血"),
        step2=StoryArc(
            setup="平凡少年", inciting="获得传承",
            rising="遭遇强敌", climax_prep="决战前夕",
            resolution="终成正果", theme="不屈",
        ),
    )
    d = data.model_dump()
    assert d["step1"]["one_sentence"] == "少年逆天改命"
    assert d["step2"]["theme"] == "不屈"
    print("  PASS: test_story_summary")


def test_character_list():
    data = CharacterList(
        characters=[
            CharacterCard(
                name="林北", role="主角", identity="山村少年",
                personality="坚韧、善良、执着",
                goal="成为最强", conflict="力量 vs 心魔",
                description="清秀少年",
                arc=CharacterArc(start_state="弱小", end_state="强大", transformation_event="遭遇背叛"),
                relationships=[CharacterRelation(target_name="苏瑶", relation_type="挚友", description="青梅竹马")],
            ),
        ],
        summary="一个主角",
    )
    assert len(data.characters) == 1
    assert data.characters[0].arc is not None
    assert data.characters[0].arc.start_state == "弱小"
    print("  PASS: test_character_list")


def test_world_setting():
    data = WorldSetting(
        power_system=PowerSystem(
            system_name="灵气体系",
            tiers=[PowerTier(name="炼气", description="入门")],
            cultivation_rules="吸收灵气",
            power_limit="大乘",
        ),
        geography=Geography(major_locations=[MajorLocation(name="青云山", description="仙门", significance="主角起点")]),
        society=Society(factions=[Faction(name="青云门", description="正派", alignment="正义")]),
        history=WorldHistory(key_events=["天魔大战"], timeline_summary="万年修仙史"),
    )
    d = data.model_dump()
    assert d["power_system"]["system_name"] == "灵气体系"
    assert len(d["society"]["factions"]) == 1
    print("  PASS: test_world_setting")


def test_chapter_outline():
    data = ChapterOutlineList(
        total_chapters=20,
        chapters=[
            ChapterOutline(
                chapter_number=1, chapter_title="初入仙门",
                core_event="入门测试", character_states="懵懂",
                story_progression="世界观展开",
                scenes=[SceneBeat(scene_id="ch01_sc01", location="山门", purpose="入门", conflict="测试")],
                hook_at_end="神秘声音响起",
            ),
        ],
        acts=[ActOutline(act_number=1, summary="第一幕", key_events=["入门"])],
    )
    assert data.total_chapters == 20
    assert data.chapters[0].scenes[0].scene_id == "ch01_sc01"
    assert data.acts[0].act_number == 1
    print("  PASS: test_chapter_outline")


def test_writing_models():
    draft = ChapterDraftContent(content="正文内容", word_count=100)
    assert draft.content == "正文内容"

    review = DraftReviewNotes(overall="不错", issues=["太短"], suggestions=["加长"], passed=True)
    assert review.passed

    proof = ProofreadReport(typos=["的得地"], grammar_issues=[], punctuation_issues=[], format_issues=[], corrected_version="修正版")
    assert proof.corrected_version == "修正版"
    print("  PASS: test_writing_models")


if __name__ == "__main__":
    print("Testing response models...")
    test_topic_list()
    test_story_summary()
    test_character_list()
    test_world_setting()
    test_chapter_outline()
    test_writing_models()
    print("\nAll tests PASSED")
