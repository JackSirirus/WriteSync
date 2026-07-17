"""
WriteSync Prompt 构建工具

提供各 Agent 的 prompt 模板和构建函数。
结构化输出由 instructor response_model 保障，prompt 只负责内容指引。
"""

from typing import Optional

# =====================================================================
# 系统提示词
# =====================================================================

SYSTEM_PROMPT = """你是一位专业的网文写作顾问，专注于帮助作家进行小说创作。
你熟悉雪花写作法（Snowflake Method），了解网文平台的特性（起点、番茄、飞卢、纵横）。
你的风格：专业、务实、直接给出建议，不废话。
"""


def _resolve_system_prompt(custom: Optional[str] = None) -> str:
    """Resolve the system prompt, preferring custom override when provided."""
    return custom if custom else SYSTEM_PROMPT


# =====================================================================
# 选题 Agent
# =====================================================================

def build_topic_prompt(
    user_idea: str,
    platform: str,
    platform_kb: str,
    template: str,
    system_prompt: Optional[str] = None,
) -> str:
    sys_prompt = _resolve_system_prompt(system_prompt)
    return f"""{sys_prompt}

## 任务

根据用户的原始想法，生成 3-5 个选题建议。

## 用户原始想法

{user_idea}

## 目标平台

{platform}

## 平台知识库

请参考以下平台特性数据：

{platform_kb}

## 要求

1. 每个选题都要有具体题材、卖点、差异化分析
2. 卖点要具体，不是泛泛的"爽文"
3. 要有平台适配分析，说明为什么适合这个平台
4. 评估每个选题的潜在风险
"""


# =====================================================================
# 选题检查 Agent
# =====================================================================

def build_topic_check_prompt(
    topic_data: str,
    platform: str,
    platform_kb: str,
    checklist: str,
    system_prompt: Optional[str] = None,
) -> str:
    sys_prompt = _resolve_system_prompt(system_prompt)
    return f"""{sys_prompt}

## 任务

检查选题建议是否符合平台特性和市场规律，输出评估报告。

## 待检查的选题数据

{topic_data}

## 目标平台

{platform}

## 平台知识库

{platform_kb}

## 选题检查清单

请按以下清单逐项检查：

{checklist}

## 要求

1. 对每个选题给出平台适配度评分（1-5星）
2. 指出每个选题的高风险点和优势
3. 给出是否建议选择该选题的结论
"""


# =====================================================================
# 策划 Agent（Step2：基于用户的一句话展开五句话）
# =====================================================================

def build_planning_prompt(
    one_sentence: str,
    tag: str,
    user_feedback: str = "",
    template: str = "",
    system_prompt: Optional[str] = None,
) -> str:
    sys_prompt = _resolve_system_prompt(system_prompt)
    feedback_section = f"\n## 用户修改意见\n\n{user_feedback}\n" if user_feedback else ""
    return f"""{sys_prompt}

## 任务

用户已经写好了一句话故事核心，请你基于这句话展开为五句话摘要（对应三幕结构的五个节点）。

## 用户的一句话

{one_sentence}（{tag}）
{feedback_section}

## 要求

1. 五句话分别对应：背景设定、第一转折、中点上升、第二转折、结局
2. 每句话要具体，不要泛泛的描述
3. 故事要有内在逻辑，前后呼应
4. 保持用户原意的核心创意不变
"""


# =====================================================================
# 角色 Agent（Step3/5）
# =====================================================================

def build_character_prompt(
    story_state: str,
    template: str,
    system_prompt: Optional[str] = None,
) -> str:
    sys_prompt = _resolve_system_prompt(system_prompt)
    return f"""{sys_prompt}

## 任务

基于故事摘要，设计主要角色的设定。

## 故事摘要

{story_state}

## 要求

1. 设计主角、女主/重要配角、反派/对手
2. 每个角色都要有清晰的目标、内心冲突、成长弧线
3. 角色之间要有关系网络
4. 主角要有金手指/核心能力设定
5. 角色性格要能与故事主题契合
"""


# =====================================================================
# 世界观 Agent
# =====================================================================

def build_world_skeleton_prompt(
    story_state: str,
    character_state: str,
    system_prompt: Optional[str] = None,
) -> str:
    """世界观大纲骨架 prompt（快速，只出名字和结构，适配全题材）"""
    sys_prompt = _resolve_system_prompt(system_prompt)
    return f"""{sys_prompt}

## 任务

基于故事和角色设定，构建世界观大纲骨架——只输出名字和结构，不展开详细描述。后续会分步细化。

**适配全题材**：奇幻/仙侠→力量体系；都市/现代→社会规则；科幻/末世→科技系统；历史/架空→时代背景。根据故事题材选择合适的体系类型。

## 故事摘要

{story_state}

## 角色设定

{character_state}

## 要求

1. **只输出框架**：
   - 体系名称（根据题材：力量体系/科技系统/社会规则/时代背景）
   - 等级/阶段名（每级一行简述即可）
   - 主要地点名（故事发生的关键场景）
   - 势力/组织名（存在竞争或合作关系的团体）
   - 时间线概述（一句话总结历史背景）
2. **不要展开详细描述**：其他字段写"待细化"
3. 设定要有独特性，避免老套
4. 即使是非奇幻题材，也要构建有层次感的世界设定
5. 完成后做内部一致性自检
"""


def build_world_prompt(
    story_state: str,
    character_state: str,
    template: str,
    skeleton_context: str = "",
    system_prompt: Optional[str] = None,
) -> str:
    """世界观详细展开 prompt（基于大纲骨架，生成完整细节）"""
    sys_prompt = _resolve_system_prompt(system_prompt)
    skeleton_block = f"""

## 世界观大纲骨架（已确认）

{skeleton_context}

请基于以上骨架，展开完整详细的世界观设定。
""" if skeleton_context else ""

    return f"""{sys_prompt}{skeleton_block}

## 任务

基于故事、角色设定和世界观大纲骨架，生成完整详细的世界观体系。

## 故事摘要

{story_state}

## 角色设定

{character_state}

## 要求

1. 力量体系要清晰、有逻辑，能支撑主角的成长路径（细化修炼规则、力量上限、特殊能力）
2. 地理和社会结构要能支撑故事发展（细化地点描述、政治区划、社会层级、文化特征）
3. 历史背景要有足够深度但不繁琐
4. 设定要有独特性，避免老套
5. 设定要能支撑长篇故事（30-100万字）
6. 完成后做内部一致性自检
"""


# =====================================================================
# 章纲 Agent（Step4 + Step6/7）
# =====================================================================

def build_outline_prompt(
    story_state: str,
    characters_state: str,
    world_state: str,
    narrative_synopsis: str = "",
    template: str = "",
    technique: Optional[str] = None,
    system_prompt: Optional[str] = None,
) -> str:
    sys_prompt = _resolve_system_prompt(system_prompt)
    return f"""{sys_prompt}

## 任务

基于故事生成三幕大纲和20章章纲。紧凑输出，每章一行。

## 故事

{story_state}

## 叙事概要

{narrative_synopsis if narrative_synopsis else '（同故事摘要，无额外叙事展开）'}

## 角色

{characters_state}

## 世界观

{world_state}

## 输出格式

=== 三幕大纲 ===
第一幕：概述
- 事件1
- 事件2

第二幕：概述
...

=== 章纲 ===
第1章：标题 — 核心事件 — POV
第2章：标题 — 核心事件 — POV
...
第20章：标题 — 核心事件 — POV

=== POV策略 ===
...
=== 伏笔规划 ===
...

## 要求

简短。每章一行。直接输出。不要思考过程。
"""


# =====================================================================
# 写作阶段 Agent
# =====================================================================

def build_writer_prompt(
    chapter: str,
    story_context: str,
    character_context: str,
    world_context: str,
    user_feedback: str = "",
    system_prompt: Optional[str] = None,
) -> str:
    sys_prompt = _resolve_system_prompt(system_prompt)
    feedback_section = f"\n## 用户修改意见\n\n{user_feedback}\n" if user_feedback else ""
    return f"""{sys_prompt}
{feedback_section}
## 任务

根据章纲、故事背景、角色设定和世界观，撰写本章正文。

## 章纲

{chapter}

## 故事核心

{story_context}

## 角色设定

{character_context}

## 世界观

{world_context}

## 要求

1. 严格遵循章纲结构
2. 保持视角统一（按章纲指定的POV）
3. 开头要有钩子
4. 章节结尾设置悬念或冲突点
5. 字数 3000-5000 字
6. 注重感官描写和情绪渲染
"""


def build_writer_prompt_v04(
    chapter: str,
    story_context: str,
    character_context: str,
    world_context: str,
    hook_card_info: str = "",
    pleasure_card_info: str = "",
    platform_style_info: str = "",
    golden_three_info: str = "",
    user_feedback: str = "",
    system_prompt: Optional[str] = None,
) -> str:
    sys_prompt = _resolve_system_prompt(system_prompt)
    feedback_section = f"\n## 用户修改意见\n\n{user_feedback}\n" if user_feedback else ""
    extra_sections = []
    if hook_card_info:
        extra_sections.append(f"## 本章钩子要求\n\n{hook_card_info}")
    if pleasure_card_info:
        extra_sections.append(f"## 本章爽点要求\n\n{pleasure_card_info}")
    if platform_style_info:
        extra_sections.append(f"## 平台风格约束\n\n{platform_style_info}")
    if golden_three_info:
        extra_sections.append(f"## ⚠ 黄金三章模式\n\n{golden_three_info}")
    extra_text = "\n\n".join(extra_sections)

    return f"""{sys_prompt}
{feedback_section}
{extra_text}

## 任务

根据章纲、故事背景、角色设定和世界观，撰写本章正文。

## 章纲

{chapter}

## 故事核心

{story_context}

## 角色设定

{character_context}

## 世界观

{world_context}

## 要求

1. 严格遵循章纲结构，特别注意上述「本章钩子要求」和「本章爽点要求」
2. 保持视角统一（按章纲指定的POV）
3. **章节最后一句必须是钩子落地句**
4. 字数 3000-5000 字
5. 注重感官描写和情绪渲染
"""


# =====================================================================
# 分步生成 Writer（分段写作，避免单次 LLM 调用超时）
# =====================================================================

def build_step_plan_prompt(
    chapter_text: str,
    story_context: str,
    character_context: str,
    world_context: str,
    extra_context: str = "",
    system_prompt: Optional[str] = None,
) -> str:
    """Step 1: 生成分段写作计划"""
    sys_prompt = _resolve_system_prompt(system_prompt)
    return f"""{sys_prompt}

## 任务

将本章拆分为 2-3 个写作分段，每段 1000-1800 字。制定分段计划。

## 章纲

{chapter_text}

## 故事核心

{story_context}

## 角色设定

{character_context}

## 世界观

{world_context}
{extra_context}

## 要求

1. 分段要自然，在情节转折点或场景切换处切分
2. 每段标明：要写什么、关键节拍、与上一段的衔接
3. 高潮放在最后一段
4. 开篇策略要具体（钩子类型/切入点）
"""


def build_step_segment_prompt(
    segment: str,
    segment_index: int,
    total_segments: int,
    chapter_text: str,
    story_context: str,
    character_context: str,
    world_context: str,
    prev_segment_end: str = "",
    extra_context: str = "",
    system_prompt: Optional[str] = None,
) -> str:
    """Step 2: 写单个分段（1000-1800字）"""
    sys_prompt = _resolve_system_prompt(system_prompt)
    position_hint = ""
    if segment_index == 1:
        position_hint = "这是本章开头，需要设计钩子吸引读者。"
    elif segment_index == total_segments:
        position_hint = "这是本章结尾，必须设置钩子/悬念引出下一章。"
    else:
        position_hint = "这是本章中间部分，保持节奏推进情节。"

    continuity = ""
    if prev_segment_end:
        continuity = f"\n## 前一段落尾\n\n{prev_segment_end[-200:]}\n\n请从上述内容自然衔接。"

    return f"""{sys_prompt}

## 任务

写本章第 {segment_index}/{total_segments} 段。{position_hint}

## 章纲

{chapter_text}

## 故事核心

{story_context}

## 角色设定

{character_context}

## 世界观

{world_context}

## 本段要求

{segment}
{continuity}
{extra_context}

## 输出要求

1. 写 1000-1800 字正文，不要 JSON 包裹，直接输出正文
2. 对话占比 ≥ 30%
3. 保持视角统一
4. 结尾不要突兀中断，给下一段留衔接空间
"""


def build_step_assemble_prompt(
    segments: list[str],
    chapter_text: str,
    story_context: str,
    system_prompt: Optional[str] = None,
) -> str:
    """Step 3: 合并分段，平滑过渡，输出完整章节"""
    sys_prompt = _resolve_system_prompt(system_prompt)
    segments_text = "\n\n--- 分段分隔 ---\n\n".join(
        f"[第{i+1}段]\n{s}" for i, s in enumerate(segments)
    )
    return f"""{sys_prompt}

## 任务

将以下 {len(segments)} 个分段合并为完整章节。平滑段落间过渡，消除重复和断裂。

## 章纲

{chapter_text}

## 故事核心

{story_context}

## 分段内容

{segments_text}

## 要求

1. 将分段合并为一篇流畅的完整章节
2. 段落间添加自然过渡（1-2句话即可）
3. 消除重复描述
4. 保持章纲指定的人称和风格
5. 直接输出完整正文，不要 JSON 包裹
"""


GOLDEN_THREE_CH1_TEMPLATE = """黄金三章 - Ch1 强制结构：
① 钩子开场（30字内，冲突/悬念/反常切入）
→ ② MC处境展示（150字内完成：身份 + 当前困境 + 与众不同的特点）
→ ③ 金手指暗示/展现（通过具体事件触发，不要平铺直叙）
→ ④ 微小收获或反击（微爽点，让读者看到主角的主动性）
→ ⑤ 章末强钩子（★★★★）：为Ch2铺垫更大危机或机遇"""

GOLDEN_THREE_CH2_TEMPLATE = """黄金三章 - Ch2 强制结构：
① 快速承接Ch1章末钩子
→ ② 冲突升级（对手施压/环境恶化/规则收紧，威胁加大）
→ ③ MC尝试应对（展现智慧和行动力，不能被动挨打）
→ ④ 小爽点（第一次明显的反击或收获，给读者兑现期待）
→ ⑤ 更强钩子（★★★★★）：暗示Ch3将迎来的正面爆发"""

GOLDEN_THREE_CH3_TEMPLATE = """黄金三章 - Ch3 强制结构：
① 快速承接Ch2钩子
→ ② 冲突推向小高潮（蓄力30-40%篇幅）
→ ③ MC关键抉择或突破（中爽点爆发，60-70%篇幅写满反击过程和结果）
→ ④ 章末钩子转向：揭示更大世界观/阴谋/目标，让读者知道"好戏才刚开始"
→ ⑤ 目标：锁定追读——读者看完第3章不点收藏来找你"""


def build_writer_check_prompt(
    chapter_number: int,
    draft: str,
    system_prompt: Optional[str] = None,
) -> str:
    sys_prompt = _resolve_system_prompt(system_prompt)
    return f"""{sys_prompt}

## 任务

检查第 {chapter_number} 章初稿质量，判断是否需要修改。

## 初稿

{draft[:3000]}

## 检查维度

1. 是否遵循章纲结构
2. 开头是否有钩子
3. 章节结尾是否有悬念
4. 字数是否在 3000-5000 范围
5. 视角是否统一
6. 是否有明显的情节漏洞
"""


def build_editor_prompt(
    chapter_number: int,
    draft: str,
    story_context: str,
    character_context: str,
    outline_context: str,
    user_feedback: str = "",
    system_prompt: Optional[str] = None,
) -> str:
    sys_prompt = _resolve_system_prompt(system_prompt)
    feedback_section = f"\n## 用户修改意见\n\n{user_feedback}\n" if user_feedback else ""
    return f"""{sys_prompt}
{feedback_section}
## 任务

对第 {chapter_number} 章进行编辑修订，检查内容质量和一致性。

## 初稿

{draft[:3000]}

## 故事核心

{story_context}

## 角色设定

{character_context}

## 章纲

{outline_context}

## 编辑维度

1. 结构性问题：章节节奏、场景转换
2. 内容问题：描写是否充分、对话是否自然
3. 角色一致性：是否OOC
4. 情节一致性：是否与章纲和大纲一致
5. 世界设定一致性：是否与世界观设定一致
"""


def build_rhythm_prompt(
    chapter_number: int,
    draft: str,
    story_context: str,
    system_prompt: Optional[str] = None,
) -> str:
    sys_prompt = _resolve_system_prompt(system_prompt)
    return f"""{sys_prompt}

## 任务

对第 {chapter_number} 章进行节奏优化和爽点评估。

## 当前正文

{draft[:3000]}

## 故事核心

{story_context}

## 分析维度

1. 整体节奏评估：快/中/慢
2. 段落节奏分析：哪些段落快、哪些慢
3. 情绪曲线：读者的情绪波动
4. 章节断点建议：最适合停下的位置
5. 爽点密度：是否有足够的爽点/高潮
6. 节奏调整建议：如何优化阅读体验
"""


def build_proofreader_prompt(
    chapter_number: int,
    draft: str,
    system_prompt: Optional[str] = None,
) -> str:
    sys_prompt = _resolve_system_prompt(system_prompt)
    return f"""{sys_prompt}

## 任务

对第 {chapter_number} 章进行最终校对和节奏评估。

## 正文

{draft}

## 校对维度

1. 错别字
2. 语法/语病
3. 标点符号错误
4. 格式问题（空格、换行、标点全半角）
5. 常见错误：的地得、了着过

## 节奏维度

1. 整体节奏评估（快/中/慢）
2. 章节断点是否合适（钩子/悬念）
3. 情绪曲线是否合理
4. 节奏调整建议

输出修正后的完整正文。
"""


# =====================================================================
# 扩展 Agent（Snowflake Step 4）
# =====================================================================

def build_expansion_prompt(
    one_sentence: str,
    tag: str,
    setup: str,
    inciting: str,
    rising: str,
    climax_prep: str,
    resolution: str,
    theme: str,
    system_prompt: Optional[str] = None,
) -> str:
    sys_prompt = _resolve_system_prompt(system_prompt)
    return f"""{sys_prompt}

## 任务

将一句话故事的五句话各自扩展成一段完整叙述。
这是雪花写作法 Step 4：每句话扩成 3-5 句的一段。

## 一句话

{one_sentence}（{tag}）

## 五句话

1. 背景设定：{setup}
2. 第一转折：{inciting}
3. 中点上升：{rising}
4. 第二转折：{climax_prep}
5. 结局：{resolution}

## 主题

{theme}

## 要求

1. 对每句话分别展开，每段 3-5 句
2. 保持叙事连贯，段与段之间有自然的过渡
3. 补充具体的场景细节和人物动机
4. 不要引入新的人物或情节分支
"""


# =====================================================================
# 叙事概要 Agent（Snowflake Step 6 叙事层）
# =====================================================================

def build_narrative_synopsis_prompt(
    one_sentence: str,
    tag: str,
    five_sentences: list[str],
    expanded_paragraphs: list[str],
    theme: str,
    system_prompt: Optional[str] = None,
) -> str:
    sys_prompt = _resolve_system_prompt(system_prompt)
    expanded_section = ""
    if expanded_paragraphs and len(expanded_paragraphs) == 5:
        expanded_section = "\n## 扩展段落\n\n" + "\n\n".join(
            f"第{i+1}段：{p}" for i, p in enumerate(expanded_paragraphs)
        )

    five_section = "\n".join(f"{i+1}. {s}" for i, s in enumerate(five_sentences))

    return f"""{sys_prompt}

## 任务

写一篇叙事性故事概要（3-5 页篇幅），按时间线流畅讲述整个故事。
这不是结构化章纲，而是一篇可读的故事描述。

## 一句话

{one_sentence}（{tag}）

## 五句话

{five_section}
{expanded_section}

## 主题

{theme}

## 要求

1. 按故事时间线叙述，而非按章节罗列
2. 读起来像一篇短故事，有起承转合
3. 涵盖所有关键情节节点
4. 注意人物动机和情绪变化
5. 篇幅 3-5 页（约 1500-3000 字）
"""


# =====================================================================
# 全书审查 Agent（Snowflake Step 9）
# =====================================================================

def build_novel_review_prompt(
    story_summary: str,
    characters_summary: str,
    total_chapters: str,
    chapter_summaries: str,
    system_prompt: Optional[str] = None,
) -> str:
    sys_prompt = _resolve_system_prompt(system_prompt)
    return f"""{sys_prompt}

## 任务

对已完成的整部小说进行全书宏观审查。
这是雪花写作法 Step 9：输出结构、节奏、角色弧线的全景评估。

## 故事核心

{story_summary}

## 角色设定

{characters_summary}

## 章节总览

{total_chapters}

## 各章摘录

{chapter_summaries}

## 审查维度

1. 结构：三幕节奏是否合理、高潮位置是否恰当
2. 角色弧线：每个角色的变化轨迹是否连贯
3. 伏笔：伏笔是否有植有收
4. 节奏：全书节奏是否有起伏
5. 篇幅：各章字数分配是否合理
"""
