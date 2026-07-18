"""
Phase 6 单元测试 — Timeline / Style Learner / References / Usage Tracker

覆盖: T6.1 Timeline CRUD + auto_extract + regex fallback
      T6.2 StyleLearner analyze/merge/inject
      T6.3 ReferenceManager CRUD + search + inject
      T6.4 UsageTracker record + stats + reset

全自包含：无 LLM 调用，无网络请求，使用 tmp_path 隔离文件 I/O。
"""

import json
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ══════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════

def _make_tmp_timeline_path(tmp_path, project_id):
    """Factory for patched _get_timeline_path."""
    p = tmp_path / project_id
    p.mkdir(parents=True, exist_ok=True)
    return p / "timeline.json"


def _make_tmp_refs_path(tmp_path, project_id):
    """Factory for patched _get_refs_path."""
    p = tmp_path / project_id
    p.mkdir(parents=True, exist_ok=True)
    return p / "references.json"


# ══════════════════════════════════════════════════════════════
# T6.1: TimelineEvent + TimelineManager
# ══════════════════════════════════════════════════════════════

class TestTimelineEvent:
    """TimelineEvent 数据模型测试"""

    def test_event_auto_id_and_created_at(self):
        """创建 TimelineEvent 自动生成 id 和 created_at"""
        from src.agents.timeline import TimelineEvent

        ev = TimelineEvent(
            project_id="proj-x",
            description="主角觉醒",
            chapter_num=3,
            story_time="第三日",
        )
        assert len(ev.id) == 12
        assert ev.created_at != ""
        assert "T" in ev.created_at

    def test_event_defaults(self):
        """TimelineEvent 默认值：event_type='plot', chapter_num=0"""
        from src.agents.timeline import TimelineEvent

        ev = TimelineEvent(project_id="p1", description="test")
        assert ev.event_type == "plot"
        assert ev.chapter_num == 0
        assert ev.story_time == ""

    def test_event_id_deterministic(self):
        """相同字段产生相同 id（不含时间戳 salt 时）"""
        from src.agents.timeline import TimelineEvent

        ev1 = TimelineEvent(
            project_id="p1", description="desc", chapter_num=1,
            story_time="day1", created_at="2026-01-01T00:00:00",
        )
        ev2 = TimelineEvent(
            project_id="p1", description="desc", chapter_num=1,
            story_time="day1", created_at="2026-01-01T00:00:00",
        )
        assert ev1.id == ev2.id

    def test_event_to_dict(self):
        """to_dict 输出所有字段"""
        from src.agents.timeline import TimelineEvent

        ev = TimelineEvent(
            project_id="p1", description="战斗开始", chapter_num=5,
            story_time="黄昏", event_type="plot",
        )
        d = ev.to_dict()
        assert d["project_id"] == "p1"
        assert d["description"] == "战斗开始"
        assert d["chapter_num"] == 5
        assert d["story_time"] == "黄昏"
        assert d["event_type"] == "plot"
        assert len(d["id"]) == 12
        assert "T" in d["created_at"]

    def test_event_from_dict(self):
        """from_dict 反序列化"""
        from src.agents.timeline import TimelineEvent

        d = {
            "id": "abc123def456", "project_id": "p2",
            "description": "角色死亡", "chapter_num": 10,
            "story_time": "第三年", "event_type": "character",
            "created_at": "2026-06-01T12:00:00",
        }
        ev = TimelineEvent.from_dict(d)
        assert ev.id == "abc123def456"
        assert ev.project_id == "p2"
        assert ev.description == "角色死亡"
        assert ev.chapter_num == 10
        assert ev.story_time == "第三年"
        assert ev.event_type == "character"
        assert ev.created_at == "2026-06-01T12:00:00"

    def test_event_from_dict_defaults(self):
        """from_dict 缺失字段使用默认值"""
        from src.agents.timeline import TimelineEvent

        ev = TimelineEvent.from_dict({})
        # from_dict passes id="" to __init__, which triggers auto-generation in __post_init__
        assert len(ev.id) == 12
        assert ev.project_id == ""
        assert ev.description == ""
        assert ev.chapter_num == 0
        assert ev.story_time == ""
        assert ev.event_type == "plot"
        # created_at is also auto-generated if empty
        assert "T" in ev.created_at


class TestTimelineManager:
    """TimelineManager CRUD + 排序测试"""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, monkeypatch):
        """每个测试使用独立的 tmp_path 存储。"""
        import src.agents.timeline as tmod

        self.tmp_path = tmp_path
        self.project_id = "test-timeline-proj"
        monkeypatch.setattr(
            tmod, "_get_timeline_path",
            lambda pid: _make_tmp_timeline_path(self.tmp_path, pid),
        )
        self.mgr = tmod.TimelineManager(self.project_id)

    def test_create_event(self):
        """create 返回带完整字段的 TimelineEvent 并持久化"""
        from src.agents.timeline import TimelineEvent

        ev = TimelineEvent(
            description="进入秘境", chapter_num=1,
            story_time="第一天下午", event_type="plot",
        )
        result = self.mgr.create(ev)
        assert result.id != ""
        assert result.project_id == self.project_id
        assert result.description == "进入秘境"
        assert len(self.mgr.get_all()) == 1

        # 验证持久化到文件
        fpath = _make_tmp_timeline_path(self.tmp_path, self.project_id)
        assert fpath.exists()
        data = json.loads(fpath.read_text(encoding="utf-8"))
        assert len(data) == 1

    def test_create_duplicate_id_forced_new(self):
        """重复 id 时 create 强制生成新 id"""
        from src.agents.timeline import TimelineEvent

        ev1 = TimelineEvent(project_id=self.project_id, description="A", chapter_num=1)
        self.mgr.create(ev1)
        # 用相同 id 再创建
        ev2 = TimelineEvent(
            id=ev1.id, project_id=self.project_id,
            description="B", chapter_num=2,
        )
        result = self.mgr.create(ev2)
        assert result.id != ev1.id
        assert len(self.mgr.get_all()) == 2

    def test_get_all(self):
        """get_all 返回所有事件"""
        from src.agents.timeline import TimelineEvent

        for i in range(3):
            ev = TimelineEvent(description=f"事件{i}", chapter_num=i + 1)
            self.mgr.create(ev)
        assert len(self.mgr.get_all()) == 3

    def test_update_event(self):
        """update 按 id 更新字段"""
        from src.agents.timeline import TimelineEvent

        ev = TimelineEvent(description="原描述", chapter_num=1, story_time="第一天")
        created = self.mgr.create(ev)
        assert self.mgr.update(created.id, description="新描述", chapter_num=99)
        updated = self.mgr.get_all()[0]
        assert updated.description == "新描述"
        assert updated.chapter_num == 99

    def test_update_nonexistent(self):
        """update 不存在的 id 返回 False"""
        assert self.mgr.update("no-such-id", description="x") is False

    def test_delete_event(self):
        """delete 按 id 删除事件"""
        from src.agents.timeline import TimelineEvent

        ev = TimelineEvent(description="待删除", chapter_num=1)
        created = self.mgr.create(ev)
        assert len(self.mgr.get_all()) == 1
        assert self.mgr.delete(created.id) is True
        assert len(self.mgr.get_all()) == 0

    def test_delete_nonexistent(self):
        """delete 不存在的 id 返回 False"""
        assert self.mgr.delete("no-such-id") is False

    def test_get_timeline_sort_numeric_prefix(self):
        """get_timeline 按 story_time 自然排序：数字前缀优先"""
        from src.agents.timeline import TimelineEvent

        ev1 = self.mgr.create(TimelineEvent(description="先", chapter_num=1, story_time="第1天"))
        time.sleep(0.02)
        ev2 = self.mgr.create(TimelineEvent(description="中", chapter_num=2, story_time="第10天"))
        time.sleep(0.02)
        ev3 = self.mgr.create(TimelineEvent(description="后", chapter_num=3, story_time="第2天"))

        sorted_events = self.mgr.get_timeline()
        assert sorted_events[0].story_time == "第1天"
        assert sorted_events[1].story_time == "第2天"
        assert sorted_events[2].story_time == "第10天"

    def test_get_timeline_sort_text_first(self):
        """get_timeline 非数字时间标记排在数字之前"""
        from src.agents.timeline import TimelineEvent

        ev1 = self.mgr.create(TimelineEvent(description="A", chapter_num=1, story_time="盛夏"))
        time.sleep(0.02)
        ev2 = self.mgr.create(TimelineEvent(description="B", chapter_num=2, story_time="第1天"))
        time.sleep(0.02)
        ev3 = self.mgr.create(TimelineEvent(description="C", chapter_num=3, story_time="深夜"))

        sorted_events = self.mgr.get_timeline()
        # 非数字 story_time: (0, 0, "盛夏"), (0, 0, "深夜")
        # 数字 story_time: (1, 1, "第1天")
        # 所以数字的排在后面
        assert sorted_events[2].story_time == "第1天"

    def test_get_timeline_empty(self):
        """空年表返回 []"""
        assert self.mgr.get_timeline() == []

    def test_regex_extract_time_markers(self):
        """_regex_extract 从文本中提取时间标记"""
        from src.agents.timeline import TimelineManager

        mgr = TimelineManager.__new__(TimelineManager)
        mgr.project_id = self.project_id
        mgr._events = []
        text = "第三天清晨，主角醒来。三年后，他已成为强者。第二天傍晚，敌人来袭。"
        events = mgr._regex_extract(text, 1)

        assert len(events) >= 2  # 至少找到 2 个不同的时间标记
        story_times = {e.story_time for e in events}
        assert "第三天" in story_times or any("第三天" in e.description for e in events)

        assert all(e.chapter_num == 1 for e in events)
        assert all(e.event_type == "plot" for e in events)

    def test_regex_extract_short_text(self):
        """_regex_extract：短文本无时间标记返回空"""
        from src.agents.timeline import TimelineManager

        mgr = TimelineManager.__new__(TimelineManager)
        mgr.project_id = self.project_id
        mgr._events = []
        events = mgr._regex_extract("今天天气很好。", 1)
        assert events == []

    def test_auto_extract_short_content(self):
        """auto_extract：小于 50 字符的内容返回空列表"""
        events = self.mgr.auto_extract("短文本", 1)
        assert events == []

    def test_auto_extract_llm_failure_fallsback_to_regex(self):
        """auto_extract：LLM 失败时回退到正则提取"""
        from src.agents.timeline import TimelineEvent

        # 用文本包含已知时间标记
        text = "第三天清晨，主角踏上了漫漫征程。夜幕降临之后，他在幽暗的森林中迷路了。三年后，他依然记得这一天，心中感慨万千。"
        assert len(text) >= 50  # 确保不触发短文本跳过

        # Mock LLM 调用失败
        with patch("src.utils.llm.create_llm_client", side_effect=Exception("LLM timeout")):
            events = self.mgr.auto_extract(text, 5)
            # 正则降级应找到时间标记
            assert len(events) > 0
            assert all(e.chapter_num == 5 for e in events)
            # 验证事件被持久化
            assert len(self.mgr.get_all()) > 0


# ══════════════════════════════════════════════════════════════
# T6.2: StyleProfile + StyleLearner
# ══════════════════════════════════════════════════════════════

class TestStyleProfile:
    """StyleProfile 序列化 / 反序列化"""

    def test_to_dict(self):
        """to_dict 输出完整字段并限制 word_frequency 为 50"""
        from src.agents.style_learner import StyleProfile

        p = StyleProfile(
            sentence_lengths={"avg": 25.5, "max": 120, "min": 3},
            word_frequency=[("的", 300), ("了", 150)],
            dialogue_ratio=0.4,
            description_density=0.6,
            avg_paragraph_length=80.5,
            sample_size_chars=5000,
            chapter_count=3,
        )
        d = p.to_dict()
        assert d["sentence_lengths"]["avg"] == 25.5
        assert d["word_frequency"] == [("的", 300), ("了", 150)]
        assert d["dialogue_ratio"] == 0.4
        assert d["description_density"] == 0.6
        assert d["avg_paragraph_length"] == 80.5
        assert d["sample_size_chars"] == 5000
        assert d["chapter_count"] == 3

    def test_from_dict(self):
        """from_dict 反序列化"""
        from src.agents.style_learner import StyleProfile

        d = {
            "sentence_lengths": {"avg": 30.0, "max": 80, "min": 2},
            "word_frequency": [("我", 100), ("是", 50)],
            "dialogue_ratio": 0.35,
            "description_density": 0.65,
            "avg_paragraph_length": 120.0,
            "sample_size_chars": 3000,
            "chapter_count": 2,
        }
        p = StyleProfile.from_dict(d)
        assert p.sentence_lengths["avg"] == 30.0
        assert p.word_frequency == [("我", 100), ("是", 50)]
        assert p.dialogue_ratio == 0.35
        assert p.description_density == 0.65
        assert p.avg_paragraph_length == 120.0
        assert p.sample_size_chars == 3000
        assert p.chapter_count == 2

    def test_from_dict_defaults(self):
        """from_dict 空 dict 使用默认值"""
        from src.agents.style_learner import StyleProfile

        p = StyleProfile.from_dict({})
        assert p.sentence_lengths == {"avg": 0, "max": 0, "min": 0}
        assert p.word_frequency == []
        assert p.dialogue_ratio == 0.0
        assert p.description_density == 0.0
        assert p.avg_paragraph_length == 0.0
        assert p.sample_size_chars == 0
        assert p.chapter_count == 0

    def test_roundtrip(self):
        """to_dict → from_dict 往返一致"""
        import math
        from src.agents.style_learner import StyleProfile

        p = StyleProfile(
            sentence_lengths={"avg": 15.3, "max": 45, "min": 1},
            word_frequency=[("的", 500), ("一", 200), ("不", 100)],
            dialogue_ratio=0.55,
            description_density=0.45,
            avg_paragraph_length=95.2,
            sample_size_chars=8000,
            chapter_count=4,
        )
        restored = StyleProfile.from_dict(p.to_dict())
        assert math.isclose(restored.dialogue_ratio, p.dialogue_ratio, rel_tol=1e-6)
        assert math.isclose(restored.description_density, p.description_density, rel_tol=1e-6)
        assert restored.sample_size_chars == p.sample_size_chars
        assert restored.chapter_count == p.chapter_count


class TestStyleLearner:
    """StyleLearner 统计分析测试（纯统计，无 LLM）"""

    def test_analyze_chapter_empty_text(self):
        """空文本返回默认 StyleProfile"""
        from src.agents.style_learner import StyleLearner

        profile = StyleLearner.analyze_chapter("")
        assert profile.sample_size_chars == 0
        # Empty text triggers early return with default StyleProfile (chapter_count=0)
        assert profile.chapter_count == 0
        assert profile.dialogue_ratio == 0.0
        assert profile.description_density == 0.0

    def test_analyze_chapter_whitespace_only(self):
        """空白文本返回默认值"""
        from src.agents.style_learner import StyleLearner

        profile = StyleLearner.analyze_chapter("   \n  \n  ")
        assert profile.sample_size_chars == 0

    def test_analyze_chapter_pure_description(self):
        """纯描述段落计算描述密度"""
        from src.agents.style_learner import StyleLearner

        text = (
            "远处的山峰笼罩在薄雾之中。古老的松树在风中摇曳。\n"
            "他独自走在山路上，脚下是松软的落叶。空气中弥漫着泥土的气息。\n"
            "这里的一切都让他想起了童年的故乡。"
        )
        profile = StyleLearner.analyze_chapter(text)
        assert profile.sample_size_chars > 0
        assert profile.dialogue_ratio == 0.0
        assert profile.description_density == 1.0
        assert profile.chapter_count == 1
        # 句长应有值
        assert profile.sentence_lengths["avg"] > 0

    def test_analyze_chapter_with_dialogue(self):
        """包含对话的文本计算对话占比"""
        from src.agents.style_learner import StyleLearner

        text = (
            "他走进房间，环顾四周。\n"
            "\"你终于来了。\"她轻声说道。\n"
            "\"我等了很久。\"他回答。\n"
            "「是的，路途遥远。」她叹了口气。\n"
            "窗外下起了雨。\n"
        )
        profile = StyleLearner.analyze_chapter(text)
        # 5 个段落，3 个有对话 → dialogue_ratio = 0.6
        assert profile.dialogue_ratio > 0.0
        assert profile.dialogue_ratio < 1.0
        assert profile.description_density > 0.0  # 有些段落无对话

    def test_analyze_chapter_word_frequency(self):
        """词频统计包含 Top 词汇"""
        from src.agents.style_learner import StyleLearner

        text = "他看着她，她也看着他。他们都很沉默，沉默了很久很久。"
        profile = StyleLearner.analyze_chapter(text)
        assert len(profile.word_frequency) > 0
        # "他" 应该是高频词
        words = {w for w, _ in profile.word_frequency}
        assert "他" in words

    def test_analyze_chapter_mixed_cjk_latin(self):
        """混合中英文文本正确分词"""
        from src.agents.style_learner import StyleLearner

        text = "他使用了 Python 编写了 AI 系统。这款 AI 非常强大。Hello World。"
        profile = StyleLearner.analyze_chapter(text)
        assert profile.sample_size_chars > 0
        # 验证有词汇产出
        assert len(profile.word_frequency) > 0

    def test_merge_profiles_empty(self):
        """空列表返回默认 StyleProfile"""
        from src.agents.style_learner import StyleLearner

        merged = StyleLearner.merge_profiles([])
        assert merged.chapter_count == 0
        assert merged.sample_size_chars == 0

    def test_merge_profiles_single(self):
        """单 profile 直接返回"""
        from src.agents.style_learner import StyleLearner

        p = StyleLearner.analyze_chapter("测试文本内容。第二句话在这里。")
        merged = StyleLearner.merge_profiles([p])
        assert merged.chapter_count == p.chapter_count
        assert merged.sample_size_chars == p.sample_size_chars

    def test_merge_profiles_multiple(self):
        """合并多个 profile：加权平均 + 词频合并"""
        from src.agents.style_learner import StyleLearner

        text1 = "他走在路上。天很蓝。风很轻。他他他他他。"  # "他" 高频
        text2 = "她坐在窗边。雨很大。她很美。她她她她她。"  # "她" 高频
        p1 = StyleLearner.analyze_chapter(text1)
        p2 = StyleLearner.analyze_chapter(text2)

        merged = StyleLearner.merge_profiles([p1, p2])
        assert merged.chapter_count == 2
        assert merged.sample_size_chars == p1.sample_size_chars + p2.sample_size_chars
        assert merged.dialogue_ratio >= 0.0
        assert len(merged.word_frequency) > 0

    def test_merge_profiles_preserves_ranges(self):
        """合并后 sentence_lengths 的 max/min 覆盖所有输入"""
        from src.agents.style_learner import StyleLearner

        p1 = StyleLearner.analyze_chapter("短句。短句。短句。短句。")
        p2 = StyleLearner.analyze_chapter("这是一个很长很长的句子包含了非常多的内容。")
        merged = StyleLearner.merge_profiles([p1, p2])
        assert merged.sentence_lengths["max"] == max(
            p1.sentence_lengths["max"], p2.sentence_lengths["max"]
        )
        assert merged.sentence_lengths["min"] == min(
            p1.sentence_lengths["min"], p2.sentence_lengths["min"]
        )

    def test_inject_into_prompt_format(self):
        """inject_into_prompt 输出格式化文风参考字符串"""
        from src.agents.style_learner import StyleLearner, StyleProfile

        p = StyleProfile(
            sentence_lengths={"avg": 20.0, "max": 100, "min": 2},
            word_frequency=[("的", 100), ("了", 80), ("我", 60), ("你", 50),
                            ("是", 40), ("不", 30), ("在", 20), ("有", 15),
                            ("人", 10), ("这", 8)],
            dialogue_ratio=0.35,
            description_density=0.65,
            avg_paragraph_length=120.0,
            sample_size_chars=5000,
            chapter_count=3,
        )
        prompt = StyleLearner.inject_into_prompt(p)
        assert "【文风参考】" in prompt
        assert "20.0" in prompt or "20" in prompt
        assert "35.0%" in prompt or "35%" in prompt
        assert "65.0%" in prompt or "65%" in prompt
        assert "5000" in prompt
        assert "3章" in prompt or "3 章" in prompt
        assert "的" in prompt  # Top10 词汇

    def test_inject_into_prompt_empty_profile(self):
        """空 profile（chapter_count=0）返回空字符串"""
        from src.agents.style_learner import StyleLearner, StyleProfile

        assert StyleLearner.inject_into_prompt(StyleProfile()) == ""
        assert StyleLearner.inject_into_prompt(None) == ""

    def test_tokenize_words_cjk_only(self):
        """_tokenize_words：纯中文逐字分词"""
        from src.agents.style_learner import StyleLearner

        words = StyleLearner._tokenize_words("你好世界")
        assert words == ["你", "好", "世", "界"]

    def test_tokenize_words_mixed_cjk_latin(self):
        """_tokenize_words：混合中英文分词（英文词长≥2才保留）"""
        from src.agents.style_learner import StyleLearner

        words = StyleLearner._tokenize_words("hello 世界 world AI")
        assert "hello" in words
        assert "world" in words
        assert "世" in words
        assert "界" in words
        # "AI" 长度为 2，应该保留
        assert "ai" in words

    def test_tokenize_words_single_letter_ignored(self):
        """_tokenize_words：单个英文字母被忽略"""
        from src.agents.style_learner import StyleLearner

        words = StyleLearner._tokenize_words("a b c hello")
        assert "hello" in words
        assert "a" not in words
        assert "b" not in words
        assert "c" not in words

    def test_tokenize_words_digits(self):
        """_tokenize_words：数字作为独立 token"""
        from src.agents.style_learner import StyleLearner

        words = StyleLearner._tokenize_words("排名第 1 和第 99")
        assert "1" in words
        assert "9" in words  # "99" → "9", "9" (逐字)


# ══════════════════════════════════════════════════════════════
# T6.3: ReferenceMaterial + ReferenceManager
# ══════════════════════════════════════════════════════════════

class TestReferenceMaterial:
    """ReferenceMaterial 数据模型测试"""

    def test_ref_auto_id_and_created_at(self):
        """创建 ReferenceMaterial 自动填充 id 和 created_at"""
        from src.agents.references import ReferenceMaterial

        ref = ReferenceMaterial(
            project_id="proj-r", title="灵力体系",
            content="灵力分九级...", ref_type="setting",
        )
        assert len(ref.id) == 12
        assert ref.created_at != ""
        assert "T" in ref.created_at

    def test_ref_defaults(self):
        """ReferenceMaterial 默认值"""
        from src.agents.references import ReferenceMaterial

        ref = ReferenceMaterial()
        assert ref.ref_type == "note"
        assert ref.tags == []
        assert ref.title == ""
        assert ref.content == ""

    def test_ref_to_dict(self):
        """to_dict 输出完整字段"""
        from src.agents.references import ReferenceMaterial

        ref = ReferenceMaterial(
            project_id="p1", title="魔法学院",
            content="学院坐落于...", ref_type="setting",
            tags=["魔法", "教育"],
        )
        d = ref.to_dict()
        assert d["title"] == "魔法学院"
        assert d["ref_type"] == "setting"
        assert d["tags"] == ["魔法", "教育"]
        assert len(d["id"]) == 12

    def test_ref_from_dict(self):
        """from_dict 反序列化"""
        from src.agents.references import ReferenceMaterial

        d = {
            "id": "xyz789", "project_id": "p3",
            "title": "妖兽图鉴", "content": "一级妖兽...",
            "ref_type": "research", "tags": ["妖兽", "图鉴"],
            "created_at": "2026-07-01T08:00:00",
        }
        ref = ReferenceMaterial.from_dict(d)
        assert ref.id == "xyz789"
        assert ref.title == "妖兽图鉴"
        assert ref.ref_type == "research"
        assert ref.tags == ["妖兽", "图鉴"]

    def test_ref_from_dict_defaults(self):
        """from_dict 空 dict 使用默认值"""
        from src.agents.references import ReferenceMaterial

        ref = ReferenceMaterial.from_dict({})
        assert ref.ref_type == "note"
        assert ref.tags == []
        assert ref.title == ""


class TestReferenceManager:
    """ReferenceManager CRUD + Search + Inject 测试"""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, monkeypatch):
        """每个测试使用独立的 tmp_path 存储。"""
        import src.agents.references as rmod

        self.tmp_path = tmp_path
        self.project_id = "test-refs-proj"
        monkeypatch.setattr(
            rmod, "_get_refs_path",
            lambda pid: _make_tmp_refs_path(self.tmp_path, pid),
        )
        self.mgr = rmod.ReferenceManager(self.project_id)

    def test_create_ref(self):
        """create 持久化一个参考资料"""
        from src.agents.references import ReferenceMaterial

        ref = ReferenceMaterial(
            title="测试资料", content="这是内容",
            ref_type="note", tags=["test"],
        )
        result = self.mgr.create(ref)
        assert result.id != ""
        assert result.project_id == self.project_id
        assert len(self.mgr.get_all()) == 1

        # 验证持久化
        fpath = _make_tmp_refs_path(self.tmp_path, self.project_id)
        assert fpath.exists()
        data = json.loads(fpath.read_text(encoding="utf-8"))
        assert len(data) == 1

    def test_create_multiple_refs(self):
        """创建多个条目"""
        from src.agents.references import ReferenceMaterial

        for i in range(5):
            ref = ReferenceMaterial(title=f"资料{i}", content=f"内容{i}")
            self.mgr.create(ref)
        assert len(self.mgr.get_all()) == 5

    def test_get_all(self):
        """get_all 返回所有条目"""
        from src.agents.references import ReferenceMaterial

        self.mgr.create(ReferenceMaterial(title="A"))
        self.mgr.create(ReferenceMaterial(title="B"))
        assert len(self.mgr.get_all()) == 2

    def test_get_by_type(self):
        """get_by_type 按类型筛选"""
        from src.agents.references import ReferenceMaterial

        self.mgr.create(ReferenceMaterial(title="设定1", ref_type="setting"))
        self.mgr.create(ReferenceMaterial(title="角色1", ref_type="character"))
        self.mgr.create(ReferenceMaterial(title="设定2", ref_type="setting"))

        settings = self.mgr.get_by_type("setting")
        assert len(settings) == 2
        assert all(r.ref_type == "setting" for r in settings)

        chars = self.mgr.get_by_type("character")
        assert len(chars) == 1

    def test_get_by_type_empty(self):
        """get_by_type 无匹配返回空列表"""
        assert self.mgr.get_by_type("plot") == []

    def test_update_ref(self):
        """update 按 id 更新字段"""
        from src.agents.references import ReferenceMaterial

        ref = ReferenceMaterial(title="旧标题", content="旧内容", tags=["old"])
        created = self.mgr.create(ref)
        assert self.mgr.update(created.id, title="新标题", content="新内容", tags=["new"])
        updated = self.mgr.get_all()[0]
        assert updated.title == "新标题"
        assert updated.content == "新内容"
        assert updated.tags == ["new"]

    def test_update_nonexistent(self):
        """update 不存在的 id 返回 False"""
        assert self.mgr.update("no-such-ref", title="x") is False

    def test_delete_ref(self):
        """delete 按 id 删除"""
        from src.agents.references import ReferenceMaterial

        ref = ReferenceMaterial(title="待删除")
        created = self.mgr.create(ref)
        assert len(self.mgr.get_all()) == 1
        assert self.mgr.delete(created.id) is True
        assert len(self.mgr.get_all()) == 0

    def test_delete_nonexistent(self):
        """delete 不存在的 id 返回 False"""
        assert self.mgr.delete("no-such-ref") is False

    def test_search_by_title(self):
        """search 按标题模糊匹配"""
        from src.agents.references import ReferenceMaterial

        self.mgr.create(ReferenceMaterial(title="灵力修炼法"))
        self.mgr.create(ReferenceMaterial(title="妖兽图鉴"))
        self.mgr.create(ReferenceMaterial(title="丹药配方"))

        results = self.mgr.search("灵力")
        assert len(results) == 1
        assert results[0].title == "灵力修炼法"

    def test_search_by_tag(self):
        """search 按标签匹配"""
        from src.agents.references import ReferenceMaterial

        self.mgr.create(ReferenceMaterial(title="A", tags=["战斗", "灵力"]))
        self.mgr.create(ReferenceMaterial(title="B", tags=["日常", "美食"]))

        results = self.mgr.search("战斗")
        assert len(results) == 1
        assert results[0].title == "A"

    def test_search_by_content(self):
        """search 按内容匹配"""
        from src.agents.references import ReferenceMaterial

        self.mgr.create(ReferenceMaterial(title="X", content="这是一个关于剑法的记录"))
        self.mgr.create(ReferenceMaterial(title="Y", content="关于魔法的研究"))

        results = self.mgr.search("剑法")
        assert len(results) == 1
        assert results[0].title == "X"

    def test_search_empty_query(self):
        """search 空查询返回所有"""
        from src.agents.references import ReferenceMaterial

        self.mgr.create(ReferenceMaterial(title="A"))
        self.mgr.create(ReferenceMaterial(title="B"))
        assert len(self.mgr.search("")) == 2

    def test_search_no_match(self):
        """search 无匹配返回空"""
        from src.agents.references import ReferenceMaterial

        self.mgr.create(ReferenceMaterial(title="A", tags=["x"]))
        assert self.mgr.search("nonexistent") == []

    def test_inject_relevant_matching(self):
        """inject_relevant 按标签匹配并格式化"""
        from src.agents.references import ReferenceMaterial

        self.mgr.create(ReferenceMaterial(
            title="灵力体系", content="九级灵力体系详解",
            tags=["灵力", "体系"], ref_type="setting",
        ))
        self.mgr.create(ReferenceMaterial(
            title="功法列表", content="各种功法汇总",
            tags=["功法"], ref_type="research",
        ))

        result = self.mgr.inject_relevant(["灵力", "战斗"])
        assert "【参考资料】" in result
        assert "灵力体系" in result
        assert "九级灵力体系详解" in result

        # 功法 不匹配标签 "灵力" 或 "战斗"
        assert "功法列表" not in result

    def test_inject_relevant_no_match(self):
        """inject_relevant 无匹配标签返回空"""
        from src.agents.references import ReferenceMaterial

        self.mgr.create(ReferenceMaterial(
            title="灵力体系", tags=["灵力"],
        ))
        assert self.mgr.inject_relevant(["不存在"]) == ""

    def test_inject_relevant_empty_tags(self):
        """inject_relevant 空 tags 返回空"""
        from src.agents.references import ReferenceMaterial

        self.mgr.create(ReferenceMaterial(title="A", tags=["x"]))
        assert self.mgr.inject_relevant([]) == ""

    def test_inject_relevant_empty_library(self):
        """inject_relevant 空库返回空"""
        assert self.mgr.inject_relevant(["灵力"]) == ""

    def test_inject_relevant_token_budget(self):
        """inject_relevant 遵守 token budget 截断"""
        from src.agents.references import ReferenceMaterial

        # 创建多个短内容条目
        for i in range(5):
            self.mgr.create(ReferenceMaterial(
                title=f"资料{i}",
                content=f"第{i}号参考资料",
                tags=["ref"],
            ))

        # 小 budget 只能容纳前几条
        result_small = self.mgr.inject_relevant(["ref"], max_tokens=50)
        assert "【参考资料】" in result_small
        # 不会包含全部 5 条
        assert result_small.count("\n- [") < 5

        # 大 budget 可以容纳所有
        result_large = self.mgr.inject_relevant(["ref"], max_tokens=500)
        assert result_large.count("\n- [") == 5


# ══════════════════════════════════════════════════════════════
# T6.4: UsageRecord + UsageTracker
# ══════════════════════════════════════════════════════════════

class TestUsageRecord:
    """UsageRecord 数据模型测试"""

    def test_record_now(self):
        """UsageRecord.now 自动填充 timestamp"""
        from src.utils.usage_tracker import UsageRecord

        rec = UsageRecord.now(
            project_id="p1", agent_name="writer",
            model="deepseek-v4-flash", prompt_tokens=100,
            completion_tokens=500, latency_ms=3000,
        )
        assert rec.timestamp != ""
        assert "T" in rec.timestamp
        assert rec.project_id == "p1"
        assert rec.agent_name == "writer"
        assert rec.model == "deepseek-v4-flash"
        assert rec.prompt_tokens == 100
        assert rec.completion_tokens == 500
        assert rec.latency_ms == 3000
        assert rec.provider == "opencode"

    def test_record_defaults(self):
        """UsageRecord.now 使用默认值"""
        from src.utils.usage_tracker import UsageRecord

        rec = UsageRecord.now()
        assert rec.project_id == ""
        assert rec.agent_name == ""
        assert rec.model == ""
        assert rec.prompt_tokens == 0
        assert rec.completion_tokens == 0
        assert rec.latency_ms == 0

    def test_record_to_dict(self):
        """to_dict 输出完整字段"""
        from src.utils.usage_tracker import UsageRecord

        rec = UsageRecord(
            timestamp="2026-07-01T12:00:00", project_id="p1",
            agent_name="proofreader", model="deepseek-v4-pro",
            prompt_tokens=200, completion_tokens=300,
            latency_ms=5000, provider="opencode",
        )
        d = rec.to_dict()
        assert d["project_id"] == "p1"
        assert d["agent_name"] == "proofreader"
        assert d["prompt_tokens"] == 200
        assert d["completion_tokens"] == 300
        assert d["latency_ms"] == 5000

    def test_record_from_dict(self):
        """from_dict 反序列化"""
        from src.utils.usage_tracker import UsageRecord

        d = {
            "timestamp": "2026-07-01T10:00:00", "project_id": "p2",
            "agent_name": "writer", "model": "gpt-4o",
            "prompt_tokens": 500, "completion_tokens": 1000,
            "latency_ms": 8000, "provider": "openai",
        }
        rec = UsageRecord.from_dict(d)
        assert rec.project_id == "p2"
        assert rec.model == "gpt-4o"
        assert rec.prompt_tokens == 500
        assert rec.completion_tokens == 1000


class TestUsageTracker:
    """UsageTracker 单例统计测试"""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, monkeypatch):
        """每个测试重置单例并使用 tmp_path 存储。"""
        import src.utils.usage_tracker as umod

        self.tmp_path = tmp_path
        # 强制重置单例
        umod.UsageTracker._instance = None
        # 创建新实例
        self.tracker = umod.UsageTracker()
        self.tracker._storage_path = self.tmp_path / "_usage.jsonl"
        self.tracker.reset()

    def test_singleton(self):
        """UsageTracker 是单例"""
        from src.utils.usage_tracker import UsageTracker

        t1 = UsageTracker()
        t2 = UsageTracker()
        assert t1 is t2

    def test_record_call_adds_to_stats(self):
        """record_call 后 get_global_stats 反映数据"""
        self.tracker.record_call(
            project_id="p1", agent_name="writer",
            model="deepseek-v4-flash",
            prompt_tokens=100, completion_tokens=400,
            latency_ms=2000,
        )
        stats = self.tracker.get_global_stats()
        assert stats["total_calls"] == 1
        assert stats["total_prompt_tokens"] == 100
        assert stats["total_completion_tokens"] == 400
        assert stats["total_tokens"] == 500

    def test_record_call_multiple(self):
        """多次 record_call 累加统计"""
        self.tracker.record_call(
            project_id="p1", agent_name="writer",
            model="flash", prompt_tokens=100, completion_tokens=200,
        )
        self.tracker.record_call(
            project_id="p1", agent_name="proofreader",
            model="flash", prompt_tokens=300, completion_tokens=400,
        )
        stats = self.tracker.get_global_stats()
        assert stats["total_calls"] == 2
        assert stats["total_tokens"] == 1000

    def test_get_project_stats_totals(self):
        """get_project_stats 按项目汇总"""
        self.tracker.record_call(
            project_id="proj-A", agent_name="writer",
            model="flash", prompt_tokens=100, completion_tokens=200,
        )
        self.tracker.record_call(
            project_id="proj-A", agent_name="proofreader",
            model="flash", prompt_tokens=300, completion_tokens=400,
        )
        self.tracker.record_call(
            project_id="proj-B", agent_name="writer",
            model="pro", prompt_tokens=50, completion_tokens=50,
        )

        stats_a = self.tracker.get_project_stats("proj-A")
        assert stats_a["total_calls"] == 2
        assert stats_a["total_tokens"] == 1000

        stats_b = self.tracker.get_project_stats("proj-B")
        assert stats_b["total_calls"] == 1
        assert stats_b["total_tokens"] == 100

        stats_none = self.tracker.get_project_stats("no-such")
        assert stats_none["total_calls"] == 0

    def test_get_project_stats_per_agent(self):
        """get_project_stats 返回 per_agent 分组"""
        self.tracker.record_call(
            project_id="p1", agent_name="writer", model="m1",
            prompt_tokens=100, completion_tokens=200,
        )
        self.tracker.record_call(
            project_id="p1", agent_name="writer", model="m2",
            prompt_tokens=100, completion_tokens=100,
        )
        self.tracker.record_call(
            project_id="p1", agent_name="proofreader", model="m1",
            prompt_tokens=50, completion_tokens=50,
        )

        stats = self.tracker.get_project_stats("p1")
        per_agent = stats["per_agent"]
        assert "writer" in per_agent
        assert per_agent["writer"]["calls"] == 2
        assert per_agent["proofreader"]["calls"] == 1

    def test_get_project_stats_per_model(self):
        """get_project_stats 返回 per_model 分组"""
        self.tracker.record_call(
            project_id="p1", agent_name="a1", model="deepseek-v4-flash",
            prompt_tokens=100, completion_tokens=200,
        )
        self.tracker.record_call(
            project_id="p1", agent_name="a2", model="deepseek-v4-pro",
            prompt_tokens=300, completion_tokens=400,
        )
        self.tracker.record_call(
            project_id="p1", agent_name="a3", model="deepseek-v4-flash",
            prompt_tokens=50, completion_tokens=50,
        )

        stats = self.tracker.get_project_stats("p1")
        per_model = stats["per_model"]
        assert "deepseek-v4-flash" in per_model
        assert per_model["deepseek-v4-flash"]["calls"] == 2
        assert per_model["deepseek-v4-pro"]["calls"] == 1

    def test_get_global_stats_empty(self):
        """空记录的全局统计"""
        stats = self.tracker.get_global_stats()
        assert stats["total_calls"] == 0
        assert stats["total_tokens"] == 0
        assert stats["per_agent"] == {}
        assert stats["per_model"] == {}

    def test_get_global_stats_cost(self):
        """get_global_stats 计算费用估算"""
        self.tracker.record_call(
            project_id="p1", agent_name="writer",
            model="flash", prompt_tokens=5000, completion_tokens=5000,
        )
        stats = self.tracker.get_global_stats()
        # 10000 tokens * $0.001/1K = $0.01
        assert stats["total_cost_usd"] == 0.01
        assert stats["avg_latency_ms"] >= 0

    def test_get_all_records_filtered(self):
        """get_all_records 按 project_id 过滤"""
        self.tracker.record_call(
            project_id="p1", agent_name="a1", model="m1",
            prompt_tokens=10, completion_tokens=10,
        )
        self.tracker.record_call(
            project_id="p2", agent_name="a2", model="m2",
            prompt_tokens=20, completion_tokens=20,
        )
        records_p1 = self.tracker.get_all_records("p1")
        assert len(records_p1) == 1
        assert records_p1[0]["project_id"] == "p1"

    def test_get_all_records_all(self):
        """get_all_records 无参数返回所有"""
        self.tracker.record_call(
            project_id="p1", agent_name="a1", model="m1",
            prompt_tokens=10, completion_tokens=10,
        )
        self.tracker.record_call(
            project_id="p2", agent_name="a2", model="m2",
            prompt_tokens=20, completion_tokens=20,
        )
        assert len(self.tracker.get_all_records()) == 2

    def test_reset_clears_everything(self):
        """reset 清除所有记录和存储文件"""
        self.tracker.record_call(
            project_id="p1", agent_name="a1", model="m1",
            prompt_tokens=100, completion_tokens=200,
        )
        assert self.tracker.get_global_stats()["total_calls"] == 1

        self.tracker.reset()
        stats = self.tracker.get_global_stats()
        assert stats["total_calls"] == 0
        assert stats["total_tokens"] == 0
        assert len(self.tracker._records) == 0
        assert not self.tracker._storage_path.exists()

    def test_record_call_persists(self):
        """record_call 写入 JSONL 文件"""
        self.tracker.record_call(
            project_id="p1", agent_name="writer",
            model="flash", prompt_tokens=100, completion_tokens=200,
        )
        fpath = self.tracker._storage_path
        assert fpath.exists()
        lines = fpath.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["project_id"] == "p1"
        assert data["agent_name"] == "writer"

    def test_unknown_agent_and_model(self):
        """空 agent_name 和 model 归类为 unknown"""
        self.tracker.record_call(
            project_id="p1", agent_name="", model="",
            prompt_tokens=100, completion_tokens=100,
        )
        stats = self.tracker.get_project_stats("p1")
        assert "unknown" in stats["per_agent"]
        assert "unknown" in stats["per_model"]
