"""
灵感反推 Agent（Inspire）

从简短前提（如 "武侠+重生"）一键生成结构化写作灵感：
- 故事核心（一句话 + 标签）
- 世界观（力量体系 / 地点 / 势力）
- 主要角色（2-3 个）
- 章纲预览（3 章）
"""

import logging
from typing import Optional

from ..utils.llm import LLMClient, create_llm_client
from .response_models import InspireResult

logger = logging.getLogger("writesync")

INSPIRE_SYSTEM_PROMPT = """你是小说灵感生成器。用户给出一段简短的想法（可以是题材组合、关键词、场景片段），你需要生成一份完整的写作构想。

请以 JSON 格式输出，字段说明：
- story_core: {one_sentence: "一句话核心（15字以内）", tag: "类型标签（如 武侠+重生、玄幻+穿越）"}
- world_building: {power_system: "力量/修炼体系简述", major_locations: "主要地点及意义", factions: "主要势力及关系"}
- main_characters: [{name, role, personality, goal}]（2-3个角色）
- outline_preview: [{chapter_title, core_event}]（前3章的标题+核心事件）

要求：
1. 故事核心必须紧贴用户输入，不要偏离
2. 世界观要具体可行，不要空泛
3. 角色要有清晰的动机和冲突
4. 章纲要体现起承转合，第1章要开篇有钩子"""

INSPIRE_USER_PROMPT_TEMPLATE = """用户的灵感想法：
{seed}

请基于这个想法生成完整的写作灵感和构想。"""


def inspire(seed_text: str, llm: Optional[LLMClient] = None) -> dict:
    """
    灵感反推：从简短文本生成结构化写作灵感。

    Args:
        seed_text: 用户输入的前提/想法（如 "武侠+重生"）
        llm: 可选的 LLM 客户端

    Returns:
        dict: 包含 story_core, world_building, main_characters, outline_preview
              如果 LLM 调用失败，返回部分结果 + error 字段
    """
    if not seed_text or not seed_text.strip():
        return {"error": "请提供灵感想法", "story_core": None,
                "world_building": None, "main_characters": [],
                "outline_preview": []}

    seed = seed_text.strip()
    prompt = INSPIRE_USER_PROMPT_TEMPLATE.format(seed=seed)

    if llm is None:
        llm = create_llm_client()

    try:
        result: InspireResult = llm.complete_structured(
            prompt,
            InspireResult,
            timeout=120,
            temperature=0.8,
        )
        return {
            "story_core": {
                "one_sentence": result.story_core.one_sentence,
                "tag": result.story_core.tag,
            },
            "world_building": {
                "power_system": result.world_building.power_system,
                "major_locations": result.world_building.major_locations,
                "factions": result.world_building.factions,
            },
            "main_characters": [
                {
                    "name": c.name,
                    "role": c.role,
                    "personality": c.personality,
                    "goal": c.goal,
                }
                for c in result.main_characters
            ],
            "outline_preview": [
                {
                    "chapter_title": ch.chapter_title,
                    "core_event": ch.core_event,
                }
                for ch in result.outline_preview
            ],
        }

    except Exception as e:
        logger.exception("灵感反推 LLM 调用失败: seed=%s", seed[:50])
        # Fallback: 返回部分结果 + 错误标记
        return {
            "error": f"生成失败: {e}。建议缩短前提描述后重试，或手动填写企划。",
            "error_note": str(e),
            "story_core": {"one_sentence": seed, "tag": ""},
            "world_building": {"power_system": "", "major_locations": "", "factions": ""},
            "main_characters": [],
            "outline_preview": [],
        }
