"""
Agent 结构化输出类型（Pydantic models）

供 instructor 做结构化 LLM 调用，替代自由文本+正则解析。
"""

from typing import Optional
from pydantic import BaseModel, Field


# =====================================================================
# 选题 Agent
# =====================================================================

class PlatformFit(BaseModel):
    heat_level: str = Field(description="'热门' | '平稳' | '冷门'")
    difficulty: str = Field(description="'红海' | '蓝海' | '未知'")
    reader_preference: str = Field(description="读者偏好匹配度")
    risk_factors: list[str] = Field(default_factory=list)

class TopicSuggestion(BaseModel):
    title: str = Field(description="选题标题")
    genre: str = Field(description="题材")
    sub_genre: str = Field(description="细分题材")
    core_selling_point: str = Field(description="核心卖点，具体不空泛")
    target_audience: Optional[str] = Field(default="", description="目标读者画像")
    competitive_analysis: Optional[str] = Field(default="", description="竞品对比分析")
    platform_fit: Optional[PlatformFit] = Field(default=None, description="平台适配分析")
    estimated_risk: Optional[str] = Field(default="", description="潜在风险评估")

class TopicList(BaseModel):
    suggestions: list[TopicSuggestion] = Field(description="3-5条选题建议")


# =====================================================================
# 选题检查 Agent
# =====================================================================

class TopicEvaluation(BaseModel):
    suggestion_index: int = Field(description="对应第几个选题（0-based）")
    title: str = Field(description="选题标题")
    platform_fit_score: int = Field(description="平台适配度评分 1-5")
    strengths: Optional[list[str]] = Field(default_factory=list, description="优势")
    risks: Optional[list[str]] = Field(default_factory=list, description="高风险点")
    conclusion: Optional[str] = Field(default="", description="是否建议选择该选题")

class TopicCheckReport(BaseModel):
    evaluations: list[TopicEvaluation]
    overall_summary: str = Field(description="整体评估结论")


# =====================================================================
# 策划 Agent（Step1 + Step2）
# =====================================================================

class StoryCore(BaseModel):
    one_sentence: str = Field(description="一句话核心，≤15词")
    tag: str = Field(description="类型标签")

class StoryArc(BaseModel):
    setup: str = Field(description="第1句：背景设定")
    inciting: str = Field(description="第2句：第一转折点")
    rising: str = Field(description="第3句：中点/上升")
    climax_prep: str = Field(description="第4句：第二转折点")
    resolution: str = Field(description="第5句：结局")
    theme: str = Field(default="", description="核心主题")

class StorySummary(BaseModel):
    step1: StoryCore
    step2: StoryArc
    extended_notes: str = Field(default="", description="策划补充笔记")


# =====================================================================
# 角色 Agent（Step3 + Step5）
# =====================================================================

class CharacterRelation(BaseModel):
    target_name: str = Field(description="关联角色名")
    relation_type: str = Field(description="关系类型：挚友/对手/导师/爱人/家人")
    description: str = Field(description="关系描述")

class CharacterArc(BaseModel):
    start_state: str = Field(description="起点状态")
    end_state: str = Field(description="终点状态")
    transformation_event: str = Field(description="触发转变的关键事件")
    change_trigger: str = Field(default="", description="内心触发点")

class CharacterCard(BaseModel):
    name: str = Field(description="角色名")
    role: str = Field(description="定位：主角/女主/反派/配角/导师")
    identity: str = Field(description="社会身份")
    personality: str = Field(description="核心性格，3个关键词")
    goal: str = Field(description="主要目标")
    conflict: str = Field(description="内心冲突")
    description: str = Field(description="外貌/气质描写要点")
    background: str = Field(default="", description="完整背景故事")
    gold_finger: str = Field(default="", description="金手指/核心能力（主角专属）")
    initial_dilemma: str = Field(default="", description="初始困境（主角专属）")
    arc: CharacterArc | None = None
    relationships: list[CharacterRelation] = Field(default_factory=list)

class CharacterList(BaseModel):
    characters: list[CharacterCard] = Field(description="角色卡列表")
    summary: str = Field(description="人物关系总览")


# =====================================================================
# 世界观 Agent
# =====================================================================

class PowerTier(BaseModel):
    name: str = Field(description="等级名称")
    description: str = Field(description="等级描述")

class PowerSystem(BaseModel):
    system_name: str = Field(description="体系名称")
    tiers: list[PowerTier] = Field(description="等级体系")
    cultivation_rules: str = Field(description="修炼规则")
    power_limit: str = Field(description="力量上限设定")
    special_abilities: list[str] = Field(default_factory=list, description="特殊能力规则")

class MajorLocation(BaseModel):
    name: str = Field(description="地点名称")
    description: str = Field(description="描述")
    significance: str = Field(description="故事意义")

class Geography(BaseModel):
    major_locations: list[MajorLocation] = Field(default_factory=list)
    political_division: str = Field(default="", description="政治区划")

class Faction(BaseModel):
    name: str = Field(description="势力名称")
    description: str = Field(description="描述")
    alignment: str = Field(description="立场")

class Society(BaseModel):
    factions: list[Faction] = Field(default_factory=list)
    social_hierarchy: str = Field(default="", description="社会层级")
    cultural_notes: str = Field(default="", description="文化特征")

class WorldHistory(BaseModel):
    key_events: list[str] = Field(default_factory=list, description="关键历史事件")
    timeline_summary: str = Field(default="", description="时间线概述")

class WorldSetting(BaseModel):
    power_system: PowerSystem
    geography: Geography
    society: Society
    history: WorldHistory
    consistency_notes: str = Field(default="", description="内部一致性说明")


# =====================================================================
# 章纲 Agent（Step4 + Step6/7）
# =====================================================================

class SceneBeat(BaseModel):
    scene_id: str = Field(description="场景编号，如 ch01_scene01")
    location: str = Field(description="场景地点")
    purpose: str = Field(description="场景目的")
    conflict: str = Field(description="冲突/张力")
    pov_character: str = Field(default="", description="POV角色")

class Foreshadow(BaseModel):
    content: str = Field(description="伏笔内容")
    planted_chapter: int = Field(description="植入章节")
    payoff_chapter: int = Field(default=0, description="回收章节")
    status: str = Field(default="planted", description="planted/paid_off")

class ChapterOutline(BaseModel):
    chapter_number: int = Field(description="章节编号")
    chapter_title: str = Field(description="章名")
    core_event: str = Field(description="核心事件")
    character_states: str = Field(description="人物状态变化")
    story_progression: str = Field(description="故事推进点")
    estimated_word_count: int = Field(default=4000)
    scenes: list[SceneBeat] = Field(default_factory=list)
    hook_at_end: str = Field(default="", description="章节结尾钩子")
    pov: str = Field(default="", description="POV视角")
    pace: str = Field(default="medium", description="节奏 fast/medium/slow")

class ActOutline(BaseModel):
    act_number: int = Field(description="幕编号 1/2/3")
    summary: str = Field(description="该幕核心概述")
    key_events: list[str] = Field(default_factory=list)
    ending_hook: str = Field(default="", description="该幕结尾钩子")

class ChapterOutlineList(BaseModel):
    total_chapters: int = Field(description="总章数")
    chapters: list[ChapterOutline] = Field(description="章纲列表")
    acts: list[ActOutline] = Field(default_factory=list, description="三幕大纲")
    word_count_plan: int = Field(default=0, description="计划总字数")
    pov_strategy_note: str = Field(default="", description="POV分配策略")
    global_foreshadows: list[Foreshadow] = Field(default_factory=list)


# =====================================================================
# 写作阶段
# =====================================================================

class ChapterDraftContent(BaseModel):
    content: str = Field(description="章节正文")
    word_count: int = Field(default=0, description="字数")
    writing_notes: str = Field(default="", description="写作备注")


# =====================================================================
# 分步生成（分段写作）
# =====================================================================

class SegmentSpec(BaseModel):
    """单个分段的规格"""
    segment_id: str = Field(description="分段编号，如 seg_01")
    scene_id: str = Field(default="", description="关联的场景编号")
    summary: str = Field(description="该分段要写什么（≤80字）")
    estimated_words: int = Field(default=1200, description="预估字数")
    key_beats: list[str] = Field(default_factory=list, description="关键节拍（≤3个）")
    hook_connect: str = Field(default="", description="与上一段/钩子的衔接说明")

class ContentPlan(BaseModel):
    """分步写作计划"""
    total_segments: int = Field(description="分段总数（推荐 2-4）")
    segments: list[SegmentSpec] = Field(description="分段规格列表")
    opening_strategy: str = Field(description="开篇策略（≤50字）")
    climax_position: str = Field(description="高潮所在分段")

class DraftReviewNotes(BaseModel):
    overall: str = Field(description="整体评价")
    issues: list[str] = Field(description="问题列表")
    suggestions: list[str] = Field(description="修改建议")
    passed: bool = Field(description="是否通过检查")

class ProofreadReport(BaseModel):
    typos: list[str] = Field(default_factory=list, description="错别字列表")
    grammar_issues: list[str] = Field(default_factory=list, description="语法/语病")
    punctuation_issues: list[str] = Field(default_factory=list, description="标点问题")
    format_issues: list[str] = Field(default_factory=list, description="格式问题")
    rhythm_assessment: str = Field(default="", description="节奏评估：快/中/慢")
    rhythm_adjustments: list[str] = Field(default_factory=list, description="节奏调整建议")
    cliffhanger_note: str = Field(default="", description="章节断点建议")
    corrected_version: str = Field(description="修正后的正文")


# =====================================================================
# 扩展 Agent（Snowflake Step 4）
# =====================================================================

class ExpansionParagraph(BaseModel):
    sentence_index: int = Field(description="对应第几句话（1-5）")
    expanded_text: str = Field(description="展开后的段落，3-5句")


class ExpandedParagraphs(BaseModel):
    paragraphs: list[ExpansionParagraph] = Field(description="五句话分别展开的段落")


# =====================================================================
# 叙事概要 Agent（Snowflake Step 6 叙事层）
# =====================================================================

class NarrativeSynopsis(BaseModel):
    synopsis: str = Field(description="3-5页叙事性故事描述，按故事时间线展开")
    tone_notes: str = Field(default="", description="风格和基调说明")


# =====================================================================
# 全书审查 Agent（Snowflake Step 9）
# =====================================================================

class NovelReviewReport(BaseModel):
    overall_assessment: str = Field(description="全书整体评估")
    structural_issues: list[str] = Field(description="结构性问题（三幕节奏、篇幅分配等）")
    pacing_assessment: str = Field(description="全书节奏评估")
    character_arc_consistency: list[str] = Field(description="角色弧线一致性问题")
    foreshadow_tracking: list[str] = Field(description="伏笔追踪结果")
    recommendations: list[str] = Field(description="修改建议")
    passed: bool = Field(description="是否通过审查")


# =====================================================================
# 动态上下文提取辅助模型
# =====================================================================

class CharacterChange(BaseModel):
    """角色状态变化"""
    name: str = Field(description="角色名")
    change: str = Field(description="变化描述 (≤20字)")


class CharacterChangeList(BaseModel):
    """角色变化列表"""
    changes: list[CharacterChange] = []


class ContradictionItem(BaseModel):
    """一致性矛盾"""
    issue: str = Field(description="矛盾描述")


class ContradictionList(BaseModel):
    """一致性矛盾列表"""
    contradictions: list[ContradictionItem] = []


# =====================================================================
# 灵感反推（Inspire）
# =====================================================================

class InspireCharacter(BaseModel):
    """灵感反推角色"""
    name: str = Field(description="角色名")
    role: str = Field(description="定位：主角/女主/反派/配角/导师")
    personality: str = Field(description="核心性格关键词")
    goal: str = Field(description="角色目标")


class InspireWorldBuilding(BaseModel):
    """灵感反推世界观"""
    power_system: str = Field(description="力量体系概述")
    major_locations: str = Field(description="主要地点列表及说明")
    factions: str = Field(description="势力/组织列表及说明")


class InspireOutlineChapter(BaseModel):
    """灵感反推章纲章节"""
    chapter_title: str = Field(description="章节标题")
    core_event: str = Field(description="核心事件")


class InspireStoryCore(BaseModel):
    """灵感反推故事核心"""
    one_sentence: str = Field(description="一句话核心，≤15词")
    tag: str = Field(description="类型标签")


class InspireResult(BaseModel):
    """灵感反推完整产出"""
    story_core: InspireStoryCore = Field(description="故事核心")
    world_building: InspireWorldBuilding = Field(description="世界观")
    main_characters: list[InspireCharacter] = Field(description="2-3个主要角色")
    outline_preview: list[InspireOutlineChapter] = Field(description="前3章大纲预览")


# =====================================================================
# Orchestrator 决策（已改用 complete() + JSON 解析，此模型备用）
# =====================================================================
# class OrchestratorDecisionModel 已移除，决策改用纯文本 JSON 解析
