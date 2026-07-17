"""
Step-by-step Playwright E2E — each step has its own timeout and diagnosis
"""
import os, sys, time, requests, threading, queue, json, glob
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["LANGGRAPH_STRICT_MSGPACK"] = "false"
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8001"
THEME = "一个程序员穿越到蒸汽时代的克鲁苏世界，发明了AI从而成为主神的故事"

def api_post(path, data=None):
    try:
        return requests.post(f"{BASE}{path}", data=data or {}, timeout=10).json()
    except Exception as e:
        return {"error": str(e)}

def api_get(path):
    try:
        return requests.get(f"{BASE}{path}", timeout=10).json()
    except Exception as e:
        return {"error": str(e)}

def status(pid):
    s = api_get(f"/api/v2/status/{pid}")
    d = s.get("dashboard", {})
    return {
        "phase": d.get("phase", "?"),
        "completed": d.get("completed_agents", []),
        "written": d.get("progress", {}).get("written", 0),
        "total": d.get("progress", {}).get("total_chapters", 0),
    }

def diagnose(pid, step_name):
    """诊断为什么卡住了"""
    st = status(pid)
    print(f"  DIAG: phase={st['phase']} completed={st['completed']} written={st['written']}/{st['total']}")
    import glob, os
    logs = sorted(glob.glob("logs/writesync-*.log"), key=os.path.getmtime, reverse=True)
    if logs:
        with open(logs[0], "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
            for line in lines[-5:]:
                if any(kw in line for kw in ["ERROR", "WARNING", "决策", "调用", "Orchestrator"]):
                    print(f"  LOG: {line.strip()[-150:]}")
    return st

def respond(pid, approved=True, fb=""):
    return api_post(f"/api/v2/respond/{pid}", {"approved": "true" if approved else "false", "feedback": fb})

def wait_for_condition(pid, check_fn, label, max_wait, events_queue=None):
    """等待条件满足，同时处理 SSE confirm 事件"""
    start = time.time()
    while time.time() - start < max_wait:
        time.sleep(3)
        st = status(pid)
        if check_fn(st):
            return True, st
        
        # Process any pending confirm events from SSE
        if events_queue:
            while not events_queue.empty():
                try:
                    evt = events_queue.get_nowait()
                    etype = evt.get("type", "")
                    edata = evt.get("data", {})
                    if etype != "confirm":
                        continue
                    agent = edata.get("agent", "")
                    content = edata.get("content", {})
                    stage = content.get("stage", "")
                    print(f"    SSE-confirm: agent={agent} stage={stage}")
                    if agent == "story" and stage == "topics":
                        respond(pid, fb="选题: 蒸汽纪元")
                    else:
                        respond(pid)
                except queue.Empty:
                    break
                except Exception as e:
                    print(f"    respond error: {e}")
        
        elapsed = int(time.time() - start)
        if elapsed % 30 < 3:
            print(f"  [{elapsed}s] phase={st['phase']} comp={st['completed'][:3]} w={st['written']}")
    return False, status(pid)


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1400, "height": 900})
        page = ctx.new_page()
        page.route("**/*", lambda route: route.abort()
            if "fonts.googleapis.com" in route.request.url
            else route.continue_())

        # ═══ STEP 1: Create project + navigate ═══
        print("\n" + "=" * 50)
        print("STEP 1: Create project")
        resp = api_post("/api/v2/start", {"idea": THEME, "platform": "起点"})
        pid = resp.get("project_id", "")
        assert pid, f"Create failed: {resp}"
        print(f"  pid={pid}")

        page.goto(BASE, wait_until="domcontentloaded")
        time.sleep(2)

        # Trigger SSE orchestrator session via API (no need to click UI cards)
        api_post("/api/v2/start", {"project_id": pid})

        # MUST connect to SSE stream to start the orchestrator loop
        events = queue.Queue()
        def sse_reader():
            try:
                r = requests.get(f"{BASE}/api/v2/stream/{pid}", stream=True, timeout=999)
                current_event = None
                for line in r.iter_lines(decode_unicode=True):
                    if line and line.startswith("event:"):
                        current_event = line[6:].strip()
                    elif line and line.startswith("data:"):
                        try:
                            d = json.loads(line[5:].strip())
                            events.put({"type": current_event, "data": d})
                        except:
                            pass
            except Exception as e:
                print(f"  SSE error: {e}")
        t = threading.Thread(target=sse_reader, daemon=True)
        t.start()
        time.sleep(3)
        print(f"  SSE connected for {pid}")

        # ═══ STEP 2: Auto-run until done, checking each milestone ═══
        milestones = [
            ("topic_selection", lambda s: s["phase"] in ("topic_selection", "planning", "writing_chapters"), 180),
            ("story confirmed", lambda s: "story" in s["completed"], 300),
            ("character confirmed", lambda s: "character" in s["completed"], 300),
            ("world confirmed", lambda s: "world" in s["completed"], 300),
            ("outline confirmed", lambda s: "outline" in s["completed"], 300),
            ("Ch1 written", lambda s: s["written"] >= 1, 300),
            ("Ch2 written", lambda s: s["written"] >= 2, 300),
            ("Ch3 written", lambda s: s["written"] >= 3, 300),
            ("novel_review", lambda s: "novel_review" in s["completed"], 300),
        ]

        step_num = 2
        for label, check_fn, max_wait in milestones:
            print(f"\n{'='*50}")
            print(f"STEP {step_num}: {label} (max {max_wait}s)")
            ok, st = wait_for_condition(pid, check_fn, label, max_wait, events)
            if not ok:
                print(f"  TIMEOUT on: {label}")
                diagnose(pid, label)
                browser.close()
                return 1
            print(f"  DONE: phase={st['phase']} comp={st['completed'][:4]} w={st['written']}")
            step_num += 1

        # ═══ Final: Done ═══
        print(f"\n{'='*50}")
        print(f"STEP {step_num}: Finish")
        api_post(f"/api/v2/finish/{pid}", {"confirmed": "true"})
        time.sleep(3)
        st = status(pid)
        print(f"  Final: phase={st['phase']} completed={st['completed']} written={st['written']}")
        print(f"\n{'='*50}")
        print("ALL STEPS COMPLETE!")
        browser.close()
        return 0

if __name__ == "__main__":
    sys.exit(main())
