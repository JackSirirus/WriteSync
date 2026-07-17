"""
test_context_e2e.py — E2E 回放测试：模拟写3章验证上下文逐章累积
"""
from unittest.mock import patch

import pytest
from src.state.state_types import (
    WriteSyncState, ProjectMetadata, StepName, ProjectStatus,
    DynamicContext, StoryState, StoryCore, StoryArc,
    CharactersState, Character,
    WorldState, PowerSystem, Geography, Society, WorldHistory,
    ChapterOutlineState, ChapterOutline, Foreshadow,
    DraftsState, ChapterDraft, DraftContent,
)
from src.agents.context import update_dynamic_context

# ── 工厂函数 ──

def _make_meta():
    return ProjectMetadata(
        project_id="e2e-test-ctx", name="novel-e2e", platform="web",
        created_at="2026-01-01", updated_at="2026-01-01",
        current_step=StepName.CHAPTER, status=ProjectStatus.WRITING,
    )


def _make_story():
    return StoryState(
        step1=StoryCore(
            one_sentence="An orphan discovers his Qi powers and defeats the demon lord.",
            tag="cultivation",
        ),
        step2=StoryArc(
            setup="In a world of cultivators, orphan ChenFan lives in a remote village.",
            inciting="He awakens a legendary power during a bandit attack.",
            rising="ChenFan enters the sect tournament seeking answers about his past.",
            climax_prep="The demon lord's influence spreads across the land.",
            resolution="ChenFan masters his power and saves the realm.",
            theme="Self-discovery through adversity",
            moral="True strength comes from within",
        ),
        expanded_paragraphs=[
            "ChenFan grew up in a small village at the foot of Azure Mountain. Orphaned as a child, he was raised by the village elder who taught him basic martial arts.",
            "After awakening his power, ChenFan was taken to the Azure Cloud Sect where he began formal cultivation training under Master Wu.",
            "The sect tournament revealed hidden enemies within the sect, forcing ChenFan to confront both external threats and his own inner demons.",
        ],
        confirmed_at="2026-01-15",
    )


def _make_characters():
    return CharactersState(
        characters=[
            Character(
                name="ChenFan",
                role="主角",
                identity="orphaned disciple",
                personality="determined, curious, impulsive",
                goal="master cultivation and uncover his past",
                conflict="fear of his own dark power",
                description="slim build, sharp eyes, always wears an ancient jade pendant",
                background="Grew up as an orphan in Misty Village. His parents disappeared during the Great Demon War.",
            ),
            Character(
                name="LinYue",
                role="女主",
                identity="senior disciple of Azure Cloud Sect",
                personality="calm, perceptive, graceful",
                goal="protect the sect from internal threats",
                conflict="duty versus personal feelings for ChenFan",
                description="elegant bearing, long black hair tied with a white ribbon, cold and distant demeanor",
                background="Daughter of the sect master. Trained since childhood to be the next generation leader.",
            ),
            Character(
                name="MasterWu",
                role="导师",
                identity="grand elder of Azure Cloud Sect",
                personality="wise, stern, secretive",
                goal="guide ChenFan without revealing too much too soon",
                conflict="past failure haunts his teaching approach",
                description="aged face with deep wrinkles, long white beard, carries a gnarled wooden staff",
                background="Once the strongest cultivator of his generation. Failed to stop the demon lord 500 years ago.",
            ),
        ],
        summary="ChenFan is the protagonist discovering his powers. LinYue is his senior and love interest. MasterWu is the wise mentor with a hidden past.",
        confirmed_at="2026-01-20",
    )


def _make_world():
    return WorldState(
        power_system=PowerSystem(
            system_name="Spiritual Qi",
            tiers=["Qi Condensation", "Foundation Building", "Core Formation", "Nascent Soul", "Immortal"],
            cultivation_rules="Cultivators absorb Qi from spirit veins. Each breakthrough requires both accumulation and enlightenment. Tribulation lightning strikes at major breakthroughs.",
            power_limit="Immortal Ascension is the theoretical peak, unachieved in the last ten thousand years.",
        ),
        geography=Geography(
            major_locations=[
                {"name": "Azure Cloud Sect", "description": "Mountain sect on the eastern range", "significance": "Main training ground and safe haven"},
                {"name": "Misty Village", "description": "ChenFan's hometown", "significance": "Origin of the protagonist"},
                {"name": "Forbidden Abyss", "description": "Cursed valley where demon energy gathers", "significance": "Final battlefield location"},
            ],
            political_division="Three great sects divide the cultivation world: Azure Cloud, Burning Lotus, and Icy Jade Palace",
            special_zones=["Forbidden Abyss", "Thunder Valley Tribulation Ground", "Ancient Spirit Vein"],
        ),
        society=Society(
            factions=[
                {"name": "Azure Cloud Sect", "description": "Righteous cultivation sect focused on balance", "align": "good"},
                {"name": "Shadow Pavilion", "description": "Secretive intelligence network", "align": "neutral"},
                {"name": "Demon Cult", "description": "Dark cultivators seeking to release the demon lord", "align": "evil"},
            ],
            social_hierarchy="Sect elders lead, followed by core disciples, inner disciples, outer disciples, and mortal servants",
            cultural_notes="Cultivation is the highest pursuit in society. Mortals revere and fear cultivators. Sects compete for spirit vein territories.",
        ),
        history=WorldHistory(
            key_events=["Great Demon War 500 years ago", "Founding of the Three Great Sects", "Disappearance of ChenFan's parents 15 years ago"],
            timeline_summary="500 years of uneasy peace since the demon lord was sealed. The seal has been weakening in recent decades.",
            past_conflicts=["Sect wars over spirit vein territories", "Purge of demon cultivators 200 years ago"],
        ),
        confirmed_at="2026-01-25",
    )


def _make_outline():
    chapter_titles = [
        "The Orphan", "First Spark", "Into the Sect", "The Tournament Begins",
        "Secret Adversary", "Master's Trial", "Awakening", "The Shadow Revealed",
        "Crisis at the Sect", "Journey North", "Ancient Ruins", "The Seal Fragment",
        "LinYue's Choice", "Demon Ambush", "Truth and Lies", "New Resolve",
        "Training Arc", "Inner Demon", "Alliance Forged", "Final Preparations",
        "March to the Abyss", "The Demon's Gate", "Battle for the Realm",
        "Sacrifice", "The Pendant's Secret", "MasterWu's Redemption",
        "Final Stand", "The Demon Lord", "Ascension", "New Dawn",
    ]
    chapters = []
    for i in range(1, 31):
        foreshadows = []
        if i == 1:
            foreshadows = [Foreshadow(content="The jade pendant glows faintly in the moonlight", planted_at=1, payoff_chapter=25, status="planted")]
        elif i == 5:
            foreshadows = [Foreshadow(content="A Shadow Pavilion spy watches from the crowd", planted_at=5, payoff_chapter=15, status="planted")]
        elif i == 10:
            foreshadows = [Foreshadow(content="Ancient seal on the Forbidden Abyss is cracking", planted_at=10, payoff_chapter=28, status="planted")]
        elif i == 20:
            foreshadows = [Foreshadow(content="MasterWu hides a crucial memory artifact", planted_at=20, payoff_chapter=26, status="planted")]
        elif i == 15:
            foreshadows = [Foreshadow(content="The traitor within the sect has not yet revealed themselves", planted_at=15, payoff_chapter=23, status="planted")]
        elif i == 25:
            foreshadows = [Foreshadow(content="The pendant contains the demon lord's sealed soul fragment", planted_at=25, payoff_chapter=28, status="planted")]

        chapters.append(ChapterOutline(
            chapter_number=i,
            chapter_title=chapter_titles[i - 1],
            core_event=f"Chapter {i}: {chapter_titles[i - 1]} unfolds",
            character_states=f"ChenFan progresses; supporting characters react to events",
            story_progression=f"The main plot advances toward the demon lord confrontation",
            estimated_word_count=3000,
            foreshadows=foreshadows,
            hook_at_end=f"Hook leading into chapter {i + 1}" if i < 30 else "The story reaches its climax",
            scenes=[],
            pov="ChenFan" if i % 2 == 1 else "LinYue",
            pace="medium",
        ))
    return ChapterOutlineState(
        total_chapters=30,
        chapters=chapters,
        written_chapters=[1, 2, 3],
        word_count_plan=90000,
        confirmed_at="2026-02-01",
    )


def _make_drafts():
    drafts = DraftsState()
    chapter_texts = [
        "The morning sun cast long shadows across Misty Village. ChenFan stood at the edge of the training ground, his wooden sword feeling heavier than usual. Elder Zhang had taught him this stance a hundred times, but today something felt different. A warmth spread from the pendant hanging around his neck, responding to an unseen force. In the distance, dust rose from the mountain path. Someone was coming.",
        "The bandits struck at noon. ChenFan fought not for glory but for survival. When a blade came too close, a burst of blue light exploded from his chest, throwing the attackers back like leaves in a storm. The villagers stared in awe. Master Wu, who had arrived with the bandits in pursuit, recognized the power. You carry the mark of the ancient lineage, he said. The Azure Cloud Sect will take you in.",
        "The Azure Cloud Sect was nothing like the village. Pagodas floated on clouds held by formations. Disciples in blue robes moved with grace that spoke of years of discipline. LinYue was the first to greet him. Her eyes held secrets he could not read. Follow me, she said. The Grand Elder is waiting. ChenFan gripped his pendant and stepped through the gates of his new life.",
    ]
    for i in range(1, 4):
        drafts.chapters[i] = ChapterDraft(
            chapter_number=i,
            stage="final",
            final=DraftContent(
                content=chapter_texts[i - 1],
                agent="writer",
                change_notes=[],
                timestamp=f"2026-02-0{i}T10:00:00",
            ),
            word_count=3200,
            written_at=f"2026-02-0{i}T10:00:00",
            updated_at=f"2026-02-0{i}T10:00:00",
        )
    return drafts


@pytest.mark.slow
class TestChapterContextAccumulation:
    """模拟3章终稿确认的全流程，验证 DynamicContext 逐章累积"""

    def _make_state(self):
        ws = WriteSyncState(metadata=_make_meta(), drafts=DraftsState())
        ws.story = _make_story()
        ws.characters = _make_characters()
        ws.world = _make_world()
        ws.chapter_outline = _make_outline()
        ws.drafts = _make_drafts()
        return ws

    def test_3_chapters_accumulate_context(self):
        ws = self._make_state()
        assert ws.dynamic_context is None

        patch_target = "src.utils.llm.create_llm_client"
        with patch(patch_target, side_effect=ImportError("no llm")):
            ctx1 = update_dynamic_context({"data": ws, "messages": []}, 1)
        ws.dynamic_context = ctx1
        assert len(ctx1.recent_chapters_summary.split("|")) >= 1

        with patch(patch_target, side_effect=ImportError("no llm")):
            ctx2 = update_dynamic_context({"data": ws, "messages": []}, 2)
        ws.dynamic_context = ctx2
        assert len(ctx2.recent_chapters_summary.split("|")) >= 2

        with patch(patch_target, side_effect=ImportError("no llm")):
            ctx3 = update_dynamic_context({"data": ws, "messages": []}, 3)
        ws.dynamic_context = ctx3
        assert len(ctx3.recent_chapters_summary.split("|")) == 3
        assert len(ctx3.chapter_word_counts) == 3
        assert "3/30章" in ctx3.plot_progress
