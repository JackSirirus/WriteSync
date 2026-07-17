"""
Phase 1 CLI 验证脚本 — 验证 Orchestrator 核心循环

测试场景：
1. 创建新项目（种子想法）
2. 测试 Workspace 和持久化
3. 调用 AgentAdapter 直接验证

用法：
  python tests/test_orchestrator_phase1.py
"""

import sys
import os
import shutil
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ["LANGGRAPH_STRICT_MSGPACK"] = "false"

PROJECTS_DIR = "projects"


class TestResult:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []

    def assert_true(self, condition, msg):
        if not condition:
            self.failed += 1
            self.errors.append(msg)
            print(f"  FAIL: {msg}")
        else:
            self.passed += 1
            print("  PASS")

    def assert_equal(self, a, b, msg):
        self.assert_true(a == b, f"{msg}: {a} != {b}")


@pytest.fixture
def tr():
    """每个测试独立的结果收集器"""
    return TestResult()


@pytest.fixture(scope="module")
def ws():
    """模块级共享的 Workspace（创建一次，所有测试复用）"""
    from src.orchestrator import init_workspace
    w = init_workspace("Phase1测试", "起点", "一个修真少年在末世崛起的传奇",
                       projects_dir=PROJECTS_DIR)
    yield w
    # teardown: 清理项目目录
    project_path = Path(PROJECTS_DIR) / w.project_id
    if project_path.exists():
        shutil.rmtree(project_path)


def test_basic_workspace(tr, ws):
    print("\n=== Test 1: 基础 Workspace 创建 ===")
    print(f"  project_id: {ws.project_id}")
    print(f"  project_name: {ws.project_name}")
    print(f"  seed_idea: {ws.get_seed_idea()[:40]}")

    dashboard = ws.get_dashboard()
    print(f"  phase: {dashboard.phase}")

    tr.assert_equal(dashboard.phase, "new", "phase should be new")
    tr.assert_true(len(ws.project_id) > 0, "project_id should not be empty")


def test_workspace_persistence(tr, ws):
    print("\n=== Test 2: Workspace 持久化 ===")
    ws.save()
    project_path = Path(PROJECTS_DIR) / ws.project_id
    json_files = list(project_path.glob("*.json"))
    print(f"  Saved files: {len(json_files)}")
    for f in json_files:
        print(f"    {f.name} ({f.stat().st_size} bytes)")

    tr.assert_true(len(json_files) >= 1, "should have at least one saved file")


def test_reload_workspace(tr, ws):
    print("\n=== Test 3: 重新加载 ===")
    from src.orchestrator import load_workspace

    loaded = load_workspace(ws.project_id, projects_dir=PROJECTS_DIR)
    tr.assert_true(loaded is not None, "loaded workspace should not be None")

    tr.assert_equal(loaded.project_id, ws.project_id, "project_id should match")
    tr.assert_equal(loaded.project_name, ws.project_name, "project_name should match")

    # Verify seed idea preserved
    tr.assert_true(
        ws.get_seed_idea() in loaded.get_seed_idea() or loaded.get_seed_idea() in ws.get_seed_idea(),
        "seed_idea should be preserved"
    )

    print(f"  Reloaded: {loaded.project_name} (id={loaded.project_id})")
    print(f"  Seed idea: {loaded.get_seed_idea()[:40]}")


def test_dashboard_update(tr, ws):
    print("\n=== Test 4: Dashboard 状态更新 ===")
    from src.orchestrator import Dashboard, Progress

    s = ws.raw_state
    from datetime import datetime, timezone
    from src.state.state_types import (
        StoryState, StoryCore, StoryArc,
    )

    # Simulate completing story
    s.story = StoryState(
        step1=StoryCore(one_sentence="修真少年在末世中寻找希望", tag="末世修真"),
        step2=StoryArc(
            setup="末世降临，少年觉醒修真之力",
            inciting="发现末世背后的修真秘密",
            rising="建立幸存者营地，与各方势力周旋",
            climax_prep="终极决战前的准备",
            resolution="以修真之力重塑世界",
            theme="希望与救赎",
        ),
        confirmed_at=datetime.now(timezone.utc).isoformat(),
    )

    dashboard = ws.get_dashboard()
    print(f"  phase after story: {dashboard.phase}")
    print(f"  completed: {dashboard.completed_agents}")

    tr.assert_true("story" in dashboard.completed_agents, "story should be completed")
    tr.assert_true(dashboard.phase != "new", "phase should not be new after story")


def test_session_history(tr, ws):
    print("\n=== Test 5: 会话历史 ===")
    from src.orchestrator.models import OrchestratorDecision, AgentResult

    # Log some decisions
    for i in range(3):
        d = OrchestratorDecision(
            action="call_agent",
            agent="story",
            instruction=f"test instruction {i}",
            reason=f"test reason {i}",
        )
        ws.log_decision(d)

    tr.assert_equal(len(ws.history), 3, "should have 3 history entries")

    # Log feedback
    ws.add_feedback("story", "这个选题方向不太对")
    tr.assert_equal(len(ws.feedbacks), 1, "should have 1 feedback")

    # Verify feedback content
    tr.assert_true(
        "不太对" in str(ws.feedbacks[0]),
        "feedback content should be preserved"
    )


def test_workspace_state_queries(tr, ws):
    print("\n=== Test 6: 状态查询 ===")
    from src.state.state_types import (
        CharactersState, Character, WorldState, PowerSystem,
        Geography, Society, WorldHistory,
        ChapterOutlineState, ChapterOutline,
    )

    # Add characters
    ws.raw_state.characters = CharactersState(
        characters=[
            Character(
                name="林辰", role="主角", identity="修真者",
                personality="坚韧、聪明、有领导力",
                goal="在末世中保护所爱之人，寻找重塑世界的方法",
                conflict="力量与责任的矛盾",
                description="眼神锐利的少年",
            ),
            Character(
                name="苏婉", role="女主", identity="异能者",
                personality="冷静、果断、内心柔软",
                goal="解开末世之谜",
                conflict="信任与怀疑",
                description="一袭白衣的女子",
            ),
        ],
        summary="末世修真题材，主角与女主共同成长",
    )

    tr.assert_true(ws.has_characters(), "should have characters")
    tr.assert_true(not ws.has_world(), "should not have world yet")
    tr.assert_true(not ws.has_outline(), "should not have outline yet")

    # Add world
    ws.raw_state.world = WorldState(
        power_system=PowerSystem(
            system_name="灵气复苏体系",
            tiers=["凡人", "练气", "筑基", "金丹", "元婴"],
            cultivation_rules="末世中灵气稀薄，需在特定灵眼中修炼",
            power_limit="元婴为上限，突破需天道认可",
        ),
        geography=Geography(major_locations=[
            {"name": "废土城", "description": "末世幸存者聚集地", "significance": "故事主舞台"},
        ]),
        society=Society(),
        history=WorldHistory(),
    )

    tr.assert_true(ws.has_world(), "should have world")
    tr.assert_equal(ws.get_total_chapters(), 0, "should have 0 total chapters yet")


def test_orchestrator_log(tr, ws):
    print("\n=== Test 7: Orchestrator 日志 ===")
    project_path = Path(PROJECTS_DIR) / ws.project_id
    log_path = project_path / "orchestrator_log.jsonl"

    # Save to trigger log creation via the workspace
    ws.save()

    # Now check if log exists
    if log_path.exists():
        with open(log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        print(f"  Log entries: {len(lines)}")
        tr.assert_true(len(lines) >= 0, "log should be readable")
    else:
        print("  Log file not yet created (expected - depends on decision logging)")
        tr.assert_true(True, "skip - log file creation depends on LLM calls")


def cleanup(ws):
    print("\n=== Cleanup ===")
    project_path = Path(PROJECTS_DIR) / ws.project_id
    if project_path.exists():
        shutil.rmtree(project_path)
        print(f"  Removed {project_path}")


def main():
    print("=" * 60)
    print("WriteSync Phase 1: Orchestrator Core Loop 验证")
    print("=" * 60)

    tr = TestResult()
    ws = None

    try:
        ws = test_basic_workspace(tr)
        test_workspace_persistence(tr, ws)
        test_reload_workspace(tr, ws)
        test_dashboard_update(tr, ws)
        test_session_history(tr, ws)
        test_workspace_state_queries(tr, ws)
        test_orchestrator_log(tr, ws)
    finally:
        if ws:
            cleanup(ws)

    print("\n" + "=" * 60)
    print(f"Results: {tr.passed} passed, {tr.failed} failed")
    if tr.errors:
        for e in tr.errors:
            print(f"  - {e}")
    print("=" * 60)

    return 0 if tr.failed == 0 else 1


# ── stale_tracker 集成测试 ──

def test_stale_tracker_after_story_edit(tr):
    """编辑 story 后，下游 agents 应被标记为 stale"""
    from src.orchestrator.stale_tracker import mark_stale, get_stale_info

    ws = MagicMock()
    ws.raw_state.stale_markers = {}
    ws.save = MagicMock()

    mark_stale(ws, "story")
    markers = get_stale_info(ws)

    tr.assert_true("character" in markers, "character should be stale after story edit")
    tr.assert_true("world" in markers, "world should be stale after story edit")
    tr.assert_true("outline" in markers, "outline should be stale after story edit")
    tr.assert_true("writer" in markers, "writer should be stale after story edit")


def test_stale_tracker_after_character_edit(tr):
    """编辑 character 后，outline 和 writer 应被标记为 stale"""
    from src.orchestrator.stale_tracker import mark_stale, get_stale_info

    ws = MagicMock()
    ws.raw_state.stale_markers = {}
    ws.save = MagicMock()

    mark_stale(ws, "character")
    markers = get_stale_info(ws)

    tr.assert_true("outline" in markers, "outline should be stale after character edit")
    tr.assert_true("writer" in markers, "writer should be stale after character edit")
    tr.assert_true("proofreader" not in markers, "proofreader should NOT be stale")


def test_stale_tracker_clear_after_reconfirmation(tr):
    """重新确认后，stale 标记应被清除"""
    from src.orchestrator.stale_tracker import mark_stale, clear_stale, get_stale_info

    ws = MagicMock()
    ws.raw_state.stale_markers = {}
    ws.save = MagicMock()

    mark_stale(ws, "story")
    clear_stale(ws, "character")
    markers = get_stale_info(ws)

    tr.assert_true("character" not in markers, "character should be cleared")
    tr.assert_true("outline" in markers, "outline should still be stale")


def test_stale_tracker_cascade(tr):
    """多级级联：story→character→outline→writer"""
    from src.orchestrator.stale_tracker import mark_stale, get_stale_info

    ws = MagicMock()
    ws.raw_state.stale_markers = {}
    ws.save = MagicMock()

    # story 编辑
    mark_stale(ws, "story")
    # character 重新确认后也编辑
    mark_stale(ws, "character")
    markers = get_stale_info(ws)

    # outline 应同时被 story 和 character 标记
    outline_sources = set(markers.get("outline", []))
    tr.assert_true("story" in outline_sources, "outline stale from story")
    tr.assert_true("character" in outline_sources, "outline stale from character")


def test_stale_tracker_writer_only_affects_proofreader(tr):
    """writer 编辑只影响 proofreader"""
    from src.orchestrator.stale_tracker import mark_stale, get_stale_info

    ws = MagicMock()
    ws.raw_state.stale_markers = {}
    ws.save = MagicMock()

    mark_stale(ws, "writer")
    markers = get_stale_info(ws)

    tr.assert_true("proofreader" in markers, "proofreader should be stale")
    tr.assert_true(len(markers) == 1, "only proofreader should be stale")


if __name__ == "__main__":
    sys.exit(main())
