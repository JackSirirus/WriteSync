"""
测试：PersistenceManager 持久化层

覆盖：save/load/create_project/list_projects/create_snapshot/rollback_to_version
"""

import sys, os, tempfile, json, shutil
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["LANGGRAPH_STRICT_MSGPACK"] = "false"

from datetime import datetime
from pathlib import Path
from src.state.persistence import PersistenceManager
from src.state.state_types import (
    WriteSyncState, ProjectMetadata, StepName, ProjectStatus, WorkflowState,
    TopicState, TopicSuggestion, PlatformFit, StoryState, StoryCore, StoryArc,
    CharactersState, Character, VersionState, VersionSnapshot,
)


def test_create_and_save_project():
    """创建项目并保存到临时目录"""
    with tempfile.TemporaryDirectory() as tmpdir:
        pm = PersistenceManager(projects_dir=tmpdir)
        state = pm.create_project(name="测试小说", platform="起点")

        assert state.metadata.name == "测试小说"
        assert state.metadata.platform == "起点"
        assert state.metadata.project_id, "project_id should be generated"
        assert state.metadata.status == ProjectStatus.DRAFTING
        assert state.workflow.current_step == StepName.TOPIC

        # 验证文件被写入
        project_dir = Path(tmpdir) / state.metadata.project_id
        assert project_dir.exists()
        assert (project_dir / "metadata.json").exists()
        assert (project_dir / "workflow.json").exists()

        pm.close()
        print("  PASS: test_create_and_save_project")


def test_save_and_load_roundtrip():
    """保存后重新加载，验证数据一致性"""
    with tempfile.TemporaryDirectory() as tmpdir:
        pm = PersistenceManager(projects_dir=tmpdir)
        state = pm.create_project(name="测试", platform="起点")

        # 添加一些业务数据
        state.topic = TopicState(
            user_original_idea="修仙逆袭",
            suggestions=[
                TopicSuggestion(
                    title="仙途", genre="仙侠", sub_genre="修仙",
                    core_selling_point="凡人逆袭",
                    target_audience="男频",
                    competitive_analysis="热门题材",
                    platform_fit=PlatformFit(heat_level="热门", difficulty="红海", reader_preference="高"),
                    inspiration_source="修仙",
                ),
            ],
            selected=0,
            confirmed_at=datetime.now().isoformat(),
        )

        # 保存
        pm.save_project(state)

        # 重新加载
        loaded = pm.load_project(state.metadata.project_id)
        assert loaded is not None
        assert loaded.metadata.name == "测试"
        assert loaded.metadata.platform == "起点"
        assert loaded.topic is not None
        assert loaded.topic.user_original_idea == "修仙逆袭"
        assert len(loaded.topic.suggestions) == 1
        assert loaded.topic.suggestions[0].title == "仙途"
        assert loaded.topic.selected == 0

        pm.close()
        print("  PASS: test_save_and_load_roundtrip")


def test_list_projects():
    """列出所有项目"""
    with tempfile.TemporaryDirectory() as tmpdir:
        pm = PersistenceManager(projects_dir=tmpdir)
        p1 = pm.create_project(name="小说A", platform="起点")
        p2 = pm.create_project(name="小说B", platform="番茄")

        projects = pm.list_projects()
        assert len(projects) == 2
        names = [p["name"] for p in projects]
        assert "小说A" in names
        assert "小说B" in names

        pm.close()
        print("  PASS: test_list_projects")


def test_create_snapshot():
    """创建版本快照"""
    with tempfile.TemporaryDirectory() as tmpdir:
        pm = PersistenceManager(projects_dir=tmpdir)
        state = pm.create_project(name="测试", platform="起点")

        state.story = StoryState(
            step1=StoryCore(one_sentence="少年修仙", tag="仙侠"),
            step2=StoryArc(setup="山村", inciting="传承", rising="修炼", climax_prep="决战", resolution="飞升"),
        )

        version = pm.create_snapshot(state, StepName.STORY1, user_note="第一版")
        assert version == 1
        assert state.versions.current_version == 1
        assert len(state.versions.snapshots) == 1

        # 第二次快照
        state.characters = CharactersState(characters=[Character(name="林逸", role="主角", identity="少年", personality="坚韧", goal="变强", conflict="心魔", description="")])
        version2 = pm.create_snapshot(state, StepName.CHARACTERS, user_note="加入角色")
        assert version2 == 2

        pm.close()
        print("  PASS: test_create_snapshot")


def test_rollback():
    """回滚到指定版本"""
    with tempfile.TemporaryDirectory() as tmpdir:
        pm = PersistenceManager(projects_dir=tmpdir)
        state = pm.create_project(name="测试", platform="起点")

        # V1: 有故事
        state.story = StoryState(
            step1=StoryCore(one_sentence="V1故事", tag="仙侠"),
            step2=StoryArc(setup="a", inciting="b", rising="c", climax_prep="d", resolution="e"),
        )
        pm.create_snapshot(state, StepName.STORY1, user_note="V1")

        # V2: 改故事
        state.story.step1.one_sentence = "V2故事"
        pm.create_snapshot(state, StepName.STORY1, user_note="V2")

        # 回滚到 V1
        success = pm.rollback_to_version(state, 1)
        assert success
        assert state.story.step1.one_sentence == "V1故事"
        assert state.versions.current_version == 2  # current_version 不减

        pm.close()
        print("  PASS: test_rollback")


def test_load_nonexistent():
    """加载不存在的项目返回 None"""
    with tempfile.TemporaryDirectory() as tmpdir:
        pm = PersistenceManager(projects_dir=tmpdir)
        result = pm.load_project("nonexistent")
        assert result is None
        pm.close()
        print("  PASS: test_load_nonexistent")


def test_empty_list():
    """空目录列出空列表"""
    with tempfile.TemporaryDirectory() as tmpdir:
        pm = PersistenceManager(projects_dir=tmpdir)
        projects = pm.list_projects()
        assert projects == []
        pm.close()
        print("  PASS: test_empty_list")


if __name__ == "__main__":
    test_create_and_save_project()
    test_save_and_load_roundtrip()
    test_list_projects()
    test_create_snapshot()
    test_rollback()
    test_load_nonexistent()
    test_empty_list()
    print("\nAll persistence tests PASSED")
