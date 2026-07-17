"""
test_decision_chain.py — 决策链单元测试

测试范围：
- decide_next_action 的 3 个硬规则
- _normalize_agent 的容错映射
- _validate_decision 的 5 类阶段守卫
- _find_selected_topic 的选题匹配（含 key 修复验证）
- _parse_decision_response 的 JSON 解析
- done 校验门（修复后验证）
"""
import pytest
from unittest.mock import MagicMock, patch
from src.orchestrator.decision import (
    decide_next_action,
    _normalize_agent,
    _validate_decision,
    _parse_decision_response,
    generate_hook_matrix,
    auto_degrade_hook_matrix,
    auto_degrade_pleasure_curve,
    validate_hook_matrix,
    validate_pleasure_curve,
)
from src.orchestrator.models import OrchestratorDecision, Dashboard, Progress
from src.state.state_types import PlatformProfile, get_platform_profile

# ============================================================================
# Dashboard 工厂
# ============================================================================


def _dash(phase="new", completed=None, total_ch=0, written=0, proofread=0, confirmed=0):
    """快速构建 Dashboard"""
    return Dashboard(
        phase=phase,
        completed_agents=completed or [],
        pending_confirm="",
        last_user_feedback="",
        progress=Progress(
            total_chapters=total_ch,
            written=written,
            proofread=proofread,
            confirmed=confirmed,
            total_volumes=1,
            current_volume=1,
        ),
        updated_at="2026-01-01T00:00:00Z",
        platform="起点",
        golden_three_active=False,
        orchestrator_mode="planning",
        hook_landing_rate=0.0,
        pleasure_density=0.0,
        auto_degraded=False,
    )


# ============================================================================
# Hard Rule Tests
# ============================================================================


class TestHardRules:
    """前端硬规则 — 不依赖 LLM"""

    def test_new_project_forces_story(self):
        """新项目无产出 → 强制调用 story"""
        dash = _dash(phase="new")
        result = decide_next_action(dashboard=dash, history=[], feedbacks=[])
        assert result.action == "call_agent"
        assert result.agent == "story"

    def test_topic_selection_forces_story(self):
        """选题阶段 story 未确认 → 强制 story"""
        dash = _dash(phase="topic_selection")
        result = decide_next_action(dashboard=dash, history=[], feedbacks=[])
        assert result.action == "call_agent"
        assert result.agent == "story"

    def test_writing_chapters_zero_written_forces_writer(self):
        """writing_chapters + 0 written → 强制 writer"""
        dash = _dash(phase="writing_chapters", completed=["story", "character", "world", "outline"],
                     total_ch=20, written=0)
        result = decide_next_action(dashboard=dash, history=[], feedbacks=[])
        assert result.action == "call_agent"
        assert result.agent == "writer"

    def test_with_history_goes_to_llm(self):
        """有历史记录时走 LLM 路径（mock 返回 done）"""
        dash = _dash(phase="planning", completed=["story"],
                     total_ch=20, written=0)
        history = [{"step": 1, "action": "call_agent", "agent": "story", "reason": "test"}]

        mock_llm = MagicMock()
        # done 会被新校验门拦截（character/world/outline 缺失）
        mock_llm.complete.return_value = '{"action": "done", "reason": "test done"}'

        result = decide_next_action(dashboard=dash, history=history, feedbacks=[], llm=mock_llm)
        # 新校验门不应允许 done（缺少 character/world/outline）
        # LLM 重试耗尽后回退到 story
        assert result.action == "call_agent"
        assert result.agent == "story"
        assert "决策失败" in result.reason


# ============================================================================
# Agent 名称归一化
# ============================================================================


class TestNormalizeAgent:
    params = [
        ("story", "story"), ("Story", "story"), ("STORY", "story"),
        ("plot", "story"), ("plan", "story"), ("topic", "story"), ("创意", "story"),
        ("character", "character"), ("角色", "character"),
        ("world", "world"), ("世界", "world"), ("setting", "world"),
        ("outline", "outline"), ("chapter", "outline"), ("章", "outline"),
        ("writer", "writer"), ("draft", "writer"), ("写", "writer"), ("文笔", "writer"),
        ("proofreader", "proofreader"), ("proofread", "proofreader"), ("校对", "proofreader"), ("edit", "proofreader"),
        ("novel_review", "novel_review"), ("review", "novel_review"), ("审查", "novel_review"), ("check", "novel_review"),
        # outline 必须在 story 之前匹配（修复验证）
        ("outline_edit", "outline"),
        # 完全不认识 → 回退 story
        ("unknown_agent_xyz", "story"),
    ]

    @pytest.mark.parametrize("input_name,expected", params)
    def test_normalize(self, input_name, expected):
        assert _normalize_agent(input_name) == expected


# ============================================================================
# 决策校验守卫
# ============================================================================


class TestValidateDecision:

    def test_call_agent_valid(self):
        d = OrchestratorDecision(action="call_agent", agent="character", instruction="test", reason="ok")
        assert _validate_decision(d) is None
        assert d.agent == "character"  # 归一化后不变

    def test_invalid_action(self):
        d = OrchestratorDecision(action="skip", agent="story", instruction="", reason="")
        err = _validate_decision(d)
        assert "无效 action" in err

    def test_topic_selection_blocks_non_story(self):
        """选题阶段禁止非 story"""
        dash = _dash(phase="topic_selection")
        d = OrchestratorDecision(action="call_agent", agent="character", instruction="", reason="")
        err = _validate_decision(d, dash)
        assert "选题阶段只能调用 story" in err

    def test_world_requires_character(self):
        """角色未确认 → 禁止 world"""
        dash = _dash(phase="planning", completed=["story"])
        d = OrchestratorDecision(action="call_agent", agent="world", instruction="", reason="")
        err = _validate_decision(d, dash)
        assert "角色尚未确认" in err

    def test_outline_requires_world(self):
        """世界观未确认 → 禁止 outline"""
        dash = _dash(phase="planning", completed=["story", "character"])
        d = OrchestratorDecision(action="call_agent", agent="outline", instruction="", reason="")
        err = _validate_decision(d, dash)
        assert "世界观尚未确认" in err

    def test_no_chapters_blocks_writer(self):
        dash = _dash(phase="planning", completed=["story"], total_ch=0)
        d = OrchestratorDecision(action="call_agent", agent="writer", instruction="", reason="")
        err = _validate_decision(d, dash)
        assert err is not None
        assert "writer" in err

    def test_zero_written_blocks_proofreader(self):
        """无已写章节 → 禁止 proofreader"""
        dash = _dash(phase="writing_chapters", completed=["story", "character", "world", "outline"],
                     total_ch=20, written=0)
        d = OrchestratorDecision(action="call_agent", agent="proofreader", instruction="", reason="")
        err = _validate_decision(d, dash)
        assert "不能调用 proofreader" in err

    def test_valid_done_sequence_allows(self):
        """所有核心阶段确认 → done 允许"""
        dash = _dash(phase="writing_chapters",
                     completed=["story", "character", "world", "outline"],
                     total_ch=20, written=20, confirmed=20)
        d = OrchestratorDecision(action="done", agent="", instruction="", reason="全书完成")
        assert _validate_decision(d, dash) is None

    def test_done_rejected_missing_character(self):
        """修复验证：story 确认但缺少 character → done 被拒绝"""
        dash = _dash(phase="planning", completed=["story"])
        d = OrchestratorDecision(action="done", agent="", instruction="", reason="")
        err = _validate_decision(d, dash)
        assert "character" in err

    def test_done_rejected_only_story(self):
        """修复验证：仅 story 确认 → done 被拒绝（旧代码会放过）"""
        dash = _dash(phase="planning", completed=["story"],
                     total_ch=20)
        d = OrchestratorDecision(action="done", agent="", instruction="", reason="完成")
        err = _validate_decision(d, dash)
        assert err is not None
        assert "核心阶段未完成" in err


# ============================================================================
# JSON 解析
# ============================================================================


class TestParseDecision:
    def test_clean_json(self):
        result = _parse_decision_response(
            '{"action": "call_agent", "agent": "story", "instruction": "test", "reason": "ok"}'
        )
        assert result is not None
        assert result.action == "call_agent"
        assert result.agent == "story"

    def test_json_with_extra_fields(self):
        result = _parse_decision_response(
            '{"action": "call_agent", "agent": "world", "instruction": "do it", "reason": "why", "extra": 1}'
        )
        assert result is not None
        assert result.agent == "world"

    def test_json_in_markdown_block(self):
        result = _parse_decision_response(
            '```json\n{"action": "done", "reason": "all good"}\n```'
        )
        assert result is not None
        assert result.action == "done"

    def test_malformed_json_returns_none(self):
        result = _parse_decision_response("not json at all")
        assert result is None


# ============================================================================
# 钩子矩阵/爽点曲线算法
# ============================================================================


class TestHookMatrix:
    def test_generate_basic(self):
        hooks = generate_hook_matrix(10, is_volume_one=True,
                                     hook_strength_min=3, golden_three_boost=True)
        assert len(hooks) == 10
        # 黄金三章: Ch1-3 强度 >= 4
        for h in hooks[:3]:
            assert h.strength >= 4, f"黄金三章 Ch{h.chapter_index+1} 强度应为 4+，实为 {h.strength}"

    def test_generate_non_golden(self):
        hooks = generate_hook_matrix(10, is_volume_one=False,
                                     hook_strength_min=3, golden_three_boost=False)
        assert len(hooks) == 10

    def test_validate_passes(self):
        hooks = generate_hook_matrix(10, is_volume_one=True,
                                     hook_strength_min=3, golden_three_boost=True)
        errors = validate_hook_matrix(hooks, 10, True, 3)
        assert len(errors) == 0

    def test_auto_degrade(self):
        hooks = auto_degrade_hook_matrix(10, 3)
        assert len(hooks) == 10
        assert hooks[-1].strength == 5  # 卷末

    def test_pleasure_auto_degrade(self):
        curve = auto_degrade_pleasure_curve(10)
        assert len(curve) == 10


# ============================================================================
# _find_selected_topic 修复验证 (loop.py)
# ============================================================================


class TestFindSelectedTopic:
    """验证 _find_selected_topic() 的 feedback 键名修复"""

    def test_feedback_key_matches(self):
        """修复后：feedback["feedback"] 键应能匹配"""
        from src.orchestrator.loop import OrchestratorSession
        from src.orchestrator.workspace import Workspace
        from src.state.state_types import (
            WriteSyncState, ProjectMetadata, TopicState,
            TopicSuggestion, PlatformFit,
        )
        from src.state.persistence import PersistenceManager
        import tempfile, shutil, os

        tmp = tempfile.mkdtemp()
        try:
            pm = PersistenceManager(tmp)
            ws_state = pm.create_project("测试项目", "起点")

            # 构造 3 个选题
            topics = [
                TopicSuggestion(title="修真狂潮", genre="玄幻", sub_genre="修真",
                                core_selling_point="少年崛起",
                                target_audience="", competitive_analysis="",
                                platform_fit=PlatformFit(
                                    heat_level="热", difficulty="中等",
                                    reader_preference="高",
                                ), inspiration_source=""),
                TopicSuggestion(title="星际迷途", genre="科幻", sub_genre="星际",
                                core_selling_point="太空冒险",
                                target_audience="", competitive_analysis="",
                                platform_fit=PlatformFit(
                                    heat_level="热", difficulty="中等",
                                    reader_preference="高",
                                ), inspiration_source=""),
                TopicSuggestion(title="末日生存", genre="末世", sub_genre="生存",
                                core_selling_point="末世求生",
                                target_audience="", competitive_analysis="",
                                platform_fit=PlatformFit(
                                    heat_level="热", difficulty="中等",
                                    reader_preference="高",
                                ), inspiration_source=""),
            ]
            ws_state.topic = TopicState(
                user_original_idea="测试想法",
                suggestions=topics,
                selected=-1,
                confirmed_at=None,
            )

            project_dir = os.path.join(tmp, ws_state.metadata.project_id)
            os.makedirs(project_dir, exist_ok=True)
            workspace = Workspace(ws_state, project_dir, schema_version=3)

            # 模拟用户选择 "星际迷途"（存为 feedback 键）
            workspace.add_feedback("story", "选择: 星际迷途")

            session = OrchestratorSession(workspace)
            result = session._find_selected_topic()
            assert result is not None
            assert result.title == "星际迷途", f"应匹配 '星际迷途'，实际: {result.title}"
            assert ws_state.topic.selected == 1
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_feedback_key_fallback_to_text(self):
        """向后兼容：旧格式 feedbacks 用 'text' 键也能匹配"""
        from src.orchestrator.loop import OrchestratorSession
        from src.orchestrator.workspace import Workspace
        from src.state.state_types import (
            WriteSyncState, ProjectMetadata, TopicState,
            TopicSuggestion, PlatformFit,
        )
        from src.state.persistence import PersistenceManager
        import tempfile, shutil, os

        tmp = tempfile.mkdtemp()
        try:
            pm = PersistenceManager(tmp)
            ws_state = pm.create_project("测试项目", "起点")

            topics = [
                TopicSuggestion(title="修真狂潮", genre="玄幻", sub_genre="修真",
                                core_selling_point="少年崛起",
                                target_audience="", competitive_analysis="",
                                platform_fit=PlatformFit(heat_level="热", difficulty="中等",
                                                         reader_preference="高"),
                                inspiration_source=""),
            ]
            ws_state.topic = TopicState(
                user_original_idea="测试", suggestions=topics, selected=-1, confirmed_at=None,
            )
            project_dir = os.path.join(tmp, ws_state.metadata.project_id)
            os.makedirs(project_dir, exist_ok=True)
            workspace = Workspace(ws_state, project_dir, schema_version=3)

            # 模拟旧格式（text 键）
            workspace.feedbacks.append({"agent": "story", "text": "选择: 修真狂潮"})

            session = OrchestratorSession(workspace)
            result = session._find_selected_topic()
            assert result is not None
            assert result.title == "修真狂潮"
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_no_feedback_falls_back_to_first(self):
        """无匹配反馈 → 取第一条"""
        from src.orchestrator.loop import OrchestratorSession
        from src.orchestrator.workspace import Workspace
        from src.state.state_types import (
            WriteSyncState, ProjectMetadata, TopicState,
            TopicSuggestion, PlatformFit,
        )
        from src.state.persistence import PersistenceManager
        import tempfile, shutil, os

        tmp = tempfile.mkdtemp()
        try:
            pm = PersistenceManager(tmp)
            ws_state = pm.create_project("测试项目", "起点")

            topics = [
                TopicSuggestion(title="第一个", genre="玄幻", sub_genre="",
                                core_selling_point="t1",
                                target_audience="", competitive_analysis="",
                                platform_fit=PlatformFit(heat_level="热", difficulty="中等",
                                                         reader_preference="高"),
                                inspiration_source=""),
                TopicSuggestion(title="第二个", genre="科幻", sub_genre="",
                                core_selling_point="t2",
                                target_audience="", competitive_analysis="",
                                platform_fit=PlatformFit(heat_level="热", difficulty="中等",
                                                         reader_preference="高"),
                                inspiration_source=""),
            ]
            ws_state.topic = TopicState(
                user_original_idea="测试", suggestions=topics, selected=-1, confirmed_at=None,
            )
            project_dir = os.path.join(tmp, ws_state.metadata.project_id)
            os.makedirs(project_dir, exist_ok=True)
            workspace = Workspace(ws_state, project_dir, schema_version=3)

            session = OrchestratorSession(workspace)
            result = session._find_selected_topic()
            assert result is not None
            assert result.title == "第一个"
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
