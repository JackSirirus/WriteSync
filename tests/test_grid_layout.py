"""
Playwright test: verify the new Xiaohongshu-style project grid layout.
Server must be running on BASE_URL (default http://127.0.0.1:8000).
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["LANGGRAPH_STRICT_MSGPACK"] = "false"
sys.stdout.reconfigure(encoding="utf-8")

from playwright.sync_api import sync_playwright

BASE = os.environ.get("WRITESYNC_URL", "http://127.0.0.1:8000")
PASS = 0
FAIL = 0

def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS: {name}")
    else:
        FAIL += 1
        print(f"  FAIL: {name} - {detail}" if detail else f"  FAIL: {name}")

def run():
    global PASS, FAIL
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        ctx = b.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        page.set_default_timeout(15000)
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        # Block render-blocking external resources
        page.route("**/*", lambda route, request:
            route.abort()
            if request.url.startswith("https://fonts.googleapis.com")
            or request.url.startswith("https://fonts.gstatic.com")
            or request.url.startswith("https://cdn.quilljs.com")
            else route.continue_())

        # === 1. Page Load - Grid Page ===
        print("\n=== 1. Page Load: Grid Page ===")
        page.goto(BASE, timeout=15000, wait_until="commit")
        page.wait_for_selector("#projectGrid", timeout=10000)
        page.wait_for_timeout(500)
        check("No JS errors", len(errors) == 0, str(errors))

        # The grid page should be visible (since we previously created test projects)
        grid_visible = page.locator("#projectGrid").is_visible()
        check("Grid page is main view (not modal)", grid_visible)
        check("Grid header with logo", page.locator(".grid-header").is_visible())
        check("New project button in header",
              page.locator(".grid-header button:has-text('新建项目')").count() > 0)
        check("Grid hero section", page.locator(".grid-hero").is_visible())

        # === 2. Grid Cards ===
        print("\n=== 2. Grid Cards ===")
        cards = page.locator(".grid-card")
        count = cards.count()
        check("At least one grid card rendered", count > 0, f"found {count}")

        if count > 0:
            first_card = cards.first
            check("Card has title", first_card.locator(".card-title").count() > 0)
            check("Card has progress bar",
                  first_card.locator(".card-progress .track").count() > 0)
            check("Card has action buttons",
                  first_card.locator(".card-actions button").count() > 0)
            check("Card has continue button",
                  first_card.locator("[data-action='continue']").count() > 0)
            check("Card has delete button",
                  first_card.locator("[data-action='delete']").count() > 0)
            check("Card has stage badge",
                  first_card.locator(".card-badge").count() > 0)
            check("Card has stats",
                  first_card.locator(".card-stats").count() > 0)

        # === 3. New Project Modal ===
        print("\n=== 3. New Project Modal ===")
        check("Modal hidden by default",
              not page.locator("#setupOverlay").is_visible())
        page.locator("button:has-text('新建项目')").click()
        page.wait_for_timeout(300)
        check("Modal visible after click",
              page.locator("#setupOverlay").is_visible())
        check("Modal has start button",
              page.locator("#startBtn").count() > 0)
        check("Modal has close button",
              page.locator(".setup-close").count() > 0)
        check("Modal has form fields",
              page.locator("#ideaInput").count() > 0)

        # Close modal
        page.locator(".setup-close").click()
        page.wait_for_timeout(200)
        check("Modal hidden after close",
              not page.locator("#setupOverlay").is_visible())

        # === 4. Loading Overlay ===
        print("\n=== 4. Loading Overlay ===")
        check("Loading overlay exists",
              page.locator("#loadingOverlay").count() > 0)
        page.evaluate("showLoading('Test','Testing')")
        page.wait_for_timeout(200)
        check("Loading overlay visible",
              page.locator("#loadingOverlay").is_visible())
        check("Spinner visible",
              page.locator(".loading-spinner").is_visible())
        page.evaluate("hideLoading()")
        page.wait_for_timeout(200)
        check("Loading overlay hidden",
              not page.locator("#loadingOverlay").is_visible())

        # === 5. Responsive ===
        print("\n=== 5. Responsive (Narrow) ===")
        ctx2 = b.new_context(viewport={"width": 768, "height": 900})
        p2 = ctx2.new_page()
        p2.route("**/*", lambda route, request:
            route.abort()
            if request.url.startswith("https://fonts.googleapis.com")
            or request.url.startswith("https://fonts.gstatic.com")
            or request.url.startswith("https://cdn.quilljs.com")
            else route.continue_())
        p2.goto(BASE, timeout=15000, wait_until="commit")
        p2.wait_for_selector(".grid-card", timeout=10000)
        check("Narrow: grid cards visible",
              p2.locator(".grid-card").count() > 0)
        check("Narrow: header visible",
              p2.locator(".grid-header").is_visible())
        ctx2.close()

        # Summary
        total = PASS + FAIL
        print(f"\n{'='*40}")
        print(f"Results: {PASS}/{total} passed, {FAIL} failed")
        b.close()
        return FAIL == 0

if __name__ == "__main__":
    ok = run()
    sys.exit(0 if ok else 1)
