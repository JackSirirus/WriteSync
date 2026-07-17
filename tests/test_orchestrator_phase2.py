"""
Phase 2 持久化与状态管理测试

测试覆盖：
- schema_version 追踪
- v1→v2 数据迁移
- L1 上下文缓存
- L2 按需深度上下文
- L3 调试日志
- 持久化完整性
"""

import sys
import os
import json
import shutil
import pytest
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ["LANGGRAPH_STRICT_MSGPACK"] = "false"

PROJECTS_DIR = "projects"


@pytest.fixture
def tr():
    """每个测试独立的结果收集器"""
    return TestResult()


class TestResult:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []

    def ok(self, condition, msg):
        if condition:
            self.passed += 1
            print(f"  PASS: {msg}")
        else:
            self.failed += 1
            self.errors.append(msg)
            print(f"  FAIL: {msg}")
        return condition

    def equal(self, a, b, msg):
        ok = a == b
        if ok:
            self.passed += 1
            print(f"  PASS: {msg}")
        else:
            self.failed += 1
            err = f"{msg}: expected {b!r}, got {a!r}"
            self.errors.append(err)
            print(f"  FAIL: {err}")
        return ok


def setup_workspace(tr, seed="一个修真少年的末世传奇"):
    """Helper: create a workspace with some content"""
    from src.orchestrator import init_workspace
    from src.state.state_types import (
        StoryState, StoryCore, StoryArc, CharactersState, Character,
        WorldState, PowerSystem, Geography, Society, WorldHistory,
        ChapterOutlineState, ChapterOutline, ChapterBeat,
    )
    now = datetime.now(timezone.utc).isoformat()

    ws = init_workspace("Phase2Test", "起点", seed)

    ws.raw_state.story = StoryState(
        step1=StoryCore(one_sentence=seed, tag="末世修真"),
        step2=StoryArc(
            setup="末世降临，少年觉醒",
            inciting="发现末世修真秘密",
            rising="建立幸存者营地",
            climax_prep="终极决战准备",
            resolution="重塑世界",
            theme="希望与救赎",
        ),
        confirmed_at=now,
    )

    ws.raw_state.characters = CharactersState(
        characters=[
            Character(name="林辰", role="主角", identity="修真者",
                      personality="坚韧、聪明", goal="保护所爱",
                      conflict="力量与责任", description="锐利少年"),
            Character(name="苏婉", role="女主", identity="异能者",
                      personality="冷静、果断", goal="解开末世之谜",
                      conflict="信任与怀疑", description="白衣女子"),
        ],
        summary="末世双主角",
        confirmed_at=now,
    )

    ws.raw_state.world = WorldState(
        power_system=PowerSystem(
            system_name="灵气复苏",
            tiers=["凡人", "练气", "筑基", "金丹", "元婴"],
            cultivation_rules="末世灵气稀薄，需灵眼修炼",
            power_limit="元婴",
            special_abilities=["神识", "御剑", "阵法"],
        ),
        geography=Geography(
            major_locations=[
                {"name": "废土城", "description": "末世幸存者聚集地", "significance": "故事主舞台"},
                {"name": "天渊", "description": "末世源头深渊", "significance": "终极战场"},
            ],
            political_division="城邦割据",
        ),
        society=Society(
            factions=[
                {"name": "修真同盟", "description": "幸存修真者组织", "align": "中立"},
                {"name": "末世猎手", "description": "掠夺资源者", "align": "反派"},
            ],
        ),
        history=WorldHistory(
            key_events=["灵气枯竭", "末世降临", "修真觉醒"],
        ),
    )

    chs = []
    for i in range(1, 6):
        chs.append(ChapterOutline(
            chapter_number=i,
            chapter_title=f"第{i}章测试标题",
            core_event=f"核心事件{i}",
            character_states=f"角色状态变化{i}",
            story_progression=f"推进点{i}",
            estimated_word_count=4000,
            scenes=[ChapterBeat(
                scene_id=f"ch{i:02d}_s01",
                location="废土城",
                time_period="白天",
                pov_character="林辰",
                purpose=f"场景{i}目的",
                conflict=f"冲突{i}",
            )],
        ))

    ws.raw_state.chapter_outline = ChapterOutlineState(
        total_chapters=5,
        chapters=chs,
        word_count_plan=20000,
    )

    return ws


def test_schema_version(tr):
    print("\n=== Test 1: Schema 版本追踪 ===")
    from src.orchestrator import init_workspace

    ws = init_workspace("SchemaTest", "起点")
    tr.equal(ws.schema_version, 2, "新项目 schema 应为 2")
    tr.ok(not ws.needs_migration(), "新项目不需迁移")

    sc_path = Path(PROJECTS_DIR) / ws.project_id / "schema_version.json"
    tr.ok(sc_path.exists(), "schema_version.json 应存在")

    loaded = json.loads(sc_path.read_text(encoding="utf-8"))
    tr.equal(loaded.get("schema_version"), 2, "文件中的 version 应为 2")

    cleanup(ws)
    return True


def test_context_cache_build(tr):
    print("\n=== Test 2: L1 上下文缓存构建 ===")
    ws = setup_workspace(tr)
    ws.build_context_cache()

    # 验证各字段
    char_summary = ws.get_l1_summary("characters_summary")
    tr.ok(len(char_summary) > 0, "角色摘要非空")
    tr.ok("林辰" in char_summary, "角色摘要含主角名")
    tr.ok(len(char_summary) <= 800, "角色摘要 ≤ 800 字")

    world_summary = ws.get_l1_summary("world_summary")
    tr.ok(len(world_summary) > 0, "世界观摘要非空")
    tr.ok("灵气复苏" in world_summary, "世界观摘要含体系名")
    tr.ok(len(world_summary) <= 800, "世界观摘要 ≤ 800 字")

    outline_summary = ws.get_l1_summary("outline_summary")
    tr.ok(len(outline_summary) > 0, "章纲摘要非空")
    tr.ok("5章" in outline_summary, "章纲摘要含总章数")

    l1_text = ws.get_l1_context_for_prompt()
    tr.ok(len(l1_text) > 0, "L1 上下文文本非空")

    cleanup(ws)
    return True


def test_l2_deep_context(tr):
    print("\n=== Test 3: L2 深度上下文 ===")
    ws = setup_workspace(tr)

    # 请求角色全文
    ctx = ws.get_l2_context(["characters_full"])
    tr.ok(len(ctx) > 100, "L2 角色全文应有足够长度")
    tr.ok("林辰" in ctx and "苏婉" in ctx, "L2 角色含所有角色")
    tr.ok("完整角色卡" in ctx, "L2 角色含标记")

    # 请求世界观全文
    ctx = ws.get_l2_context(["world_full"])
    tr.ok("灵气复苏" in ctx, "L2 世界观含体系")
    tr.ok("废土城" in ctx, "L2 世界观含地点")
    tr.ok("完整世界观" in ctx, "L2 世界观含标记")

    # 请求章纲全文
    ctx = ws.get_l2_context(["outline_full"])
    tr.ok("完整章纲" in ctx, "L2 章纲含标记")
    for i in range(1, 6):
        tr.ok(f"第{i}章" in ctx, f"L2 章纲含第{i}章")

    # 组合请求
    ctx = ws.get_l2_context(["characters_full", "outline_full"])
    tr.ok(len(ctx) > 500, "L2 组合请求应有足够长度")

    # 空请求
    ctx = ws.get_l2_context([])
    tr.equal(ctx, "", "空请求返回空字符串")

    cleanup(ws)
    return True


def test_persistence_roundtrip(tr):
    print("\n=== Test 4: 持久化往返 ===")
    from src.orchestrator import Workspace

    ws = setup_workspace(tr)
    ws.build_context_cache()
    from src.orchestrator.models import OrchestratorDecision
    ws.log_decision(OrchestratorDecision(
        action="call_agent", agent="story",
        instruction="测试", reason="持久化测试",
    ))
    ws.add_feedback("story", "测试反馈")

    # 保存
    ws.save()
    pid = ws.project_id

    # 验证文件存在
    project_path = Path(PROJECTS_DIR) / pid
    tr.ok((project_path / "metadata.json").exists(), "metadata.json")
    tr.ok((project_path / "story.json").exists(), "story.json")
    tr.ok((project_path / "characters.json").exists(), "characters.json")
    tr.ok((project_path / "world.json").exists(), "world.json")
    tr.ok((project_path / "chapter_outline.json").exists(), "chapter_outline.json")
    tr.ok((project_path / "context_cache.json").exists(), "context_cache.json")
    tr.ok((project_path / "schema_version.json").exists(), "schema_version.json")

    # 重新加载
    loaded = Workspace.load(pid)

    tr.ok(loaded is not None, "重新加载成功")
    tr.equal(loaded.project_id, pid, "ID 一致")
    tr.equal(loaded.schema_version, 2, "schema 一致")
    tr.ok(loaded.has_story(), "故事恢复")
    tr.ok(loaded.has_characters(), "角色恢复")
    tr.ok(loaded.has_world(), "世界观恢复")
    tr.ok(loaded.has_outline(), "章纲恢复")

    # 验证上下文缓存恢复
    char_s = loaded.get_l1_summary("characters_summary")
    tr.ok(len(char_s) > 0, "角色摘要恢复")
    tr.ok("林辰" in char_s, "角色摘要内容正确")

    # 验证反馈恢复
    tr.ok(len(loaded.feedbacks) >= 1, "反馈恢复")
    tr.ok("测试反馈" in str(loaded.feedbacks), "反馈内容正确")

    cleanup(ws)
    return True


def test_v1_to_v2_migration(tr):
    print("\n=== Test 5: v1→v2 数据迁移 ===")
    from src.orchestrator import Workspace
    from src.state.persistence import PersistenceManager

    pm = PersistenceManager(PROJECTS_DIR)
    ws_state = pm.create_project("MigrationTest", "起点")
    project_dir = Path(PROJECTS_DIR) / ws_state.metadata.project_id

    # 不创建 schema_version.json（模拟 v1 项目）
    tr.ok(not (project_dir / "schema_version.json").exists(), "模拟 v1 项目（无 schema 文件）")

    # 创建 Workspace（auto_migrate=True）
    ws = Workspace(ws_state, str(project_dir))

    # 加载时 schema_version 应为 1（v1 项目无文件时默认 1）
    tr.equal(ws.schema_version, 1, "v1 项目检测到 schema=1")
    tr.ok(ws.needs_migration(), "v1 项目需要迁移")

    # 执行迁移
    changes = ws.migrate()
    tr.ok(len(changes) > 0, f"迁移产生变更: {changes}")
    tr.equal(ws.schema_version, 2, "迁移后 schema=2")
    tr.ok(not ws.needs_migration(), "迁移后不再需要迁移")

    # 验证 schema_version.json 已创建
    tr.ok((project_dir / "schema_version.json").exists(), "迁移后 schema 文件已创建")

    # 验证 context_cache.json 已创建
    tr.ok((project_dir / "context_cache.json").exists(), "迁移后 context_cache 文件已创建")

    # 重新加载，验证不再需要迁移
    loaded = Workspace.load(ws_state.metadata.project_id)
    tr.equal(loaded.schema_version, 2, "重新加载后 schema=2")
    tr.ok(not loaded.needs_migration(), "重新加载后不需迁移")

    cleanup(ws)
    return True


def test_orchestrator_log(tr):
    print("\n=== Test 6: L3 调试日志 ===")
    ws = setup_workspace(tr)

    # 模拟一些决策和结果
    from src.orchestrator.models import OrchestratorDecision, AgentResult

    for i in range(5):
        d = OrchestratorDecision(
            action="call_agent",
            agent="story",
            instruction=f"测试指令 {i}",
            reason=f"测试理由 {i}",
        )
        ws.log_decision(d)

    for i in range(3):
        r = AgentResult(
            agent="story",
            content={"stage": "topics", "count": i},
            requires_confirmation=True,
            summary=f"摘要 {i}",
        )
        ws.log_agent_result(r)

    # 验证日志文件
    log_path = Path(PROJECTS_DIR) / ws.project_id / "orchestrator_log.jsonl"
    tr.ok(log_path.exists(), "日志文件存在")

    # 读取日志
    records = ws.read_orchestrator_log()
    tr.ok(len(records) >= 8, f"日志记录数应 ≥ 8，实际 {len(records)}")

    # 验证类型分布
    types = [r.get("type") for r in records if "type" in r]
    tr.ok("decision" in types, "日志含 decision 记录")
    tr.ok("agent_result" in types, "日志含 agent_result 记录")

    # 验证 JSONL 格式
    with open(log_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    for i, line in enumerate(lines):
        try:
            json.loads(line.strip())
        except json.JSONDecodeError:
            tr.ok(False, f"第{i+1}行 JSON 解析失败")
            break
    else:
        tr.ok(True, "所有日志行均为合法 JSONL")

    cleanup(ws)
    return True


def test_context_cache_persistence(tr):
    print("\n=== Test 7: 上下文缓存持久化 ===")
    ws = setup_workspace(tr)
    ws.build_context_cache()

    original_char = ws.get_l1_summary("characters_summary")
    ws.save()

    # 重新加载
    from src.orchestrator import Workspace
    loaded = Workspace.load(ws.project_id)

    tr.equal(
        loaded.get_l1_summary("characters_summary"),
        original_char,
        "角色摘要持久化一致"
    )

    # 更新后重新保存和加载
    ws.raw_state.characters.characters.append(
        __import__('src.state.state_types', fromlist=['Character']).Character(
            name="新角色", role="配角", identity="商人",
            personality="精明", goal="获利", conflict="贪婪",
            description="胖商人",
        )
    )
    ws.build_context_cache()
    ws.save()

    loaded2 = Workspace.load(ws.project_id)
    tr.ok("新角色" in loaded2.get_l1_summary("characters_summary"),
          "上下文缓存随状态更新")

    cleanup(ws)
    return True


def cleanup(ws):
    project_path = Path(PROJECTS_DIR) / ws.project_id
    if project_path.exists():
        shutil.rmtree(project_path)


def main():
    print("=" * 60)
    print("WriteSync Phase 2: 持久化与状态管理 验证")
    print("=" * 60)

    tr = TestResult()

    tests = [
        ("Schema 版本追踪", test_schema_version),
        ("L1 上下文缓存", test_context_cache_build),
        ("L2 深度上下文", test_l2_deep_context),
        ("持久化往返", test_persistence_roundtrip),
        ("v1→v2 迁移", test_v1_to_v2_migration),
        ("L3 调试日志", test_orchestrator_log),
        ("上下文缓存持久化", test_context_cache_persistence),
    ]

    for name, fn in tests:
        try:
            fn(tr)
        except Exception as e:
            tr.ok(False, f"{name}: 异常 - {e}")
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 60)
    print(f"Results: {tr.passed} passed, {tr.failed} failed")
    if tr.errors:
        for e in tr.errors:
            print(f"  - {e}")
    print("=" * 60)

    return 0 if tr.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
