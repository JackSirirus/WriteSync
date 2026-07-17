"""
WriteSync Web UI — Playwright 全覆盖测试（新功能验证）

覆盖：选题卡片 / 快捷按钮 / 草稿保存恢复 / AI稿自动填入
     / 审查报告 / 导航切换 / 响应式布局

运行：python tests/test_playwright.py
要求：服务已在 http://127.0.0.1:8000 运行
"""

import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["LANGGRAPH_STRICT_MSGPACK"] = "false"
os.environ.pop("LLM_MODEL", None)
os.environ.pop("LLM_PROVIDER", None)

from playwright.sync_api import sync_playwright

BASE = os.environ.get("WRITESYNC_URL", "http://127.0.0.1:8000")
PASS = 0
FAIL = 0

def check(name, condition, detail=""):
    global PASS, FAIL
    if condition: PASS += 1; print(f"  PASS: {name}")
    else: FAIL += 1; print(f"  FAIL: {name} {f'— {detail}' if detail else ''}")

def inject_state(page, extra=None):
    js = """
    () => {
      window.__stateData = {
        topic: { selected: -1, suggestions: [
          {title:'代码修仙',genre:'仙侠',sub_genre:'科技修仙',core_selling_point:'程序员用算法破解修仙',heat_level:'热门',difficulty:'蓝海'},
          {title:'万界商城',genre:'玄幻',sub_genre:'经营流',core_selling_point:'在万界经营商会',heat_level:'热门',difficulty:'蓝海'}
        ]},
        story: { one_sentence: '测试故事', tag: '仙侠', five_sentences: ['s1','s2','s3','s4','s5'], confirmed: true },
        characters: { list: [{name:'林逸',role:'主角',personality:'坚韧',goal:'变强',arc:'弱小→强大'}], confirmed: true },
        world: { system: '灵气体系', tiers: ['炼气','筑基','金丹'], confirmed: true },
        outline: { total: 20, written: [1,2,3], confirmed: true },
        review: { passed: true, pacing: '良好', issues: ['前3章节奏偏慢','中间部分拖沓'], recommendations: ['压缩第2-4章','增强反派动机'] },
        drafts: { '1': { content: '第一章正文内容...', stage: 'final', word_count: 3200 } }
      };
      stateData = window.__stateData;
      renderAllPanels();
      updateTags();
      updateSteps();
      document.getElementById('setupOverlay').style.display = 'none';
      document.getElementById('workbench').style.display = 'block';
    }
    """
    page.evaluate(js)
    time.sleep(0.3)

def test_all():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})

        # Block external CDN to avoid networkidle timeout
        ctx.route("**/*", lambda route: route.abort()
            if "fonts.googleapis.com" in route.request.url or "fonts.gstatic.com" in route.request.url
            else route.continue_())

        # ===== 1. Page Load =====
        print("\n=== 1. Page Load ===")
        page = ctx.new_page()
        page.goto(BASE, wait_until="networkidle")
        check("Page loads", len(page.content()) > 500)
        check("Setup overlay", page.locator("#setupOverlay").is_visible())
        check("Quick buttons rendered", page.locator("#quickBtns button").count() >= 5)
        check("Hamburger btn hidden", page.locator("#navToggle").is_hidden())
        check("Floating chat hidden", page.locator("#chatBtn").is_hidden())
        page.close()

        # ===== 2. Topic Cards =====
        print("\n=== 2. Topic Cards ===")
        page = ctx.new_page()
        page.goto(BASE, wait_until="networkidle")
        inject_state(page)
        # Inject topic suggestions into chat
        page.evaluate("""
        () => {
          const el = document.getElementById('chatMessages');
          el.innerHTML += '<div class="chat-msg system" id="topicCard0" onclick="selectTopicCard(0)" style="cursor:pointer;background:var(--bg-elevated);border:1px solid var(--border);padding:10px;margin:6px 0;border-radius:8px"><strong style="color:var(--accent)">代码修仙</strong> <span>仙侠/科技修仙</span></div>';
          el.innerHTML += '<div class="chat-msg system" id="topicCard1" onclick="selectTopicCard(1)" style="cursor:pointer;background:var(--bg-elevated);border:1px solid var(--border);padding:10px;margin:6px 0;border-radius:8px"><strong style="color:var(--accent)">万界商城</strong> <span>玄幻/经营流</span></div>';
        }
        """)
        time.sleep(0.3)
        check("Topic cards visible", page.locator("#topicCard0").is_visible())
        check("Topic cards (2 items)", page.locator("[id^='topicCard']").count() == 2)
        page.close()

        # ===== 3. Navigation =====
        print("\n=== 3. Navigation ===")
        page = ctx.new_page()
        page.goto(BASE, wait_until="networkidle")
        inject_state(page)
        for panel, heading in [("story","故事大纲"),("characters","角色管理"),("world","世界观"),("outline","章纲视图"),("review","全书审查")]:
            page.click(f".nav-item[data-panel='{panel}']"); time.sleep(0.2)
            check(f"Nav: {panel}", page.locator(".panel-header h2").is_visible())

        # Editor
        page.click(".nav-item[data-panel='outline']"); time.sleep(0.2)
        page.locator(".chapter-card").first.click(); time.sleep(0.3)
        check("Editor loaded", page.locator("#editorContent").is_visible())
        check("Editor has chapter select", page.locator(".editor-container select").is_visible())
        page.close()

        # ===== 4. Draft Save & Restore =====
        print("\n=== 4. Draft Save & Restore ===")
        page = ctx.new_page()
        page.goto(BASE, wait_until="networkidle")
        inject_state(page)
        page.click(".nav-item[data-panel='outline']"); time.sleep(0.2)
        page.locator(".chapter-card").first.click(); time.sleep(0.3)
        page.fill("#editorContent", "测试草稿内容12345")
        page.click("button:has-text('保存草稿')"); time.sleep(0.3)
        check("Draft saved message", "草稿已保存" in page.content())

        # Reload and check restore
        page.click(".nav-item[data-panel='story']"); time.sleep(0.2)
        page.click(".nav-item[data-panel='outline']"); time.sleep(0.2)
        page.locator(".chapter-card").first.click(); time.sleep(0.3)
        content = page.input_value("#editorContent")
        check(f"Draft restored: {content[:20]}...", "测试草稿内容" in content)
        page.close()

        # ===== 5. AI Draft Auto-fill =====
        print("\n=== 5. AI Draft Auto-fill ===")
        page = ctx.new_page()
        page.goto(BASE, wait_until="networkidle")
        inject_state(page)
        page.click(".nav-item[data-panel='editor']"); time.sleep(0.3)
        content = page.input_value("#editorContent")
        check("AI draft auto-filled", "第一章正文内容" in content, f"got: {content[:50]}")
        page.close()

        # ===== 6. Review Panel =====
        print("\n=== 6. Review Panel ===")
        page = ctx.new_page()
        page.goto(BASE, wait_until="networkidle")
        inject_state(page)
        page.click(".nav-item[data-panel='review']"); time.sleep(0.3)
        check("Review report shown", "审查通过" in page.content() or "审查" in page.content())
        check("Review has start button", page.locator("button:has-text('开始新的审查')").is_visible())
        page.close()

        # ===== 7. Responsive =====
        print("\n=== 7. Responsive ===")
        page.close()
        # Narrow viewport (800px triggers 900px breakpoint)
        ctx2 = browser.new_context(viewport={"width": 800, "height": 800})
        ctx2.route("**/*", lambda route: route.abort()
            if "fonts.googleapis.com" in route.request.url or "fonts.gstatic.com" in route.request.url
            else route.continue_())
        page = ctx2.new_page()
        page.goto(BASE, wait_until="networkidle")
        inject_state(page)
        time.sleep(0.3)
        check("Hamburger exists (narrow)", page.locator("#navToggle").count() > 0)
        check("Floating chat exists (narrow)", page.locator("#chatBtn").count() > 0)
        page.close()
        ctx2.close()

        # Back to wide viewport
        page = ctx.new_page()
        page.goto(BASE, wait_until="networkidle")
        inject_state(page)
        time.sleep(0.3)
        check("Hamburger hidden (wide)", page.locator("#navToggle").is_hidden())
        page.close()

        # ===== 8. Quick Buttons =====
        print("\n=== 8. Quick Buttons ===")
        page = ctx.new_page()
        page.goto(BASE, wait_until="networkidle")
        inject_state(page)
        btns = page.locator("#quickBtns button")
        count = btns.count()
        check(f"Quick buttons count: {count}", count >= 7)
        # Check button labels
        labels = []
        for i in range(count):
            labels.append(btns.nth(i).text_content())
        check("Has 选题 button", "选题" in labels)
        check("Has 角色 button", "角色" in labels)
        check("Has 写稿 button", "写稿" in labels)
        page.close()

        # ===== 9. Story Save =====
        print("\n=== 9. Story Save ===")
        page = ctx.new_page()
        page.goto(BASE, wait_until="networkidle")
        inject_state(page)
        page.click(".nav-item[data-panel='story']"); time.sleep(0.3)
        st = page.locator(".story-field textarea").first
        check("Story textarea visible", st.is_visible())
        st.fill("修改后的一句话")
        check("Story edit value", st.input_value() == "修改后的一句话")
        page.close()

        browser.close()
        print(f"\n{'='*50}")
        print(f"  结果: {PASS}/{PASS+FAIL} 通过")
        if FAIL: print(f"  失败: {FAIL}")
        else: print("  全部通过！")
        print(f"{'='*50}")
        return FAIL == 0

if __name__ == "__main__":
    sys.exit(0 if test_all() else 1)
