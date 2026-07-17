"""
E2E 真实 LLM 测试 — 写作阶段 5 个 Agent 全串联

运行：python tests/e2e_write_agents.py
WARNING: 调用真实 LLM API，单次运行约 5-10 分钟
"""

import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.stdout.reconfigure(encoding="utf-8")
os.environ["LANGGRAPH_STRICT_MSGPACK"] = "false"

from datetime import datetime
from src.state.state_types import init_graph_state
from src.state.state_types import (
    WriteSyncState, ProjectMetadata, StepName, ProjectStatus, WorkflowState,
    TopicState, StoryState, StoryCore, StoryArc,
    CharactersState, Character, CharacterArc, CharacterRelation,
    WorldState, PowerSystem, Geography, Society, WorldHistory,
    ChapterOutlineState, ChapterOutline, ChapterBeat,
    DraftsState, ChapterDraft, DraftContent,
)


# fmt: off
def build_prerequisite_state() -> WriteSyncState:
    """构造全量前置状态（story + characters + world + chapter_outline）"""
    now = datetime.now().isoformat()

    return WriteSyncState(
        metadata=ProjectMetadata(
            project_id="e2e-writing", name="写作E2E测试", platform="起点",
            created_at=now, updated_at=now, status=ProjectStatus.WRITING,
        ),
        workflow=WorkflowState(current_step=StepName.CHAPTER),
        topic=TopicState(user_original_idea="军人重生末日建立基地", suggestions=[], confirmed_at=now),
        story=StoryState(
            step1=StoryCore(one_sentence="退役特种兵在末日中建立基地对抗尸潮", tag="热血末世"),
            step2=StoryArc(
                setup="丧尸病毒爆发，城市沦陷", inciting="退伍兵陈锋觉醒基地系统",
                rising="建设基地、招募幸存者", climax_prep="百万尸潮围城",
                resolution="守住基地成为人类灯塔", theme="在绝境中重建文明",
            ),
        ),
        characters=CharactersState(
            characters=[
                Character(
                    name="陈锋", role="主角", identity="退役特种兵",
                    personality="坚韧、冷静、重情义", goal="在末日中活下去并保护同伴",
                    conflict="个人生存 vs 团队责任", description="三十岁，特种部队退役，体能过人",
                    background="某军区特种部队退役，父母双亡，单身",
                    gold_finger="基地系统：可建造、升级、招募",
                    initial_dilemma="孤身一人在丧尸包围的城市中求生",
                    reader_empathy_path="从普通人的恐惧到领袖的担当",
                    arc=CharacterArc(
                        start_state="独自求生的幸存者",
                        end_state="凝聚众人的领袖",
                        transformation_event="第一次尸潮攻城，同伴牺牲",
                        change_trigger="意识到一个人无法在末日生存",
                    ),
                    relationships=[
                        CharacterRelation(target_name="李薇", relation_type="同伴", description="被救的医生，后来成为基地医疗负责人", dynamic="陌生→信任→依赖"),
                    ],
                ),
                Character(
                    name="李薇", role="女主", identity="急诊科医生",
                    personality="善良、坚强、理性", goal="在末日中救治更多的人",
                    conflict="医者仁心 vs 资源有限", description="二十八岁，市医院急诊科医生",
                    background="普通家庭出身，工作三年，见惯生死",
                ),
                Character(
                    name="王磊", role="配角", identity="退伍老兵",
                    personality="忠厚、勇猛、固执", goal="跟随陈锋重建家园",
                    conflict="习惯服从 vs 需要自主决策", description="五十岁，炊事班退伍军人",
                ),
            ],
            summary="三人小队从城市突围到建立安全基地",
        ),
        world=WorldState(
            power_system=PowerSystem(
                system_name="基地系统",
                tiers=["D级", "C级", "B级", "A级", "S级"],
                cultivation_rules="通过收集物资、建造建筑、招募人口升级",
                power_limit="S级可抵御核弹级尸潮",
                special_abilities=["雷达扫描", "自动生产", "能量护盾"],
            ),
            geography=Geography(
                major_locations=[
                    {"name": "临城", "description": "主角所在的三线城市，人口百万", "significance": "故事起点"},
                ],
                political_division="旧行政区划已崩溃",
            ),
            society=Society(
                social_hierarchy="基地分级制：核心成员→战斗人员→普通幸存者",
                factions=[
                    {"name": "幸存者基地", "description": "主角建立的基地，秩序阵营", "align": "守序善良"},
                    {"name": "掠夺者", "description": "以抢劫为生的武装团伙", "align": "混乱邪恶"},
                ],
                cultural_notes="末日生存主义文化，强者为尊",
            ),
            history=WorldHistory(
                key_events=["病毒爆发", "社会崩溃", "政府失能"],
                timeline_summary="病毒爆发后一个月，社会秩序完全崩溃",
            ),
            self_check_passed=True,
            consistency_notes="设定自洽",
        ),
        chapter_outline=ChapterOutlineState(
            total_chapters=3,
            chapters=[
                ChapterOutline(
                    chapter_number=1, chapter_title="末日降临",
                    core_event="陈锋从昏迷中醒来，发现世界已经变成丧尸地狱，觉醒基地系统",
                    character_states="陈锋：震惊→恐惧→冷静应对",
                    story_progression="世界观展开，主角获得金手指",
                    scenes=[
                        ChapterBeat(scene_id="ch01_sc01", location="破败公寓", time_period="清晨", pov_character="陈锋",
                                    purpose="主角苏醒，展示末日景象", conflict="被丧尸围困"),
                        ChapterBeat(scene_id="ch01_sc02", location="公寓楼下", time_period="中午", pov_character="陈锋",
                                    purpose="第一次战斗，觉醒系统", conflict="击杀丧尸+逃生"),
                    ],
                    hook_at_end="系统提示：检测到其他幸存者信号",
                    pov="陈锋", pace="fast",
                ),
                ChapterOutline(
                    chapter_number=2, chapter_title="初建基地",
                    core_event="陈锋清理出一栋建筑作为临时基地，遇到李薇",
                    character_states="陈锋：坚定、果断；李薇：警惕→信任",
                    story_progression="主角建立第一个安全据点",
                    hook_at_end="远处传来巨大的咆哮声",
                    pov="陈锋", pace="medium",
                ),
                ChapterOutline(
                    chapter_number=3, chapter_title="尸潮前夜",
                    core_event="基地初具规模，但雷达显示大批尸潮正在接近",
                    character_states="陈锋：焦虑但坚定；全员：备战状态",
                    story_progression="第一次大危机铺垫",
                    hook_at_end="尸潮出现在地平线上",
                    pov="陈锋", pace="slow→fast",
                ),
            ],
            written_chapters=[],
        ),
        drafts=DraftsState(),
    )
# fmt: on


def run_writer(data: WriteSyncState, ch: int, timeline: list):
    print(f"\n{'='*50}")
    print(f"▶ 文笔Agent — 第{ch}章")
    print(f"{'='*50}")
    from src.agents import run_writer_agent
    gs = init_graph_state(data)
    t0 = time.time()
    try:
        result = run_writer_agent(gs, chapter_number=ch)
        elapsed = time.time() - t0
        cd = result["data"].drafts.chapters[ch]
        timeline.append(("文笔Agent", ch, elapsed, "ok"))
        print(f"  ✓ {elapsed:.1f}s | {cd.word_count} 字")
        print(f"  开头: {cd.draft.content[:100]}...")
        print(f"  结尾: ...{cd.draft.content[-100:]}")
        return result["data"]
    except Exception as e:
        elapsed = time.time() - t0
        timeline.append(("文笔Agent", ch, elapsed, f"FAIL: {str(e)[:80]}"))
        print(f"  ✗ FAIL after {elapsed:.1f}s: {type(e).__name__}: {str(e)[:120]}")
        return data


def run_writer_check(data: WriteSyncState, ch: int, timeline: list):
    print(f"\n{'='*50}")
    print(f"▶ 文笔检查Agent — 第{ch}章")
    print(f"{'='*50}")
    from src.agents import run_writer_check_agent
    gs = init_graph_state(data)
    t0 = time.time()
    try:
        result = run_writer_check_agent(gs, chapter_number=ch)
        elapsed = time.time() - t0
        cd = result["data"].drafts.chapters[ch]
        status = "通过" if cd.stage == "checked" else "需修改"
        timeline.append(("文笔检查Agent", ch, elapsed, status))
        print(f"  ✓ {elapsed:.1f}s | {status}")
        print(f"  问题: {cd.draft_checked.change_notes[:3]}")
        return result["data"]
    except Exception as e:
        elapsed = time.time() - t0
        timeline.append(("文笔检查Agent", ch, elapsed, f"FAIL: {str(e)[:80]}"))
        print(f"  ✗ FAIL after {elapsed:.1f}s: {type(e).__name__}: {str(e)[:120]}")
        return data


def run_proofreader(data: WriteSyncState, ch: int, timeline: list):
    print(f"\n{'='*50}")
    print(f"▶ 校对Agent — 第{ch}章")
    print(f"{'='*50}")
    from src.agents import run_proofreader_agent
    gs = init_graph_state(data)
    t0 = time.time()
    try:
        result = run_proofreader_agent(gs, chapter_number=ch)
        elapsed = time.time() - t0
        cd = result["data"].drafts.chapters[ch]
        n_typos = len(cd.final.change_notes) if cd.final else 0
        timeline.append(("校对Agent", ch, elapsed, f"{cd.word_count}字, {n_typos} fixes"))
        print(f"  ✓ {elapsed:.1f}s | {cd.word_count} 字, 修正 {n_typos} 处")
        return result["data"]
    except Exception as e:
        elapsed = time.time() - t0
        timeline.append(("校对Agent", ch, elapsed, f"FAIL: {str(e)[:80]}"))
        print(f"  ✗ FAIL after {elapsed:.1f}s: {type(e).__name__}: {str(e)[:120]}")
        return data


if __name__ == "__main__":
    auto_yes = os.environ.get("E2E", "").lower() in ("1", "true", "yes")
    if not auto_yes:
        resp = input("将调用真实 LLM API（5 次调用，约 5-10 分钟），确认？(y/N): ").strip().lower()
        if resp != "y":
            print("已取消")
            sys.exit(0)

    print("=" * 50)
    print("写作阶段 3 Agent E2E 测试")
    print("=" * 50)

    timeline = []
    ch = 1
    t_total = time.time()

    # 用同一个状态对象避免每次重建
    state = build_prerequisite_state()

    # Step 1: 文笔Agent
    state = run_writer(state, ch, timeline)
    cd = state.drafts.chapters.get(ch)
    if not cd or cd.stage != "draft":
        print("\n✗ 文笔Agent 失败，终止")
    else:
        # Step 2: 文笔检查Agent
        state = run_writer_check(state, ch, timeline)

        # Step 3: 校对Agent
        state = run_proofreader(state, ch, timeline)

    total = time.time() - t_total

    print(f"\n{'='*50}")
    print("结果汇总")
    print(f"{'='*50}")
    print(f"{'Agent':<20} {'章':>3} {'耗时':>7} {'状态'}")
    print("-" * 50)
    for agent, chapter, elapsed, status in timeline:
        flag = "✓" if not status.startswith("FAIL") else "✗"
        print(f"{flag} {agent:<18} {chapter:>3} {elapsed:>6.1f}s {status}")

    print(f"\n总耗时: {total:.1f}s")
    if state.drafts.chapters.get(ch):
        cd = state.drafts.chapters[ch]
        print(f"最终状态: stage={cd.stage}, {cd.word_count}字")

    success = all(not s.startswith("FAIL") for _, _, _, s in timeline)
    print(f"\n{'ALL PASSED' if success else 'SOME FAILED'}")
    sys.exit(0 if success else 1)
