"""
全书审查 Agent（Snowflake Step 9）

在所有章节写完后运行，对全书进行宏观结构评估。
检查：三幕节奏、角色弧线一致性、伏笔回收、篇幅分配等。
"""

from typing import Optional

from ..state.state_types import GraphState
from ..state.state_types import NovelReviewState
from ..utils.llm import LLMClient, create_llm_client
from .prompts import build_novel_review_prompt
from .response_models import NovelReviewReport


def run_novel_review_agent(
    state: GraphState,
    llm: Optional[LLMClient] = None,
) -> dict:
    data = state["data"]
    drafts = data.drafts
    if not drafts or not drafts.chapters:
        raise ValueError("尚无已完成的章节")

    prompt = build_novel_review_prompt(
        story_summary=_format_story(data.story),
        characters_summary=_format_characters(data.characters),
        total_chapters=_format_chapter_list(data.chapter_outline),
        chapter_summaries=_format_draft_summaries(drafts),
        system_prompt=state.get("_prompt_system_override"),
    )

    if llm is None:
        llm = create_llm_client()
    response: NovelReviewReport = llm.complete_structured(
        prompt, output_class=NovelReviewReport, temperature=0.4, max_tokens=4096,
    )

    data.novel_review = NovelReviewState(
        structural_issues=response.structural_issues,
        pacing_assessment=response.pacing_assessment,
        character_arc_consistency=response.character_arc_consistency,
        foreshadow_tracking=response.foreshadow_tracking,
        recommendations=response.recommendations,
        passed=response.passed,
    )

    messages = state.get("messages", [])
    verdict = "通过" if response.passed else "需修改"
    messages.append({
        "role": "assistant",
        "content": f"全书审查完成：{verdict}。{response.overall_assessment}",
        "attachments": [{
            "type": "novel_review",
            "structural": response.structural_issues,
            "pacing": response.pacing_assessment,
            "character_arcs": response.character_arc_consistency,
            "foreshadows": response.foreshadow_tracking,
            "recommendations": response.recommendations,
        }],
    })

    return {"data": data, "messages": messages}


def _format_story(story) -> str:
    if story is None:
        return "待定义"
    return f"""{story.step1.one_sentence}
{story.step2.theme}"""


def _format_characters(characters) -> str:
    if characters is None:
        return "待定义"
    lines = []
    for c in characters.characters:
        arc = f" {c.arc.start_state}→{c.arc.end_state}" if c.arc else ""
        lines.append(f"- {c.name}（{c.role}）：{c.goal}{arc}")
    return "\n".join(lines)


def _format_chapter_list(outline) -> str:
    if outline is None:
        return "待定义"
    lines = [f"总章数：{outline.total_chapters}"]
    for ch in outline.chapters:
        status = "✓" if ch.chapter_number in (outline.written_chapters or []) else " "
        lines.append(f"  [{status}] 第{ch.chapter_number}章：{ch.chapter_title}")
    return "\n".join(lines)


def _format_draft_summaries(drafts) -> str:
    lines = []
    for ch_num in sorted(drafts.chapters.keys()):
        cd = drafts.chapters[ch_num]
        wc = cd.word_count or 0
        stage = cd.stage
        first_100 = ""
        if cd.final and cd.final.content:
            first_100 = cd.final.content[:100].replace("\n", " ")
        elif cd.draft and cd.draft.content:
            first_100 = cd.draft.content[:100].replace("\n", " ")
        lines.append(f"第{ch_num}章：{wc}字 stage={stage}")
        lines.append(f"  开头：{first_100}...")
    return "\n".join(lines)
