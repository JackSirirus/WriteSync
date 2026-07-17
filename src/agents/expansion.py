"""
扩展 Agent（Snowflake Step 4）

将 Step 2 的五句话各扩展成一段完整叙述（3-5句/段）。
长文本场景，使用 complete() 避免 instructor 结构化输出的额外开销和重试。
"""

import re
from typing import Optional

from ..state.state_types import GraphState
from ..utils.llm import LLMClient, create_llm_client
from .prompts import build_expansion_prompt


def run_expansion_agent(
    state: GraphState,
    llm: Optional[LLMClient] = None,
) -> dict:
    data = state["data"]
    story = data.story
    if story is None:
        raise ValueError("story 为空，请先运行策划 Agent")

    prompt = build_expansion_prompt(
        one_sentence=story.step1.one_sentence,
        tag=story.step1.tag,
        setup=story.step2.setup,
        inciting=story.step2.inciting,
        rising=story.step2.rising,
        climax_prep=story.step2.climax_prep,
        resolution=story.step2.resolution,
        theme=story.step2.theme,
    )

    if llm is None:
        llm = create_llm_client()

    response = llm.complete(prompt, temperature=0.7, timeout=300)

    # 解析输出：按 【段落 X】或 第X段 或 数字序号 分割
    paragraphs = []
    # 尝试按标记分割
    parts = re.split(r'[【\[]\s*(?:段落|第)\s*(\d+)\s*[】\]]', response)
    if len(parts) >= 3:
        # 格式: ["前置文本", "1", "段落内容...", "2", "..."]
        i = 1
        while i < len(parts):
            text = parts[i + 1].strip() if i + 1 < len(parts) else ""
            if text:
                paragraphs.append(text)
            i += 2
    else:
        # 按连续数字序号分割：1. xxx\n\n2. xxx
        parts2 = re.split(r'\n\s*\d+\s*[.、]\s*', response)
        if len(parts2) > 1:
            paragraphs = [p.strip() for p in parts2 if p.strip()]
        else:
            # 按双换行分割
            paragraphs = [p.strip() for p in response.split('\n\n') if p.strip()]

    # 只取前5段
    story.expanded_paragraphs = paragraphs[:5]

    messages = state.get("messages", [])
    messages.append({
        "role": "assistant",
        "content": "五句话已展开为五段叙述",
        "attachments": [{"type": "expanded_paragraphs", "count": len(story.expanded_paragraphs)}],
    })

    return {"data": data, "messages": messages}
