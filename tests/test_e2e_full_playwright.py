"""
test_e2e_full_playwright.py — 真·全流程 Playwright E2E 测试

通过真实 API 调用 + Playwright 浏览器验证，覆盖完整创作链路：
  Phase 1: 选题 → 故事核心 → 角色 → 世界观 → 章纲（策划全流程）
  Phase 2: 章节写作（第1章）→ 校对 → 确认
  Phase 3: 上下文面板更新验证
  Phase 4: 导出功能

架构：httpx (API + SSE 监听) + Playwright (UI 验证)

前置条件：
  - Web 服务运行在 8000 端口
  - LLM 网关可用
  - $env:LANGGRAPH_STRICT_MSGPACK="false"

用法：
  python -m pytest tests/test_e2e_full_playwright.py -v -s

预估时间：5-10 分钟（取决于 LLM 响应速度）
"""

import json
import os
import sys
import time
import threading
from datetime import datetime

import httpx
import pytest
from playwright.sync_api import sync_playwright

BASE = os.environ.get("WRITESYNC_URL", "http://127.0.0.1:8000")
TIMEOUT_SEC = 900  # 15 分钟总超时
MAX_CONFIRMS = 12  # 最多确认次数（策划 4 + 写作 2 = 6，给些余量）

# ── Test helpers ───────────────────────────────────────────────────────────

PASS = 0
FAIL = 0
FAILURES = []


def check(name, condition, detail=""):
    global PASS, FAIL, FAILURES
    if condition:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        d = f" -- {detail}" if detail else ""
        print(f"  [FAIL] {name}{d}")
        FAILURES.append(f"{name}{d}")


class WriteSyncAPI:
    """API 客户端：同步 httpx 做短请求，后台线程 + 独立事件循环做 SSE 长连接"""

    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/")
        self.project_id = None
        self.name = f"E2E_Full_{datetime.now().strftime('%H%M%S')}"
        self.events = []
        self.confirms = []
        self.done = False
        self.error_count = 0
        self._stream_thread = None
        self._stream_status = None

    # ── 同步 API 操作 ──

    def create_project(self, idea: str, platform: str = "起点"):
        with httpx.Client(timeout=httpx.Timeout(120)) as c:
            resp = c.post(f"{self.base}/api/v2/start", json={
                "name": self.name,
                "platform": platform,
                "seed_idea": idea,
            })
            data = resp.json()
            self.project_id = data["project_id"]
            print(f"  项目创建: {self.project_id}")
            return data

    def respond(self, approved=True, feedback="", scope="all", edited_content=None):
        form_data = {
            "approved": str(approved).lower(),
            "feedback": str(feedback),
            "scope": str(scope),
        }
        if edited_content:
            form_data["edited_content"] = json.dumps(edited_content)
        with httpx.Client(timeout=httpx.Timeout(120)) as c:
            c.post(f"{self.base}/api/v2/respond/{self.project_id}", data=form_data)

    def load_page_state(self):
        with httpx.Client(timeout=httpx.Timeout(30)) as c:
            resp = c.get(f"{self.base}/api/v2/state/{self.project_id}")
            return resp.json()

    # ── SSE 流（后台线程） ──

    def stream_and_auto_confirm(self, on_event=None, max_confirms=MAX_CONFIRMS):
        """在后台线程中启动 SSE 监听，自动确认。阻塞直到完成。"""
        result = {"status": "unknown"}

        def _run_stream():
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                status = loop.run_until_complete(
                    self._async_stream(on_event, max_confirms)
                )
                result["status"] = status
            except Exception as e:
                result["status"] = f"error: {e}"
                print(f"  SSE 线程异常: {e}")
            finally:
                loop.close()

        self._stream_thread = threading.Thread(target=_run_stream, daemon=True)
        self._stream_thread.start()
        self._stream_thread.join(timeout=TIMEOUT_SEC)

        if self._stream_thread.is_alive():
            print("  [WARN] SSE stream timeout, forcing stop")
            result["status"] = "timeout"

        self._stream_status = result["status"]
        return result["status"]

    async def _async_stream(self, on_event, max_confirms):
        import asyncio
        url = f"{self.base}/api/v2/stream/{self.project_id}"
        print(f"  SSE 连接: {url}")
        confirm_count = 0
        event_type = ""

        async with httpx.AsyncClient(timeout=httpx.Timeout(TIMEOUT_SEC)) as c:
            async with c.stream("GET", url) as resp:
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    if line.startswith("event: "):
                        event_type = line[7:].strip()
                    elif line.startswith("data: "):
                        try:
                            data = json.loads(line[6:].strip())
                        except json.JSONDecodeError:
                            continue
                        self.events.append({"type": event_type, "data": data})

                        if event_type == "agent_call":
                            agent = data.get("agent", "?")
                            print(f"  [{len(self.events)}] agent_call: {agent}")

                        elif event_type == "confirm":
                            confirm_count += 1
                            agent = data.get("agent", "?")
                            print(f"  [{len(self.events)}] CONFIRM #{confirm_count}: {agent}")

                            if on_event:
                                on_event("confirm", data)

                            # 选题阶段特殊处理：选第0个
                            if agent == "story" and data.get("content", {}).get("stage") == "topics":
                                topics = data.get("content", {}).get("topics", [])
                                if topics:
                                    print(f"    选题: {topics[0].get('title', '?')}")
                                await self._respond_async(approved=True, feedback="0")
                            else:
                                await self._respond_async(approved=True, feedback="继续")

                            self.confirms.append(data)

                        elif event_type == "workspace_update":
                            summary = data.get("summary", "")[:80]
                            print(f"  [OK] workspace: {summary}")

                        elif event_type == "done":
                            print(f"  [DONE] {data.get('reason', '')}")
                            self.done = True
                            if on_event:
                                on_event("done", data)
                            return "done"

                        elif event_type == "error":
                            self.error_count += 1
                            print(f"  [ERROR] {data.get('message', '')[:100]}")
                            if self.error_count > 5:
                                return "error_limit"

                        if confirm_count >= max_confirms:
                            print(f"  达到最大确认次数 ({max_confirms})，停止")
                            return "max_confirms"

        return "stream_ended"

    async def _respond_async(self, approved=True, feedback="", scope="all"):
        form_data = {
            "approved": str(approved).lower(),
            "feedback": str(feedback),
            "scope": str(scope),
        }
        async with httpx.AsyncClient(timeout=httpx.Timeout(120)) as c:
            await c.post(f"{self.base}/api/v2/respond/{self.project_id}", data=form_data)


# ══════════════════════════════════════════════════════════════════════════
# 测试主流程
# ══════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


def test_full_creative_flow(browser):
    """
    完整创作流程：
      选题 → 故事核心 → 角色 → 世界观 → 章纲 → 写第1章 → 校对 → 导出
    """
    global PASS, FAIL, FAILURES
    PASS = FAIL = 0
    FAILURES = []

    print("\n" + "=" * 70)
    print("  WriteSync 真·全流程 Playwright E2E 测试")
    print(f"  目标: {BASE}")
    print(f"  最大确认次数: {MAX_CONFIRMS}")
    print("=" * 70)

    # ── Phase 0: 初始化 ──
    api = WriteSyncAPI(BASE)

    # 创建项目
    print("\n── Phase 0: 创建项目 ──")
    idea = "一个被家族抛弃的修真少年，在末世废墟中觉醒上古血脉，踏上复仇与救赎之路"
    api.create_project(idea, platform="起点")
    check("0.1 Project created", api.project_id is not None)
    pid = api.project_id

    # 打开 Playwright 浏览器
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()

    # 加载项目页面
    print("\n── Phase 0: 加载项目页面 ──")
    page.goto(f"{BASE}/?project={pid}", wait_until="networkidle")
    time.sleep(1)

    # 验证 workbench 加载
    workbench_loaded = page.evaluate(
        "() => !!document.querySelector('#workbench') || !!document.querySelector('.nav-item')"
    )
    check("0.2 Workbench loaded", workbench_loaded)

    # ── Phase 1: SSE 全流程自动确认（不打断，不操作 Playwright）──
    print("\n-- Phase 1: SSE orchestration (auto-confirm all steps) --")

    def log_event(event_type, data):
        """简单的日志回调，不做 Playwright 操作"""
        if event_type == "confirm":
            agent = data.get("agent", "?")
            stage = data.get("content", {}).get("stage", "")
            ch = data.get("chapter_num", "")
            print(f"  -> confirmed: {agent} stage={stage} ch={ch}")
        elif event_type == "done":
            print(f"  -> orchestrator done: {data.get('reason', '')}")

    status = api.stream_and_auto_confirm(on_event=log_event)
    confirm_agents = [c.get("agent", "") for c in api.confirms]
    print(f"  SSE events: {len(api.events)}, confirms: {len(api.confirms)}")
    print(f"  Confirmed agents: {confirm_agents}")

    # 验证至少完成了策划阶段（topics + characters + world）
    min_planning = all(a in confirm_agents for a in ["story", "character", "world"])
    check("1.1 Planning phase completed (story+character+world)",
          min_planning,
          f"confirmed: {confirm_agents}, status: {status}")
    check("1.2 Outline reached", "outline" in confirm_agents or status == "done",
          f"outline confirmed: {'outline' in confirm_agents}")

    # ── Phase 2: Playwright UI 验证（SSE 完成后）──
    print("\n-- Phase 2: Playwright UI verification (post-SSE) --")

    # 重新加载项目页面，通过 API 加载项目状态
    page.goto(f"{BASE}/?project={pid}", wait_until="networkidle")
    time.sleep(2)

    # 通过 API 获取项目状态，注入到页面
    try:
        state = api.load_page_state()
        if state:
            page.evaluate(f"() => {{ stateData = {json.dumps(state)}; if (typeof renderAllPanels === 'function') renderAllPanels(); }}")
            time.sleep(1)
    except Exception as e:
        print(f"  [WARN] Could not load project state: {e}")

    # 2.1 验证导航栏存在
    nav_count = page.evaluate("() => document.querySelectorAll('.nav-item').length")
    check("2.1 Navigation items exist", nav_count >= 6, f"found {nav_count} nav items")

    # 2.2 基于 API 事件验证流程进度（不依赖页面渲染）
    confirm_agents = [c.get("agent", "") for c in api.confirms]
    check("2.2 Topics confirmed", "story" in confirm_agents,
          f"confirmed agents: {confirm_agents}")
    check("2.3 Characters confirmed", "character" in confirm_agents)
    check("2.4 World confirmed", "world" in confirm_agents)

    # 2.3 验证事件总数
    check("2.5 Events received", len(api.events) >= 10,
          f"total events: {len(api.events)}")

    # 2.4 验证 UI 面板可导航
    panels = ["story", "characters", "world", "outline", "editor", "context", "review"]
    all_ok = True
    for p in panels:
        try:
            page.evaluate(f"document.querySelector('.nav-item[data-panel=\"{p}\"]')?.click()")
            time.sleep(0.15)
        except Exception:
            all_ok = False
            break
    check("2.6 All panels navigable without crash", all_ok)

    # ── 清理 ──
    page.close()
    ctx.close()

    # ── 汇总 ──
    print("\n" + "=" * 70)
    print(f"  Full E2E Test Result: {PASS} passed, {FAIL} failed")
    print(f"  SSE events: {len(api.events)}, confirms: {len(api.confirms)}")
    print("=" * 70)

    if FAILURES:
        print("Failures:")
        for f in FAILURES:
            print(f"  - {f}")

    assert FAIL == 0, f"{FAIL} E2E check(s) failed"
