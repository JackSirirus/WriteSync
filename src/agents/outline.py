"""
章纲 Agent

Step4：三幕大纲 + Step6/7：章级/场景级章纲。

策略：从 LLM 提取高层结构（幕、章数、前几章详情），
剩余章纲用程序化模板填充避免超时。
"""

import re
from typing import Optional

from ..state.state_types import GraphState
from ..state.state_types import (
    ChapterOutlineState, ChapterOutline, ActOutline,
    ChapterBeat,
)
from ..utils.knowledge import get_knowledge_base
from ..utils.llm import LLMClient, create_llm_client
from .prompts import build_outline_prompt


def run_outline_agent(
    state: GraphState,
    llm: Optional[LLMClient] = None,
) -> dict:
    if state["data"].story is None or state["data"].characters is None or state["data"].world is None:
        raise ValueError("story / characters / world 字段为空")

    # 如果存在叙事概要（Step 6 叙事层），传递给章纲生成以增强故事感知
    narrative_ctx = ""
    if state["data"].story and state["data"].story.narrative_synopsis:
        narrative_ctx = f"\n## 叙事概要（故事时间线）\n\n{state["data"].story.narrative_synopsis}\n"

    kb = get_knowledge_base()
    template = kb.load_template("章纲")

    try:
        technique = kb.load_technique("开篇三章")
    except FileNotFoundError:
        technique = None

    prompt = build_outline_prompt(
        story_state=_format_story(state["data"].story),
        characters_state=_format_characters(state["data"].characters),
        world_state=_format_world(state["data"].world),
        narrative_synopsis=narrative_ctx,
        template=template,
        technique=technique,
        system_prompt=state.get("_prompt_system_override"),
    )

    if llm is None:
        llm = create_llm_client()

    # 使用 complete() 避免结构化输出超时；紧凑输出，max_tokens=4096 足够
    response = llm.complete(prompt, temperature=0.7, max_tokens=4096, timeout=300)

    # 解析输出
    acts, chapters, total, note, foreshadows = _parse_outline_response(response, state)
    outline_state = ChapterOutlineState(
        total_chapters=total,
        chapters=chapters,
        word_count_plan=total * 4000,
        pov_strategy_note=note,
        global_foreshadows=foreshadows,
    )
    state["data"].chapter_outline = outline_state

    messages = state.get("messages", [])
    messages.append({
        "role": "assistant",
        "content": f"章纲已生成，共 {total} 章",
        "attachments": [{"type": "outline", "chapter_count": total}],
    })

    return {"data": state["data"], "messages": messages}


def _format_story(story_state) -> str:
    s1 = story_state.step1
    s2 = story_state.step2
    return f"""一句话：{s1.one_sentence}
1. {s2.setup}
2. {s2.inciting}
3. {s2.rising}
4. {s2.climax_prep}
5. {s2.resolution}"""


def _format_characters(characters_state) -> str:
    return "\n".join(
        f"- {c.name}（{c.role}）：{c.goal}" for c in characters_state.characters
    ) or "待定义"


def _format_world(world_state) -> str:
    ps = world_state.power_system
    return f"""力量体系：{ps.system_name}
等级：{', '.join(ps.tiers) if ps.tiers else '待定义'}
修炼规则：{ps.cultivation_rules or '待定义'}"""


def _parse_outline_response(response: str, state: GraphState):
    """解析 LLM 输出的章纲 Markdown，提取结构化数据"""
    lines = response.split("\n")

    # 提取总章数
    total = 20
    for line in lines:
        nums = re.findall(r"\d+", line)
        if nums and ("总章" in line or "共" in line and "章" in line):
            total = max(int(n) for n in nums if 5 <= int(n) <= 200)
            break

    # 提取三幕
    acts = []
    current_act = None
    for line in lines:
        m = re.match(r"第[一二三]幕", line)
        if m:
            current_act = len(acts)
            acts.append({"summary": line.strip(), "events": []})
        elif current_act is not None and line.strip().startswith("-"):
            acts[current_act]["events"].append(line.strip().lstrip("- "))

    # 提取已命名的章节（通常前5-10章有详细命名）
    named_chapters = {}
    for line in lines:
        m = re.match(r"第(\d+)章[:：]?\s*(.+)", line.strip())
        if m:
            ch_num = int(m.group(1))
            title = m.group(2).strip()
            named_chapters[ch_num] = title

    # 提取 POV 策略
    pov_note = ""
    for line in lines:
        if "POV" in line or "视角" in line:
            pov_note = (pov_note + " " + line.strip()).strip()

    # 提取核心事件描述（从分章内容中）
    chapter_events = {}
    current_ch = None
    for line in lines:
        m = re.match(r"第(\d+)章[:：]?\s*(.+)", line.strip())
        if m:
            current_ch = int(m.group(1))
            chapter_events[current_ch] = m.group(2).strip()
        elif current_ch and line.strip() and not line.startswith("#") and not line.startswith("-"):
            chapter_events[current_ch] = chapter_events.get(current_ch, "") + " " + line.strip()

    # 提取伏笔
    foreshadows = []
    for line in lines:
        if "伏笔" in line or "铺垫" in line:
            foreshadows.append({"content": line.strip(), "planted": 1, "payoff": 0})

    # 构造章节列表
    chapters = []
    for i in range(1, total + 1):
        title = named_chapters.get(i, f"第{i}章")
        event = chapter_events.get(i, "")
        chapters.append(ChapterOutline(
            chapter_number=i,
            chapter_title=title,
            core_event=event[:100] if event else "",
            character_states="",
            story_progression="",
            estimated_word_count=4000,
        ))

    act_models = [
        ActOutline(act_number=i + 1, summary=a["summary"], key_events=a["events"])
        for i, a in enumerate(acts)
    ]

    return act_models, chapters, total, pov_note, foreshadows
