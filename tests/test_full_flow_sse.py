"""
WriteSync Full Flow E2E — SSE-driven
Connects to SSE stream, auto-responds to confirm events, runs until done.
"""
import requests, json, time, threading, queue, sys

BASE = "http://127.0.0.1:8001"
THEME = "一个程序员穿越到蒸汽时代的克鲁苏世界，发明了AI从而成为主神的故事"
MAX_CHAPTERS = 3

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


def main():
    global PASS, FAIL
    print("=" * 60)
    print("WriteSync Full Flow E2E (SSE-driven)")
    print(f"BASE={BASE}")
    print("=" * 60)

    # Step 1: Create project
    print("\n--- Step 1: Create project ---")
    r = requests.post(
        f"{BASE}/api/v2/start",
        data={"idea": THEME, "platform": u"\u8d77\u70b9"},
        timeout=10,
    )
    data = r.json()
    pid = data["project_id"]
    check("Project created", data.get("ok"), str(data))
    print(f"  pid: {pid}")

    # Step 2: Connect SSE
    print("\n--- Step 2: Connect SSE ---")
    events = queue.Queue()
    confirm_done = threading.Event()

    def sse_reader():
        try:
            r = requests.get(
                f"{BASE}/api/v2/stream/{pid}", stream=True, timeout=900
            )
            current_event = None
            for line in r.iter_lines(decode_unicode=True):
                if line and line.startswith("event:"):
                    current_event = line[6:].strip()
                elif line and line.startswith("data:"):
                    try:
                        d = json.loads(line[5:].strip())
                        events.put({"type": current_event, "data": d})
                    except json.JSONDecodeError:
                        pass
        except Exception as e:
            events.put({"type": "error", "data": {"message": str(e)}})

    t = threading.Thread(target=sse_reader, daemon=True)
    t.start()
    time.sleep(3)
    check("SSE connected", t.is_alive())

    # Step 3: Auto-respond loop
    print("\n--- Step 3: Auto-respond loop ---")
    confirm_count = 0
    chapter_count = 0
    done_received = False
    error_count = 0
    start_time = time.time()
    max_runtime = 1800  # 30 min max

    def respond(approved=True, feedback=""):
        requests.post(
            f"{BASE}/api/v2/respond/{pid}",
            data={"approved": "true" if approved else "false", "feedback": feedback},
            timeout=5,
        )

    while time.time() - start_time < max_runtime:
        try:
            evt = events.get(timeout=10)
            etype = evt.get("type", "")
            edata = evt.get("data", {})

            if etype == "thinking":
                step = edata.get("step", "?")
                print(f"  thinking step={step}")

            elif etype == "agent_call":
                agent = edata.get("agent", "?")
                inst = edata.get("instruction", "")[:60]
                print(f"  agent_call: {agent} | {inst}")

            elif etype == "workspace_update":
                summary = edata.get("summary", "")
                print(f"  workspace_update: {summary[:80]}")

            elif etype == "auxiliary_check":
                checks = edata.get("checks", [])
                for c in checks:
                    icon = "PASS" if c.get("status") == "pass" else "WARN"
                    print(f"  aux_check: [{icon}] {c.get('name')} - {c.get('detail', '')[:40]}")

            elif etype == "confirm":
                confirm_count += 1
                agent = edata.get("agent", "?")
                content = edata.get("content", {})
                stage = content.get("stage", "")

                print(f"  CONFIRM #{confirm_count}: agent={agent} stage={stage}")

                if agent == "story" and stage == "topics":
                    time.sleep(1)
                    respond(approved=True, feedback=f"选题: {THEME[:20]}")
                    print(f"    -> topic selected")

                elif agent == "writer":
                    chapter_count += 1
                    ch = edata.get("chapter_num", chapter_count)
                    print(f"    -> Ch{ch} confirmed ({chapter_count}/{MAX_CHAPTERS})")
                    respond(approved=True)
                    if chapter_count >= MAX_CHAPTERS:
                        print(f"    -> Max chapters reached, stopping chapter writes")

                elif agent == "novel_review":
                    respond(approved=True)
                    print(f"    -> novel_review confirmed")

                else:
                    respond(approved=True)
                    print(f"    -> {agent} confirmed")

            elif etype == "done":
                done_received = True
                print(f"  DONE: {edata.get('reason', '')}")
                requests.post(
                    f"{BASE}/api/v2/finish/{pid}",
                    data={"confirmed": "true"},
                    timeout=5,
                )
                print(f"    -> finish confirmed")
                break

            elif etype == "error":
                error_count += 1
                msg = edata.get("message", "")[:100]
                print(f"  ERROR: {msg}")
                if error_count > 5:
                    print("  Too many errors, stopping")
                    break

            elif etype == "volume_change":
                print(f"  VOLUME_CHANGE: {edata}")

            # Check phase from status periodically
            if confirm_count > 0 and confirm_count % 3 == 0:
                try:
                    s = requests.get(
                        f"{BASE}/api/v2/status/{pid}", timeout=5
                    ).json()
                    d = s.get("dashboard", {})
                    print(f"  STATUS: phase={d.get('phase')} "
                          f"completed={d.get('completed_agents', [])[:4]} "
                          f"written={d.get('progress', {}).get('written', 0)}")
                except Exception:
                    pass

        except queue.Empty:
            elapsed = int(time.time() - start_time)
            if elapsed % 60 < 10:
                print(f"  ... idle {elapsed}s ...")

    # Final
    print(f"\n{'='*60}")
    print(f"FINAL RESULTS")
    print(f"{'='*60}")
    try:
        s = requests.get(f"{BASE}/api/v2/status/{pid}", timeout=5).json()
        d = s.get("dashboard", {})
        print(f"  phase: {d.get('phase')}")
        print(f"  completed: {d.get('completed_agents')}")
        print(f"  progress: {d.get('progress')}")
        print(f"  hook_rate: {d.get('hook_landing_rate', 0)}")
        print(f"  pleasure: {d.get('pleasure_density', 0)}")
    except Exception as e:
        print(f"  status error: {e}")

    print(f"  confirm_count: {confirm_count}")
    print(f"  chapter_count: {chapter_count}")
    print(f"  done: {done_received}")
    print(f"  errors: {error_count}")
    print(f"  PASS={PASS} FAIL={FAIL}")

    return 0 if done_received and FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
