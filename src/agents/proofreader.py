"""
校对 Agent

对章节进行最终校对（错别字/语法/标点/格式）。
使用 instructor 结构化输出。
"""

from typing import Optional

from ..state.state_types import GraphState
from ..state.state_types import DraftContent
from ..utils.llm import LLMClient, create_llm_client
from .prompts import build_proofreader_prompt
from .response_models import ProofreadReport


def run_proofreader_agent(
    state: GraphState,
    chapter_number: int,
    llm: Optional[LLMClient] = None,
) -> dict:
    data = state["data"]
    drafts = data.drafts
    if chapter_number not in drafts.chapters:
        raise ValueError(f"第 {chapter_number} 章尚无内容")

    cd = drafts.chapters[chapter_number]
    source = cd.polished.content if cd.polished else (
        cd.revised.content if cd.revised else (
            cd.draft_checked.content if cd.draft_checked else cd.draft.content
        )
    )

    prompt = build_proofreader_prompt(
        chapter_number, source,
        system_prompt=state.get("_prompt_system_override"),
    )

    from .context import build_writing_context
    ctx_text = build_writing_context(state)
    if ctx_text:
        prompt = (
            "# 写作上下文（以下信息基于已完成章节提取，请严格遵循）\n\n"
            + ctx_text + "\n\n---\n\n# 本章写作指令\n\n" + prompt
        )

    if llm is None:
        llm = create_llm_client()

    from .response_models import ProofreadReport
    try:
        response: ProofreadReport = llm.complete_structured(
            prompt, output_class=ProofreadReport, temperature=0.2,
            max_tokens=16384, timeout=90, max_retries=1,
        )
    except Exception:
        # fallback: complete() 直接获取修正后正文
        text = llm.complete(prompt, temperature=0.2, max_tokens=16384, timeout=90, max_retries=1)
        response = ProofreadReport(
            typos=[], grammar_issues=[], punctuation_issues=[],
            format_issues=[], corrected_version=text,
        )

    from datetime import datetime
    now = datetime.now().isoformat()
    cd.final = DraftContent(
        content=response.corrected_version or source,
        agent="校对Agent",
        change_notes=(response.typos + response.grammar_issues
                      + response.rhythm_adjustments),
        timestamp=now,
    )
    cd.stage = "proofread"
    cd.word_count = len(response.corrected_version or source)
    cd.updated_at = now

    from ..state.state_types import ChapterOutlineState
    if data.chapter_outline:
        data.chapter_outline.word_count_by_chapter[chapter_number] = cd.word_count
        data.chapter_outline.word_count_actual = sum(
            data.chapter_outline.word_count_by_chapter.values()
        )

    messages = state.get("messages", [])
    typos_str = f"修正 {len(response.typos)} 处错别字" if response.typos else "无错别字"
    rhythm_str = f"节奏{response.rhythm_assessment}" if response.rhythm_assessment else ""
    messages.append({
        "role": "assistant",
        "content": f"第 {chapter_number} 章校对完成（{cd.word_count} 字，{typos_str}，{rhythm_str}）",
        "attachments": [{
            "type": "proofread_report",
            "typos": response.typos,
            "grammar": response.grammar_issues,
            "punctuation": response.punctuation_issues,
            "format": response.format_issues,
            "rhythm": response.rhythm_assessment,
            "rhythm_adjustments": response.rhythm_adjustments,
            "cliffhanger": response.cliffhanger_note,
        }],
    })

    return {"data": data, "messages": messages}
