"""
主 Agent 决策逻辑

调用 LLM 决定下一步调用哪个子 Agent。
v0.4.0 新增：三种编排模式、钩子矩阵生成、爽点曲线规划、平台策略注入。
"""

import json
import logging
import random
from typing import Optional

from ..utils.llm import LLMClient, create_llm_client
from ..state.state_types import (
    HookCard,
    PleasurePointCard,
    PlatformProfile,
    VolumeState,
    get_platform_profile,
    get_pleasure_density_target,
)
from .models import OrchestratorDecision, Dashboard, OrchestratorMode

logger = logging.getLogger("writesync")


SYSTEM_PROMPT = """你是WriteSync的主编，负责统筹一部小说的协作写作流程。

## 你的职责
评估当前状态，决定下一步调用哪个子Agent或提议全书完成。

## 子Agent目录（只能用这些名称）
- story: 选题建议 → 一句话 → 五句话扩展故事框架
- character: 生成/修改角色卡
- world: 构建世界观设定
- outline: 规划章节目录和章节节拍
- writer: 撰写指定章节正文
- proofreader: 校对指定章节并分析节奏
- novel_review: 全书完稿后整体审查

## 决策规则（必须严格遵守）
1. **CRITICAL**: 如果 completed_agents 为空，唯一正确的选择是调用 story agent
2. 写作自然顺序（逐阶段推进）：story → character → world → outline → writer → proofreader
3. 每个阶段在上一个阶段确认后才能进行
4. writer产出章节草稿后，应紧接着调用proofreader校对同一章
5. 全书完成条件：所有章节已写+已校对，且全书审查已通过
6. instruction用自然语言描述具体任务，包含用户创作想法作为参考

## 输出格式
严格返回JSON，agent字段必须使用上述目录中的名称：
{"action": "call_agent", "agent": "story", "instruction": "...", "reason": "...", "options": [...]}
或
{"action": "done", "reason": "全部完成的原因"}

## 备选方案（v0.5.0 Suggestion Mode）
除了给出主决策外，还必须提供 2-3 个备选方案放在 `options` 数组中：
- 第一个选项必须与主决策 (action/agent) 一致
- 每个选项包含: action (agent名), reasoning (为什么这是好选择), confidence (0.0-1.0)
- 备选方案应该代表不同思路（如：保守/激进/备选阶段）
- confidence 之和不必为 1.0，相对大小反映优先级
- 如果无法判断，给出空数组 []（向后兼容）

示例：
{
  "action": "call_agent",
  "agent": "character",
  "instruction": "基于已确认的故事核心设计主角卡",
  "reason": "故事核心已确认，按雪花写作法下一步是创建角色",
  "options": [
    {"action": "character", "reasoning": "按标准流程，故事确认后必须先建角色", "confidence": 0.75},
    {"action": "story", "reasoning": "若用户对故事核心仍有疑虑可重调", "confidence": 0.15},
    {"action": "world", "reasoning": "若用户希望提前构世界观骨架", "confidence": 0.10}
  ]
}
"""

HOOK_TYPES = ["悬念", "冲突", "期待", "危机", "反转", "情感"]
PP_TYPES = ["打脸", "突破升级", "收获获得", "复仇", "逆袭反转", "智胜碾压", "情感满足", "身份揭晓", "伏笔回收"]

HOOK_TYPE_DISTRIBUTION = {"悬念": 0.30, "冲突": 0.25, "期待": 0.20, "危机": 0.15, "反转": 0.07, "情感": 0.03}
PP_TYPE_DISTRIBUTION = {"打脸": 0.30, "突破升级": 0.25, "收获获得": 0.20, "反转": 0.15, "智胜": 0.10}


def generate_hook_matrix(chapter_count: int, is_volume_one: bool = False,
                         hook_strength_min: int = 3, golden_three_boost: bool = False) -> list[HookCard]:
    hooks = []
    last_type = ""
    second_last_type = ""
    for i in range(chapter_count):
        ch = i + 1
        # 开篇卷 Ch1-3 强制高强钩子
        if golden_three_boost and is_volume_one and ch <= 3:
            strength = max(4, hook_strength_min)  # 最低★★★★
        elif ch == chapter_count:
            strength = 5  # 卷末爆点
        else:
            strength = random.choices([s for s in range(hook_strength_min, 6)],
                                      weights=[0.05, 0.15, 0.35, 0.3, 0.15][hook_strength_min - 1:],
                                      k=1)[0]
        # 类型不连续重复超过2次
        available = [t for t in HOOK_TYPES if not (t == last_type == second_last_type)]
        if not available:
            available = [t for t in HOOK_TYPES if t != last_type]
        hook_type = random.choices(available, k=1)[0] if available else "悬念"
        hooks.append(HookCard(
            chapter_index=i,
            hook_type=hook_type,
            strength=strength,
            content="",
            connect_chapter=ch + 1 if ch < chapter_count else 0,
        ))
        second_last_type = last_type
        last_type = hook_type
    return hooks


def generate_pleasure_curve(chapter_count: int, density_target: float,
                            is_volume_one: bool = False) -> list[PleasurePointCard]:
    cards = []
    last_type = ""
    for i in range(chapter_count):
        ch = i + 1
        # 每章至少微爽点
        # 每3-5章小爽点(★★★)，每8-10章中爽点(★★★★)
        if ch == chapter_count:
            strength = 5
        elif ch % 8 == 0 or ch % 10 == 0:
            strength = 4
        elif ch % 3 == 0 or ch % 5 == 0:
            strength = 3
        else:
            strength = random.choice([1, 1, 1, 2])  # 大多数微爽点
        available = [t for t in PP_TYPES if t != last_type]
        pp_type = random.choice(available) if available else "打脸"
        cards.append(PleasurePointCard(
            chapter_index=i,
            pp_type=pp_type,
            strength=strength,
            description="",
            word_ratio_target=density_target,
        ))
        last_type = pp_type
    return cards


def validate_hook_matrix(hooks: list[HookCard], chapter_count: int,
                         is_golden_three: bool, strength_min: int) -> list[str]:
    errors = []
    if len(hooks) != chapter_count:
        errors.append(f"钩子数量({len(hooks)}) != 章数({chapter_count})")
        return errors
    for i, h in enumerate(hooks):
        ch = i + 1
        # 黄金三章强度检查
        if is_golden_three and ch <= 3 and h.strength < 4:
            errors.append(f"Ch{ch} 钩子强度 {h.strength} < ★★★★（黄金三章要求）")
        # 普通强度检查
        elif not (is_golden_three and ch <= 3) and h.strength < strength_min:
            errors.append(f"Ch{ch} 钩子强度 {h.strength} < 平台下限 {strength_min}")
        # 卷末检查
        if ch == chapter_count and h.strength < 4:
            errors.append(f"卷末 Ch{ch} 钩子强度 {h.strength} < ★★★★")
    # 连续重复检查
    for i in range(2, len(hooks)):
        if hooks[i].hook_type == hooks[i - 1].hook_type == hooks[i - 2].hook_type:
            errors.append(f"Ch{i-1}-Ch{i+1} 钩子类型连续重复: {hooks[i].hook_type}")
    return errors


def validate_pleasure_curve(curve: list[PleasurePointCard], chapter_count: int) -> list[str]:
    errors = []
    if len(curve) != chapter_count:
        errors.append(f"爽点数量({len(curve)}) != 章数({chapter_count})")
        return errors
    # 类型不连续使用检查
    for i in range(1, len(curve)):
        if curve[i].pp_type == curve[i - 1].pp_type:
            errors.append(f"Ch{i}-Ch{i+1} 爽点类型连续重复: {curve[i].pp_type}")
    # 卷末检查
    if curve[-1].strength < 5:
        errors.append(f"卷末爽点强度 {curve[-1].strength} < ★★★★★")
    return errors


def auto_degrade_hook_matrix(chapter_count: int, strength_min: int = 3) -> list[HookCard]:
    hooks = []
    for i in range(chapter_count):
        ch = i + 1
        strength = 5 if ch == chapter_count else max(3, strength_min)
        hook_type = HOOK_TYPES[i % len(HOOK_TYPES)]
        hooks.append(HookCard(
            chapter_index=i, hook_type=hook_type, strength=strength,
            content="", connect_chapter=ch + 1 if ch < chapter_count else 0,
        ))
    return hooks


def auto_degrade_pleasure_curve(chapter_count: int) -> list[PleasurePointCard]:
    cards = []
    for i in range(chapter_count):
        strength = 5 if i == chapter_count - 1 else (1 if i % 2 == 0 else 2)
        cards.append(PleasurePointCard(
            chapter_index=i,
            pp_type=PP_TYPES[i % len(PP_TYPES)],
            strength=strength,
            description="",
        ))
    return cards


def build_decision_prompt(dashboard: Dashboard, history: list[dict],
                          feedbacks: list[dict], l1_context: str = "",
                          seed_idea: str = "", platform_profile: Optional[PlatformProfile] = None,
                          golden_three: bool = False, hook_stats: dict = None,
                          pleasure_stats: dict = None) -> str:
    """构建决策 prompt（v0.4.0 增强）"""
    lines = [
        "## 当前状态（仪表盘）",
        f"- 阶段：{dashboard.phase}",
        f"- 编排模式：{dashboard.orchestrator_mode or 'auto'}",
        f"- 已完成并确认：{', '.join(dashboard.completed_agents) if dashboard.completed_agents else '无'}",
    ]

    if seed_idea:
        lines.append(f"- 用户创作想法：{seed_idea}")

    if dashboard.pending_confirm:
        lines.append(f"- 待确认：{dashboard.pending_confirm}")

    if dashboard.last_user_feedback:
        lines.append(f"- 用户最新反馈：{dashboard.last_user_feedback}")

    p = dashboard.progress
    if p.total_chapters > 0:
        lines.append(f"- 进度：{p.written}/{p.total_chapters} 已写 | {p.proofread} 已校对 | {p.confirmed} 已确认")
    if p.total_volumes > 1:
        lines.append(f"- 分卷：第 {p.current_volume}/{p.total_volumes} 卷")

    # platform context
    if platform_profile:
        lines.append(f"\n## 平台策略")
        lines.append(f"- 平台：{platform_profile.platform}")
        lines.append(f"- 爽点密度：{platform_profile.pleasure_density}")
        lines.append(f"- 钩子强度下限：{'★' * platform_profile.hook_strength_min}")
        lines.append(f"- 文风要求：{platform_profile.style_requirement}")
        if platform_profile.suppress_tolerance == "零容忍":
            lines.append(f"- ⚠ 开篇零压主：Ch1-3 主角被压制时长 ≤ 15%")

    if golden_three:
        lines.append(f"\n## ⚠ 黄金三章模式已激活（Ch1-3）")
        lines.append(f"- 钩子强度 ≥ ★★★★，Ch3 末 ≥ ★★★★★")
        lines.append(f"- 开场30字冲突，禁止环境描写开头")
        lines.append(f"- 对话占比 ≥ 50%，200字内完成 MC 身份展示")

    if hook_stats:
        lines.append(f"\n## 钩子统计")
        lines.append(f"- 落地率：{hook_stats.get('rate', 0):.1%}")
        lines.append(f"- 类型分布：{hook_stats.get('distribution', '无')}")

    if pleasure_stats:
        lines.append(f"\n## 爽点统计")
        lines.append(f"- 密度：{pleasure_stats.get('density', 0):.1%}（预设 {pleasure_stats.get('target', 0):.1%}）")

    if feedbacks:
        lines.append("\n## 用户反馈记录")
        for fb in feedbacks[-5:]:
            lines.append(f"- [{fb.get('agent', '')}] {fb.get('feedback', '')}")

    if history:
        lines.append("\n## 最近调度历史")
        for h in history[-10:]:
            lines.append(f"- Step {h.get('step', '?')}: {h.get('action', '')} {h.get('agent', '')} ({h.get('reason', '')})")

    if l1_context:
        lines.append("\n## 当前创作状态（L1 摘要）")
        lines.append(l1_context)

    lines.append("\n## 请决定下一步")
    lines.append("返回 { \"action\": \"call_agent\"|\"done\", \"agent\": \"...\", \"instruction\": \"...\", \"reason\": \"...\", \"options\": [{\"action\": \"...\", \"reasoning\": \"...\", \"confidence\": 0.0-1.0}, ...] }")
    lines.append("主决策 (action/agent) 必须与 options 中 confidence 最高的项一致。提供 2-3 个备选。")

    return "\n".join(lines)


def _extract_json_object(text: str) -> str:
    """在文本中找到第一个完整的 JSON 对象（用花括号配对，处理嵌套）"""
    start = text.find('{')
    if start < 0:
        return ""
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        c = text[i]
        if escape:
            escape = False
            continue
        if c == '\\':
            escape = True
            continue
        if c == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return ""


def _parse_decision_response(text: str) -> Optional[OrchestratorDecision]:
    """从 LLM 响应文本中解析决策 JSON（支持嵌套 options 数组）"""
    import re
    text = text.strip()

    # 1. 尝试从 markdown 代码块提取
    md_match = re.search(r'```(?:json)?\s*\n(.*?)\n```', text, re.DOTALL)
    if md_match:
        candidate = md_match.group(1).strip()
        extracted = _extract_json_object(candidate)
        if extracted:
            try:
                data = json.loads(extracted)
                return _build_decision_from_dict(data)
            except json.JSONDecodeError:
                pass

    # 2. 尝试用花括号配对找到完整的 JSON 对象（支持嵌套 options）
    extracted = _extract_json_object(text)
    if extracted:
        try:
            data = json.loads(extracted)
            return _build_decision_from_dict(data)
        except json.JSONDecodeError:
            pass

    # 3. 兜底：尝试正则匹配（处理简单无嵌套的旧格式）
    json_match = re.search(r'\{[^{}]*"action"\s*:\s*"[^"]*"[^{}]*\}', text, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group(0))
            return _build_decision_from_dict(data)
        except json.JSONDecodeError:
            pass

    # 4. 最后尝试：直接 json.loads 整个文本
    try:
        data = json.loads(text)
        return _build_decision_from_dict(data)
    except json.JSONDecodeError:
        pass

    logger.warning("无法从响应中解析决策JSON: %s", text[:200])
    return None


def _build_decision_from_dict(data: dict) -> OrchestratorDecision:
    """从已解析的 dict 构建 OrchestratorDecision，提取 options 备选方案"""
    options_raw = data.get("options", [])
    options: list[dict] = []
    if isinstance(options_raw, list):
        for opt in options_raw:
            if not isinstance(opt, dict):
                continue
            try:
                confidence = float(opt.get("confidence", 0.0))
            except (TypeError, ValueError):
                confidence = 0.0
            # 限制 confidence 范围
            confidence = max(0.0, min(1.0, confidence))
            options.append({
                "action": str(opt.get("action", "")).strip(),
                "reasoning": str(opt.get("reasoning", "")).strip(),
                "confidence": confidence,
            })
    return OrchestratorDecision(
        action=data.get("action", ""),
        agent=data.get("agent", ""),
        instruction=data.get("instruction", ""),
        reason=data.get("reason", ""),
        options=options,
    )


def _normalize_agent(name: str) -> str:
    """将 LLM 可能使用的变体名称映射到规范名称（极度宽容）"""
    name = name.strip().lower().replace(" ", "_").replace("-", "_")
    
    # 关键词匹配（outline 必须在 story 之前检查，避免 "outline" 子串被 story 分支拦截）
    if "outline" in name or "chapter" in name or "章" in name:
        return "outline"
    if "story" in name or "plot" in name or "plan" in name or "topic" in name or "创意" in name:
        return "story"
    if "character" in name or "角色" in name:
        return "character"
    if "world" in name or "世界" in name or "setting" in name:
        return "world"
    if "writer" in name or "draft" in name or "写" in name or "文笔" in name or "create" in name:
        return "writer"
    if "proof" in name or "校对" in name or "edit" in name:
        return "proofreader"
    if "review" in name or "审查" in name or "check" in name:
        return "novel_review"
    
    # 完全不认识的 agent 名 → 默认回退到 story（安全选择）
    logger.warning("无法识别 agent 名称: %s，默认回退到 story", name)
    return "story"


def _validate_decision(
    decision: OrchestratorDecision,
    dashboard: Optional[Dashboard] = None,
    attempted_agents: Optional[set] = None,
) -> Optional[str]:
    """校验决策合法性，返回错误信息或 None"""
    if decision.action not in ("call_agent", "done"):
        return f"无效 action: {decision.action}"

    if decision.action == "call_agent":
        normalized = _normalize_agent(decision.agent)
        valid_agents = {"story", "character", "world", "outline", "writer", "proofreader", "novel_review"}
        if normalized not in valid_agents:
            return f"无效 agent: {decision.agent} (可选: {', '.join(sorted(valid_agents))})"
        decision.agent = normalized

        # v0.5.0 Suggestion Mode: 规范化 options 中的 action 名称（保持一致性）
        if decision.options:
            for opt in decision.options:
                if isinstance(opt, dict) and opt.get("action"):
                    opt["action"] = _normalize_agent(opt["action"])

        # ── 阶段感知守卫 ──
        if dashboard:
            phase = dashboard.phase.lower()
            total_ch = dashboard.progress.total_chapters
            written_ch = dashboard.progress.written
            attempted = attempted_agents or set()

            # 故事已确认时：不禁止 story 重调（用户可能提修改意见），但加提示
            # 选题/策划早期阶段：只允许 story
            if phase in ("", "topic_selection") and not dashboard.completed_agents:
                if decision.agent != "story":
                    return f"选题阶段只能调用 story，当前选择: {decision.agent}"

            # 角色未确认时：禁止调用 world（world 依赖 characters）
            if dashboard:
                if decision.agent == "world" and "character" not in dashboard.completed_agents:
                    return f"角色尚未确认（completed={dashboard.completed_agents}），请先调用 character"

            # 世界观未完成时：
            # - 骨架已确认但细节未完成 → 必须先完成 world 细节再调 outline
            # - 骨架未确认且 world 从未尝试 → 必须先调 world
            if dashboard:
                if decision.agent == "outline" and "world" not in dashboard.completed_agents:
                    if "world_skeleton" in dashboard.completed_agents:
                        # 骨架已确认，但世界细节未完成 — 不能跳到章纲
                        return "世界观大纲已确认，请先调用 world 完成详细展开（不要跳步骤到 outline）"
                    if "world" not in attempted:
                        return f"世界观尚未确认（completed={dashboard.completed_agents}），请先调用 world"
                    # world was attempted but failed → allow outline to break deadlock
                    logger.info("world 已尝试但未确认，允许 outline 继续推进（防止死锁）")

            # 尚无章节：禁止调用 writer / proofreader / novel_review
            if total_ch == 0:
                if decision.agent in ("writer", "proofreader", "novel_review"):
                    return f"尚无章节（total=0），不能调用 {decision.agent}"

            # 世界观细节未完成（骨架已确认）时：禁止调 writer/proofreader/novel_review
            if dashboard and "world_skeleton" in dashboard.completed_agents and "world" not in dashboard.completed_agents:
                if decision.agent in ("writer", "proofreader", "novel_review"):
                    return f"世界观大纲已确认但细节未完成，请先调用 world 完成详细展开才能写章节"

            # 尚未写完任何章节：禁止调用 proofreader（它需要校对已写内容）
            if written_ch == 0 and decision.agent == "proofreader":
                return f"尚无已写章节（written=0），不能调用 proofreader"

    # ── done 阶段守卫：核心阶段未完成时禁止 done ──
    if decision.action == "done" and dashboard:
        essential = ["story", "character", "world", "outline"]
        missing = [a for a in essential if a not in dashboard.completed_agents]
        if missing:
            return f"核心阶段未完成: {', '.join(missing)} 尚未确认，不能结束"

    if not decision.reason:
        return "缺少 reason"

    return None


def decide_next_action(
    dashboard: Dashboard,
    history: list[dict],
    feedbacks: list[dict],
    l1_context: str = "",
    seed_idea: str = "",
    llm: Optional[LLMClient] = None,
    max_retries: int = 2,
    platform_profile: Optional[PlatformProfile] = None,
    golden_three: bool = False,
    hook_stats: Optional[dict] = None,
    pleasure_stats: Optional[dict] = None,
) -> OrchestratorDecision:
    """调用主Agent LLM，获取下一步决策（v0.4.0 增强）"""
    if llm is None:
        llm = create_llm_client()

    # 硬性规则：如果没有任何产出，第一步必须是 story
    if not dashboard.completed_agents and not history:
        return OrchestratorDecision(
            action="call_agent",
            agent="story",
            instruction=seed_idea or "开始故事创作流程",
            reason="初始阶段，必须从 story 开始",
        )

    # 硬性规则：选题阶段未完成 → 强制 story（防止 done 绕过守卫后的无限循环）
    if dashboard.phase == "topic_selection" and "story" not in dashboard.completed_agents:
        return OrchestratorDecision(
            action="call_agent",
            agent="story",
            instruction=seed_idea or "根据已选选题生成一句话核心",
            reason="选题阶段未完成，必须调用 story 确认",
        )

    # 硬性规则：writing_chapters 阶段 + 0 已写章节 → 强制 writer
    if (dashboard.phase == "writing_chapters"
            and dashboard.progress.written == 0
            and dashboard.progress.total_chapters > 0):
        return OrchestratorDecision(
            action="call_agent",
            agent="writer",
            instruction="开始撰写第1章正文",
            reason="章纲已确认，进入逐章写作阶段",
        )

    # ── 防循环守卫：防止 LLM 反复调同一 agent 而不推进 ──
    attempted_agents: set[str] = set()
    if dashboard and history:
        all_history_agents = [h.get("agent", "") for h in history if h.get("agent")]
        attempted_agents = set(a for a in all_history_agents if a)
        recent_agents = [h.get("agent", "") for h in history[-6:] if h.get("agent")]
        recent_story_count = recent_agents.count("story")
        logger.info(
            "防循环检查: completed=%s recent=%s story_count=%d history_len=%d",
            dashboard.completed_agents, recent_agents[-6:],
            recent_story_count, len(history),
        )

        # 故事已确认 + 角色未确认 + 最近 6 次有 2+ 故事调用 → 强制角色
        if ("story" in dashboard.completed_agents
                and "character" not in dashboard.completed_agents
                and recent_story_count >= 2):
            return OrchestratorDecision(
                action="call_agent",
                agent="character",
                instruction="根据已确认的故事核心设计角色",
                reason="故事已确认，下一步必须创建角色",
            )

        # 角色+世界观已确认 + 大纲未确认 + 最近 6 次全是 story/world → 强制大纲
        if ("character" in dashboard.completed_agents
                and "world" in dashboard.completed_agents
                and "outline" not in dashboard.completed_agents
                and all(a in ("story", "world", "") for a in recent_agents)):
            return OrchestratorDecision(
                action="call_agent",
                agent="outline",
                instruction="根据已确认的故事、角色、世界观生成章纲",
                reason="策划阶段基本完成，需要章纲才能推进写作",
            )

        # ★ 新增：角色已确认 + story 连续调用 ≥4 次 → 强制推进
        # 覆盖 world 失败 / 未确认导致的死循环（world attempted but failed）
        if ("character" in dashboard.completed_agents
                and "outline" not in dashboard.completed_agents
                and recent_story_count >= 4):
            if "world" in attempted_agents:
                # world 被尝试过但未确认 → 跳过 world 直接 outline
                return OrchestratorDecision(
                    action="call_agent",
                    agent="outline",
                    instruction="世界观生成遇到问题，直接基于故事和角色生成章纲",
                    reason="story 反复调用，world 已尝试但未确认，强制推进到 outline",
                )
            else:
                # world 从未尝试 → 先尝试 world
                return OrchestratorDecision(
                    action="call_agent",
                    agent="world",
                    instruction="根据已确认的故事和角色构建世界观",
                    reason="story 重复调用过多，必须先完成 world",
                )

        # ★ 新增：通用死循环检测 — 同一 agent 连续调用 4+ 次 → 强制推进
        if len(recent_agents) >= 4 and len(set(recent_agents[-4:])) == 1:
            stuck_agent = recent_agents[-1]
            if stuck_agent == "story":
                next_agents = ["character", "world", "outline", "writer"]
                for na in next_agents:
                    if na not in dashboard.completed_agents:
                        instructions = {
                            "character": "根据已确认的故事设计角色",
                            "world": "根据已确认的故事和角色构建世界观",
                            "outline": "根据已确认的故事、角色、世界观生成章纲",
                            "writer": "开始撰写第一章正文",
                        }
                        return OrchestratorDecision(
                            action="call_agent",
                            agent=na,
                            instruction=instructions.get(na, ""),
                            reason=f"{stuck_agent} 反复调用 4+ 次，强制推进到 {na}",
                        )
            elif stuck_agent == "world":
                if "world" in attempted_agents and "outline" not in dashboard.completed_agents:
                    return OrchestratorDecision(
                        action="call_agent",
                        agent="outline",
                        instruction="世界观生成遇到技术问题，直接基于故事和角色生成章纲",
                        reason="world 反复调用 4+ 次均失败，跳过 world 推进到 outline",
                    )
            elif stuck_agent in ("writer", "proofreader"):
                # writer/proofreader 反复超时 → 保持当前章节标记为 draft，推进
                if stuck_agent == "writer":
                    return OrchestratorDecision(
                        action="call_agent",
                        agent="proofreader",
                        instruction="对已生成的初稿进行校对",
                        reason="writer 反复超时 4+ 次，保留现有初稿推进到 proofreader",
                    )

    prompt = build_decision_prompt(
        dashboard, history, feedbacks, l1_context, seed_idea,
        platform_profile=platform_profile,
        golden_three=golden_three,
        hook_stats=hook_stats,
        pleasure_stats=pleasure_stats,
    )

    last_error = ""
    for attempt in range(max_retries):
        try:
            text = llm.complete(prompt, temperature=0.3, max_tokens=4096, timeout=60, max_retries=1)
            parsed = _parse_decision_response(text)
            if parsed is None:
                last_error = "JSON 解析失败"
                prompt += "\n\n[系统提示：请只返回JSON，格式: {\"action\":\"call_agent\",\"agent\":\"...\",\"instruction\":\"...\",\"reason\":\"...\"}]"
                continue

            decision = OrchestratorDecision(
                action=parsed.action,
                agent=parsed.agent or "",
                instruction=parsed.instruction or "",
                reason=parsed.reason or "",
                options=parsed.options or [],
            )

            # v0.5.0 Suggestion Mode: 若 LLM 提供了 options，确保主决策与最高置信度一致
            if decision.options:
                best = max(decision.options, key=lambda o: o.get("confidence", 0.0))
                if best.get("action") and best["action"] != decision.agent:
                    logger.info(
                        "主决策与最高置信度选项不一致，自动修正: %s → %s (confidence=%.2f)",
                        decision.agent, best["action"], best.get("confidence", 0.0),
                    )
                    decision.agent = best["action"]

            error = _validate_decision(decision, dashboard, attempted_agents)
            if error:
                logger.warning("决策校验失败 (attempt %d/%d): %s", attempt + 1, max_retries, error)
                last_error = error
                if "agent" in error and attempt == 0:
                    normalized = _normalize_agent(decision.agent)
                    if normalized in {"story", "character", "world", "outline", "writer", "proofreader", "novel_review"}:
                        decision.agent = normalized
                        logger.info("agent 名称已自动修正: %s", normalized)
                        break
                if attempt >= max_retries - 1:
                    break
                hint = f"\n\n[系统提示：上次失败 - {error}]"
                hint += " agent字段只能用: story, character, world, outline, writer, proofreader, novel_review"
                prompt += hint
                continue

            return decision

        except Exception as e:
            logger.warning("决策LLM调用失败 (attempt %d/%d): %s", attempt + 1, max_retries, e)
            last_error = str(e)

    logger.error("主Agent决策全部重试失败: %s", last_error)
    return OrchestratorDecision(
        action="call_agent",
        agent="story",
        instruction="",
        reason=f"决策失败（{last_error}），默认回到故事编辑",
    )
