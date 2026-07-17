"""
Phase 4 单元测试 — 伏笔追踪 / 状态表 / 物品栏 / 灵感反推

覆盖 T4.1, T4.2, T4.3
"""
import sys
import os
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ["LANGGRAPH_STRICT_MSGPACK"] = "false"


# ──────────────────────────────────────────────────────────────
# T4.1: GlobalForeshadow CRUD + 看板 + 联动
# ──────────────────────────────────────────────────────────────

class TestGlobalForeshadowCRUD:
    """GlobalForeshadow 数据模型 + ForeshadowManager CRUD"""

    def test_foreshadow_auto_id(self):
        """GlobalForeshadow 自动生成 MD5 ID"""
        from src.agents.foreshadow import GlobalForeshadow

        fs = GlobalForeshadow(project_id="p1", title="神秘戒指", planted_chapter=3)
        assert len(fs.id) == 12
        assert fs.status == "planned"

    def test_foreshadow_to_dict(self):
        """to_dict 输出完整字段"""
        from src.agents.foreshadow import GlobalForeshadow

        fs = GlobalForeshadow(
            project_id="p1", title="伏笔A", description="测试描述",
            type="mystery", status="planted", planted_chapter=5,
            urgency=4, deadline_chapter=10,
        )
        d = fs.to_dict()
        assert d["title"] == "伏笔A"
        assert d["type"] == "mystery"
        assert d["urgency"] == 4
        assert d["deadline_chapter"] == 10

    def test_foreshadow_from_dict(self):
        """from_dict 反序列化"""
        from src.agents.foreshadow import GlobalForeshadow

        d = {
            "id": "abc123", "project_id": "p1", "title": "测试",
            "description": "desc", "type": "item", "status": "called_back",
            "planted_chapter": 2, "callback_chapters": [5, 8],
            "resolved_chapter": 0, "urgency": 5,
        }
        fs = GlobalForeshadow.from_dict(d)
        assert fs.id == "abc123"
        assert fs.callback_chapters == [5, 8]
        assert fs.urgency == 5

    def test_foreshadow_from_dict_defaults(self):
        """from_dict 缺失字段用默认值"""
        from src.agents.foreshadow import GlobalForeshadow

        fs = GlobalForeshadow.from_dict({})
        assert fs.type == "plot"
        assert fs.status == "planned"
        assert fs.urgency == 3

    def test_foreshadow_manager_create(self):
        """ForeshadowManager.create 去重"""
        from src.agents.foreshadow import ForeshadowManager, GlobalForeshadow

        ws = MagicMock()
        ws.context_cache = {}
        mgr = ForeshadowManager(ws)

        fs = GlobalForeshadow(project_id="p1", title="伏笔1", planted_chapter=1)
        mgr.create(fs)
        mgr.create(fs)  # 重复创建
        assert len(mgr.get_all()) == 1

    def test_foreshadow_manager_update(self):
        """ForeshadowManager.update 修改字段"""
        from src.agents.foreshadow import ForeshadowManager, GlobalForeshadow

        ws = MagicMock()
        ws.context_cache = {}
        mgr = ForeshadowManager(ws)

        fs = GlobalForeshadow(project_id="p1", title="伏笔1", planted_chapter=1)
        mgr.create(fs)
        ok = mgr.update(fs.id, status="planted", urgency=5)
        assert ok is True
        assert mgr.get(fs.id).status == "planted"
        assert mgr.get(fs.id).urgency == 5

    def test_foreshadow_manager_update_not_found(self):
        """ForeshadowManager.update 不存在的 ID 返回 False"""
        from src.agents.foreshadow import ForeshadowManager

        ws = MagicMock()
        ws.context_cache = {}
        mgr = ForeshadowManager(ws)
        assert mgr.update("nonexistent", status="resolved") is False

    def test_foreshadow_manager_delete(self):
        """ForeshadowManager.delete 删除"""
        from src.agents.foreshadow import ForeshadowManager, GlobalForeshadow

        ws = MagicMock()
        ws.context_cache = {}
        mgr = ForeshadowManager(ws)

        fs = GlobalForeshadow(project_id="p1", title="伏笔1", planted_chapter=1)
        mgr.create(fs)
        ok = mgr.delete(fs.id)
        assert ok is True
        assert mgr.get(fs.id) is None

    def test_foreshadow_manager_delete_not_found(self):
        """ForeshadowManager.delete 不存在的 ID 返回 False"""
        from src.agents.foreshadow import ForeshadowManager

        ws = MagicMock()
        ws.context_cache = {}
        mgr = ForeshadowManager(ws)
        assert mgr.delete("nonexistent") is False

    def test_foreshadow_manager_list_by_project(self):
        """list_by_project 按项目过滤"""
        from src.agents.foreshadow import ForeshadowManager, GlobalForeshadow

        ws = MagicMock()
        ws.context_cache = {}
        mgr = ForeshadowManager(ws)

        mgr.create(GlobalForeshadow(project_id="p1", title="A", planted_chapter=1))
        mgr.create(GlobalForeshadow(project_id="p2", title="B", planted_chapter=1))
        mgr.create(GlobalForeshadow(project_id="p1", title="C", planted_chapter=2))

        p1 = mgr.list_by_project("p1")
        assert len(p1) == 2
        assert all(f.project_id == "p1" for f in p1)

    def test_foreshadow_manager_persist_cache(self):
        """save 写入 context_cache"""
        from src.agents.foreshadow import ForeshadowManager, GlobalForeshadow

        ws = MagicMock()
        ws.context_cache = {}
        mgr = ForeshadowManager(ws)

        mgr.create(GlobalForeshadow(project_id="p1", title="X", planted_chapter=1))
        cached = ws.context_cache.get("global_foreshadows")
        assert cached is not None
        data = json.loads(cached)
        assert len(data) == 1
        assert data[0]["title"] == "X"

    def test_foreshadow_manager_load_from_cache(self):
        """从 context_cache 加载已有伏笔"""
        from src.agents.foreshadow import ForeshadowManager

        ws = MagicMock()
        ws.context_cache = {
            "global_foreshadows": json.dumps([
                {"id": "existing", "project_id": "p1", "title": "已存在",
                 "planted_chapter": 3, "status": "planted"}
            ])
        }
        mgr = ForeshadowManager(ws)
        assert len(mgr.get_all()) == 1
        assert mgr.get("existing").title == "已存在"


# ──────────────────────────────────────────────────────────────
# T4.1: 看板 + 状态过滤 + Writer Prompt 注入
# ──────────────────────────────────────────────────────────────

class TestForeshadowKanban:
    """看板视图 + writer prompt injection"""

    def _make_mgr_with_foreshadows(self):
        """创建带预设伏笔的 manager"""
        from src.agents.foreshadow import ForeshadowManager, GlobalForeshadow

        ws = MagicMock()
        ws.context_cache = {}
        mgr = ForeshadowManager(ws)

        mgr.create(GlobalForeshadow(project_id="p1", title="计划中", status="planned", planted_chapter=0))
        mgr.create(GlobalForeshadow(project_id="p1", title="已埋设", status="planted", planted_chapter=3))
        mgr.create(GlobalForeshadow(project_id="p1", title="已呼应", status="called_back", planted_chapter=2))
        mgr.create(GlobalForeshadow(project_id="p1", title="已回收", status="resolved", planted_chapter=1))
        return mgr

    def test_get_by_status(self):
        """按状态过滤"""
        mgr = self._make_mgr_with_foreshadows()
        assert len(mgr.get_foreshadows_by_status("planned")) == 1
        assert len(mgr.get_foreshadows_by_status("planted")) == 1
        assert len(mgr.get_foreshadows_by_status("called_back")) == 1
        assert len(mgr.get_foreshadows_by_status("resolved")) == 1

    def test_kanban_data(self):
        """看板数据包含4列"""
        mgr = self._make_mgr_with_foreshadows()
        kb = mgr.get_kanban_data()
        assert "planned" in kb
        assert "planted" in kb
        assert "called_back" in kb
        assert "resolved" in kb
        assert len(kb["planned"]) == 1
        assert kb["planned"][0]["title"] == "计划中"

    def test_active_foreshadows_exclude_resolved(self):
        """get_active_foreshadows 排除已回收"""
        mgr = self._make_mgr_with_foreshadows()
        active = mgr.get_active_foreshadows("p1", up_to_chapter=10)
        titles = [f.title for f in active]
        assert "已回收" not in titles
        assert "已呼应" in titles
        assert "已埋设" in titles

    def test_writer_prompt_injection_no_foreshadows(self):
        """无伏笔时返回空字符串"""
        from src.agents.foreshadow import ForeshadowManager
        ws = MagicMock()
        ws.context_cache = {}
        mgr = ForeshadowManager(ws)
        assert mgr.inject_into_writer_prompt("p1", up_to_chapter=5) == ""

    def test_writer_prompt_injection_with_foreshadows(self):
        """有伏笔时返回格式化提示"""
        from src.agents.foreshadow import ForeshadowManager, GlobalForeshadow

        ws = MagicMock()
        ws.context_cache = {}
        mgr = ForeshadowManager(ws)

        mgr.create(GlobalForeshadow(
            project_id="p1", title="神秘力量", description="主角隐藏的血脉",
            type="mystery", status="planted", planted_chapter=2, urgency=4,
            deadline_chapter=10,
        ))
        mgr.create(GlobalForeshadow(
            project_id="p1", title="古老契约", description="与魔族的契约",
            type="plot", status="planted", planted_chapter=5, urgency=3,
        ))

        prompt = mgr.inject_into_writer_prompt("p1", up_to_chapter=8)
        assert "2 个待呼应伏笔" in prompt
        assert "神秘力量" in prompt
        assert "古老契约" in prompt

    def test_writer_prompt_injection_sorted_by_urgency(self):
        """伏笔按紧急度排序"""
        from src.agents.foreshadow import ForeshadowManager, GlobalForeshadow

        ws = MagicMock()
        ws.context_cache = {}
        mgr = ForeshadowManager(ws)

        mgr.create(GlobalForeshadow(project_id="p1", title="低优", status="planted", urgency=1, planted_chapter=1))
        mgr.create(GlobalForeshadow(project_id="p1", title="高优", status="planted", urgency=5, planted_chapter=2))

        prompt = mgr.inject_into_writer_prompt("p1", up_to_chapter=5)
        high_pos = prompt.find("高优")
        low_pos = prompt.find("低优")
        assert high_pos < low_pos

    def test_writer_prompt_injection_max_tokens(self):
        """max_tokens 限制输出长度"""
        from src.agents.foreshadow import ForeshadowManager, GlobalForeshadow

        ws = MagicMock()
        ws.context_cache = {}
        mgr = ForeshadowManager(ws)

        for i in range(20):
            mgr.create(GlobalForeshadow(
                project_id="p1", title=f"伏笔{i:02d}",
                description=f"描述{'长' * 40}",
                status="planted", planted_chapter=i + 1, urgency=3,
            ))

        prompt = mgr.inject_into_writer_prompt("p1", up_to_chapter=20, max_tokens=100)
        # Should be limited
        assert len(prompt) < 2000


# ──────────────────────────────────────────────────────────────
# T4.1: 关键词提取
# ──────────────────────────────────────────────────────────────

class TestForeshadowKeywordExtract:
    """关键词降级提取"""

    def test_keyword_extract_finds_patterns(self):
        """从正文中识别伏笔语言模式"""
        from src.agents.foreshadow import ForeshadowManager

        ws = MagicMock()
        ws.context_cache = {}
        mgr = ForeshadowManager(ws)

        content = (
            "他不知道的是，这枚古老的戒指将在日后拯救整个大陆。"
            "此时他还不知道，戒指中隐藏着一个远古神灵的残魂。"
        )
        results = mgr._keyword_extract(content, chapter_num=3, project_id="p1")
        assert len(results) >= 1
        assert all(f.planted_chapter == 3 for f in results)

    def test_keyword_extract_dedup(self):
        """同一伏笔不重复提取"""
        from src.agents.foreshadow import ForeshadowManager

        ws = MagicMock()
        ws.context_cache = {}
        mgr = ForeshadowManager(ws)

        content = "日后才知道真相。后来才知道真相。"
        results = mgr._keyword_extract(content, chapter_num=1, project_id="p1")
        titles = [f.title for f in results]
        # Should deduplicate similar patterns
        assert len(set(titles)) == len(titles)

    def test_keyword_extract_empty_content(self):
        """空内容返回空列表"""
        from src.agents.foreshadow import ForeshadowManager

        ws = MagicMock()
        ws.context_cache = {}
        mgr = ForeshadowManager(ws)
        assert mgr._keyword_extract("", chapter_num=1, project_id="p1") == []


# ──────────────────────────────────────────────────────────────
# T4.1: apply_extraction 合并逻辑
# ──────────────────────────────────────────────────────────────

class TestForeshadowApplyExtraction:
    """apply_extraction 合并逻辑"""

    def test_apply_adds_new_foreshadows(self):
        """新伏笔被添加"""
        from src.agents.foreshadow import ForeshadowManager, GlobalForeshadow

        ws = MagicMock()
        ws.context_cache = {}
        mgr = ForeshadowManager(ws)

        new = [GlobalForeshadow(project_id="p1", title="新伏笔", planted_chapter=5)]
        mgr.apply_extraction(new, chapter_num=5)
        assert len(mgr.get_all()) == 1

    def test_apply_updates_status(self):
        """已有伏笔状态更新"""
        from src.agents.foreshadow import ForeshadowManager, GlobalForeshadow

        ws = MagicMock()
        ws.context_cache = {}
        mgr = ForeshadowManager(ws)

        # 初始埋设
        mgr.create(GlobalForeshadow(project_id="p1", title="伏笔A", status="planted", planted_chapter=3))

        # LLM 提取到呼应
        new = [GlobalForeshadow(project_id="p1", title="伏笔A", status="called_back", planted_chapter=3)]
        mgr.apply_extraction(new, chapter_num=8)

        fs = mgr.get_all()[0]
        assert fs.status == "called_back"
        assert 8 in fs.callback_chapters

    def test_apply_resolves(self):
        """已有伏笔状态变为 resolved"""
        from src.agents.foreshadow import ForeshadowManager, GlobalForeshadow

        ws = MagicMock()
        ws.context_cache = {}
        mgr = ForeshadowManager(ws)

        mgr.create(GlobalForeshadow(project_id="p1", title="伏笔B", status="called_back", planted_chapter=2))

        new = [GlobalForeshadow(project_id="p1", title="伏笔B", status="resolved", planted_chapter=2)]
        mgr.apply_extraction(new, chapter_num=12)

        fs = mgr.get_all()[0]
        assert fs.status == "resolved"
        assert fs.resolved_chapter == 12


# ──────────────────────────────────────────────────────────────
# T4.2: 状态表 StateTable
# ──────────────────────────────────────────────────────────────

class TestStateTable:
    """CharacterState + StateTable CRUD"""

    def test_character_state_auto_id(self):
        """CharacterState 自动生成 ID"""
        from src.agents.state_table import CharacterState

        cs = CharacterState(project_id="p1", character_name="林逸")
        assert len(cs.character_id) == 12

    def test_character_state_to_dict(self):
        """to_dict 输出完整字段"""
        from src.agents.state_table import CharacterState

        cs = CharacterState(
            project_id="p1", character_name="林逸",
            current_location="青云山", current_status="修炼",
            health_state="完好", held_items=["长剑", "丹药"],
            last_updated_chapter=5,
        )
        d = cs.to_dict()
        assert d["character_name"] == "林逸"
        assert d["held_items"] == ["长剑", "丹药"]
        assert d["last_updated_chapter"] == 5

    def test_character_state_from_dict(self):
        """from_dict 反序列化"""
        from src.agents.state_table import CharacterState

        d = {
            "character_id": "abc", "character_name": "张三",
            "project_id": "p1", "current_location": "城镇",
            "held_items": ["金币"],
        }
        cs = CharacterState.from_dict(d)
        assert cs.character_name == "张三"
        assert cs.held_items == ["金币"]

    def test_state_table_manager(self):
        """StateTable 增删查"""
        from src.agents.state_table import StateTable, CharacterState

        ws = MagicMock()
        ws.context_cache = {}
        mgr = StateTable(ws)

        cs = CharacterState(project_id="p1", character_name="林逸", current_location="山顶")
        mgr.upsert_state(cs)
        assert len(mgr.list_states("p1")) == 1

        found = mgr.get_state_by_name("林逸")
        assert found is not None
        assert found.current_location == "山顶"

    def test_state_table_upsert_update(self):
        """upsert_state 更新已有角色"""
        from src.agents.state_table import StateTable, CharacterState

        ws = MagicMock()
        ws.context_cache = {}
        mgr = StateTable(ws)

        cs1 = CharacterState(project_id="p1", character_name="林逸", current_location="山顶")
        mgr.upsert_state(cs1)

        cs2 = CharacterState(project_id="p1", character_name="林逸", current_location="山谷")
        mgr.upsert_state(cs2)

        found = mgr.get_state_by_name("林逸")
        assert found.current_location == "山谷"
        assert len(mgr.list_states("p1")) == 1  # 仍然只有1条

    def test_state_table_timeline(self):
        """upsert_state 归档旧快照到 timeline"""
        from src.agents.state_table import StateTable, CharacterState

        ws = MagicMock()
        ws.context_cache = {}
        mgr = StateTable(ws)

        cs1 = CharacterState(project_id="p1", character_name="林逸",
                           current_location="山顶", last_updated_chapter=1)
        mgr.upsert_state(cs1)

        cs2 = CharacterState(project_id="p1", character_name="林逸",
                           current_location="山谷", last_updated_chapter=5)
        mgr.upsert_state(cs2)

        timeline = mgr.get_character_timeline(cs1.character_id)
        assert len(timeline) >= 2


# ──────────────────────────────────────────────────────────────
# T4.2: 物品栏 ItemLedger
# ──────────────────────────────────────────────────────────────

class TestItemLedger:
    """ItemTransaction + ItemLedgerManager"""

    def test_item_transaction_auto_id(self):
        """ItemTransaction 自动生成 ID"""
        from src.agents.item_ledger import ItemTransaction

        tx = ItemTransaction(item_name="玄铁剑", action="acquire", holder="林逸", chapter=5)
        assert len(tx.item_id) == 12

    def test_item_transaction_to_dict(self):
        """to_dict 输出完整字段"""
        from src.agents.item_ledger import ItemTransaction

        tx = ItemTransaction(
            item_name="玄铁剑", action="transfer_in",
            holder="林逸", previous_holder="张三",
            chapter=5, quantity=1, note="战斗中获得",
        )
        d = tx.to_dict()
        assert d["item_name"] == "玄铁剑"
        assert d["action"] == "transfer_in"
        assert d["previous_holder"] == "张三"

    def test_item_transaction_from_dict(self):
        """from_dict 反序列化"""
        from src.agents.item_ledger import ItemTransaction

        d = {
            "item_id": "abc", "item_name": "丹药",
            "action": "consume", "holder": "林逸", "chapter": 8,
        }
        tx = ItemTransaction.from_dict(d)
        assert tx.item_name == "丹药"
        assert tx.action == "consume"

    def test_item_ledger_manager_record(self):
        """ItemLedger.record_transaction 添加交易"""
        from src.agents.item_ledger import ItemLedger, ItemTransaction

        ws = MagicMock()
        ws.context_cache = {}
        mgr = ItemLedger(ws)

        tx = ItemTransaction(item_name="玄铁剑", action="acquire", holder="林逸", chapter=5)
        mgr.record_transaction(tx)
        assert len(mgr.get_all_transactions()) == 1

    def test_item_ledger_manager_current_holder(self):
        """get_current_holder 查询物品当前持有者"""
        from src.agents.item_ledger import ItemLedger, ItemTransaction

        ws = MagicMock()
        ws.context_cache = {}
        mgr = ItemLedger(ws)

        mgr.record_transaction(ItemTransaction(item_name="玄铁剑", action="acquire", holder="林逸", chapter=5))
        mgr.record_transaction(ItemTransaction(item_name="玄铁剑", action="transfer_out",
                                   holder="张三", previous_holder="林逸", chapter=8))

        holder = mgr.get_current_holder("玄铁剑")
        # Last tx is transfer_out by 张三 (from 林逸), but no subsequent transfer_in
        # → returns "（去向不明）"
        assert "去向不明" in holder

    def test_item_ledger_manager_history(self):
        """item_history 查询物品完整流水"""
        from src.agents.item_ledger import ItemLedger, ItemTransaction

        ws = MagicMock()
        ws.context_cache = {}
        mgr = ItemLedger(ws)

        mgr.record_transaction(ItemTransaction(item_name="玄铁剑", action="acquire", holder="林逸", chapter=5))
        mgr.record_transaction(ItemTransaction(item_name="玄铁剑", action="transfer_out",
                                   holder="张三", previous_holder="林逸", chapter=8))

        history = mgr.get_item_history("玄铁剑")
        assert len(history) == 2
        assert history[0].chapter < history[1].chapter


# ──────────────────────────────────────────────────────────────
# T4.3: 灵感反推 Inspire
# ──────────────────────────────────────────────────────────────

class TestInspire:
    """灵感反推单元测试"""

    def test_inspire_prompt_contains_seed(self):
        """INSPIRE_USER_PROMPT_TEMPLATE 包含用户输入"""
        from src.agents.inspire import INSPIRE_USER_PROMPT_TEMPLATE

        result = INSPIRE_USER_PROMPT_TEMPLATE.format(seed="武侠+重生")
        assert "武侠+重生" in result

    def test_inspire_system_prompt_specifies_fields(self):
        """系统提示词指定输出字段"""
        from src.agents.inspire import INSPIRE_SYSTEM_PROMPT

        assert "story_core" in INSPIRE_SYSTEM_PROMPT
        assert "world_building" in INSPIRE_SYSTEM_PROMPT
        assert "main_characters" in INSPIRE_SYSTEM_PROMPT
        assert "outline_preview" in INSPIRE_SYSTEM_PROMPT

    def test_inspire_empty_seed(self):
        """空 seed 调用不会崩溃"""
        from src.agents.inspire import inspire

        # Mock LLM to avoid real API call
        mock_llm = MagicMock()
        mock_llm.complete.return_value = "{}"
        result = inspire("", llm=mock_llm)
        assert isinstance(result, dict)


# ──────────────────────────────────────────────────────────────
# T4.1: 章节级 Foreshadow 联动
# ──────────────────────────────────────────────────────────────

class TestForeshadowChapterSync:
    """全书级 ↔ 章节级伏笔联动"""

    def test_sync_to_chapter_outline(self):
        """新伏笔同步到 ChapterOutline.foreshadows"""
        from src.agents.foreshadow import ForeshadowManager, GlobalForeshadow
        from src.state.state_types import ChapterOutline, ChapterOutlineState, Foreshadow

        ws = MagicMock()
        ws.context_cache = {}
        mgr = ForeshadowManager(ws)

        # 模拟章纲状态
        ch = ChapterOutline(
            chapter_number=5, chapter_title="第五章",
            core_event="测试", character_states="", story_progression="",
        )
        ws.raw_state.chapter_outline = MagicMock()
        ws.raw_state.chapter_outline.chapters = [ch]

        # 添加伏笔
        mgr.create(GlobalForeshadow(project_id="p1", title="新伏笔",
                                     status="planted", planted_chapter=5))
        mgr._sync_to_chapter_outline(5)

        # 检查章级伏笔是否被同步
        assert len(ch.foreshadows) >= 1

    def test_sync_no_duplicate(self):
        """同步不会产生重复伏笔"""
        from src.agents.foreshadow import ForeshadowManager, GlobalForeshadow
        from src.state.state_types import ChapterOutline

        ws = MagicMock()
        ws.context_cache = {}
        mgr = ForeshadowManager(ws)

        ch = ChapterOutline(
            chapter_number=5, chapter_title="第五章",
            core_event="", character_states="", story_progression="",
        )
        ws.raw_state.chapter_outline = MagicMock()
        ws.raw_state.chapter_outline.chapters = [ch]

        mgr.create(GlobalForeshadow(project_id="p1", title="伏笔X",
                                     status="planted", planted_chapter=5))
        mgr._sync_to_chapter_outline(5)
        mgr._sync_to_chapter_outline(5)  # 再次同步

        assert len(ch.foreshadows) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
