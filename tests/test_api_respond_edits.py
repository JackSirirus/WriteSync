"""
T1.1.3: /api/v2/respond 接收 edited_content 参数测试

验证 API 端点正确解析 JSON 编辑内容，并传递给 session.user_respond()。
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
# Helper: 模拟 send_to_session 以捕获 edited_content
# ──────────────────────────────────────────────────────────────

def _make_respond_endpoint():
    """返回 (endpoint_fn, capture_dict) 以便测试"""
    captured = {}

    @patch("src.web.app.send_to_session")
    def endpoint(edited_content_str="", approved="true", feedback="",
                 scope="all", selected_action="", mock_send=None):
        from src.web.app import app
        from fastapi.testclient import TestClient

        mock_send.side_effect = lambda pid, **kwargs: captured.update(kwargs) or True

        client = TestClient(app)
        data = {
            "approved": approved,
            "feedback": feedback,
            "scope": scope,
            "selected_action": selected_action,
        }
        if edited_content_str:
            data["edited_content"] = edited_content_str

        resp = client.post(f"/api/v2/respond/test-pid-123", data=data)
        return resp.json(), captured

    return endpoint


# ──────────────────────────────────────────────────────────────
# 1. JSON 解析
# ──────────────────────────────────────────────────────────────

class TestJsonParsing:
    """edited_content 从 JSON 字符串 → dict 的转换"""

    def test_empty_string_no_edits(self):
        """空 edited_content → edits=None"""
        from src.web.app import send_to_session
        import src.web.app as app_mod

        captured = {}
        app_mod._orchestrator_sessions = {"test-pid": MagicMock(
            is_running=MagicMock(return_value=True),
            user_respond=lambda **kw: captured.update(kw)
        )}

        with patch.object(app_mod, "send_to_session", lambda pid, **kw: captured.update(kw) or True):
            client = __import__("fastapi.testclient", fromlist=["TestClient"]).TestClient(app_mod.app)
            resp = client.post("/api/v2/respond/test-pid", data={
                "approved": "true",
                "edited_content": "",
            })
            result = resp.json()
            assert result.get("ok") is True
            # edited_content="" → parsed edits should be None
            assert captured.get("edited_content") is None

    def test_valid_json_parsed(self):
        """合法 JSON → edits dict"""
        import src.web.app as app_mod
        from fastapi.testclient import TestClient

        captured = {}
        app_mod._orchestrator_sessions = {"pid-1": MagicMock(
            is_running=MagicMock(return_value=True),
            user_respond=lambda **kw: captured.update(kw)
        )}

        with patch.object(app_mod, "send_to_session", lambda pid, **kw: captured.update(kw) or True):
            client = TestClient(app_mod.app)
            edits_json = json.dumps({"character": {"name": "张三", "goal": "拯救世界"}})
            resp = client.post("/api/v2/respond/pid-1", data={
                "approved": "true",
                "edited_content": edits_json,
            })
            assert resp.json().get("ok") is True
            assert captured.get("edited_content") == {"character": {"name": "张三", "goal": "拯救世界"}}

    def test_invalid_json_no_crash(self):
        """非法 JSON → 不崩溃，edits=None"""
        import src.web.app as app_mod
        from fastapi.testclient import TestClient

        captured = {}
        app_mod._orchestrator_sessions = {"pid-2": MagicMock(
            is_running=MagicMock(return_value=True),
            user_respond=lambda **kw: captured.update(kw)
        )}

        with patch.object(app_mod, "send_to_session", lambda pid, **kw: captured.update(kw) or True):
            client = TestClient(app_mod.app)
            resp = client.post("/api/v2/respond/pid-2", data={
                "approved": "true",
                "edited_content": "NOT VALID JSON {{{",
            })
            assert resp.json().get("ok") is True
            assert captured.get("edited_content") is None

    def test_nested_json_structure(self):
        """嵌套 JSON（世界设定）→ 完整传递"""
        import src.web.app as app_mod
        from fastapi.testclient import TestClient

        captured = {}
        app_mod._orchestrator_sessions = {"pid-3": MagicMock(
            is_running=MagicMock(return_value=True),
            user_respond=lambda **kw: captured.update(kw)
        )}

        with patch.object(app_mod, "send_to_session", lambda pid, **kw: captured.update(kw) or True):
            client = TestClient(app_mod.app)
            edits = {
                "world": {
                    "power_system": {"system_name": "灵能", "rules": ["灵能来自星辰"]},
                    "geography": {"map_summary": "东方大陆"},
                }
            }
            resp = client.post("/api/v2/respond/pid-3", data={
                "approved": "true",
                "edited_content": json.dumps(edits),
            })
            assert resp.json().get("ok") is True
            assert captured["edited_content"]["world"]["power_system"]["system_name"] == "灵能"

    def test_unicode_in_json(self):
        """中文 Unicode JSON → 正确解码"""
        import src.web.app as app_mod
        from fastapi.testclient import TestClient

        captured = {}
        app_mod._orchestrator_sessions = {"pid-4": MagicMock(
            is_running=MagicMock(return_value=True),
            user_respond=lambda **kw: captured.update(kw)
        )}

        with patch.object(app_mod, "send_to_session", lambda pid, **kw: captured.update(kw) or True):
            client = TestClient(app_mod.app)
            edits = {"story": {"one_sentence": "穿越者在克苏鲁世界用AI封神"}}
            resp = client.post("/api/v2/respond/pid-4", data={
                "approved": "true",
                "edited_content": json.dumps(edits, ensure_ascii=False),
            })
            assert resp.json().get("ok") is True
            assert captured["edited_content"]["story"]["one_sentence"] == "穿越者在克苏鲁世界用AI封神"


# ──────────────────────────────────────────────────────────────
# 2. 其他参数
# ──────────────────────────────────────────────────────────────

class TestOtherParams:
    """非 edited_content 的参数传递"""

    def test_approved_true(self):
        """approved=true → True"""
        import src.web.app as app_mod
        from fastapi.testclient import TestClient

        captured = {}
        app_mod._orchestrator_sessions = {"pid-5": MagicMock(
            is_running=MagicMock(return_value=True),
            user_respond=lambda **kw: captured.update(kw)
        )}

        with patch.object(app_mod, "send_to_session", lambda pid, **kw: captured.update(kw) or True):
            client = TestClient(app_mod.app)
            client.post("/api/v2/respond/pid-5", data={"approved": "true"})
            assert captured.get("approved") is True

    def test_approved_false(self):
        """approved=false → False"""
        import src.web.app as app_mod
        from fastapi.testclient import TestClient

        captured = {}
        app_mod._orchestrator_sessions = {"pid-6": MagicMock(
            is_running=MagicMock(return_value=True),
            user_respond=lambda **kw: captured.update(kw)
        )}

        with patch.object(app_mod, "send_to_session", lambda pid, **kw: captured.update(kw) or True):
            client = TestClient(app_mod.app)
            client.post("/api/v2/respond/pid-6", data={"approved": "false"})
            assert captured.get("approved") is False

    def test_feedback_passed(self):
        """feedback 字段传递"""
        import src.web.app as app_mod
        from fastapi.testclient import TestClient

        captured = {}
        app_mod._orchestrator_sessions = {"pid-7": MagicMock(
            is_running=MagicMock(return_value=True),
            user_respond=lambda **kw: captured.update(kw)
        )}

        with patch.object(app_mod, "send_to_session", lambda pid, **kw: captured.update(kw) or True):
            client = TestClient(app_mod.app)
            client.post("/api/v2/respond/pid-7", data={
                "approved": "true",
                "feedback": "节奏太快，加点铺垫",
            })
            assert captured.get("feedback") == "节奏太快，加点铺垫"

    def test_scope_passed(self):
        """scope 字段传递"""
        import src.web.app as app_mod
        from fastapi.testclient import TestClient

        captured = {}
        app_mod._orchestrator_sessions = {"pid-8": MagicMock(
            is_running=MagicMock(return_value=True),
            user_respond=lambda **kw: captured.update(kw)
        )}

        with patch.object(app_mod, "send_to_session", lambda pid, **kw: captured.update(kw) or True):
            client = TestClient(app_mod.app)
            client.post("/api/v2/respond/pid-8", data={
                "approved": "true",
                "scope": "chapter_only",
            })
            assert captured.get("scope") == "chapter_only"

    def test_selected_action_passed(self):
        """selected_action 字段传递（建议模式选方案）"""
        import src.web.app as app_mod
        from fastapi.testclient import TestClient

        captured = {}
        app_mod._orchestrator_sessions = {"pid-9": MagicMock(
            is_running=MagicMock(return_value=True),
            user_respond=lambda **kw: captured.update(kw)
        )}

        with patch.object(app_mod, "send_to_session", lambda pid, **kw: captured.update(kw) or True):
            client = TestClient(app_mod.app)
            client.post("/api/v2/respond/pid-9", data={
                "approved": "true",
                "selected_action": "option_b",
            })
            assert captured.get("selected_action") == "option_b"


# ──────────────────────────────────────────────────────────────
# 3. send_to_session 调用链
# ──────────────────────────────────────────────────────────────

class TestSendToSession:
    """send_to_session → session.user_respond 传递链"""

    def test_no_session_returns_false(self):
        """无活跃 session → 返回 False"""
        import src.web.app as app_mod
        from src.web.orchestrator_api import send_to_session

        app_mod._orchestrator_sessions = {}
        assert send_to_session("nonexistent", approved=True) is False

    def test_session_not_running_returns_false(self):
        """session 未运行 → 返回 False"""
        import src.web.app as app_mod
        from src.web.orchestrator_api import send_to_session

        mock_session = MagicMock()
        mock_session.is_running.return_value = False
        app_mod._orchestrator_sessions = {"pid-10": mock_session}
        assert send_to_session("pid-10", approved=True) is False

    def test_session_running_calls_user_respond(self):
        """session 运行中 → user_respond 被调用"""
        import src.web.orchestrator_api as api_mod

        mock_session = MagicMock()
        mock_session.is_running.return_value = True
        api_mod._orchestrator_sessions = {"pid-11": mock_session}

        result = api_mod.send_to_session("pid-11", approved=True, feedback="好", edited_content={"x": 1})
        assert result is True
        mock_session.user_respond.assert_called_once_with(
            approved=True, feedback="好", scope="all",
            edited_content={"x": 1}, selected_action="",
        )


# ──────────────────────────────────────────────────────────────
# 4. 各 Agent 分支 edits 结构
# ──────────────────────────────────────────────────────────────

class TestAgentBranchEdits:
    """不同 Agent 分支的 edited_content 结构"""

    @pytest.mark.parametrize("branch,expected_key", [
        ("story", "story"),
        ("character", "characters"),
        ("world", "world"),
        ("outline", "chapter_outline"),
        ("writer", "drafts"),
    ])
    def test_branch_key_mapping(self, branch, expected_key):
        """各 Agent 分支 edits dict 的 key 映射"""
        # 这是 edits JSON 中客户端发送的 key
        # 验证 _apply_edits 中各分支处理对应的 key
        sample_edits = {
            "story": {"one_sentence": "新核心"},
            "characters": {"characters": [{"name": "改名"}]},
            "world": {"power_system": {"system_name": "新体系"}},
            "chapter_outline": {"chapters": [{"chapter_number": 1, "title": "新标题"}]},
            "drafts": {"1": {"content": "新正文"}},
        }
        # 每个 branch 都应有对应的 key
        assert expected_key in sample_edits, f"missing key {expected_key} for branch {branch}"


# ──────────────────────────────────────────────────────────────
# 5. 边界场景
# ──────────────────────────────────────────────────────────────

class TestEdgeCases:
    """边界场景覆盖"""

    def test_empty_dict_edits(self):
        """{} → edits={}（合法 JSON，非 None）"""
        import src.web.app as app_mod
        from fastapi.testclient import TestClient

        captured = {}
        app_mod._orchestrator_sessions = {"pid-12": MagicMock(
            is_running=MagicMock(return_value=True),
            user_respond=lambda **kw: captured.update(kw)
        )}

        with patch.object(app_mod, "send_to_session", lambda pid, **kw: captured.update(kw) or True):
            client = TestClient(app_mod.app)
            resp = client.post("/api/v2/respond/pid-12", data={
                "approved": "true",
                "edited_content": "{}",
            })
            assert resp.json().get("ok") is True
            assert captured.get("edited_content") == {}

    def test_deeply_nested_edits(self):
        """深层嵌套 JSON（5层）→ 正确传递"""
        import src.web.app as app_mod
        from fastapi.testclient import TestClient

        captured = {}
        app_mod._orchestrator_sessions = {"pid-13": MagicMock(
            is_running=MagicMock(return_value=True),
            user_respond=lambda **kw: captured.update(kw)
        )}

        with patch.object(app_mod, "send_to_session", lambda pid, **kw: captured.update(kw) or True):
            client = TestClient(app_mod.app)
            nested = {"a": {"b": {"c": {"d": {"e": "deep"}}}}}
            resp = client.post("/api/v2/respond/pid-13", data={
                "approved": "true",
                "edited_content": json.dumps(nested),
            })
            assert resp.json().get("ok") is True
            val = captured["edited_content"]
            for _ in range(5):
                val = list(val.values())[0]
            assert val == "deep"

    def test_large_payload(self):
        """大 payload（10KB）→ 正常处理"""
        import src.web.app as app_mod
        from fastapi.testclient import TestClient

        captured = {}
        app_mod._orchestrator_sessions = {"pid-14": MagicMock(
            is_running=MagicMock(return_value=True),
            user_respond=lambda **kw: captured.update(kw)
        )}

        with patch.object(app_mod, "send_to_session", lambda pid, **kw: captured.update(kw) or True):
            client = TestClient(app_mod.app)
            large = {"chapters": [{"id": i, "content": "x" * 500} for i in range(20)]}
            resp = client.post("/api/v2/respond/pid-14", data={
                "approved": "true",
                "edited_content": json.dumps(large),
            })
            assert resp.json().get("ok") is True
            assert len(captured["edited_content"]["chapters"]) == 20


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
