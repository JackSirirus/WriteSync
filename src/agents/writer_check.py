"""
文笔检查 Agent

检查初稿质量，判断是否需要修改。
使用 instructor 结构化输出。
"""

from typing import Optional

from ..state.state_types import GraphState
from ..state.state_types import DraftContent
from ..utils.llm import LLMClient, create_llm_client
from .prompts import build_writer_check_prompt
from .response_models import DraftReviewNotes


def run_writer_check_agent(
    state: GraphState,
    chapter_number: int,
    llm: Optional[LLMClient] = None,
) -> dict:
    data = state["data"]
    drafts = data.drafts
    if chapter_number not in drafts.chapters:
        raise ValueError(f"第 {chapter_number} 章尚无初稿")

    cd = drafts.chapters[chapter_number]
    if cd.draft is None:
        raise ValueError(f"第 {chapter_number} 章 draft 为空")

    prompt = build_writer_check_prompt(chapter_number, cd.draft.content)

    from .context import build_writing_context
    ctx_text = build_writing_context(state)
    if ctx_text:
        prompt = (
            "# 写作上下文（以下信息基于已完成章节提取，请严格遵循）\n\n"
            + ctx_text + "\n\n---\n\n# 本章写作指令\n\n" + prompt
        )

    if llm is None:
        llm = create_llm_client()
    response: DraftReviewNotes = llm.complete_structured(
        prompt, output_class=DraftReviewNotes, temperature=0.3,
    )

    from datetime import datetime
    now = datetime.now().isoformat()
    cd.draft_checked = DraftContent(
        content=cd.draft.content,
        agent="文笔检查Agent",
        change_notes=response.issues,
        timestamp=now,
    )
    cd.stage = "checked" if response.passed else "draft_rejected"
    cd.updated_at = now

    messages = state.get("messages", [])
    status = "通过" if response.passed else "需修改"
    messages.append({
        "role": "assistant",
        "content": f"第 {chapter_number} 章文笔检查：{status}。{response.overall}",
        "attachments": [{
            "type": "writer_check",
            "passed": response.passed,
            "issues": response.issues,
            "suggestions": response.suggestions,
        }],
    })

    return {"data": data, "messages": messages}
