"""
选题 Agent

根据用户原始想法 + 目标平台，生成选题建议列表。
使用 instructor 结构化输出，替代自由文本+正则解析。
"""

from datetime import datetime
from typing import Optional

from ..state.state_types import TopicState, TopicSuggestion as TopicSuggestionData, PlatformFit as PlatformFitData
from ..state.state_types import GraphState
from ..utils.knowledge import get_knowledge_base
from ..utils.llm import LLMClient, create_llm_client
from .prompts import build_topic_prompt
from .response_models import TopicList, TopicSuggestion, PlatformFit


def run_topic_agent(
    state: GraphState,
    llm: Optional[LLMClient] = None,
) -> dict:
    topic_state = state["data"].topic
    if topic_state is None:
        raise ValueError("topic 字段为空，请先初始化")

    platform = state["data"].metadata.platform

    # 1. 加载知识库
    kb = get_knowledge_base()
    try:
        platform_kb = kb.load_platform(platform)
    except FileNotFoundError:
        platform_kb = kb.load_platform("起点")

    template = kb.load_template("选题卡")

    # 2. 构建 prompt
    prompt = build_topic_prompt(
        user_idea=topic_state.user_original_idea,
        platform=platform,
        platform_kb=platform_kb,
        template=template,
        system_prompt=state.get("_prompt_system_override"),
    )

    # 3. 调用 LLM（优先结构化输出，兜底自由文本+正则解析）
    if llm is None:
        llm = create_llm_client()
    try:
        # 结构化输出 — 直接用 TopicList Pydantic model
        response = llm.complete_structured(
            prompt,
            output_class=TopicList,
            temperature=0.7,
            max_tokens=8192,
        )
    except Exception as e:
        import logging
        _logger = logging.getLogger("writesync")
        _logger.warning("结构化输出失败，回退到文本解析: %s", e)
        text = llm.complete(prompt, temperature=0.7, max_tokens=8192)
        response = _parse_topic_fallback(text)

    # 4. 转换 Pydantic → dataclass，更新 State
    suggestions = [
        TopicSuggestionData(
            title=s.title,
            genre=s.genre,
            sub_genre=s.sub_genre,
            core_selling_point=s.core_selling_point,
            target_audience=s.target_audience or "",
            competitive_analysis=s.competitive_analysis or "",
            platform_fit=PlatformFitData(
                heat_level=s.platform_fit.heat_level if s.platform_fit else "平稳",
                difficulty=s.platform_fit.difficulty if s.platform_fit else "未知",
                reader_preference=s.platform_fit.reader_preference if s.platform_fit else "中等",
                risk_factors=list(s.platform_fit.risk_factors) if s.platform_fit else [],
            ),
            inspiration_source=topic_state.user_original_idea,
        )
        for s in response.suggestions
    ]
    topic_state.suggestions = suggestions

    messages = state.get("messages", [])
    messages.append({
        "role": "assistant",
        "content": f"我为您生成了 {len(suggestions)} 个选题建议：",
        "attachments": [{"type": "topics", "count": len(suggestions)}],
    })

    return {"data": state["data"], "messages": messages}


def _parse_topic_fallback(text: str) -> "TopicList":
    """complete() 回退：从文本中提取选题 — 增强版，截断长标题"""
    import re

    def _clean_title(raw: str) -> str:
        """清理并截断标题：去前缀 → 截断到第一个句末标点 → 限制40字符"""
        t = raw.strip().lstrip('#- *0123456789.、).').strip()
        # 在第一个句末标点处截断
        for sep in ['。', '！', '？', '；', '：', '\n', '，']:
            idx = t.find(sep)
            if idx > 3:  # 至少保留3个字符
                t = t[:idx]
                break
        if len(t) > 40:
            t = t[:40]
        return t

    titles = re.findall(r'(?:title|标题|选题)[：:]\s*(.+)', text, re.IGNORECASE)
    if not titles:
        titles = re.findall(r'^(?:[0-9]+[.、]|\*\s*)(.+)', text, re.MULTILINE)

    suggestions = []
    for t in titles[:5]:
        title = _clean_title(t)
        if len(title) >= 3:
            suggestions.append(TopicSuggestion(
                title=title[:40],
                genre="玄幻",
                sub_genre="",
                core_selling_point=title[:60],
                target_audience="",
                competitive_analysis="",
                platform_fit=PlatformFit(heat_level="平稳", difficulty="未知", reader_preference="中等"),
            ))
    if not suggestions:
        first_line = _clean_title(text.split('\n')[0])
        if len(first_line) >= 3:
            suggestions.append(TopicSuggestion(
                title=first_line[:40],
                genre="玄幻",
                sub_genre="",
                core_selling_point=first_line[:60],
                target_audience="",
                competitive_analysis="",
                platform_fit=PlatformFit(heat_level="平稳", difficulty="未知", reader_preference="中等"),
            ))
    if not suggestions:
        suggestions.append(TopicSuggestion(
            title="修真末世", genre="玄幻", sub_genre="末世修真",
            core_selling_point="修真少年在末世中崛起", target_audience="",
            competitive_analysis="",
            platform_fit=PlatformFit(heat_level="平稳", difficulty="未知", reader_preference="中等"),
        ))

    return TopicList(suggestions=suggestions[:5])
