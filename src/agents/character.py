"""
角色 Agent

Step3：基础角色卡 + Step5：角色 Synopsis
使用 instructor 结构化输出。
"""

from typing import Optional

from ..state.state_types import GraphState
from ..state.state_types import (
    CharactersState, Character, CharacterRelation as CharacterRelationData,
    CharacterArc as CharacterArcData,
)
from ..utils.knowledge import get_knowledge_base
from ..utils.llm import LLMClient, create_llm_client
from .prompts import build_character_prompt
from .response_models import CharacterList


def run_character_agent(
    state: GraphState,
    llm: Optional[LLMClient] = None,
) -> dict:
    story_state = state["data"].story
    if story_state is None:
        raise ValueError("story 字段为空，请先运行策划 Agent")

    kb = get_knowledge_base()
    template = kb.load_template("角色卡")

    prompt = build_character_prompt(
        story_state=_format_story_for_prompt(story_state),
        template=template,
        system_prompt=state.get("_prompt_system_override"),
    )

    if llm is None:
        llm = create_llm_client()
    response: CharacterList = llm.complete_structured(prompt, output_class=CharacterList, temperature=0.7, max_tokens=8192)

    characters = [
        Character(
            name=c.name,
            role=c.role,
            identity=c.identity,
            personality=c.personality,
            goal=c.goal,
            conflict=c.conflict,
            description=c.description,
            background=c.background or "",
            gold_finger=c.gold_finger or "",
            initial_dilemma=c.initial_dilemma or "",
            arc=CharacterArcData(
                start_state=c.arc.start_state,
                end_state=c.arc.end_state,
                transformation_event=c.arc.transformation_event,
                change_trigger=c.arc.change_trigger,
            ) if c.arc else None,
            relationships=[
                CharacterRelationData(
                    target_name=r.target_name,
                    relation_type=r.relation_type,
                    description=r.description,
                    dynamic="",
                )
                for r in (c.relationships or [])
            ],
        )
        for c in response.characters
    ]
    characters_state = CharactersState(characters=characters, summary=response.summary)
    state["data"].characters = characters_state

    messages = state.get("messages", [])
    messages.append({
        "role": "assistant",
        "content": f"角色设定已生成，共 {len(characters)} 个角色：",
        "attachments": [{"type": "character_cards", "count": len(characters)}],
    })

    return {"data": state["data"], "messages": messages}


def _format_story_for_prompt(story_state) -> str:
    s1 = story_state.step1
    s2 = story_state.step2
    return f"""## 一句话摘要
{s1.one_sentence}

## 五句话摘要
1. {s2.setup}
2. {s2.inciting}
3. {s2.rising}
4. {s2.climax_prep}
5. {s2.resolution}

## 主题
{s2.theme or "待定义"}
"""
