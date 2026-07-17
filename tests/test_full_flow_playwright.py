"""
全流程 Playwright E2E - 创建项目到全书完成
运行: python tests/test_full_flow_playwright.py
"""
import sys, os, time, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["LANGGRAPH_STRICT_MSGPACK"] = "false"
import requests
from playwright.sync_api import sync_playwright

BASE = os.environ.get("WRITESYNC_URL", "http://127.0.0.1:8001")
THEME = "一个程序员穿越到蒸汽时代的克鲁苏世界，发明了AI从而成为主神的故事"

PASS = 0
FAIL = 0

def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS: {name}")
    else:
        FAIL += 1
        print(f"  FAIL: {name} {detail}")

def api(method, path, data=None):
    url = f"{BASE}{path}"
    try:
        if method == "GET":
            return requests.get(url, timeout=10).json()
        elif method == "POST":
            return requests.post(url, data=data or {}, timeout=10).json()
    except Exception as e:
        return {"error": str(e)}

def main():
    global PASS, FAIL
    print("=" * 60)
    print("WriteSync Full Flow E2E")
    print(f"BASE={BASE}")
    print("=" * 60)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1400, "height": 900})
        page = ctx.new_page()
        page.route("**/*", lambda route: route.abort()
            if "fonts.googleapis.com" in route.request.url
            else route.continue_())

        # Step 1: Open page
        print("\n--- Step 1: Open ---")
        page.goto(BASE, wait_until="domcontentloaded")
        time.sleep(2)
        check("Page loads", len(page.content()) > 500)

        # Step 2: Create project via API
        print("\n--- Step 2: Create project ---")
        resp = api("POST", "/api/v2/start", {"idea": THEME, "platform": "起点"})
        check("Project created", resp.get("ok") == True, str(resp.get("error", "")))
        project_id = resp.get("project_id", "")
        print(f"  project_id: {project_id}")

        # Load in browser and trigger SSE
        page.goto(BASE, wait_until="domcontentloaded")
        time.sleep(2)
        cards = page.locator(".project-card, [class*=project]")
        if cards.count() > 0:
            cards.first.click()
            time.sleep(3)

        api("POST", "/api/v2/start", {"project_id": project_id})
        page.goto(BASE, wait_until="domcontentloaded")
        time.sleep(3)
        cards = page.locator(".project-card, [class*=project]")
        if cards.count() > 0:
            cards.first.click()
            time.sleep(5)

        # Helper: auto confirm an agent by polling status
        def auto_confirm(label, max_wait=180):
            start = time.time()
            responded = False
            while time.time() - start < max_wait:
                time.sleep(5)
                s = api("GET", f"/api/v2/status/{project_id}")
                d = s.get("dashboard", {})
                phase = d.get("phase", "")
                completed = d.get("completed_agents", [])
                progress = d.get("progress", {})

                if label == "story" and "story" in completed:
                    return True
                if label == "character" and "character" in completed:
                    return True
                if label == "world" and "world" in completed:
                    return True
                if label == "outline" and "outline" in completed:
                    return True
                if label == "novel_review" and "novel_review" in completed:
                    return True

                # Try responding if orchestrator might be waiting
                if not responded:
                    resp = api("POST", f"/api/v2/respond/{project_id}", {"approved": "true"})
                    if resp.get("ok"):
                        responded = True

                print(f"  [{label}] phase={phase} completed={completed[:3]}")

            return False

        # Step 3: Topic selection
        print("\n--- Step 3: Topic ---")
        resp = api("POST", f"/api/v2/respond/{project_id}", {
            "approved": "true",
            "feedback": "选题: 蒸汽纪元",
        })
        check("Topic confirmed", resp.get("ok") == True)
        time.sleep(5)

        # Steps 4-7: Planning
        check("Story expansion", auto_confirm("story", 180))
        check("Character", auto_confirm("character", 180))
        check("World", auto_confirm("world", 180))
        check("Outline", auto_confirm("outline", 180))

        # Step 8: Chapters
        for ch in range(1, 4):
            print(f"\n--- Chapter {ch} ---")
            check(f"Ch{ch} writer", auto_confirm("writer", 300))

        # Step 9: Review
        print("\n--- Review ---")
        check("Novel review", auto_confirm("novel_review", 300))

        # Step 10: Done
        print("\n--- Done ---")
        done = False
        for _ in range(24):
            time.sleep(5)
            s = api("GET", f"/api/v2/status/{project_id}")
            d = s.get("dashboard", {})
            if "novel_review" in d.get("completed_agents", []):
                api("POST", f"/api/v2/finish/{project_id}", {"confirmed": "true"})
                done = True
                break
            print(f"  phase={d.get('phase')} completed={d.get('completed_agents', [])[:4]}")
        check("Done", done)

        # Final status
        s = api("GET", f"/api/v2/status/{project_id}")
        d = s.get("dashboard", {})
        print(f"\n=== FINAL ===")
        print(f"  phase: {d.get('phase')}")
        print(f"  completed: {d.get('completed_agents')}")
        print(f"  progress: {d.get('progress')}")
        print(f"  PASS={PASS} FAIL={FAIL}")

        browser.close()

    return 0 if FAIL == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
