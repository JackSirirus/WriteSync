"""
WriteSync Web UI — 上下文面板 Playwright E2E 测试

覆盖：面板展示 / 角色快照 / 手动修正 / 伏笔添加 / 对话区折叠条
     / 导航切换 / 窄屏响应式 / 骨架屏

运行：python tests/test_context_e2e_playwright.py
要求：服务已在 http://127.0.0.1:8000 运行（可通过 WRITESYNC_URL 环境变量覆盖）
"""

import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["LANGGRAPH_STRICT_MSGPACK"] = "false"

from playwright.sync_api import sync_playwright

BASE = os.environ.get("WRITESYNC_URL", "http://127.0.0.1:8000")
PASS = 0
FAIL = 0

def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS: {name}")
    else:
        FAIL += 1
        print(f"  FAIL: {name} {'— ' + detail if detail else ''}")

def inject_state_with_context(page):
    """注入 stateData（含 context 字段）到前端"""
    js = """
    () => {
      window.__stateData = {
        topic: { selected: 0, suggestions: [
          {title:'Test Story',genre:'Fantasy',sub_genre:'Xianxia',core_selling_point:'Test'}
        ], confirmed: true },
        story: { one_sentence: 'A test story', tag: 'Fantasy', five_sentences: ['s1','s2','s3','s4','s5'], confirmed: true },
        characters: { list: [
          {name:'LiFan',role:'protagonist',personality:'determined',goal:'become strong',arc:'weak→strong'},
          {name:'LiuRuyan',role:'heroine',personality:'cold',goal:'breakthrough',arc:'cold→warm'}
        ], confirmed: true },
        world: { system: 'Qi', tiers: ['QiRefining','Foundation','CoreFormation'], confirmed: true },
        outline: { total: 30, written: [1,2,3], confirmed: true },
        context: {
          character_snapshot: 'LiFan(protagonist): determined, become strong. Arc 10%; LiuRuyan(heroine): cold, breakthrough. Arc 5%',
          recent_chapters_summary: 'Ch1 Start: LiFan awakens Qi [hook: shadow figure] | Ch2 Training: enters sect [hook: jade moves]',
          unresolved_foreshadows: ['Ch1: shadow figure identity', 'Ch2: jade secret', 'Ch7: ultimate truth'],
          resolved_foreshadows: ['Ch3: father truth → resolved Ch3'],
          foreshadow_deadline: {'7': 'Ch7 must reveal jade secret'},
          world_changes: 'New faction: Blood Sect(Ch2); New location: Jade Tower(Ch4)',
          world_consistency_notes: 'Ch3: LiFan at Foundation can refine 3rd-grade pill vs Ch2 says Foundation only 1st-grade',
          pacing_state: 'Ch3 words 2900(target 3000), normal pace. Ch4 recommend 3000 words',
          chapter_word_counts: {'1': 3200, '2': 3050, '3': 2900},
          plot_progress: '3/30 chapters, progress 10%',
          story_beats_remaining: 27,
          updated_at: '2026-05-06T15:30:00',
          updated_chapter: 3
        }
      };
      stateData = window.__stateData;
      sessionId = 'test-session';
      renderAllPanels();
      updateTags();
      updateSteps();
      document.getElementById('setupOverlay').style.display = 'none';
      document.getElementById('workbench').style.display = 'block';
    }
    """
    page.evaluate(js)
    time.sleep(0.5)

def test_all():
    global PASS, FAIL
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        ctx.route("**/*", lambda route: route.abort()
            if "fonts.googleapis.com" in route.request.url or "fonts.gstatic.com" in route.request.url
            else route.continue_())

        # ===== 1. 页面加载与导航 =====
        print("\n=== 1. Page Load & Nav ===")
        page = ctx.new_page()
        page.goto(BASE, wait_until="networkidle")
        inject_state_with_context(page)
        check("State injected (context present)",
              page.evaluate("typeof stateData.context !== 'undefined'"))

        # 切换到上下文面板
        nav_items = page.locator(".nav-item[data-panel='context']")
        check("Context nav item exists", nav_items.count() == 1)
        nav_items.first.click()
        time.sleep(0.3)
        check("Context panel rendered",
              page.evaluate("document.getElementById('centerPanel').innerHTML.includes('写作上下文')"))

        # ===== 2. 上下文面板展示 =====
        print("\n=== 2. Context Panel Display ===")
        check("Character snapshot shown",
              page.evaluate("document.querySelector('#ctx-content')?.innerHTML.includes('角色状态快照')"))
        check("Recent chapters shown",
              page.evaluate("document.querySelector('#ctx-content')?.innerHTML.includes('前章回顾')"))
        check("Foreshadows shown",
              page.evaluate("document.querySelector('#ctx-content')?.innerHTML.includes('伏笔追踪')"))
        check("Progress bar shown",
              page.evaluate("document.querySelector('#ctx-content')?.innerHTML.includes('全书进度')"))
        check("Consistency notes shown",
              page.evaluate("document.querySelector('#ctx-content')?.innerHTML.includes('一致性提醒')"))
        check("Pacing state shown",
              page.evaluate("document.querySelector('#ctx-content')?.innerHTML.includes('节奏状态')"))
        page.close()

        # ===== 3. 角色快照手动修正 =====
        print("\n=== 3. Manual Edit Character Snapshot ===")
        page = ctx.new_page()
        page.goto(BASE, wait_until="networkidle")
        inject_state_with_context(page)
        nav_items = page.locator(".nav-item[data-panel='context']")
        nav_items.first.click()
        time.sleep(0.3)

        # 点击编辑按钮
        edit_btn = page.locator("button:has-text('手动修正')").first
        check("Edit button visible", edit_btn.is_visible())
        edit_btn.click()
        time.sleep(0.3)
        check("Edit mode activated",
              page.evaluate("!!document.querySelector('.ctx-edit')"))
        check("Char count shown",
              page.evaluate("!!document.querySelector('.char-count')"))
        # 取消编辑
        cancel_btn = page.locator("button:has-text('取消')")
        check("Cancel button visible", cancel_btn.is_visible())
        cancel_btn.click()
        time.sleep(0.3)
        page.close()

        # ===== 4. 伏笔手动添加 =====
        print("\n=== 4. Manual Foreshadow Add ===")
        page = ctx.new_page()
        page.goto(BASE, wait_until="networkidle")
        inject_state_with_context(page)
        nav_items = page.locator(".nav-item[data-panel='context']")
        nav_items.first.click()
        time.sleep(0.3)

        # 找到添加伏笔的输入框
        fs_input = page.locator("input[placeholder*='手动添加']")
        check("Foreshadow add input visible", fs_input.is_visible())
        fs_input.fill("Ch4: mysterious stranger appears")
        add_btn = page.locator("button:has-text('添加')")
        check("Add button visible", add_btn.is_visible())
        page.close()

        # ===== 5. 对话区上下文折叠条 =====
        print("\n=== 5. Chat Context Collapse ===")
        page = ctx.new_page()
        page.goto(BASE, wait_until="networkidle")
        inject_state_with_context(page)

        # 在对话区模拟一条 AI 消息 + 上下文折叠条
        page.evaluate("""
        () => {
          const chat = document.getElementById('chatMessages');
          const ctxHtml = window.renderContextCollapse(
            '## Current Characters\\nLiFan: determined, become strong\\n\\n## Recent Chapters\\nCh1 Start\\n\\n## Unresolved Foreshadows\\n- Ch1: shadow figure'
          );
          chat.innerHTML += ctxHtml;
          chat.innerHTML += '<div class="chat-msg system">AI chapter draft completed</div>';
        }
        """)
        time.sleep(0.3)
        collapse = page.locator(".ctx-collapse")
        check("Context collapse bar exists", collapse.count() >= 1)
        collapse_title = page.locator(".ctx-collapse-title")
        check("Collapse title visible", collapse_title.first.is_visible())
        # 展开折叠条
        collapse_title.first.click()
        time.sleep(0.3)
        check("Collapse body visible after click",
              collapse.first.evaluate("el => el.classList.contains('open')"))
        page.close()

        # ===== 6. 窄屏响应式 =====
        print("\n=== 6. Responsive (Narrow) ===")
        ctx2 = browser.new_context(viewport={"width": 600, "height": 900})
        ctx2.route("**/*", lambda route: route.abort()
            if "fonts.googleapis.com" in route.request.url or "fonts.gstatic.com" in route.request.url
            else route.continue_())
        page = ctx2.new_page()
        page.goto(BASE, wait_until="networkidle")
        inject_state_with_context(page)
        # 窄屏下导航被隐藏，汉堡菜单出现
        check("Hamburger visible (narrow)",
              page.locator("#navToggle").is_visible())
        # 导航默认隐藏
        check("Nav hidden (narrow)",
              page.locator(".nav").evaluate("el => el.style.display === 'none' || el.offsetWidth === 0"))
        page.close()

        # ===== 7. 骨架屏 =====
        print("\n=== 7. Skeleton Loading ===")
        page = ctx.new_page()
        page.goto(BASE, wait_until="networkidle")
        # 不注入 context，模拟加载中状态
        page.evaluate("""
        () => {
          document.getElementById('setupOverlay').style.display = 'none';
          document.getElementById('workbench').style.display = 'block';
          stateData = {};
          currentPanel = 'context';
          renderContext();
        }
        """)
        time.sleep(0.3)
        check("Loading state visible",
              page.evaluate("document.getElementById('ctx-loading')?.style.display !== 'none'"))
        # 骨架屏元素可见
        check("Skeleton elements exist",
              page.locator(".ctx-skeleton").count() >= 2)
        page.close()

        # ===== 8. 空态 =====
        print("\n=== 8. Empty State ===")
        page = ctx.new_page()
        page.goto(BASE, wait_until="networkidle")
        page.evaluate("""
        () => {
          document.getElementById('setupOverlay').style.display = 'none';
          document.getElementById('workbench').style.display = 'block';
          stateData = {};
          currentPanel = 'context';
          renderContext();
        }
        """)
        time.sleep(0.3)
        check("Empty state visible",
              page.evaluate("document.getElementById('ctx-empty')?.style.display !== 'none'"))
        check("Empty hint contains 策划",
              page.evaluate("document.getElementById('ctx-empty')?.innerHTML.includes('策划')"))
        page.close()

        # ===== 结果 =====
        print(f"\n{'='*50}")
        print(f"  结果: {PASS}/{PASS+FAIL} 通过")
        print(f"{'='*50}")
        browser.close()
        sys.exit(1 if FAIL > 0 else 0)

if __name__ == "__main__":
    test_all()
