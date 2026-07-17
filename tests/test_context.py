"""
tests/test_context.py — DynamicContext 构建器单元测试

覆盖: update_dynamic_context / build_writing_context / persist_context
      _inject / _guess_arc_progress / LLM 提取 mock / 边界值
"""

import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from src.state.state_types import (
    WriteSyncState, DynamicContext, ProjectMetadata, StepName, ProjectStatus,
    StoryState, StoryCore, StoryArc,
    CharactersState, Character,
    WorldState, PowerSystem, Geography, Society, WorldHistory,
    ChapterOutlineState, ChapterOutline, DraftsState, ChapterDraft, DraftContent,
)
from src.agents.context import (
    update_dynamic_context, build_writing_context, persist_context,
    _inject, _guess_arc_progress, _get_recent_chapters,
    _scan_foreshadows, _gather_word_counts, _assess_pacing,
    _extract_character_changes, _regex_extract_changes,
    _check_foreshadow_resolved,
)


# ── 测试辅助工厂函数 ──

def _make_meta():
    return ProjectMetadata(
        project_id="test-ctx", name="test", platform="test",
        created_at="2026-01-01", updated_at="2026-01-01",
        current_step=StepName.TOPIC, status=ProjectStatus.DRAFTING,
    )

def _make_char(name="ZhangSan", role="主角"):
    return Character(
        name=name, role=role, identity="swordsman", personality="tough",
        goal="revenge", conflict="pursued", description="ordinary person",
    )

def _make_chapter(num, title="start", event="begin", foreshadows=None):
    return ChapterOutline(
        chapter_number=num, chapter_title=title, core_event=event,
        character_states=[], story_progression="",
        foreshadows=foreshadows or [], hook_at_end="",
        scenes=[], pov="", pace="", estimated_word_count="3000",
    )


class TestUpdateDynamicContext:

    def test_empty_state(self):
        ws = WriteSyncState(metadata=_make_meta(), drafts=DraftsState())
        ctx = update_dynamic_context({"data": ws, "messages": []}, 0)
        assert isinstance(ctx, DynamicContext)
        assert ctx.character_snapshot == ""
        assert ctx.updated_chapter == 0

    def test_chars_confirmed(self):
        ws = WriteSyncState(metadata=_make_meta(), drafts=DraftsState())
        ws.characters = CharactersState(
            characters=[_make_char()],
            confirmed_at="2026-01-01",
        )
        ctx = update_dynamic_context({"data": ws, "messages": []}, 0)
        assert "ZhangSan" in ctx.character_snapshot

    def test_world_confirmed(self):
        ws = WriteSyncState(metadata=_make_meta(), drafts=DraftsState())
        ws.world = WorldState(
            power_system=PowerSystem(system_name="qi", tiers=["lvl1", "lvl2"],
                                      cultivation_rules="absorb", power_limit="max"),
            geography=Geography(major_locations=[{"name": "city", "description": "town"}]),
            society=Society(factions=[{"name": "clan", "align": "good"}]),
            history=WorldHistory(),
            confirmed_at="2026-01-01",
        )
        ctx = update_dynamic_context({"data": ws, "messages": []}, 0)
        assert "qi" in ctx.world_changes

    def test_outline_confirmed(self):
        ws = WriteSyncState(metadata=_make_meta(), drafts=DraftsState())
        ws.chapter_outline = ChapterOutlineState(
            total_chapters=30, word_count_plan="3000",
            chapters=[
                _make_chapter(1, foreshadows=["foreshadowA"]),
                _make_chapter(2),
            ],
            confirmed_at="2026-01-01",
        )
        ctx = update_dynamic_context({"data": ws, "messages": []}, 1)
        assert len(ctx.unresolved_foreshadows) >= 1
        assert "30" in ctx.plot_progress


class TestBuildWritingContext:

    def test_null_context(self):
        result = build_writing_context({"data": WriteSyncState(metadata=_make_meta())})
        assert result == ""

    def test_full_context(self):
        ws = WriteSyncState(metadata=_make_meta())
        ws.dynamic_context = DynamicContext(
            character_snapshot="ZhangSan: tough, revenge",
            recent_chapters_summary="Ch1: start [hook: hookA]",
            unresolved_foreshadows=["Ch1: foreshadowA"],
            world_consistency_notes="test consistency",
            pacing_state="Ch1 wc 3200; normal",
        )
        result = build_writing_context({"data": ws})
        assert len(result) <= 800
        assert "ZhangSan" in result

    def test_truncation(self):
        ws = WriteSyncState(metadata=_make_meta())
        long_text = "x" * 500
        ws.dynamic_context = DynamicContext(
            character_snapshot=long_text,
            recent_chapters_summary=long_text[:200],
        )
        result = build_writing_context({"data": ws})
        assert len(result) <= 800


class TestInject:

    def test_with_context(self):
        result = _inject("original prompt", "context text")
        assert "context text" in result
        assert "original prompt" in result

    def test_empty_context(self):
        result = _inject("original prompt", "")
        assert result == "original prompt"


class TestGuessArcProgress:

    def test_zero(self):
        c = _make_char()
        assert _guess_arc_progress(c, 0, 30) == "0%"

    def test_protagonist(self):
        c = _make_char(role="主角")
        result = _guess_arc_progress(c, 5, 30)
        assert "16" in result or "17" in result

    def test_mentor(self):
        c = _make_char(name="Wang", role="导师")
        result = _guess_arc_progress(c, 5, 30)
        assert "23" in result or "24" in result or "22" in result


class TestPersist:

    def setup_method(self):
        self.test_dir = Path("projects/test-ctx-persist")
        self.test_dir.mkdir(parents=True, exist_ok=True)

    def teardown_method(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_roundtrip(self):
        from src.state.persistence import _safe_load_context
        ws = WriteSyncState(metadata=_make_meta())
        ws.metadata.project_id = "test-ctx-persist"
        ws.dynamic_context = DynamicContext(
            character_snapshot="ZhangSan: test",
            updated_chapter=3,
            chapter_word_counts={1: 3200, 2: 3050},
            foreshadow_deadline={7: "test"},
        )
        persist_context(ws)
        ctx_path = self.test_dir / "context.json"
        assert ctx_path.exists()
        loaded = _safe_load_context(ctx_path)
        assert loaded.character_snapshot == "ZhangSan: test"
        assert loaded.updated_chapter == 3
        assert 1 in loaded.chapter_word_counts


class TestExtractCharacterChanges:

    def test_timeout_fallback(self):
        with patch("src.utils.llm.create_llm_client") as mock_llm:
            mock_client = MagicMock()
            mock_client.complete_structured.side_effect = TimeoutError("timeout")
            mock_llm.return_value = mock_client
            chars = [_make_char("LiFan")]
            changes = _extract_character_changes("LiFan breakthrough", chars)
            assert isinstance(changes, list)

    def test_rate_limit_retry(self):
        with patch("src.utils.llm.create_llm_client") as mock_llm:
            from src.agents.response_models import CharacterChange, CharacterChangeList
            mock_client = MagicMock()
            mock_client.complete_structured.side_effect = [
                Exception("429 rate limit"),
                CharacterChangeList(changes=[CharacterChange(name="LiFan", change="breakthrough")]),
            ]
            mock_llm.return_value = mock_client
            chars = [_make_char("LiFan")]
            changes = _extract_character_changes("LiFan breaks through", chars)
            assert isinstance(changes, list)

    def test_empty_changes(self):
        with patch("src.utils.llm.create_llm_client") as mock_llm:
            from src.agents.response_models import CharacterChangeList
            mock_client = MagicMock()
            mock_client.complete_structured.return_value = CharacterChangeList(changes=[])
            mock_llm.return_value = mock_client
            chars = [_make_char("LiFan")]
            changes = _extract_character_changes("ordinary day", chars)
            assert isinstance(changes, list)

    def test_malformed_json(self):
        with patch("src.utils.llm.create_llm_client") as mock_llm:
            mock_client = MagicMock()
            mock_client.complete_structured.side_effect = ValueError("Invalid JSON")
            mock_llm.return_value = mock_client
            chars = [_make_char("LiFan")]
            changes = _extract_character_changes("LiFan joins clan", chars)
            assert isinstance(changes, list)

    def test_no_char_names_in_content(self):
        changes = _extract_character_changes("unrelated text", [_make_char("LiFan")])
        assert changes == []

    def test_regex_extract(self):
        chars = [_make_char("LiFan")]
        changes = _regex_extract_changes("LiFan breakthrough to lvl2, LiFan gains item", chars)
        assert isinstance(changes, list)


class TestBoundaryValues:

    def test_ch_out_of_range(self):
        ws = WriteSyncState(metadata=_make_meta(), drafts=DraftsState())
        ws.chapter_outline = ChapterOutlineState(total_chapters=30, chapters=[])
        ctx = update_dynamic_context({"data": ws, "messages": []}, 999)
        assert isinstance(ctx, DynamicContext)

    def test_content_none(self):
        ws = WriteSyncState(metadata=_make_meta(), drafts=DraftsState())
        ws.characters = CharactersState(characters=[_make_char()], confirmed_at="t")
        ws.chapter_outline = ChapterOutlineState(total_chapters=30, chapters=[_make_chapter(1)])
        ws.drafts = DraftsState()
        ws.drafts.chapters[1] = ChapterDraft(chapter_number=1, stage="draft",
                                              draft=DraftContent(content="test", agent="writer"))
        ctx = update_dynamic_context({"data": ws, "messages": []}, 1)
        assert isinstance(ctx, DynamicContext)

    def test_chapter_outline_none(self):
        ws = WriteSyncState(metadata=_make_meta(), drafts=DraftsState())
        ctx = update_dynamic_context({"data": ws, "messages": []}, 0)
        assert isinstance(ctx, DynamicContext)

    def test_cd_final_none(self):
        ws = WriteSyncState(metadata=_make_meta(), drafts=DraftsState())
        ws.characters = CharactersState(characters=[_make_char()], confirmed_at="t")
        ws.chapter_outline = ChapterOutlineState(total_chapters=30, chapters=[_make_chapter(1)])
        ws.drafts = DraftsState()
        ws.drafts.chapters[1] = ChapterDraft(chapter_number=1, stage="draft")
        ctx = update_dynamic_context({"data": ws, "messages": []}, 1)
        assert isinstance(ctx, DynamicContext)

    def test_chapters_empty(self):
        ws = WriteSyncState(metadata=_make_meta(), drafts=DraftsState())
        ws.chapter_outline = ChapterOutlineState(total_chapters=30, chapters=[_make_chapter(1)])
        ctx = update_dynamic_context({"data": ws, "messages": []}, 1)
        assert ctx.recent_chapters_summary == ""

    def test_persist_disk_full(self):
        ws = WriteSyncState(metadata=_make_meta())
        ws.metadata.project_id = "test-disk-full"
        ws.dynamic_context = DynamicContext(character_snapshot="test")
        with patch("builtins.open", side_effect=OSError("disk full")):
            persist_context(ws)

    def test_data_cap_foreshadows(self):
        ws = WriteSyncState(metadata=_make_meta(), drafts=DraftsState())
        ws.chapter_outline = ChapterOutlineState(
            total_chapters=35,
            chapters=[_make_chapter(i, foreshadows=[f"fs{i}"]) for i in range(1, 35)],
        )
        ctx = update_dynamic_context({"data": ws, "messages": []}, 0)
        assert len(ctx.unresolved_foreshadows) <= 30

    def test_data_cap_word_counts(self):
        ws = WriteSyncState(metadata=_make_meta(), drafts=DraftsState())
        ws.chapter_outline = ChapterOutlineState(
            total_chapters=60, written_chapters=list(range(1, 60)),
            chapters=[_make_chapter(i) for i in range(1, 60)],
        )
        for i in range(1, 60):
            ws.drafts.chapters[i] = ChapterDraft(chapter_number=i, stage="final",
                                                  final=DraftContent(content="text", agent="writer"), word_count=3000)
        ctx = update_dynamic_context({"data": ws, "messages": []}, 0)
        assert len(ctx.chapter_word_counts) <= 50


class TestRecentChapters:

    def test_single_chapter(self):
        ws = WriteSyncState(metadata=_make_meta())
        ws.chapter_outline = ChapterOutlineState(total_chapters=30, chapters=[_make_chapter(1)])
        result = _get_recent_chapters(ws, 1)
        assert len(result) == 1


class TestForeshadowFunctions:

    def test_scan_foreshadows(self):
        ws = WriteSyncState(metadata=_make_meta())
        ws.chapter_outline = ChapterOutlineState(total_chapters=5, chapters=[
            _make_chapter(1, foreshadows=["fsA", "fsB"]),
            _make_chapter(2, foreshadows=["fsC"]),
        ])
        result = _scan_foreshadows(ws, 2)
        assert len(result) == 3

    def test_check_resolved_true(self):
        assert _check_foreshadow_resolved(3, "secret revealed",
                                          "the secret was revealed 真相大白")

    def test_check_resolved_false(self):
        assert not _check_foreshadow_resolved(3, "truth", "LiFan kept training")


class TestPacing:

    def test_gather_word_counts(self):
        ws = WriteSyncState(metadata=_make_meta())
        ws.chapter_outline = ChapterOutlineState(
            total_chapters=5, written_chapters=[1, 2],
            chapters=[_make_chapter(i) for i in range(1, 6)],
        )
        ws.drafts = DraftsState()
        ws.drafts.chapters[1] = ChapterDraft(chapter_number=1, stage="final",
                                              final=DraftContent(content="text", agent="writer"), word_count=3200)
        ws.drafts.chapters[2] = ChapterDraft(chapter_number=2, stage="final",
                                              final=DraftContent(content="text", agent="writer"), word_count=2800)
        result = _gather_word_counts(ws)
        assert result[1] == 3200
        assert result[2] == 2800

    def test_assess_pacing(self):
        ws = WriteSyncState(metadata=_make_meta())
        ws.chapter_outline = ChapterOutlineState(
            total_chapters=5, written_chapters=[1],
            chapters=[_make_chapter(1)],
        )
        ws.drafts = DraftsState()
        ws.drafts.chapters[1] = ChapterDraft(chapter_number=1, stage="final",
                                              final=DraftContent(content="text", agent="writer"), word_count=3200)
        result = _assess_pacing(ws, 1)
        assert "3200" in result

    def test_assess_pacing_no_data(self):
        ws = WriteSyncState(metadata=_make_meta())
        ws.chapter_outline = ChapterOutlineState(total_chapters=30, chapters=[])
        result = _assess_pacing(ws, 0)
        assert "not started" in result.lower() or "0" in result
