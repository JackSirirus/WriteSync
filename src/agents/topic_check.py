"""
选题检查 Agent

检查选题建议是否符合平台特性和市场规律。
使用 instructor 结构化输出。
"""

from typing import Optional

from ..state.state_types import GraphState
from ..utils.knowledge import get_knowledge_base
from ..utils.llm import LLMClient, create_llm_client
from .prompts import build_topic_check_prompt
from .response_models import TopicCheckReport


def run_topic_check_agent(
    state: GraphState,
    llm: Optional[LLMClient] = None,
) -> dict:
    topic_state = state["data"].topic
    if topic_state is None or not topic_state.suggestions:
        raise ValueError("topic.suggestions 为空，请先运行选题 Agent")

    platform = state["data"].metadata.platform

    kb = get_knowledge_base()
    try:
        platform_kb = kb.load_platform(platform)
    except FileNotFoundError:
        platform_kb = kb.load_platform("起点")

    try:
        checklist = kb.load_standard("选题检查清单")
    except FileNotFoundError:
        checklist = "请按以下维度检查：平台适配性、市场差异化、题材饱和度、核心卖点、高概率扑街预警"

    topic_text = _format_topics_for_prompt(topic_state)
    prompt = build_topic_check_prompt(
        topic_data=topic_text,
        platform=platform,
        platform_kb=platform_kb,
        checklist=checklist,
    )

    if llm is None:
        llm = create_llm_client()
    response: TopicCheckReport = llm.complete_structured(prompt, output_class=TopicCheckReport, temperature=0.3)

    messages = state.get("messages", [])
    messages.append({
        "role": "assistant",
        "content": f"选题检查报告：{response.overall_summary}",
        "attachments": [{"type": "topic_check_report", "evaluations": [e.model_dump() for e in response.evaluations]}],
    })

    return {"data": state["data"], "messages": messages}


def _format_topics_for_prompt(topic_state) -> str:
    lines = []
    for i, s in enumerate(topic_state.suggestions):
        lines.append(f"\n## 选题 {i + 1}：{s.title}")
        lines.append(f"- 题材：{s.genre} / {s.sub_genre}")
        lines.append(f"- 核心卖点：{s.core_selling_point}")
        lines.append(f"- 目标读者：{s.target_audience}")
        lines.append(f"- 竞品分析：{s.competitive_analysis}")
    return "\n".join(lines)
