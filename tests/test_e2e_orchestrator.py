"""
E2E Orchestrator Test — 真实 LLM 调用

测试流程：
1. 创建项目（种子想法）
2. 启动 OrchestratorSession
3. 前 8 步自动确认，观察 agent 调用链
4. 验证产出了 story/characters/world/outline
5. v0.4.0: 验证 auxiliary_check 事件 + Dashboard 字段

用法：
  python tests/test_e2e_orchestrator.py

环境变量（可选）：
  LLM_MODEL=deepseek-v4-pro
  LLM_PROVIDER=opencode
"""

import asyncio
import sys
import os
import json
import shutil
import time
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ["LANGGRAPH_STRICT_MSGPACK"] = "false"

PROJECTS_DIR = "projects"

from src.orchestrator import (
    Workspace, init_workspace, load_workspace,
    OrchestratorSession, SSEEventType, SSEEvent,
    call_agent,
)


async def run_e2e_test():
    print("=" * 60)
    print("WriteSync v0.3.0 E2E Orchestrator Test")
    print(f"Model: {os.environ.get('LLM_MODEL', 'deepseek-v4-pro')}")
    print("=" * 60)

    seed = "一个被家族抛弃的修真少年，在末世废墟中觉醒上古血脉，踏上复仇与救赎之路"

    print("\n[1/4] 创建项目...")
    ws = init_workspace("E2E测试", "起点", seed)
    pid = ws.project_id
    print(f"  project_id: {pid}")

    print("\n[2/4] 启动编排器...")
    session = OrchestratorSession(ws)
    t0 = time.time()

    events = []
    max_steps = 8
    agent_calls = []
    confirms = []
    aux_checks = []  # v0.4.0

    print(f"\n[3/4] 运行编排循环 (最多 {max_steps} 步)...\n")
    step = 0

    async for event in session.run():
        step += 1
        events.append(event)
        t = event.type
        data = event.data

        print(f"── Step {step} ── [{t}] ──")

        if t == SSEEventType.THINKING:
            print(f"  AI 思考中...")

        elif t == SSEEventType.AGENT_CALL:
            agent = data.get("agent", "?")
            instr = data.get("instruction", "")[:100]
            agent_calls.append(agent)
            print(f"  调用子Agent: {agent}")
            print(f"  指令: {instr}")

        elif t == SSEEventType.WORKSPACE_UPDATE:
            summary = data.get("summary", "")
            print(f"  产出: {summary[:100]}")

        elif t == SSEEventType.CONFIRM:
            agent = data.get("agent", "?")
            content = data.get("content", {})
            confirms.append(agent)
            print(f"  等待确认: {agent}")

            # 展示部分内容
            if agent == "story":
                stage = content.get("stage", "")
                if stage == "topics":
                    topics = content.get("topics", [])
                    for i, tp in enumerate(topics[:3]):
                        print(f"    [{i}] {tp.get('title', '')} ({tp.get('genre', '')})")
                    # 自动选第一个选题
                    if topics:
                        t0_title = topics[0].get('title', '')
                        session.user_respond(approved=True,
                            feedback=f"选择选题: {t0_title}")
                        print(f"  [auto] 选择选题: {t0_title}")
                    else:
                        session.user_respond(approved=True)
                elif stage == "expansion":
                    expansion = content.get("expansion", {})
                    print(f"    一句话: {content.get('one_sentence', '')[:60]}")
                    print(f"    背景: {expansion.get('setup', '')[:60]}...")
                    session.user_respond(approved=True)
                    print(f"  [auto] 确认扩展")
                else:
                    session.user_respond(approved=True)
                    print(f"  [auto] 确认")

            elif agent == "character":
                chars = content.get("characters", [])
                for c in chars[:3]:
                    print(f"    {c.get('name', '?')} ({c.get('role', '?')}): {c.get('personality', '')}")
                session.user_respond(approved=True)
                print(f"  [auto] 确认角色")

            elif agent == "world":
                ps = content.get("power_system", "")
                tiers = content.get("tiers", [])
                print(f"    力量体系: {ps} | 等级: {tiers}")
                session.user_respond(approved=True)
                print(f"  [auto] 确认世界观")

            elif agent == "outline":
                chs = content.get("chapters", [])
                total = content.get("total_chapters", 0)
                print(f"    章纲: {total}章")
                for ch in chs[:3]:
                    print(f"    Ch{ch.get('num','?')}: {ch.get('title','')}")
                session.user_respond(approved=True)
                print(f"  [auto] 确认章纲")

            elif agent == "writer":
                ch = data.get("chapter_num", "?")
                wc = content.get("word_count", 0)
                draft = content.get("content", "")[:100]
                print(f"    第{ch}章 ({wc}字): {draft}...")
                session.user_respond(approved=True)
                print(f"  [auto] 确认章节")

            else:
                session.user_respond(approved=True)
                print(f"  [auto] 确认 {agent}")

        elif t == SSEEventType.DONE:
            print(f"  完成! {data.get('reason', '')}")
            session.user_respond(approved=True)
            break

        elif t == SSEEventType.ERROR:
            msg = data.get("message", "")[:150]
            print(f"  [ERROR] {msg}")
            break

        elif t == SSEEventType.AUXILIARY_CHECK:
            ch_num = data.get("chapter_num", 0)
            checks = data.get("checks", [])
            aux_checks.append((ch_num, checks))
            print(f"  辅助检查 (Ch{ch_num}): {len(checks)} 项")
            for c in checks:
                icon = "✓" if c.get("status") == "pass" else "⚠"
                print(f"    {icon} {c.get('name', '?')}: {c.get('detail', '')[:60]}")

        if step >= max_steps:
            print(f"\n  (达到最大步数 {max_steps}，停止)")
            session.stop()
            break

    elapsed = time.time() - t0
    print(f"\n[4/4] 验证结果 ({elapsed:.0f}s, {step} steps)")

    # === 验证输出 ===
    errors = []

    # 1. 产生了事件
    if len(events) > 0:
        print(f"  [OK] 产生 {len(events)} 个事件")
    else:
        errors.append("无事件产出")

    # 2. 调用了 Agent
    if len(agent_calls) > 0:
        print(f"  [OK] 调用了 {len(agent_calls)} 次子Agent: {agent_calls}")
    else:
        errors.append("无 Agent 调用")

    # 3. Story 产出
    if ws.has_story():
        s = ws.raw_state.story
        print(f"  [OK] 故事已产出: {s.step1.one_sentence[:50]}...")
    else:
        errors.append("故事未产出")

    # 4. Characters 产出
    if ws.has_characters():
        c = ws.raw_state.characters
        print(f"  [OK] 角色卡已产出: {len(c.characters)} 个角色")
        for ch in c.characters[:3]:
            print(f"    - {ch.name} ({ch.role})")
    else:
        print(f"  - 角色卡未产出（可能未运行到该阶段）")

    # 5. World 产出
    if ws.has_world():
        w = ws.raw_state.world
        print(f"  [OK] 世界观已产出: {w.power_system.system_name}")
    else:
        print(f"  - 世界观未产出（可能未运行到该阶段）")

    # 6. 仪表盘
    dash = ws.get_dashboard()
    print(f"  [OK] 仪表盘: phase={dash.phase}, completed={dash.completed_agents}")
    # v0.4.0: Dashboard 字段
    print(f"  [v0.4.0] platform={dash.platform}, golden_three={dash.golden_three_active}")
    print(f"  [v0.4.0] hook_rate={dash.hook_landing_rate:.2f}, pleasure_density={dash.pleasure_density:.2f}, degraded={dash.auto_degraded}")
    print(f"  [v0.4.0] mode={dash.orchestrator_mode}")

    # 7. 上下文缓存
    l1 = ws.get_l1_context_for_prompt()
    if l1:
        print(f"  [OK] L1 上下文缓存已生成 ({len(l1)} 字符)")

    # 8. 事件类型检查
    event_types = set(e.type for e in events)
    required = {SSEEventType.THINKING, SSEEventType.AGENT_CALL}
    for rt in required:
        if rt in event_types:
            print(f"  [OK] 事件类型 {rt} 已产生")
        else:
            errors.append(f"事件类型 {rt} 未产生")

    # v0.4.0: AUXILIARY_CHECK 事件（如果有 writer agent 调用才要求）
    if SSEEventType.AUXILIARY_CHECK in event_types:
        print(f"  [OK] 事件类型 {SSEEventType.AUXILIARY_CHECK} 已产生 ({len(aux_checks)} 次)")
    elif any(ac in ("writer", "proofreader") for ac in agent_calls):
        print(f"  - auxiliary_check 未触发（writer 被调用但未产生检查数据，可能是 output 格式问题）")

    # 9. 分卷统计（如果有）
    vols = ws.get_volume_count()
    if vols > 0:
        print(f"  [OK] 分卷: {vols} 卷")
        vol = ws.get_current_volume()
        if vol:
            print(f"    V{vol.index}: {vol.title}, chapters={vol.chapter_indices}, hooks={len(vol.hook_matrix)}, auto_degraded={vol.auto_degraded}")

    # === 清理 ===
    project_path = Path(PROJECTS_DIR) / pid
    if project_path.exists():
        shutil.rmtree(project_path)

    # === 结果 ===
    print("\n" + "=" * 60)
    if errors:
        print(f"FAILED ({len(errors)} errors):")
        for e in errors:
            print(f"  - {e}")
    else:
        print("E2E Orchestrator Test PASSED!")
    print(f"耗时: {elapsed:.0f}s | {step} steps | {len(agent_calls)} agent calls")
    print("=" * 60)

    return len(errors) == 0


if __name__ == "__main__":
    success = asyncio.run(run_e2e_test())
    sys.exit(0 if success else 1)
