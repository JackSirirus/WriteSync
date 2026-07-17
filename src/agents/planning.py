"""
策划 Agent — 仅负责 Step 2

Step 1 由用户自己撰写（协作模式），
策划 Agent 基于用户的一句话，展开为五句话摘要。
"""

from typing import Optional

from ..state.state_types import GraphState
from ..state.state_types import StoryState, StoryCore, StoryArc
from ..utils.knowledge import get_knowledge_base
from ..utils.llm import LLMClient, create_llm_client
from .prompts import build_planning_prompt
from .response_models import StorySummary


def run_planning_agent(
    state: GraphState,
    llm: Optional[LLMClient] = None,
) -> dict:
    data = state["data"]
    story = data.story
    if story is None or not story.step1.one_sentence:
        raise ValueError("story.step1.one_sentence 为空，请先让用户写一句话")

    # 如果五句话已经生成过了，跳过（防止重复生成）
    if story.step2 and story.step2.setup:
        return {"data": data, "messages": state.get("messages", [])}

    user_sentence = story.step1.one_sentence
    user_tag = story.step1.tag

    # 读取用户反馈（多轮讨论支持）
    feedback = state.get("pending_feedback") or ""

    kb = get_knowledge_base()
    template = kb.load_template("摘要")

    prompt = build_planning_prompt(
        one_sentence=user_sentence,
        tag=user_tag,
        user_feedback=feedback,
        template=template,
        system_prompt=state.get("_prompt_system_override"),
    )

    if llm is None:
        llm = create_llm_client()
    text = llm.complete(prompt, temperature=0.7, max_tokens=2048)
    response = _parse_planning_fallback(text)

    story.step2 = StoryArc(
        setup=response.step2.setup,
        inciting=response.step2.inciting,
        rising=response.step2.rising,
        climax_prep=response.step2.climax_prep,
        resolution=response.step2.resolution,
        theme=response.step2.theme,
    )

    messages = state.get("messages", [])
    msg = "根据您的意见重新生成了五句话" if feedback else "基于您的一句话，为您展开了五句话摘要"
    messages.append({
        "role": "assistant",
        "content": msg,
    })

    data.story.confirmed_at = None  # 重置确认状态，等待用户对五句话的确认

    return {"data": data, "messages": messages, "pending_feedback": None}


def _parse_planning_fallback(text: str) -> "StorySummary":
    """complete() 回退：从文本中提取五句话"""
    import re
    from .response_models import StorySummary, StoryCore, StoryArc as PydanticStoryArc

    sentences = []
    for match in re.finditer(r'(?:^|\n)(?:[1-5][.、)]|\d+\s*[-:])\s*(.+)', text):
        sentences.append(match.group(1).strip()[:200])
    if not sentences:
        lines = [l.strip() for l in text.split('\n') if len(l.strip()) > 10]
        sentences = lines[:5]

    while len(sentences) < 5:
        sentences.append("")

    return StorySummary(
        step1=StoryCore(one_sentence=sentences[0][:50] if sentences[0] else "故事", tag="小说"),
        step2=PydanticStoryArc(
            setup=sentences[0], inciting=sentences[1], rising=sentences[2],
            climax_prep=sentences[3], resolution=sentences[4],
        ),
    )
