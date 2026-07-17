"""
WriteSync CLI v0.3.0 — Orchestrator 模式

运行方式：
    python -m src.cli
    python -m src.cli --model deepseek-v4-pro
"""

import sys, os, argparse, asyncio
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")


def _setup_env(args):
    for key in ["LLM_MODEL", "LLM_PROVIDER"]:
        os.environ.pop(key, None)
    if args.model:
        os.environ["LLM_MODEL"] = args.model
    if args.provider:
        os.environ["LLM_PROVIDER"] = args.provider
    if args.local_model:
        from src.utils.provider_config import AIProviderConfig
        from src.utils.provider_manager import get_provider_manager
        pm = get_provider_manager()
        ollama = AIProviderConfig.create_ollama(model=args.local_model)
        pm.add_provider(ollama)
        pm.set_default("ollama")
        print(f"[CLI] 已启用本地 Ollama 模型: {args.local_model}")


async def _main(args) -> int:
    from src.orchestrator import Workspace, OrchestratorSession, SSEEventType, init_workspace, load_workspace
    from src.state.persistence import PersistenceManager

    print("=" * 50)
    print("WriteSync v0.3.0 CLI")
    print("=" * 50)
    print()

    pm = PersistenceManager(projects_dir="projects")

    projects = pm.list_projects()
    ws = None
    if projects:
        print("已有项目：")
        for i, p in enumerate(projects):
            print(f"  [{i}] {p['name']} ({p['project_id']}) - {p['status']}")
        print("  [n] 新建项目")
        choice = input("\n选择项目（默认 [n]）: ").strip().lower()
        if choice != "n" and choice != "":
            try:
                idx = int(choice)
                pid = projects[idx]["project_id"]
                ws = load_workspace(pid)
                if ws:
                    print(f"已加载: {ws.project_name}")
            except (ValueError, IndexError):
                pass

    if ws is None:
        name = input("项目名称: ").strip() or "我的小说"
        platform = input("目标平台（默认 起点）: ").strip() or "起点"
        idea = input("请描述您的创作想法：\n> ")
        ws = init_workspace(name, platform, idea)

    print(f"\n项目ID: {ws.project_id} | schema: v{ws.schema_version}")
    dashboard = ws.get_dashboard()
    print(f"阶段: {dashboard.phase}")
    print()

    session = OrchestratorSession(ws)
    print("编排器启动...\n")

    async for event in session.run():
        t = event.type
        data = event.data

        if t == SSEEventType.THINKING:
            print(f"[{data.get('step', '?')}] AI 思考中...")

        elif t == SSEEventType.AGENT_CALL:
            print(f"  → 调用 {data.get('agent', '?')}: {data.get('instruction', '')[:80]}")

        elif t == SSEEventType.WORKSPACE_UPDATE:
            s = data.get("summary", "")
            if s:
                print(f"  ✓ {s}")

        elif t == SSEEventType.CONFIRM:
            agent = data.get("agent", "?")
            content = data.get("content", {})
            print(f"\n{'='*40}")
            print(f"[需确认] {agent}")
            print(f"{'='*40}")
            choice = _handle_confirm(agent, content, data)
            if choice is None:
                break
            session.user_respond(**choice)

        elif t == SSEEventType.DONE:
            print(f"\n🎉 全书写作完成！{data.get('reason', '')}")
            print("[y] 确认完成  [q] 退出")
            c = input("> ").strip().lower()
            if c == 'q':
                session.stop()
                break
            session.user_respond(approved=c != 'n')

        elif t == SSEEventType.ERROR:
            print(f"\n❌ 错误: {data.get('message', '')}")
            print("[r] 重试  [q] 退出")
            if input("> ").strip().lower() == 'q':
                session.stop()
                break

    print("\n会话结束。")
    ws.save()
    return 0


def _handle_confirm(agent: str, content: dict, event_data: dict) -> dict | None:
    """处理确认事件，返回 user_respond 参数或 None 表示退出"""
    if agent == "story" and content.get("stage") == "topics":
        topics = content.get("topics", [])
        for i, t in enumerate(topics):
            print(f"  [{i}] {t.get('title', '')} — {t.get('genre', '')}/{t.get('sub_genre', '')}")
        print("  选择编号 / r=重新生成 / q=退出")
        c = input("> ").strip().lower()
        if c == 'q': return None
        if c == 'r': return {"approved": False, "feedback": "换个方向"}
        try:
            idx = int(c)
            t = topics[idx]
            return {"approved": True, "feedback": f"选择: {t.get('title', '')}"}
        except (ValueError, IndexError):
            return {"approved": True}

    if agent == "story" and content.get("stage") == "expansion":
        exp = content.get("expansion", {})
        print(f"  一句话: {content.get('one_sentence', '')}")
        for k, l in [("setup", "背景"), ("inciting", "转折1"), ("rising", "中点"),
                      ("climax_prep", "转折2"), ("resolution", "结局")]:
            print(f"  {l}: {exp.get(k, '')}")
        print("  [y] 确认  [n] 提修改意见  [q] 退出")
        c = input("> ").strip().lower()
        if c == 'q': return None
        if c == 'y': return {"approved": True}
        fb = input("修改意见: ").strip()
        return {"approved": False, "feedback": fb}

    if agent == "writer":
        ch = event_data.get("chapter_num", "?")
        print(f"  第{ch}章 ({content.get('word_count', 0)}字)")
        print(f"  {content.get('content', '')[:200]}...")
        print("  [y] 确认  [m] 提意见重写  [q] 退出")
        c = input("> ").strip().lower()
        if c == 'q': return None
        if c == 'y': return {"approved": True}
        if c == 'm':
            fb = input("修改意见: ").strip()
            return {"approved": False, "feedback": fb}
        return {"approved": False}

    if agent == "novel_review":
        print(f"  审查: {'通过' if content.get('passed') else '需修改'}")
        for r in content.get("recommendations", [])[:5]:
            print(f"  - {r}")
        print("  [y] 确认完成  [q] 退出")
        c = input("> ").strip().lower()
        if c == 'q': return None
        return {"approved": c == 'y'}

    # 通用
    print(f"  产出: {str(content)[:200]}...")
    print("  [y] 确认  [n] 提意见  [q] 退出")
    c = input("> ").strip().lower()
    if c == 'q': return None
    if c == 'y': return {"approved": True}
    fb = input("修改意见: ").strip()
    return {"approved": False, "feedback": fb}


def main():
    parser = argparse.ArgumentParser(description="WriteSync v0.3.0 CLI")
    parser.add_argument("--model", default="", help="LLM 模型名")
    parser.add_argument("--provider", default="", help="LLM 供应商")
    parser.add_argument("--local-model", default="", help="使用本地 Ollama 模型（例如 llama3）")
    args = parser.parse_args()

    _setup_env(args)
    return asyncio.run(_main(args))


if __name__ == "__main__":
    main()
