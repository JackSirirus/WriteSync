"""
WriteSync State 数据结构定义

对应设计文档: docs/superpowers/specs/2026-04-20-snowflake-roles-design.md
State 设计文档: docs/state-design.md
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from typing_extensions import TypedDict


class StepName(Enum):
    """工作流步骤枚举"""
    TOPIC = "topic"                          # 选题
    STORY1 = "story1"                        # Step1 一句话摘要
    STORY2 = "story2"                        # Step2 五句话摘要
    CHARACTERS = "characters"                # Step3/5 角色
    WORLD = "world"                          # 世界观
    OUTLINE = "outline"                      # Step4 大纲
    CHAPTER_OUTLINE = "chapter_outline"       # Step6/7 章纲
    CHAPTER = "chapter"                      # 逐章写作
    COMPLETED = "completed"                  # 全部完成


class ProjectStatus(Enum):
    """项目状态"""
    DRAFTING = "drafting"        # 策划中
    WRITING = "writing"          # 写作中
    PAUSED = "paused"            # 暂停
    COMPLETED = "completed"      # 已完成


# ============================================================================
# 选题阶段
# ============================================================================

@dataclass
class PlatformFit:
    """平台适配分析"""
    heat_level: str                    # "热门" | "平稳" | "冷门"
    difficulty: str                     # "红海" | "蓝海" | "未知"
    reader_preference: str              # 读者偏好匹配度
    risk_factors: list[str] = field(default_factory=list)


@dataclass
class TopicSuggestion:
    """单个选题建议"""
    title: str                          # 选题标题
    genre: str                          # 题材
    sub_genre: str                      # 细分题材
    core_selling_point: str             # 核心卖点
    target_audience: str                # 目标读者
    competitive_analysis: str           # 竞品对比分析
    platform_fit: PlatformFit           # 平台适配分析
    inspiration_source: str             # 用户原始想法来源


@dataclass
class TopicState:
    """选题阶段完整产出"""
    user_original_idea: str              # 用户原始想法
    suggestions: list[TopicSuggestion]  # 建议列表
    selected: int = -1                  # 用户选择了哪个（索引，-1表示未选择）
    confirmed_at: Optional[str] = None   # 确认时间


# ============================================================================
# 故事核心（Step1 + Step2）
# ============================================================================

@dataclass
class StoryCore:
    """Step1: 一句话摘要"""
    one_sentence: str                    # ≤15词的一句话核心
    tag: str                             # 类型标签


@dataclass
class StoryArc:
    """Step2: 五句话摘要"""
    setup: str                           # 第1句：背景设定
    inciting: str                        # 第2句：第一转折点
    rising: str                          # 第3句：中点
    climax_prep: str                      # 第4句：第二转折点
    resolution: str                       # 第5句：结局
    theme: str = ""                      # 核心主题
    moral: str = ""                      # 道德/寓意


@dataclass
class StoryState:
    """故事核心完整产出"""
    step1: StoryCore
    step2: StoryArc
    # Step4: 五句话各扩成一段（雪花写作法核心扩展层）
    expanded_paragraphs: list[str] = field(default_factory=list)
    # Step6: 叙事性概要（3-5页故事描述）
    narrative_synopsis: str = ""
    # 扩展笔记
    extended_notes: dict = field(default_factory=dict)
    confirmed_at: Optional[str] = None


# ============================================================================
# 角色（Step3 + Step5）
# ============================================================================

@dataclass
class CharacterRelation:
    """角色关系"""
    target_name: str                     # 关联角色名
    relation_type: str                   # "挚友" | "对手" | "导师" | "爱人" | "家人"
    description: str                     # 关系描述
    dynamic: str                        # 关系变化趋势


@dataclass
class CharacterArc:
    """角色弧线"""
    start_state: str                     # 起点状态
    end_state: str                       # 终点状态
    transformation_event: str            # 触发转变的关键事件
    change_trigger: str                  # 内心触发点


@dataclass
class Character:
    """单个角色"""
    name: str
    role: str                            # "主角" | "女主" | "反派" | "配角" | "导师" | "功能型配角"
    identity: str                        # 社会身份

    # Step3 产出（基础）
    personality: str                     # 核心性格（3个关键词）
    goal: str                            # 主要目标
    conflict: str                        # 内心冲突
    description: str                    # 外貌/气质描写要点

    # Step5 产出（扩展）
    background: str = ""               # 完整背景故事
    arc: Optional[CharacterArc] = None  # 成长弧线详细
    relationships: list[CharacterRelation] = field(default_factory=list)

    # 写作参考
    scene_notes: str = ""               # 场景描写要点（语气/习惯用语）

    # 主角专属
    gold_finger: str = ""               # 金手指/核心能力
    initial_dilemma: str = ""           # 初始困境
    reader_empathy_path: str = ""       # 读者代入路径


@dataclass
class CharactersState:
    """角色阶段完整产出"""
    characters: list[Character]
    summary: str = ""                   # 人物关系总览
    confirmed_at: Optional[str] = None


# ============================================================================
# 世界观
# ============================================================================

@dataclass
class PowerSystem:
    """力量体系"""
    system_name: str                     # 体系名称
    tiers: list[str]                     # 等级列表
    cultivation_rules: str               # 修炼规则
    power_limit: str                    # 力量上限设定
    special_abilities: list[str] = field(default_factory=list)  # 特殊能力规则


@dataclass
class Geography:
    """地理结构"""
    major_locations: list[dict] = field(default_factory=list)  # [{"name": "...", "description": "...", "significance": "..."}]
    political_division: str = ""       # 政治区划
    special_zones: list[str] = field(default_factory=list)     # 特殊区域


@dataclass
class Society:
    """社会结构"""
    factions: list[dict] = field(default_factory=list)  # [{"name": "...", "description": "...", "align": "..."}]
    social_hierarchy: str = ""          # 社会层级
    cultural_notes: str = ""            # 文化特征


@dataclass
class WorldHistory:
    """历史背景"""
    key_events: list[str] = field(default_factory=list)  # 关键历史事件
    timeline_summary: str = ""           # 时间线概述
    past_conflicts: list[str] = field(default_factory=list)  # 过往冲突


@dataclass
class WorldState:
    """世界观完整产出（两阶段：大纲骨架 → 详细展开）"""
    power_system: PowerSystem
    geography: Geography
    society: Society
    history: WorldHistory
    self_check_passed: bool = False    # 自检是否通过
    consistency_notes: str = ""        # 自检一致性说明
    # 两阶段确认：先确认大纲骨架（快速），再确认详细展开
    skel_confirmed_at: Optional[str] = None   # 大纲骨架确认时间
    confirmed_at: Optional[str] = None        # 完整详细确认时间


# ============================================================================
# 大纲（Step4）
# ============================================================================

@dataclass
class ActOutline:
    """单幕大纲"""
    act_number: int                     # 1 | 2 | 3
    summary: str                        # 该幕核心概述
    key_events: list[str] = field(default_factory=list)  # 关键事件列表
    character_enter: list[str] = field(default_factory=list)  # 出场角色
    ending_hook: str = ""              # 该幕结尾钩子


@dataclass
class OutlineState:
    """Step4 完整产出"""
    one_sentence: str                   # Step1 一句话（引用）
    five_sentence: str = ""             # Step2 五句话（引用，拼接存储）
    acts: list[ActOutline] = field(default_factory=list)
    total_estimated_chapters: int = 0   # 预估总章数
    estimated_word_count: str = ""      # 预估总字数
    confirmed_at: Optional[str] = None


# ============================================================================
# 章纲（Step6 + Step7）
# ============================================================================

@dataclass
class Foreshadow:
    """伏笔（章节级）"""
    content: str                        # 伏笔内容
    planted_at: int                     # 植入章节编号
    payoff_chapter: int = 0             # 回收章节编号
    payoff_content: str = ""           # 回收内容
    status: str = "planted"            # "planted" | "paid_off" | "abandoned"


@dataclass
class GlobalForeshadow:
    """全书级伏笔（Phase 4）"""
    id: str                             # 唯一标识 (e.g. "fs-001")
    content: str                        # 伏笔内容
    planted_at: int                     # 植入章节编号
    status: str = "planned"            # "planned" | "planted" | "called_back" | "resolved"
    urgency: str = "normal"            # "low" | "normal" | "high" | "critical"
    related_chapters: list[int] = field(default_factory=list)  # 关联章节
    payoff_chapter: int = 0             # 回收章节编号
    payoff_content: str = ""           # 回收内容
    created_at: str = ""               # ISO timestamp


@dataclass
class ChapterBeat:
    """单个场景（Step7: 场景卡粒度）"""
    scene_id: str                       # "ch01_scene01"
    location: str                       # 场景地点
    time_period: str                    # 时间段
    pov_character: str                   # POV角色
    purpose: str                         # 场景目的
    conflict: str                       # 冲突/张力
    events: list[str] = field(default_factory=list)  # 发生的事件
    emotional_shift: str = ""            # 情绪变化


@dataclass
class ChapterOutline:
    """单章大纲"""
    chapter_number: int
    chapter_title: str

    # Step6 产出（章级）
    core_event: str                     # 本章核心事件
    character_states: str               # 人物状态变化
    story_progression: str             # 故事推进点
    estimated_word_count: int = 0       # 预估字数（3000-5000）

    # Step7 产出（场景级）
    scenes: list[ChapterBeat] = field(default_factory=list)

    # 特殊设计
    foreshadows: list[Foreshadow] = field(default_factory=list)  # 本章伏笔
    hook_at_end: str = ""               # 章节结尾钩子

    # 元信息
    pov: str = ""                       # 本章POV视角
    emotional_tone: str = ""            # 情绪基调
    pace: str = "medium"               # 节奏："fast" | "medium" | "slow"


@dataclass
class ChapterOutlineState:
    """章纲阶段完整产出"""
    total_chapters: int = 0
    chapters: list[ChapterOutline] = field(default_factory=list)
    written_chapters: list[int] = field(default_factory=list)  # 已写完的章节编号

    # 全局管理
    pov_distribution: dict[int, str] = field(default_factory=dict)  # {章节号: POV角色名}
    pov_strategy_note: str = ""          # POV分配策略说明

    # 字数统计
    word_count_plan: int = 0            # 计划总字数
    word_count_actual: int = 0           # 实际总字数
    word_count_by_chapter: dict[int, int] = field(default_factory=dict)  # {章节号: 字数}

    # 全局伏笔追踪
    global_foreshadows: list[Foreshadow] = field(default_factory=list)

    confirmed_at: Optional[str] = None


# ============================================================================
# 草稿
# ============================================================================

@dataclass
class DraftContent:
    """草稿内容"""
    content: str                        # 正文
    agent: str                          # 哪个Agent产出
    change_notes: list[str] = field(default_factory=list)  # 本次修改说明
    timestamp: str = ""                  # 时间戳


@dataclass
class ChapterDraft:
    """单章草稿"""
    chapter_number: int

    draft: Optional[DraftContent] = None          # 文笔Agent初稿
    draft_checked: Optional[DraftContent] = None  # 文笔检查后
    revised: Optional[DraftContent] = None        # 编辑Agent修订
    polished: Optional[DraftContent] = None      # 节奏Agent优化
    final: Optional[DraftContent] = None          # 校对Agent终版

    stage: str = "draft"                # 当前阶段
    word_count: int = 0                  # 终版字数
    written_at: str = ""                  # 首次完成时间
    updated_at: str = ""                  # 最后更新时间


@dataclass
class DraftsState:
    """草稿阶段完整产出"""
    chapters: dict[int, ChapterDraft] = field(default_factory=dict)  # chapter_number → ChapterDraft
    current_writing: Optional[int] = None  # 当前正在写的章节


# ============================================================================
# 工作流状态
# ============================================================================

@dataclass
class WorkflowState:
    """工作流状态"""
    current_step: StepName
    completed_steps: list[StepName] = field(default_factory=list)
    pending_confirmation: bool = False   # 是否等待用户确认
    last_saved: str = ""                # 上次保存时间
    version: int = 1                    # 乐观锁版本号


# ============================================================================
# 全书审查（Step9）
# ============================================================================

@dataclass
class NovelReviewState:
    """全书审查报告（Snowflake Step 9）"""
    structural_issues: list[str] = field(default_factory=list)
    pacing_assessment: str = ""
    character_arc_consistency: list[str] = field(default_factory=list)
    foreshadow_tracking: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    passed: bool = False
    confirmed_at: Optional[str] = None


# ============================================================================
# 版本快照
# ============================================================================

@dataclass
class VersionSnapshot:
    """版本快照"""
    version: int
    step: StepName
    timestamp: str
    snapshot: dict                       # 该版本的完整State快照
    user_note: Optional[str] = None     # 用户备注


@dataclass
class VersionState:
    """版本管理"""
    snapshots: list[VersionSnapshot] = field(default_factory=list)
    current_version: int = 0


# ============================================================================
# 项目元信息
# ============================================================================

@dataclass
class ProjectMetadata:
    """项目元信息"""
    project_id: str                     # UUID，唯一标识
    name: str                           # 项目名称
    platform: str = ""                  # 目标平台
    created_at: str = ""                # ISO时间
    updated_at: str = ""                # ISO时间
    current_step: StepName = StepName.TOPIC
    status: ProjectStatus = ProjectStatus.DRAFTING


# ============================================================================
# v0.4.0 网文专属：钩子矩阵 / 爽点曲线 / 平台策略 / 分卷
# ============================================================================

@dataclass
class HookCard:
    chapter_index: int
    hook_type: str = ""                 # "悬念" | "冲突" | "期待" | "危机" | "反转" | "情感"
    strength: int = 3                   # 1-5 (→ ★ 颗数)
    content: str = ""                   # 钩子内容简述（≤50 字）
    connect_chapter: int = 0            # 衔接的下一章索引


@dataclass
class PleasurePointCard:
    chapter_index: int
    pp_type: str = ""                  # "打脸" | "突破升级" | "收获获得" | "复仇" |
                                        # "逆袭反转" | "智胜碾压" | "情感满足" | "身份揭晓" | "伏笔回收"
    strength: int = 1                   # 1-5
    description: str = ""              # 爽点场景简述（≤50 字）
    word_ratio_target: float = 0.10    # 建议字数占比（0.10 = 10%）


@dataclass
class PlatformProfile:
    platform: str = ""                 # "起点" | "飞卢" | "番茄" | "纵横"
    pleasure_density: str = "中高"     # "极高" | "高" | "中高" | "中"
    hook_strength_min: int = 3         # 钩子强度下限（1-5）
    suppress_tolerance: str = "低"     # "零容忍" | "低"
    style_requirement: str = "中性"    # "轻松/梗密集" | "轻松/快节奏" | "中性" | "文学性"
    daily_ref_words_low: int = 3000    # 日更参考下限
    daily_ref_words_high: int = 5000   # 日更参考上限
    system_panel_preference: str = "可选"     # "强烈推荐" | "可选" | "不推荐"
    audit_strictness: str = "中等"     # "最严" | "中等" | "较松"
    golden_three_boost: str = "标准"   # "极度强化" | "标准"


def get_platform_profile(platform_name: str) -> PlatformProfile:
    profiles = {
        "起点": PlatformProfile(
            platform="起点", pleasure_density="中高", hook_strength_min=3,
            suppress_tolerance="低", style_requirement="中性",
            daily_ref_words_low=3000, daily_ref_words_high=5000,
            system_panel_preference="可选", audit_strictness="最严",
            golden_three_boost="标准",
        ),
        "飞卢": PlatformProfile(
            platform="飞卢", pleasure_density="极高", hook_strength_min=4,
            suppress_tolerance="零容忍", style_requirement="轻松/梗密集",
            daily_ref_words_low=5000, daily_ref_words_high=10000,
            system_panel_preference="强烈推荐", audit_strictness="中等",
            golden_three_boost="极度强化",
        ),
        "番茄": PlatformProfile(
            platform="番茄", pleasure_density="高", hook_strength_min=4,
            suppress_tolerance="零容忍", style_requirement="轻松/快节奏",
            daily_ref_words_low=4000, daily_ref_words_high=6000,
            system_panel_preference="强烈推荐", audit_strictness="较松",
            golden_three_boost="极度强化",
        ),
        "纵横": PlatformProfile(
            platform="纵横", pleasure_density="中", hook_strength_min=3,
            suppress_tolerance="低", style_requirement="文学性",
            daily_ref_words_low=4000, daily_ref_words_high=6000,
            system_panel_preference="不推荐", audit_strictness="中等",
            golden_three_boost="标准",
        ),
    }
    return profiles.get(platform_name, profiles["起点"])


def get_pleasure_density_target(profile: PlatformProfile) -> float:
    _map = {"极高": 0.18, "高": 0.14, "中高": 0.12, "中": 0.10}
    return _map.get(profile.pleasure_density, 0.12)


@dataclass
class VolumeState:
    index: int = 0                     # 卷序号（1-based）
    title: str = ""                    # 卷标题
    one_sentence: str = ""             # 卷一句话核心
    main_conflict: str = ""            # 卷级冲突主线
    chapter_indices: list[int] = field(default_factory=list)  # 全书章索引范围（0-based）
    hook_matrix: list[HookCard] = field(default_factory=list)
    pleasure_curve: list[PleasurePointCard] = field(default_factory=list)
    outline_confirmed_at: str = ""      # 卷纲确认时间
    status: str = "planning"           # "planning" | "writing" | "reviewing" | "completed"
    auto_degraded: bool = False        # 钩子矩阵自动降级标记（3次失败后）


@dataclass
class AuxiliaryCheckItem:
    name: str                          # "钩子落地" | "爽点密度" | "毒点扫描" | "字数范围" | "黄金三章"
    status: str = "warn"               # "pass" | "warn"
    detail: str = ""                   # 详情描述
    position: int = 0                  # 位置行号（毒点扫描用）


# ============================================================================
# 根 State
# ============================================================================

@dataclass
class DynamicContext:
    """累积的运行时知识摘要，注入写作Agent上下文（≤800字）"""

    character_snapshot: str = ""
    recent_chapters_summary: str = ""
    unresolved_foreshadows: list = field(default_factory=list)
    resolved_foreshadows: list = field(default_factory=list)
    foreshadow_deadline: dict = field(default_factory=dict)
    world_changes: str = ""
    world_consistency_notes: str = ""
    pacing_state: str = ""
    chapter_word_counts: dict = field(default_factory=dict)
    plot_progress: str = ""
    story_beats_remaining: int = 0
    updated_at: str = ""
    updated_chapter: int = 0
    # Phase 3: Fact Ledger — structured temporal facts (list of dicts)
    facts: list = field(default_factory=list)
    # Phase 3: Continuity Envelope (last chapter's handoff stored here as dict)
    continuity_envelope: dict = field(default_factory=dict)


@dataclass
class WriteSyncState:
    """
    WriteSync 完整状态

    所有字段都是 JSON 可序列化的，确保可以持久化到文件和 Checkpoint。
    """
    # 元信息
    metadata: ProjectMetadata

    # 各阶段产出
    topic: Optional[TopicState] = None
    story: Optional[StoryState] = None
    outline: Optional[OutlineState] = None
    characters: Optional[CharactersState] = None
    world: Optional[WorldState] = None
    chapter_outline: Optional[ChapterOutlineState] = None
    drafts: DraftsState = field(default_factory=DraftsState)
    novel_review: Optional[NovelReviewState] = None  # Step9 全书审查
    global_foreshadows: list[GlobalForeshadow] = field(default_factory=list)  # Phase 4: 全书级伏笔

    # v0.4.0 分卷 + 网文策略
    volumes: list[VolumeState] = field(default_factory=list)
    current_volume_index: int = 0      # 当前卷索引（0-based）
    platform_profile: Optional[PlatformProfile] = None  # 当前平台策略（可卷间修改）

    # 工作流
    workflow: Optional[WorkflowState] = None
    versions: VersionState = field(default_factory=VersionState)
    stale_markers: dict = field(default_factory=dict)
    dynamic_context: Optional["DynamicContext"] = None


# ============================================================================
# GraphState (TypedDict for LangGraph / Agent compatibility)
# ============================================================================

class GraphState(TypedDict, total=False):
    """
    Agent 使用的状态类型（TypedDict）。

    字段：
    - data: WriteSyncState 业务数据
    - messages: 对话历史
    - pending_step: 当前等待用户确认的步骤
    - user_note: 用户确认时的备注
    - pending_feedback: 用户修改意见，传给 Agent 重生成用
    """
    data: WriteSyncState
    messages: list[dict]
    pending_step: Optional[StepName]
    user_note: Optional[str]
    pending_feedback: Optional[str]


def init_graph_state(ws_state: WriteSyncState) -> GraphState:
    """从 WriteSyncState 创建初始 GraphState"""
    return GraphState(
        data=ws_state,
        messages=[],
        pending_step=None,
        user_note=None,
        pending_feedback=None,
    )
