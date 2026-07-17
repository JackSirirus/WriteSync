"""
WriteSync 动态上下文构建器

从 state 累积知识中提取精简摘要（≤800字），注入写作Agent prompt。
每次策划确认/章节终稿后更新 DynamicContext 并持久化到磁盘。
"""

import os
import json
import time
import logging
from pathlib import Path
from typing import Optional
from datetime import datetime

from ..state.state_types import (
    WriteSyncState, DynamicContext, StoryState, CharactersState,
    WorldState, ChapterOutlineState, DraftsState,
)

logger = logging.getLogger("writesync")

_PROJECT_ROOT = Path(__file__).parent.parent.parent


def update_dynamic_context(state: dict, ch_num: int = 0, skip_llm: bool = False) -> DynamicContext:
    """从当前 state 提取最新信息，更新 DynamicContext。ch_num=0=策划阶段，N=第N章终稿确认。"""
    t0 = time.time()
    data = state.get("data") if isinstance(state, dict) else state
    if not isinstance(data, WriteSyncState):
        logger.warning("[context.update] invalid state type: %s", type(data))
        return DynamicContext()

    ctx = data.dynamic_context or DynamicContext()

    try:
        # ① 角色快照 — ch_num>0 时用 LLM 提取正文中的角色变化
        if ch_num > 0 and data.drafts and data.characters and not skip_llm:
            cd = data.drafts.chapters.get(ch_num)
            if cd and cd.final and cd.final.content:
                changes = _extract_character_changes(
                    cd.final.content, data.characters.characters
                )
                if changes:
                    lines = _build_character_snapshot(data.characters.characters, changes, ch_num)
                    ctx.character_snapshot = "；".join(lines)[:300]
                elif data.characters and data.characters.characters:
                    lines = []
                    for c in data.characters.characters:
                        arc = _guess_arc_progress(
                            c, ch_num,
                            data.chapter_outline.total_chapters if data.chapter_outline else 0
                        )
                        lines.append(f"{c.name}({c.role})：{c.personality}，{c.goal}。弧线进度{arc}")
                    ctx.character_snapshot = "；".join(lines)[:300]
            else:
                if data.characters and data.characters.characters:
                    lines = []
                    for c in data.characters.characters:
                        arc = _guess_arc_progress(c, ch_num, data.chapter_outline.total_chapters if data.chapter_outline else 0)
                        lines.append(f"{c.name}({c.role})：{c.personality}，{c.goal}。弧线进度{arc}")
                    ctx.character_snapshot = "；".join(lines)[:300]
        elif ch_num > 0 and data.characters and data.characters.characters:
            lines = []
            for c in data.characters.characters:
                arc = _guess_arc_progress(
                    c, ch_num,
                    data.chapter_outline.total_chapters if data.chapter_outline else 0
                )
                lines.append(f"{c.name}({c.role})：{c.personality}，{c.goal}。弧线进度{arc}")
            ctx.character_snapshot = "；".join(lines)[:300]
        elif data.characters and data.characters.characters:
            lines = []
            for c in data.characters.characters:
                arc = _guess_arc_progress(
                    c, ch_num,
                    data.chapter_outline.total_chapters if data.chapter_outline else 0
                )
                lines.append(f"{c.name}({c.role})：{c.personality}，{c.goal}。弧线进度{arc}")
            ctx.character_snapshot = "；".join(lines)[:300]
    except Exception:
        pass  # character_snapshot 保持上版值

    try:
        # ② 世界格局
        if data.world:
            w = data.world
            parts = [f"力量体系：{w.power_system.system_name}"]
            if w.power_system.tiers:
                parts.append(f"等级：{'→'.join(w.power_system.tiers)}")
            if w.society.factions:
                names = [f.get('name', '?') for f in w.society.factions[:5]]
                parts.append(f"势力：{'、'.join(names)}")
            if w.geography.major_locations:
                locs = [l.get('name', '?') for l in w.geography.major_locations[:5]]
                parts.append(f"主要地点：{'、'.join(locs)}")
            ctx.world_changes = "；".join(parts)[:100]
    except Exception:
        pass

    try:
        # ②b 一致性检测 — ch_num>0 时用 LLM 检测矛盾
        if ch_num > 0 and data.drafts and not skip_llm:
            cd = data.drafts.chapters.get(ch_num)
            if cd and cd.final and cd.final.content:
                contradictions = _extract_contradictions(cd.final.content, ctx)
                if contradictions:
                    issues = [c.issue for c in contradictions]
                    ctx.world_consistency_notes = "；".join(issues)[:100]
    except Exception:
        pass

    try:
        # ③ 前章摘要（ch_num > 0 时取最近 3 章）
        if ch_num > 0 and data.chapter_outline and data.drafts and data.drafts.chapters:
            recent = _get_recent_chapters(data, ch_num, n=3)
            ctx.recent_chapters_summary = " | ".join(recent)[:200]
    except Exception:
        pass

    try:
        # ④ 伏笔追踪
        if data.chapter_outline and data.chapter_outline.chapters:
            ctx.unresolved_foreshadows = _scan_foreshadows(data, ch_num)
            ctx.resolved_foreshadows = _scan_resolved(data, ch_num)
            ctx.foreshadow_deadline = _deadline_foreshadows(data, ch_num)
            # 数据上限裁剪
            if len(ctx.unresolved_foreshadows) > 30:
                ctx.unresolved_foreshadows = ctx.unresolved_foreshadows[-30:]
            if len(ctx.resolved_foreshadows) > 30:
                ctx.resolved_foreshadows = ctx.resolved_foreshadows[-30:]
    except Exception:
        pass

    try:
        # ⑤ 节奏统计
        ctx.chapter_word_counts = _gather_word_counts(data)
        if len(ctx.chapter_word_counts) > 50:
            ctx.chapter_word_counts = dict(
                sorted(ctx.chapter_word_counts.items())[-50:]
            )
        ctx.pacing_state = _assess_pacing(data, ch_num)[:80]
    except Exception:
        pass

    try:
        # ⑥ 全书进度
        if data.chapter_outline:
            total = data.chapter_outline.total_chapters
            written = len(data.chapter_outline.written_chapters or [])
            pct = written * 100 // total if total else 0
            ctx.plot_progress = f"{written}/{total}章，进度{pct}%"
            ctx.story_beats_remaining = max(0, total - written)
    except Exception:
        pass

    try:
        # ⑦ Continuity Envelope — 章节交接（Phase 3）
        if ch_num > 0 and data.drafts and data.drafts.chapters:
            ctx.continuity_envelope = _build_continuity_envelope(data, ch_num)
    except Exception:
        pass

    ctx.updated_chapter = ch_num
    ctx.updated_at = datetime.now().isoformat()

    elapsed = (time.time() - t0) * 1000
    logger.info(
        "[context.update] ch=%d snapshot_len=%d recent_len=%d "
        "foreshadows_unresolved=%d consistency_len=%d elapsed=%.0fms",
        ch_num, len(ctx.character_snapshot), len(ctx.recent_chapters_summary),
        len(ctx.unresolved_foreshadows), len(ctx.world_consistency_notes), elapsed
    )
    return ctx


def build_writing_context(state: dict, chapter_num: int = 0) -> str:
    """从 DynamicContext 拼装上下文摘要，注入 Agent prompt。

    Phase 3 upgrade: Uses B0-B3 budget layering with ContextBudget when
    chapter_num > 0 and a FactLedger is available. Falls back to the
    original flat ≤800-char approach for planning-phase calls.
    """
    t0 = time.time()
    data = state.get("data") if isinstance(state, dict) else state
    ctx = getattr(data, "dynamic_context", None) if hasattr(data, "dynamic_context") else None
    if not ctx:
        return ""

    # Phase 3: Try B0-B3 budget system when we have a chapter context
    if chapter_num > 0:
        try:
            return _build_budget_context(state, chapter_num)
        except Exception:
            logger.debug("[context.build] budget failed, falling back to flat")

    # ── Fallback: original flat ≤800-char assembly ──
    parts = []
    remaining = 800

    # 优先1: 角色快照 (≤300)
    if ctx.character_snapshot:
        snap = ctx.character_snapshot[:min(300, remaining)]
        parts.append(f"## 当前角色状态\n{snap}")
        remaining -= len(snap) + 20

    # 优先2: 前章回顾 (≤200)
    if remaining > 30 and ctx.recent_chapters_summary:
        recent = ctx.recent_chapters_summary[:min(200, remaining)]
        parts.append(f"## 前章回顾\n{recent}")
        remaining -= len(recent) + 20

    # Phase 3: Continuity Envelope — 上章交接状态 (≤150)
    if remaining > 30 and ctx.continuity_envelope:
        env = ctx.continuity_envelope
        env_lines = []
        if env.get("handoff"):
            env_lines.append(f"[上章结束状态] {env['handoff']}")
        if env.get("protected"):
            env_lines.append(f"[保护元素·不可变更] {env['protected']}")
        if env.get("plan_delta"):
            env_lines.append(f"[本章计划调整] {env['plan_delta']}")
        if env_lines:
            env_text = "\n".join(env_lines)[:min(150, remaining)]
            parts.append(f"## 章节交接\n{env_text}")
            remaining -= len(env_text) + 20

    # 优先3: 伏笔 (≤100)
    if remaining > 30 and ctx.unresolved_foreshadows:
        items = "\n".join(f"- {f}" for f in ctx.unresolved_foreshadows[:5])
        fores = items[:min(100, remaining)]
        parts.append(f"## 未收伏笔\n{fores}")
        remaining -= len(fores) + 20

    # 优先4: 待处理提醒
    if remaining > 20 and ctx.foreshadow_deadline:
        items = "\n".join(f"- Ch{k}: {v}" for k, v in list(ctx.foreshadow_deadline.items())[:3])
        deadline = items[:min(80, remaining)]
        parts.append(f"## 待处理提醒\n{deadline}")
        remaining -= len(deadline) + 20

    # 优先5: 一致性注意 (≤100)
    if remaining > 20 and ctx.world_consistency_notes:
        notes = ctx.world_consistency_notes[:min(100, remaining)]
        parts.append(f"## 一致性注意\n{notes}")
        remaining -= len(notes) + 20

    # 优先6: 节奏状态
    if remaining > 20 and ctx.pacing_state:
        pace = ctx.pacing_state[:min(80, remaining)]
        parts.append(f"## 节奏状态\n{pace}")

    result = "\n\n".join(parts)
    elapsed = (time.time() - t0) * 1000
    logger.debug("[context.build] output_len=%d elapsed=%.1fms (flat)", len(result), elapsed)
    return result


def _build_budget_context(state: dict, chapter_num: int) -> str:
    """Build context using B0-B3 ContextBudget with FactLedger."""
    try:
        from .fact_ledger import ContextBudget, FactLedger
    except ImportError:
        raise

    # We need workspace to get FactLedger; check for it in state extras
    ws = state.get("_workspace") if isinstance(state, dict) else None
    if ws is None:
        if isinstance(state, dict):
            ws = state.get("_ws")
    if ws is None:
        raise ValueError("workspace not available in state for budget context")

    ledger = FactLedger(ws)
    budget = ContextBudget()
    return budget.assemble(state, chapter_num, ledger)


def persist_context(data: WriteSyncState) -> None:
    """将 DynamicContext 写入磁盘（projects/ + docs/dynamic/ 双份）。"""
    t0 = time.time()
    if not data.metadata or not data.metadata.project_id:
        return
    ctx = data.dynamic_context
    if ctx is None:
        return

    project_dir = _PROJECT_ROOT / "projects" / data.metadata.project_id
    dyn_dir = _PROJECT_ROOT / "docs" / "dynamic"
    project_dir.mkdir(parents=True, exist_ok=True)
    dyn_dir.mkdir(parents=True, exist_ok=True)

    raw = {
        "character_snapshot": ctx.character_snapshot,
        "recent_chapters_summary": ctx.recent_chapters_summary,
        "unresolved_foreshadows": ctx.unresolved_foreshadows,
        "resolved_foreshadows": ctx.resolved_foreshadows,
        "foreshadow_deadline": {str(k): v for k, v in ctx.foreshadow_deadline.items()},
        "world_changes": ctx.world_changes,
        "world_consistency_notes": ctx.world_consistency_notes,
        "pacing_state": ctx.pacing_state,
        "chapter_word_counts": {str(k): v for k, v in ctx.chapter_word_counts.items()},
        "plot_progress": ctx.plot_progress,
        "story_beats_remaining": ctx.story_beats_remaining,
        "updated_at": ctx.updated_at,
        "updated_chapter": ctx.updated_chapter,
        "facts": ctx.facts,
        "continuity_envelope": ctx.continuity_envelope,
    }

    try:
        # 原子写入: tmp → rename
        tmp_path = project_dir / "context.tmp.json"
        target_path = project_dir / "context.json"
        tmp_path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        os.replace(str(tmp_path), str(target_path))
    except OSError as e:
        logger.error("[context.persist] project write failed: %s", e)
        return

    try:
        (dyn_dir / "context.json").write_text(
            json.dumps(raw, ensure_ascii=False), encoding="utf-8"
        )
    except OSError as e:
        logger.warning("[context.persist] docs write failed: %s", e)

    elapsed = (time.time() - t0) * 1000
    logger.debug("[context.persist] elapsed=%.1fms", elapsed)


def _inject(prompt: str, ctx_text: str) -> str:
    """将上下文注入到 prompt 前面。ctx_text 为空时返回原 prompt。"""
    if not ctx_text:
        return prompt
    return (
        "# 写作上下文（以下信息基于已完成章节提取，请严格遵循）\n\n"
        + ctx_text
        + "\n\n---\n\n"
        + "# 本章写作指令\n\n"
        + prompt
    )


def _guess_arc_progress(character, ch_num: int, total_chapters: int) -> str:
    """基于章节进度估算角色弧线完成度。"""
    if total_chapters == 0 or ch_num == 0:
        return "0%"
    progress = ch_num / total_chapters
    role = getattr(character, "role", "")
    if role == "主角":
        pass
    elif role == "反派":
        progress *= 1.1
    elif role == "导师":
        progress = progress * 0.8 + 0.1
    else:
        progress *= 0.9
    return f"{min(int(progress * 100), 99)}%"


def _get_recent_chapters(data: WriteSyncState, ch_num: int, n: int = 3) -> list[str]:
    """取最近 n 章摘要。"""
    if not data.chapter_outline or not data.chapter_outline.chapters:
        return []
    chapters = data.chapter_outline.chapters
    start = max(0, ch_num - n)
    end = ch_num
    result = []
    for ch in chapters[start:end]:
        if ch.chapter_number <= ch_num:
            hook = ch.hook_at_end[:30] if ch.hook_at_end else ""
            summary = f"Ch{ch.chapter_number}《{ch.chapter_title}》：{ch.core_event[:60]}"
            if hook:
                summary += f" [钩子：{hook}]"
            result.append(summary)
    return result


def _scan_foreshadows(data: WriteSyncState, up_to: int) -> list[str]:
    """从章纲提取未收伏笔列表。"""
    if not data.chapter_outline or not data.chapter_outline.chapters:
        return []
    result = []
    for ch in data.chapter_outline.chapters:
        if ch.chapter_number > up_to:
            break
        if ch.foreshadows:
            for f in ch.foreshadows:
                content = f.content if hasattr(f, 'content') else str(f)
                entry = f"Ch{ch.chapter_number}: {content}"
                if entry not in result:
                    result.append(entry)
    return result


def _scan_resolved(data: WriteSyncState, ch_num: int) -> list[str]:
    """检测已收伏笔。"""
    if not data.chapter_outline or not data.drafts or ch_num <= 0:
        return []
    cd = data.drafts.chapters.get(ch_num)
    if not cd or not cd.final or not cd.final.content:
        return []
    content = cd.final.content
    resolved = []
    for ch in data.chapter_outline.chapters:
        if ch.chapter_number >= ch_num:
            break
        if ch.foreshadows:
            for f in ch.foreshadows:
                f_text = f.content if hasattr(f, 'content') else str(f)
                if _check_foreshadow_resolved(ch_num, f_text, content):
                    entry = f"Ch{ch.chapter_number}: {f_text} → 收于Ch{ch_num}"
                    resolved.append(entry)
    return resolved


def _check_foreshadow_resolved(chapter_number: int, foreshadow: str, content: str) -> bool:
    """关键词匹配判断伏笔是否已收。
    中文使用字符集合重叠率；英文使用空格分词匹配率。
    """
    resolve_words = ["终于", "揭开", "原来是", "真相", "发现", "得知", "揭露", "果然", "原来如此"]
    en_resolve_words = ["finally", "revealed", "discovered", "truth", "found", "turned out", "uncovered"]
    f_text = foreshadow[:80]

    # 检测是否含中文
    has_cjk = any('\u4e00' <= c <= '\u9fff' for c in f_text)
    if has_cjk:
        any_resolve_found = any(rw in content for rw in resolve_words)
        # 中文：提取独特 CJK 字符，计算与正文的重叠率
        cjk_chars = set(c for c in f_text if '\u4e00' <= c <= '\u9fff')
        if not cjk_chars:
            return any_resolve_found
        content_set = set(content)
        matched = len(cjk_chars & content_set)
        ratio = matched / len(cjk_chars)
        keywords_matched = ratio >= 0.5
    else:
        any_resolve_found = any(rw in content for rw in en_resolve_words) or any(rw in content for rw in resolve_words)
        keywords = [w for w in f_text.split() if len(w) >= 2]
        match_count = sum(1 for kw in keywords if kw in content) if keywords else 0
        ratio = match_count / max(len(keywords), 1)
        keywords_matched = ratio >= 0.5 if keywords else False

    return keywords_matched and any_resolve_found


def _deadline_foreshadows(data: WriteSyncState, ch_num: int) -> dict:
    """预估伏笔收束章节。当前简单策略：标注最近的一条。"""
    if not data.chapter_outline or not data.chapter_outline.chapters:
        return {}
    result = {}
    for ch in data.chapter_outline.chapters:
        if ch.chapter_number <= ch_num:
            continue
        if ch.foreshadows:
            f = ch.foreshadows[0]
            f_text = f.content if hasattr(f, 'content') else str(f)
            result[ch.chapter_number] = f_text[:40]
            break
    return result


def _gather_word_counts(data: WriteSyncState) -> dict:
    """统计所有已写章节的字数。"""
    result = {}
    if data.chapter_outline and data.chapter_outline.written_chapters:
        for ch_num in data.chapter_outline.written_chapters:
            cd = data.drafts.chapters.get(ch_num)
            if cd and cd.word_count:
                result[ch_num] = cd.word_count
    return result


def _assess_pacing(data: WriteSyncState, ch_num: int) -> str:
    """基于字数统计生成节奏建议。"""
    if ch_num <= 0:
        if data.chapter_outline:
            return f"尚未开始写作，目标 {data.chapter_outline.total_chapters} 章"
        return "尚未开始写作"
    counts = list(_gather_word_counts(data).values())
    if not counts:
        return f"Ch{ch_num} 缺少字数数据"
    avg = sum(counts) / len(counts)
    last = counts[-1]
    if last > avg * 1.2:
        suggestion = "字数偏多，下章建议精简"
    elif last < avg * 0.8:
        suggestion = "字数偏少，下章可适度展开"
    else:
        suggestion = "节奏正常"
    return f"Ch{ch_num}字数{last}(均{avg:.0f})；{suggestion}"


def _extract_character_changes(content: str, chars: list) -> list:
    """LLM 提取角色状态变化。超时→正则降级；429→重试1次。"""
    import re
    from ..utils.llm import create_llm_client
    from .response_models import CharacterChangeList

    if not content or not chars:
        return []

    char_names = [c.name for c in chars]

    # 正则预扫描：无角色名 → 跳过 LLM
    if not any(name in content for name in char_names):
        return []

    client = create_llm_client()
    prompt = (
        f"从以下章节正文提取角色状态变化，只列出有变化的角色：\n\n"
        f"{content[:2000]}\n\n"
        f"已知角色列表：\n"
        + "\n".join(f"- {c.name}({c.role})：{c.personality}" for c in chars)
        + "\n\n返回JSON：{{\"changes\": [{{\"name\": \"角色名\", \"change\": \"变化描述(≤20字)\"}}]}}\n"
        "若无变化返回：{{\"changes\": []}}"
    )

    try:
        t0 = time.time()
        result = client.complete_structured(prompt, CharacterChangeList, timeout=15)
        elapsed = (time.time() - t0) * 1000
        logger.info("[context.llm.chars] changes=%d elapsed=%.0fms status=ok",
                     len(result.changes), elapsed)
        return result.changes
    except Exception as e:
        err_str = str(e).lower()
        if "429" in err_str or "rate" in err_str:
            logger.warning("[context.llm.chars] rate limited, retrying after 5s")
            try:
                time.sleep(5)
                result = client.complete_structured(prompt, CharacterChangeList, timeout=15)
                logger.info("[context.llm.chars] retry ok, changes=%d", len(result.changes))
                return result.changes
            except Exception:
                logger.warning("[context.llm.chars] retry failed, falling back to regex")

    # 降级：正则扫描
    logger.warning("[context.llm.chars] falling back to regex extraction")
    return _regex_extract_changes(content, chars)


def _regex_extract_changes(content: str, chars: list) -> list:
    """正则提取角色变化（LLM 降级方案）。"""
    import re
    from .response_models import CharacterChange
    patterns = [
        (r"{name}.{0,20}(突破|晋升|升级|进阶)至(.+?)[，。\n]", "突破至{3}"),
        (r"{name}.{0,20}(觉醒|领悟|参透|掌握)(.+?)[，。\n]", "觉醒{3}"),
        (r"{name}与(.+?)(关系|之间).{0,10}(升温|确立|破裂|恶化|暧昧)", "与{1}关系{5}"),
        (r"{name}.{0,10}(成为|当上|被任命为|继承)(.+?)[，。\n]", "成为{3}"),
        (r"{name}.{0,20}(获得|得到|入手|拿到)(.+?)[，。\n]", "获得{3}"),
    ]
    result = []
    seen = set()
    for c in chars:
        for pattern_str, _ in patterns:
            pat = pattern_str.replace("{name}", re.escape(c.name))
            for m in re.finditer(pat, content):
                desc = m.group(0).strip()[:20]
                if c.name not in seen:
                    result.append(CharacterChange(name=c.name, change=desc))
                    seen.add(c.name)
                break
    return result


def _extract_contradictions(content: str, ctx: DynamicContext) -> list:
    """LLM 检测一致性矛盾。失败直接跳过（无正则降级）。"""
    from ..utils.llm import create_llm_client
    from .response_models import ContradictionList

    if not content or not ctx:
        return []

    client = create_llm_client()
    prompt = (
        f"检查本章正文是否与已有设定矛盾：\n\n"
        f"已知世界格局：{ctx.world_changes}\n"
        f"已记录的一致性问题：{ctx.world_consistency_notes}\n\n"
        f"本章正文（前800字）：\n{content[:800]}\n\n"
        "请检查是否有矛盾之处。返回JSON：{\"contradictions\": [{\"issue\": \"矛盾描述\"}]}\n"
        "若无矛盾返回：{\"contradictions\": []}"
    )

    try:
        t0 = time.time()
        result = client.complete_structured(prompt, ContradictionList, timeout=15)
        elapsed = (time.time() - t0) * 1000
        logger.info("[context.llm.consistency] contradictions=%d elapsed=%.0fms status=ok",
                     len(result.contradictions), elapsed)
        return result.contradictions
    except Exception as e:
        err_str = str(e).lower()
        if "429" in err_str or "rate" in err_str:
            logger.warning("[context.llm.consistency] rate limited, retrying after 5s")
            try:
                time.sleep(5)
                result = client.complete_structured(prompt, ContradictionList, timeout=15)
                logger.info("[context.llm.consistency] retry ok, contradictions=%d",
                            len(result.contradictions))
                return result.contradictions
            except Exception:
                pass
        logger.warning("[context.llm.consistency] failed: %s", e)
        return []  # 无正则降级，静默跳过


def _build_character_snapshot(chars: list, changes: list, ch_num: int) -> list[str]:
    """基于 LLM 提取的变化构建角色快照行。"""
    change_map = {c.name: c.change for c in changes}
    lines = []
    for ch in chars:
        if ch.name in change_map:
            lines.append(f"{ch.name}({ch.role})：{ch.personality}。Ch{ch_num}{change_map[ch.name]}")
        else:
            lines.append(f"{ch.name}({ch.role})：{ch.personality}，{ch.goal}")
    return lines


# ── Continuity Envelope (Phase 3) ──────────────────────────────────────────

def _build_continuity_envelope(data, ch_num: int) -> dict:
    """
    Build the continuity envelope from chapter N to N+1.

    Extracted from:
    - Chapter N's final content (handoff state)
    - Outline plan for chapter N+1 (plan_delta)
    - Writer-level protected elements (regex-based fallback, no LLM)
    """
    envelope = {"handoff": "", "protected": "", "plan_delta": ""}

    # ── Handoff: extract last 2-3 sentences of chapter N ──
    try:
        cd = data.drafts.chapters.get(ch_num)
        if cd and cd.final and cd.final.content:
            text = cd.final.content.strip()
            # Take last ~150 chars as the handoff snapshot
            handoff = text[-200:] if len(text) > 200 else text
            # Clean: remove chapter markers, trim to sentence boundary
            handoff = handoff.lstrip("第").lstrip("章").strip("：:。，, \n\t")
            # Find last sentence break
            last_period = max(handoff.rfind("。"), handoff.rfind("！"), handoff.rfind("？"))
            if last_period > 30:
                handoff = handoff[last_period + 1:]
            envelope["handoff"] = handoff[:120]
    except Exception:
        pass

    # ── Plan delta: check outline for chapter N+1 ──
    try:
        next_ch = ch_num + 1
        if data.chapter_outline and data.chapter_outline.chapters:
            for ch in data.chapter_outline.chapters:
                if ch.chapter_number == next_ch:
                    envelope["plan_delta"] = f"第{next_ch}章计划：{ch.chapter_title} — {ch.core_event}"
                    break
            if not envelope["plan_delta"]:
                envelope["plan_delta"] = f"第{next_ch}章（章纲待规划）"
    except Exception:
        pass

    # ── Protected: scan for marked elements (regex) ──
    try:
        protected = []
        cd = data.drafts.chapters.get(ch_num)
        if cd and cd.final and cd.final.content:
            text = cd.final.content
            # Look for explicit protected markers
            import re
            for match in re.finditer(r"\[保护[:：]([^\]]+)\]", text):
                protected.append(match.group(1))
        # Also protect key character states from character snapshot
        if data.characters and data.characters.characters:
            main_char = data.characters.characters[0]
            if main_char.name:
                protected.append(f"{main_char.name}存活且为主线角色")
        if protected:
            envelope["protected"] = "；".join(protected[:3])[:150]
    except Exception:
        pass

    return envelope
