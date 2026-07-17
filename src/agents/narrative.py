"""
叙事概要 Agent（Snowflake Step 6 叙事层）

基于 Step 1+2+4 的内容，生成 3-5 页叙事性故事描述。
与 Step 6/7 的结构化章纲不同，这是一篇"读起来像故事"的概要，
为章纲 Agent 提供叙事感知。
"""

from typing import Optional

from ..state.state_types import GraphState
from ..utils.llm import LLMClient, create_llm_client
from .prompts import build_narrative_synopsis_prompt
from .response_models import NarrativeSynopsis


def run_narrative_agent(
    state: GraphState,
    llm: Optional[LLMClient] = None,
) -> dict:
    data = state["data"]
    story = data.story
    if story is None:
        raise ValueError("story 为空")

    paras = story.expanded_paragraphs or []
    prompt = build_narrative_synopsis_prompt(
        one_sentence=story.step1.one_sentence,
        tag=story.step1.tag,
        five_sentences=[
            story.step2.setup,
            story.step2.inciting,
            story.step2.rising,
            story.step2.climax_prep,
            story.step2.resolution,
        ],
        expanded_paragraphs=paras,
        theme=story.step2.theme,
    )

    if llm is None:
        llm = create_llm_client()
    response: NarrativeSynopsis = llm.complete_structured(
        prompt, output_class=NarrativeSynopsis, temperature=0.7, max_tokens=4096,
    )

    story.narrative_synopsis = response.synopsis

    messages = state.get("messages", [])
    sync_len = len(response.synopsis)
    messages.append({
        "role": "assistant",
        "content": f"叙事概要已生成（{sync_len} 字）",
        "attachments": [{"type": "narrative_synopsis", "tone": response.tone_notes}],
    })

    return {"data": data, "messages": messages}
