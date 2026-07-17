"""WriteSync Full Flow E2E - API driven"""
import requests, time, json, sys

BASE = "http://127.0.0.1:8001"
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


def wait_and_confirm(pid, agent, max_wait=180):
    print(f"\n--- Waiting: {agent} ---")
    start = time.time()
    while time.time() - start < max_wait:
        time.sleep(5)
        s = api("GET", f"/api/v2/status/{pid}")
        d = s.get("dashboard", {})
        phase = d.get("phase", "")
        comp = d.get("completed_agents", [])
        prog = d.get("progress", {})

        if agent in comp:
            return True

        # Try responding to unblock orchestrator
        api("POST", f"/api/v2/respond/{pid}", {"approved": "true"})

        elapsed = int(time.time() - start)
        w = prog.get("written", 0)
        print(f"  [{elapsed}s] phase={phase} comp={comp[:3]} w={w}")
    return False


def main():
    global PASS, FAIL
    print("=" * 60)
    print("WriteSync Full Flow E2E")
    print(f"BASE={BASE}")
    print("=" * 60)

    # Step 1: Create
    print("\n--- Step 1: Create project ---")
    resp = api("POST", "/api/v2/start", {"idea": THEME, "platform": u"\u8d77\u70b9"})
    check("Project created", resp.get("ok"), str(resp))
    pid = resp.get("project_id", "")
    print(f"  pid: {pid}")

    # Step 2: Start session
    print("\n--- Step 2: Start session ---")
    resp = api("POST", "/api/v2/start", {"project_id": pid})
    check("Session started", resp.get("ok"))
    d = resp.get("dashboard", {})
    print(f"  phase: {d.get('phase')}")

    # Step 3: Wait for topics
    print("\n--- Step 3: Wait for topics ---")
    ok = False
    for i in range(36):
        time.sleep(5)
        s = api("GET", f"/api/v2/status/{pid}")
        phase = s.get("dashboard", {}).get("phase", "")
        print(f"  [{i}] phase={phase}")
        if phase == "topic_selection":
            ok = True
            break
    check("Topics ready", ok)

    # Step 4: Select topic
    print("\n--- Step 4: Select topic ---")
    resp = api("POST", f"/api/v2/respond/{pid}", {"approved": "true", "feedback": "xuantib: zhengqi jiyuan"})
    check("Topic selected", resp.get("ok"), str(resp))
    time.sleep(5)

    # Steps 5-8: Planning agents
    check("Story expansion", wait_and_confirm(pid, "story", 180))
    check("Character", wait_and_confirm(pid, "character", 180))
    check("World", wait_and_confirm(pid, "world", 180))
    check("Outline", wait_and_confirm(pid, "outline", 180))

    # Step 9: Chapters
    for ch in range(1, 4):
        print(f"\n--- Chapter {ch} ---")
        start = time.time()
        ok = False
        while time.time() - start < 300:
            time.sleep(5)
            s = api("GET", f"/api/v2/status/{pid}")
            w = s.get("dashboard", {}).get("progress", {}).get("written", 0)
            if w >= ch:
                ok = True
                break
            api("POST", f"/api/v2/respond/{pid}", {"approved": "true"})
            print(f"  Ch{ch}: written={w}")
        check(f"Ch{ch} written", ok)
        time.sleep(5)

    # Step 10: Review + Done
    check("Novel review", wait_and_confirm(pid, "novel_review", 300))

    print("\n--- Done ---")
    ok = False
    for i in range(24):
        time.sleep(5)
        s = api("GET", f"/api/v2/status/{pid}")
        comp = s.get("dashboard", {}).get("completed_agents", [])
        if "novel_review" in comp:
            api("POST", f"/api/v2/finish/{pid}", {"confirmed": "true"})
            ok = True
            break
        print(f"  done-wait: {comp[:4]}")
    check("Done", ok)

    # Final
    s = api("GET", f"/api/v2/status/{pid}")
    d = s.get("dashboard", {})
    print(f"\n=== FINAL ===")
    print(f"  phase: {d.get('phase')}")
    print(f"  completed: {d.get('completed_agents')}")
    print(f"  progress: {d.get('progress')}")
    print(f"  PASS={PASS} FAIL={FAIL}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
