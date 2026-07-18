"""
文笔 Agent

按章写初稿。接收章纲 + 故事/角色/世界观上下文，调用 LLM 生成正文。

v0.4.1: 分步生成模式（Plan → Write Segments → Assemble）
  将单次大 prompt 拆为 2-3 个小 prompt，每步输出 < 1800 字，
  保证单次 LLM 调用在网关 100s 硬超时内完成。
  失败时自动降级到单次调用模式。

v0.5.0: Speed optimization
  - All timeouts aligned to 90s (well under gateway 100s limit)
  - max_retries=1 for transient failure resilience
  - Concurrent segment writing: odd/even segments can overlap
    (even segments use only segment description without prev_end)
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from ..state.state_types import GraphState
from ..state.state_types import DraftContent
from ..utils.llm import LLMClient, create_llm_client
from .prompts import (
    build_writer_prompt,
    build_step_plan_prompt,
    build_step_segment_prompt,
    build_step_assemble_prompt,
)
from .response_models import ChapterDraftContent, ContentPlan

logger = logging.getLogger("writesync")


# ──────────────────────────────────────────────
# 入口：分步优先，单次兜底
# ──────────────────────────────────────────────

def run_writer_agent(
    state: GraphState,
    chapter_number: int,
    llm: Optional[LLMClient] = None,
) -> dict:
    """按章写初稿。优先分步生成，失败降级单次调用。"""
    try:
        return _run_writer_step_by_step(state, chapter_number, llm)
    except Exception as e:
        logger.warning(
            f"Step-by-step writer failed for ch {chapter_number}: {e}. "
            f"Falling back to single-call mode."
        )
        return _run_writer_single_call(state, chapter_number, llm)


# ──────────────────────────────────────────────
# 分步生成模式
# ──────────────────────────────────────────────

def _run_writer_step_by_step(
    state: GraphState,
    chapter_number: int,
    llm: Optional[LLMClient] = None,
) -> dict:
    """
    分步生成：Plan → Write Segments → Assemble

    每步 prompt 远小于原始单次 prompt，单次 LLM 调用在 30-90s
    内完成，远低于网关 100s 硬超时。
    """
    data = state["data"]
    if data.chapter_outline is None:
        raise ValueError("chapter_outline 为空，请先运行章纲 Agent")

    chapter = None
    for ch in data.chapter_outline.chapters:
        if ch.chapter_number == chapter_number:
            chapter = ch
            break
    if chapter is None:
        raise ValueError(f"章纲中未找到第 {chapter_number} 章")

    if llm is None:
        llm = create_llm_client()

    # ── 构建上下文 ──
    story_ctx = _format_story_context(data.story)
    char_ctx = _format_character_context(data.characters)
    world_ctx = _format_world_context(data.world)
    chapter_text = _format_chapter(chapter)

    enhanced_instruction = state.get("pending_feedback") or ""
    prompt_override = state.get("_prompt_system_override")

    from .context import build_writing_context
    ctx_text = build_writing_context(state, chapter_num=chapter_number)

    extra_ctx_parts = []
    if ctx_text:
        extra_ctx_parts.append(f"## 写作上下文\n\n{ctx_text}")

    # Phase 3: Inject ContinuityEnvelope + FactLedger context
    phase3_ctx = _build_phase3_context(data, chapter_number)
    if phase3_ctx:
        extra_ctx_parts.append(f"## 上章衔接与事实\n\n{phase3_ctx}")
    if enhanced_instruction:
        extra_ctx_parts.append(f"## 增强指令\n\n{enhanced_instruction}")
    extra_ctx = "\n\n".join(extra_ctx_parts)

    # ── Step 1: 生成分段计划 ──
    plan_prompt = build_step_plan_prompt(
        chapter_text, story_ctx, char_ctx, world_ctx,
        extra_context=f"\n\n---\n\n{extra_ctx}" if extra_ctx else "",
        system_prompt=prompt_override,
    )
    plan: ContentPlan = llm.complete_structured(
        plan_prompt, output_class=ContentPlan,
        temperature=0.7, max_tokens=2048, timeout=90, max_retries=1,
    )
    logger.info(
        f"Writer plan for ch {chapter_number}: {plan.total_segments} segments, "
        f"climax at [{plan.climax_position}]"
    )

    # ── Step 2: 并发段落写作（v0.5.0 speed optimization） ──
    # 奇数段和偶数段可以并发写：偶数段不使用 prev_end，仅靠 segment description 保持连贯。
    # 收到结果后再按顺序排列，assemble 步骤负责最终衔接。
    def _write_segment(i: int, seg, prev_segment_end: str = "") -> tuple[int, str]:
        """写单个段落（线程安全，供并发调用）。"""
        seg_desc = f"分段 {seg.segment_id}：{seg.summary}"
        if seg.key_beats:
            seg_desc += f"\n关键节拍：{' → '.join(seg.key_beats)}"
        if seg.hook_connect:
            seg_desc += f"\n衔接说明：{seg.hook_connect}"

        seg_extra = f"开篇策略：{plan.opening_strategy}\n高潮段：{plan.climax_position}"
        if extra_ctx:
            seg_extra += f"\n\n{extra_ctx}"

        seg_prompt = build_step_segment_prompt(
            seg_desc, i, plan.total_segments,
            chapter_text, story_ctx, char_ctx, world_ctx,
            prev_segment_end=prev_segment_end,
            extra_context=f"\n\n---\n\n{seg_extra}",
            system_prompt=prompt_override,
        )
        text = llm.complete(
            seg_prompt, temperature=0.8, max_tokens=4096,
            timeout=90, max_retries=1,
        )
        return i, text

    segments: list[str] = [""] * len(plan.segments)
    prev_end = ""

    if len(plan.segments) <= 2:
        # 少于3段直接顺序写，无需并发开销
        for i, seg in enumerate(plan.segments, start=1):
            _, text = _write_segment(i, seg, prev_end)
            segments[i - 1] = text
            prev_end = text
            logger.info(f"Writer segment {i}/{plan.total_segments} for ch {chapter_number}: {len(text)} chars")
    else:
        # 3+段：第1段顺序写（建立基调），后续段2-3并发，每轮收完再发下一轮
        # Round 1: 第1段顺序
        first_i, first_text = _write_segment(1, plan.segments[0], "")
        segments[0] = first_text
        prev_end = first_text
        logger.info(f"Writer segment 1/{plan.total_segments} for ch {chapter_number}: {len(first_text)} chars")

        # Round 2+: 每轮并发写 2 段（用 prev_end 作参考）
        remaining = list(enumerate(plan.segments[1:], start=2))
        CHUNK = 2
        for chunk_start in range(0, len(remaining), CHUNK):
            chunk = remaining[chunk_start:chunk_start + CHUNK]
            with ThreadPoolExecutor(max_workers=min(CHUNK, len(chunk))) as pool:
                futures = {
                    pool.submit(_write_segment, idx, seg, prev_end): idx
                    for idx, seg in chunk
                }
                for future in as_completed(futures):
                    idx, text = future.result()
                    segments[idx - 1] = text
                    logger.info(f"Writer segment {idx}/{plan.total_segments} for ch {chapter_number}: {len(text)} chars")
            # 用最后完成的段落文本作为下一轮 prev_end
            # 按原始顺序取最后一个非空段
            for idx, _ in reversed(chunk):
                if segments[idx - 1]:
                    prev_end = segments[idx - 1]
                    break

    # ── Step 3: 合并组装 ──
    assemble_prompt = build_step_assemble_prompt(
        segments, chapter_text, story_ctx,
        system_prompt=prompt_override,
    )
    final_text = llm.complete(
        assemble_prompt, temperature=0.5, max_tokens=8192,
        timeout=90, max_retries=1,
    )
    logger.info(f"Writer assembled ch {chapter_number}: {len(final_text)} chars")

    # ── 更新草稿 ──
    _update_drafts(data, chapter_number, final_text, state)
    return {"data": data, "messages": state.get("messages", [])}


# ──────────────────────────────────────────────
# 单次调用模式（降级兜底）
# ──────────────────────────────────────────────

def _run_writer_single_call(
    state: GraphState,
    chapter_number: int,
    llm: Optional[LLMClient] = None,
) -> dict:
    """原始单次调用模式：一次性输入全部上下文，一次性输出全文。"""
    data = state["data"]
    if data.chapter_outline is None:
        raise ValueError("chapter_outline 为空，请先运行章纲 Agent")

    chapter = None
    for ch in data.chapter_outline.chapters:
        if ch.chapter_number == chapter_number:
            chapter = ch
            break
    if chapter is None:
        raise ValueError(f"章纲中未找到第 {chapter_number} 章")

    story_ctx = _format_story_context(data.story)
    char_ctx = _format_character_context(data.characters)
    world_ctx = _format_world_context(data.world)
    chapter_text = _format_chapter(chapter)

    feedback = state.get("pending_feedback") or ""
    prompt_override = state.get("_prompt_system_override")

    prompt = build_writer_prompt(
        chapter_text, story_ctx, char_ctx, world_ctx, user_feedback=feedback,
        system_prompt=prompt_override,
    )

    from .context import build_writing_context
    ctx_text = build_writing_context(state, chapter_num=chapter_number)

    # Phase 3: Inject ContinuityEnvelope + FactLedger
    phase3_ctx = _build_phase3_context(data, chapter_number)
    ctx_parts = []
    if ctx_text:
        ctx_parts.append(ctx_text)
    if phase3_ctx:
        ctx_parts.append(f"## 上章衔接与事实\n\n{phase3_ctx}")

    if ctx_parts:
        full_ctx = "\n\n---\n\n".join(ctx_parts)
        prompt = (
            "# 写作上下文（以下信息基于已完成章节提取，请严格遵循）\n\n"
            + full_ctx + "\n\n---\n\n# 本章写作指令\n\n" + prompt
        )

    if llm is None:
        llm = create_llm_client()

    try:
        response: ChapterDraftContent = llm.complete_structured(
            prompt, output_class=ChapterDraftContent, temperature=0.8,
            max_tokens=16384, timeout=90, max_retries=1,
        )
    except Exception:
        text = llm.complete(prompt, temperature=0.8, max_tokens=16384, timeout=90, max_retries=1)
        wc = len(text.replace(" ", ""))
        response = ChapterDraftContent(content=text, word_count=wc)

    _update_drafts(data, chapter_number, response.content, state)
    return {"data": data, "messages": state.get("messages", [])}


# ──────────────────────────────────────────────
# 共享辅助：更新草稿状态
# ──────────────────────────────────────────────

def _update_drafts(data, chapter_number: int, content: str, state: GraphState) -> None:
    """将生成的正文写入 data.drafts"""
    drafts = data.drafts
    if chapter_number not in drafts.chapters:
        from ..state.state_types import ChapterDraft as CD
        drafts.chapters[chapter_number] = CD(chapter_number=chapter_number)

    cd = drafts.chapters[chapter_number]
    from datetime import datetime
    now = datetime.now().isoformat()
    wc = len(content.replace(" ", ""))
    cd.draft = DraftContent(
        content=content,
        agent="文笔Agent",
        timestamp=now,
    )
    cd.stage = "draft"
    cd.word_count = wc
    cd.written_at = cd.written_at or now
    cd.updated_at = now
    data.drafts.current_writing = chapter_number

    messages = state.get("messages", [])
    messages.append({
        "role": "assistant",
        "content": f"第 {chapter_number} 章初稿完成（{wc} 字）",
    })
    state["messages"] = messages


# ──────────────────────────────────────────────
# 上下文格式化工具
# ──────────────────────────────────────────────

def _format_story_context(story) -> str:
    if story is None:
        return "待定义"
    s1, s2 = story.step1, story.step2
    return f"""一句话：{s1.one_sentence}
类型标签：{s1.tag}
1. {s2.setup}
2. {s2.inciting}
3. {s2.rising}
4. {s2.climax_prep}
5. {s2.resolution}
主题：{s2.theme}"""


def _format_character_context(characters) -> str:
    if characters is None:
        return "待定义"
    lines = []
    for c in characters.characters:
        lines.append(f"- {c.name}（{c.role}）：{c.goal} | {c.personality}")
    return "\n".join(lines)


def _format_world_context(world) -> str:
    if world is None:
        return "待定义"
    ps = world.power_system
    return f"""力量体系：{ps.system_name}
修炼规则：{ps.cultivation_rules}"""


def _build_phase3_context(data, chapter_num: int) -> str:
    """Phase 3: Build ContinuityEnvelope + FactLedger context for writer prompt.

    Reads from DynamicContext.continuity_envelope and facts fields.
    Falls back gracefully if no Phase 3 data exists yet.
    """
    import logging
    log = logging.getLogger("writesync")
    parts = []

    try:
        ctx = getattr(data, "dynamic_context", None)
        if not ctx:
            return ""

        # 1. Continuity Envelope (handoff from previous chapter)
        envelope = getattr(ctx, "continuity_envelope", None)
        if envelope and isinstance(envelope, dict):
            handoff = envelope.get("handoff", "")
            protected = envelope.get("protected", "")
            plan_delta = envelope.get("plan_delta", "")

            if handoff:
                parts.append(f"### 上章末状态\n{handoff}")

            if protected:
                parts.append(
                    f"### ⚠ 必须严格保持的事实\n{protected}\n"
                    f"> 硬约束：在正文前40%必须逐项落实以上 #PROTECTED 块中的事实。"
                )

            if plan_delta:
                parts.append(f"### 章纲偏差\n{plan_delta}")

        # 2. Active Facts from Fact Ledger
        facts = getattr(ctx, "facts", None)
        if facts and isinstance(facts, list) and len(facts) > 0:
            # Only show confirmed facts valid up to this chapter
            active = [
                f for f in facts
                if f.get("status") == "confirmed"
                and f.get("valid_from_ch", 0) <= chapter_num
                and (f.get("valid_to_ch") is None or f.get("valid_to_ch", 0) > chapter_num)
            ]
            if active:
                cat_labels = {"character": "角色", "plot": "情节", "world": "世界", "item": "物品"}
                fact_lines = []
                for f in active[:15]:  # limit to 15 facts
                    cat = cat_labels.get(f.get("category", ""), f.get("category", "?"))
                    fact_lines.append(
                        f"- [{cat}] Ch{f.get('source_chapter', '?')}: {f.get('content', '?')}"
                    )
                parts.append(f"### 已确认事实（共{len(active)}条）\n" + "\n".join(fact_lines))
    except Exception as e:
        log.debug("[phase3_ctx] build failed: %s", e)

    return "\n\n".join(parts) if parts else ""


def _format_chapter(chapter) -> str:
    scenes_text = ""
    if chapter.scenes:
        scenes_text = "\n场景：\n" + "\n".join(
            f"  - {s.scene_id}: {s.location} | {s.purpose} | {s.conflict}"
            for s in chapter.scenes
        )
    return f"""## 第{chapter.chapter_number}章：{chapter.chapter_title}
核心事件：{chapter.core_event}
人物状态：{chapter.character_states}
故事推进：{chapter.story_progression}
POV：{chapter.pov}
节奏：{chapter.pace}
结尾钩子：{chapter.hook_at_end or '（无）'}
预估字数：{chapter.estimated_word_count}{scenes_text}"""
