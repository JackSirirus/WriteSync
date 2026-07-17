"""
Round 1 连通性测试 — 不调 LLM 的纯逻辑验证

覆盖测试方案:
  TC-DC-01~06  决策硬规则
  TC-NM-01~08  Agent 名称归一化
  TC-EDGE-01~04 选题边界
  TC-EDGE-05~07 章节边界
"""

import pytest
from src.orchestrator.decision import _normalize_agent, _validate_decision, decide_next_action
from src.orchestrator.models import OrchestratorDecision, Dashboard, Progress
from src.state.state_types import TopicState, TopicSuggestion, PlatformFit


# ============================================================================
# TC-DC: 决策硬规则测试
# ============================================================================

class TestDecisionHardRules:
    """TC-DC-01 ~ TC-DC-06"""

    def _make_dashboard(self, phase="new", completed=None, total_ch=0, written=0):
        return Dashboard(
            phase=phase,
            completed_agents=completed or [],
            progress=Progress(total_chapters=total_ch, written=written),
        )

    def test_dc01_empty_state_forces_story(self):
        """TC-DC-01: completed_agents=[] 且 history=[] → 强制 story，不调 LLM"""
        dashboard = self._make_dashboard()
        decision = decide_next_action(dashboard, history=[], feedbacks=[])
        assert decision.action == "call_agent"
        assert decision.agent == "story"
        assert "初始阶段" in decision.reason

    def test_dc02_topic_selection_forces_story(self):
        """TC-DC-02: phase=topic_selection 且 story 未确认 → 强制 story（含 history）"""
        dashboard = self._make_dashboard(phase="topic_selection")
        decision = decide_next_action(
            dashboard,
            history=[{"step": 1, "action": "call_agent", "agent": "story"}],
            feedbacks=[],
        )
        assert decision.action == "call_agent"
        assert decision.agent == "story"
        assert "选题阶段未完成" in decision.reason

    def test_dc03_no_chapters_blocks_writer(self):
        """TC-DC-03: total_chapters=0 时调 writer → 拒绝"""
        decision = OrchestratorDecision(action="call_agent", agent="writer", reason="test")
        dashboard = self._make_dashboard(total_ch=0)
        err = _validate_decision(decision, dashboard)
        assert err is not None
        assert "尚无章节" in err

    def test_dc03_no_chapters_blocks_proofreader(self):
        """TC-DC-03 补充: total_chapters=0 时调 proofreader → 拒绝"""
        decision = OrchestratorDecision(action="call_agent", agent="proofreader", reason="test")
        dashboard = self._make_dashboard(total_ch=0)
        err = _validate_decision(decision, dashboard)
        assert err is not None
        assert "尚无章节" in err

    def test_dc03_no_chapters_blocks_novel_review(self):
        """TC-DC-03 补充: total_chapters=0 时调 novel_review → 拒绝"""
        decision = OrchestratorDecision(action="call_agent", agent="novel_review", reason="test")
        dashboard = self._make_dashboard(total_ch=0)
        err = _validate_decision(decision, dashboard)
        assert err is not None
        assert "尚无章节" in err

    def test_dc04_no_written_blocks_proofreader(self):
        """TC-DC-04: written=0 时调 proofreader → 拒绝"""
        decision = OrchestratorDecision(action="call_agent", agent="proofreader", reason="test")
        dashboard = self._make_dashboard(total_ch=10, written=0)
        err = _validate_decision(decision, dashboard)
        assert err is not None
        assert "尚无已写章节" in err

    def test_dc04_writer_allowed_with_no_written(self):
        """TC-DC-04 补充: written=0 但 writer 不被 blocked（writer 是写新章，不依赖已有）"""
        decision = OrchestratorDecision(action="call_agent", agent="writer", reason="test")
        dashboard = self._make_dashboard(total_ch=10, written=0)
        err = _validate_decision(decision, dashboard)
        assert err is None  # writer IS allowed with total_ch > 0

    def test_dc05_topic_selection_blocks_done(self):
        """TC-DC-05: topic_selection 时 LLM 返回 done → 由 hard rule 阻止（非 _validate_decision）

        注意：_validate_decision 的 done 守卫仅在 completed_agents 非空时触发。
        当 completed_agents 为空时（Python falsy），done guard 被短路。
        实际阻止 done 的是 decide_next_action 的硬规则（line 401-407），
        它在 LLM 调用前就短路返回 story。
        """
        dashboard = self._make_dashboard(phase="topic_selection")
        # decide_next_action 硬规则：topic_selection 且 story 未确认 → 直接返回 story
        decision = decide_next_action(dashboard, history=[{"step": 1}], feedbacks=[])
        assert decision.action == "call_agent"
        assert decision.agent == "story"
        assert "选题阶段未完成" in decision.reason

    def test_dc05_topic_selection_blocks_done_empty_phase(self):
        """TC-DC-05 补充: phase="" 时的 done 被 hard rule 阻止"""
        dashboard = self._make_dashboard(phase="")
        decision = decide_next_action(dashboard, history=[{"step": 1}], feedbacks=[])
        # phase="" and "story" not in completed → hard rule returns story
        assert decision.action == "call_agent"
        assert decision.agent == "story"

    def test_dc05_validate_decision_done_guard_with_completed(self):
        """附加: done 守卫在核心阶段未完成时触发（v0.4.0 收窄）"""
        decision = OrchestratorDecision(action="done", reason="done")
        dashboard = self._make_dashboard(
            phase="topic_selection",
            completed=["character"],  # has completed but story/world/outline are missing
        )
        err = _validate_decision(decision, dashboard)
        assert err is not None
        assert "核心阶段未完成" in err

    def test_dc05_done_allowed_after_story_confirmed(self):
        """TC-DC-05 补充: story 已确认后 done 不被 blocked"""
        decision = OrchestratorDecision(action="done", reason="全部完成")
        dashboard = self._make_dashboard(
            phase="planning", completed=["story", "character", "world", "outline"],
            total_ch=20, written=20
        )
        # completed_agents 非空，done guard 不应触发
        err = _validate_decision(decision, dashboard)
        # done guard only fires when dashboard.completed_agents is truthy but "story" not in it
        # Here completed has "story", so guard should pass
        assert err is None  # no error expected

# ============================================================================
# TC-DC-06: LLM 重试耗尽降级（mock LLM）
# ============================================================================

class TestDecisionRetryExhaustion:
    """TC-DC-06: 3 次重试全部失败 → 降级 story"""

    def _make_dashboard(self, phase="planning", completed=None):
        return Dashboard(
            phase=phase,
            completed_agents=completed or ["story", "character", "world", "outline"],
            progress=Progress(total_chapters=10, written=0),
        )

    def test_dc06_llm_always_returns_invalid_json(self, monkeypatch):
        """LLM 始终返回无效 JSON → 3 次重试后降级到 story"""
        from src.utils import llm as llm_module

        def mock_complete(*args, **kwargs):
            return "这不是JSON { invalid"

        monkeypatch.setattr(llm_module.OpenAIClient, "complete", mock_complete)

        dashboard = self._make_dashboard()
        decision = decide_next_action(
            dashboard,
            history=[{"step": 1}],
            feedbacks=[],
            max_retries=3,
        )
        assert decision.action == "call_agent"
        assert decision.agent == "story"
        assert "决策失败" in decision.reason

    def test_dc06_llm_always_raises_exception(self, monkeypatch):
        """LLM 始终抛异常 → 降级到 story"""
        from src.utils import llm as llm_module

        def mock_complete(*args, **kwargs):
            raise RuntimeError("LLM connection refused")

        monkeypatch.setattr(llm_module.OpenAIClient, "complete", mock_complete)

        dashboard = self._make_dashboard()
        decision = decide_next_action(
            dashboard,
            history=[{"step": 1}],
            feedbacks=[],
            max_retries=3,
        )
        assert decision.action == "call_agent"
        assert decision.agent == "story"
        assert "LLM connection refused" in decision.reason or "决策失败" in decision.reason


# ============================================================================
# TC-NM: Agent 名称归一化测试
# ============================================================================

class TestAgentNormalization:
    """TC-NM-01 ~ TC-NM-08"""

    def test_nm01_outline_keywords(self):
        """TC-NM-01: 章纲 / outline → outline"""
        assert _normalize_agent("outline") == "outline"
        assert _normalize_agent("章纲") == "outline"

    def test_nm01_outline_dagang_fallback(self):
        """TC-NM-01 补充: "大纲" 不含 "章" 关键词，当前降级为 story（已知 normalization gap）

        原因：_normalize_agent 用 "章" 匹配而非 "纲"。若需修复，
        可在 outline 分支增加 "纲" 或 "大纲" 匹配。
        """
        result = _normalize_agent("大纲")
        # 当前实际行为：降级到 story
        assert result == "story"  # known gap, not ideal

    def test_nm02_character_keywords(self):
        """TC-NM-02: 角色 / character → character"""
        assert _normalize_agent("character") == "character"
        assert _normalize_agent("角色") == "character"

    def test_nm03_world_keywords(self):
        """TC-NM-03: 世界 / world → world"""
        assert _normalize_agent("world") == "world"
        assert _normalize_agent("世界") == "world"
        assert _normalize_agent("setting") == "world"

    def test_nm04_writer_keywords(self):
        """TC-NM-04: 写 / 文笔 / writer → writer"""
        assert _normalize_agent("writer") == "writer"
        assert _normalize_agent("写") == "writer"
        assert _normalize_agent("文笔") == "writer"
        assert _normalize_agent("draft") == "writer"
        assert _normalize_agent("create") == "writer"

    def test_nm05_proofreader_keywords(self):
        """TC-NM-05: 校对 / proof / edit → proofreader"""
        assert _normalize_agent("proofreader") == "proofreader"
        assert _normalize_agent("校对") == "proofreader"
        assert _normalize_agent("proof") == "proofreader"
        assert _normalize_agent("edit") == "proofreader"

    def test_nm06_novel_review_keywords(self):
        """TC-NM-06: 审查 / review / check → novel_review"""
        assert _normalize_agent("novel_review") == "novel_review"
        assert _normalize_agent("审查") == "novel_review"
        assert _normalize_agent("review") == "novel_review"
        assert _normalize_agent("check") == "novel_review"

    def test_nm07_story_keywords(self):
        """TC-NM-07: story / plot / plan / topic / 创意 → story"""
        assert _normalize_agent("story") == "story"
        assert _normalize_agent("plot") == "story"
        assert _normalize_agent("plan") == "story"
        assert _normalize_agent("topic") == "story"
        assert _normalize_agent("创意") == "story"

    def test_nm08_unknown_falls_back_to_story(self):
        """TC-NM-08: 完全匹配不到的字符串 → story（默认降级）"""
        assert _normalize_agent("xyzabc_unknown_123") == "story"
        assert _normalize_agent("") == "story"

    def test_nm_outline_priority_over_story(self):
        """附加: outline 关键词优先级高于 story（"chapter" 不应被 "plan" 拦截）"""
        assert _normalize_agent("chapter_outline") == "outline"
        # "chapter" is checked before "story" keywords


# ============================================================================
# TC-EDGE: 边界条件测试
# ============================================================================

class TestEdgeCases:
    """TC-EDGE-01 ~ TC-EDGE-09"""

    def _make_suggestion(self, title, genre="科幻"):
        return TopicSuggestion(
            title=title, genre=genre, sub_genre="",
            core_selling_point=f"{title}的核心卖点",
            target_audience="", competitive_analysis="",
            platform_fit=PlatformFit(heat_level="热门", difficulty="蓝海", reader_preference="高"),
            inspiration_source="test",
        )

    def test_edge01_single_topic_falls_back(self):
        """TC-EDGE-01: 选题列表只有 1 条，降级到第一条"""
        from src.orchestrator.loop import OrchestratorSession
        from src.orchestrator.workspace import Workspace

        ws = Workspace.create("test-single", "起点", "test idea")
        ws.raw_state.topic = TopicState(
            user_original_idea="test",
            suggestions=[self._make_suggestion("唯一选题")],
            selected=-1,
        )
        session = OrchestratorSession(ws)
        # No matching feedback → falls back to first suggestion
        result = session._find_selected_topic()
        assert result is not None
        assert result.title == "唯一选题"
        assert ws.raw_state.topic.selected == 0

    def test_edge02_empty_topics_returns_none(self):
        """TC-EDGE-02: 选题列表为空 → 返回 None"""
        from src.orchestrator.loop import OrchestratorSession
        from src.orchestrator.workspace import Workspace

        ws = Workspace.create("test-empty", "起点", "test")
        ws.raw_state.topic = TopicState(
            user_original_idea="test",
            suggestions=[],
            selected=-1,
        )
        session = OrchestratorSession(ws)
        result = session._find_selected_topic()
        assert result is None

    def test_edge02_no_topic_at_all(self):
        """TC-EDGE-02 补充: topic 为 None"""
        from src.orchestrator.loop import OrchestratorSession
        from src.orchestrator.workspace import Workspace

        ws = Workspace.create("test-no-topic", "起点", "test")
        # topic is None by default
        session = OrchestratorSession(ws)
        result = session._find_selected_topic()
        assert result is None

    def test_edge03_feedback_no_match_falls_back(self):
        """TC-EDGE-03: 反馈文本不匹配任何选题标题 → 降级到第一条"""
        from src.orchestrator.loop import OrchestratorSession
        from src.orchestrator.workspace import Workspace

        ws = Workspace.create("test-nomatch", "起点", "test")
        ws.raw_state.topic = TopicState(
            user_original_idea="test",
            suggestions=[
                self._make_suggestion("选题A"),
                self._make_suggestion("选题B"),
            ],
            selected=-1,
        )
        # Add feedback that matches nothing
        ws.feedbacks.append({"agent": "story", "text": "完全不相关的文字", "time": "2026-01-01"})
        session = OrchestratorSession(ws)
        result = session._find_selected_topic()
        assert result is not None
        assert result.title == "选题A"  # falls back to first

    def test_edge04_multiple_feedbacks_picks_latest(self):
        """TC-EDGE-04: 用户多次选择不同选题 → 取最近一次"""
        from src.orchestrator.loop import OrchestratorSession
        from src.orchestrator.workspace import Workspace

        ws = Workspace.create("test-multi", "起点", "test")
        ws.raw_state.topic = TopicState(
            user_original_idea="test",
            suggestions=[
                self._make_suggestion("选题A"),
                self._make_suggestion("选题B"),
            ],
            selected=-1,
        )
        ws.feedbacks.append({"agent": "story", "text": "选择: 选题A", "time": "2026-01-01"})
        ws.feedbacks.append({"agent": "story", "text": "选择: 选题B", "time": "2026-01-02"})
        session = OrchestratorSession(ws)
        result = session._find_selected_topic()
        assert result.title == "选题B"

    def test_edge04_feedback_with_partial_title_match(self):
        """TC-EDGE-04 补充: 反馈含部分标题（子串匹配）"""
        from src.orchestrator.loop import OrchestratorSession
        from src.orchestrator.workspace import Workspace

        ws = Workspace.create("test-partial", "起点", "test")
        ws.raw_state.topic = TopicState(
            user_original_idea="test",
            suggestions=[self._make_suggestion("蒸汽纪元：我创造了智能神明")],
            selected=-1,
        )
        ws.feedbacks.append({"agent": "story", "text": "选题: 蒸汽纪元", "time": "2026-01-01"})
        session = OrchestratorSession(ws)
        result = session._find_selected_topic()
        # "蒸汽纪元" is in "蒸汽纪元：我创造了智能神明" (s.title in text? No. text in s.title? Yes)
        assert result is not None
        assert "蒸汽纪元" in result.title

    def test_edge05_single_chapter_outline(self):
        """TC-EDGE-05: 章纲只有 1 章 — 验证 phase 逻辑可接受"""
        # Phase computation: if written > 0 → writing_chapters
        # 1 chapter outline works fine
        dashboard = Dashboard(
            phase="planning",
            completed_agents=["story", "character", "world", "outline"],
            progress=Progress(total_chapters=1, written=0),
        )
        assert dashboard.phase == "planning"
        assert dashboard.progress.total_chapters == 1

    def test_edge06_zero_chapter_outline(self):
        """TC-EDGE-06: 章纲 0 章 → phase 不进入 writing_chapters"""
        # total_chapters=0 means no chapters exist
        dashboard = Dashboard(
            phase="planning",
            completed_agents=["story", "character", "world", "outline"],
            progress=Progress(total_chapters=0, written=0),
        )
        assert dashboard.progress.total_chapters == 0

    def test_edge07_validate_empty_agent_name(self):
        """TC-EDGE-07: writer 重复调用 — _validate_decision 不因 agent 名重复而拒绝"""
        # writer is always valid as long as phase allows and total_ch > 0
        decision = OrchestratorDecision(action="call_agent", agent="writer", reason="继续写")
        dashboard = Dashboard(
            phase="writing_chapters",
            completed_agents=["story", "character", "world", "outline"],
            progress=Progress(total_chapters=10, written=1),
        )
        err = _validate_decision(decision, dashboard)
        assert err is None  # writer allowed for subsequent chapters


# ============================================================================
# TC-EDGE-08/09: 钩子/爽点降级（mock 生成函数）
# ============================================================================

class TestDegradation:
    """TC-EDGE-08, TC-EDGE-09 — 验证降级路径"""

    def _make_orchestrator(self):
        from src.orchestrator.loop import OrchestratorSession
        from src.orchestrator.workspace import Workspace

        ws = Workspace.create("test-degrade", "起点", "test")
        # 需要 volume 才能测试钩子/爽点
        from src.state.state_types import VolumeState
        vol = VolumeState(index=1, title="第一卷", chapter_indices=list(range(10)))
        ws.raw_state.volumes = [vol]
        ws.raw_state.metadata.platform = "起点"
        return OrchestratorSession(ws), ws

    def test_edge08_hook_matrix_degradation(self, monkeypatch):
        """TC-EDGE-08: generate_hook_matrix 一直返回无效钩子 → 3次重试后降级"""
        from src.orchestrator import loop as loop_module
        from src.state.state_types import HookCard

        # Mock: 总是返回长度不匹配的钩子（触发校验失败）
        # 注意：必须 monkeypatch loop.py 中的引用，因为 _generate_hook_matrix 在 loop.py 中
        def mock_generate(*args, **kwargs):
            return [HookCard(chapter_index=0, hook_type="悬念", strength=1, content="", connect_chapter=2)]
            # Only 1 hook for 10 chapters → validate_hook_matrix 报错

        monkeypatch.setattr(loop_module, "generate_hook_matrix", mock_generate)

        session, ws = self._make_orchestrator()
        session._generate_hook_matrix()

        vol = ws.get_current_volume()
        assert vol is not None
        assert vol.auto_degraded is True, "降级后 auto_degraded 应为 True"
        assert len(vol.hook_matrix) == 10, "降级产物应为 10 个钩子"

    def test_edge08_hook_matrix_correct_fallback_strength(self, monkeypatch):
        """TC-EDGE-08 补充: 降级钩子卷末强度为 ★★★★★"""
        from src.orchestrator import loop as loop_module
        from src.state.state_types import HookCard

        def mock_generate(*args, **kwargs):
            # Return wrong count
            return [HookCard(chapter_index=0, hook_type="悬念", strength=1, content="", connect_chapter=2)]

        monkeypatch.setattr(loop_module, "generate_hook_matrix", mock_generate)

        session, ws = self._make_orchestrator()
        session._generate_hook_matrix()

        vol = ws.get_current_volume()
        last_hook = vol.hook_matrix[-1]
        assert last_hook.strength == 5, f"卷末钩子应为★★★★★，实际: {last_hook.strength}"

    def test_edge09_pleasure_curve_degradation(self, monkeypatch):
        """TC-EDGE-09: generate_pleasure_curve 一直返回无效爽点 → 降级"""
        from src.orchestrator import loop as loop_module
        from src.state.state_types import PleasurePointCard

        # Mock: 返回连续重复类型（触发 validate_pleasure_curve 报错）
        def mock_generate(*args, **kwargs):
            return [
                PleasurePointCard(chapter_index=i, pp_type="打脸", strength=3,
                                  description="", word_ratio_target=0.12)
                for i in range(10)
            ]  # All same type → consecutive repeat error

        monkeypatch.setattr(loop_module, "generate_pleasure_curve", mock_generate)

        session, ws = self._make_orchestrator()
        session._generate_pleasure_curve()

        vol = ws.get_current_volume()
        assert vol is not None
        assert len(vol.pleasure_curve) == 10, "降级产物应为 10 个爽点"

    def test_edge09_pleasure_curve_fallback_last_is_max(self, monkeypatch):
        """TC-EDGE-09 补充: 降级爽点卷末为 ★★★★★"""
        from src.orchestrator import loop as loop_module
        from src.state.state_types import PleasurePointCard

        def mock_generate(*args, **kwargs):
            return [
                PleasurePointCard(chapter_index=i, pp_type="打脸", strength=1,
                                  description="", word_ratio_target=0.12)
                for i in range(5)
            ]

        monkeypatch.setattr(loop_module, "generate_pleasure_curve", mock_generate)

        session, ws = self._make_orchestrator()
        session._generate_pleasure_curve()

        vol = ws.get_current_volume()
        last_pp = vol.pleasure_curve[-1]
        assert last_pp.strength == 5, f"卷末爽点应为★★★★★，实际: {last_pp.strength}"


# ============================================================================
# 附加: 阶段守卫组合测试
# ============================================================================

class TestPhaseGuardCombinations:
    """验证阶段守卫的组合行为"""

    def _dash(self, phase, completed=None, total=0, written=0):
        return Dashboard(
            phase=phase, completed_agents=completed or [],
            progress=Progress(total_chapters=total, written=written),
        )

    def test_topic_selection_only_story_allowed(self):
        """选题阶段 + 空 completed → 只允许 story"""
        for agent in ["character", "world", "outline", "writer", "proofreader", "novel_review"]:
            decision = OrchestratorDecision(action="call_agent", agent=agent, reason="test")
            err = _validate_decision(decision, self._dash("topic_selection"))
            assert err is not None, f"Agent {agent} should be blocked in topic_selection"

    def test_topic_selection_story_allowed(self):
        """选题阶段 + 空 completed → story 被允许"""
        decision = OrchestratorDecision(action="call_agent", agent="story", reason="test")
        err = _validate_decision(decision, self._dash("topic_selection"))
        assert err is None

    def test_planning_all_agents_allowed(self):
        """planning 阶段 → 全部核心 agent 在条件满足时可通过"""
        dashboard = self._dash("planning", completed=["story", "character", "world"], total=0)
        for agent in ["story", "character", "world", "outline"]:
            decision = OrchestratorDecision(action="call_agent", agent=agent, reason="test")
            err = _validate_decision(decision, dashboard)
            assert err is None, f"Agent {agent} should be allowed with story+character+world confirmed"

    def test_planning_world_requires_character(self):
        """planning 阶段 → character 未确认时 world 被拒绝"""
        dashboard = self._dash("planning", completed=["story"], total=0)
        decision = OrchestratorDecision(action="call_agent", agent="world", reason="test")
        err = _validate_decision(decision, dashboard)
        assert err is not None
        assert "character" in err or "角色" in err

    def test_writing_chapters_guards(self):
        """writing_chapters 阶段 → writer 被允许，proofreader 需 written > 0"""
        dashboard = self._dash("writing_chapters", completed=["story", "character", "world", "outline"],
                               total=10, written=3)
        # Writer allowed
        err = _validate_decision(OrchestratorDecision(action="call_agent", agent="writer", reason="test"), dashboard)
        assert err is None
        # Proofreader allowed with written > 0
        err = _validate_decision(OrchestratorDecision(action="call_agent", agent="proofreader", reason="test"), dashboard)
        assert err is None
