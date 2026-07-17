"""
Fact Ledger — Phase 3 长时记忆系统

TemporalFact 数据模型 + FactLedger 类，从章节正文中提取结构化事实，
追踪其生命周期（valid_from → valid_to），跨章注入 writer prompt。

Architecture:
  FactLedger stores facts in workspace.raw_state.dynamic_context.facts
  (a dict list, serializable to JSON), plus a local in-memory index
  for fast filtered queries. LLM extraction is fire-and-forget to avoid
  blocking the orchestration loop.
"""

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Optional

from pydantic import BaseModel, Field

logger = logging.getLogger("writesync")


# ─────────────────────────────────────────────────────────────
# Data Models
# ─────────────────────────────────────────────────────────────

@dataclass
class TemporalFact:
    """A single structured fact with temporal validity window."""

    content: str  # "张三在12岁学会了剑法"
    category: str  # "character" | "plot" | "world" | "item"
    valid_from_ch: int  # 从第几章开始有效
    valid_to_ch: Optional[int] = None  # 到第几章失效（None=至今有效）
    status: str = "candidate"  # "candidate" | "confirmed" | "denied"
    source_chapter: int = 0  # 来源章节
    id: str = ""  # auto-generated hash key

    def __post_init__(self):
        if not self.id:
            import hashlib
            raw = f"{self.category}:{self.content}:{self.source_chapter}"
            self.id = hashlib.md5(raw.encode()).hexdigest()[:12]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "content": self.content,
            "category": self.category,
            "valid_from_ch": self.valid_from_ch,
            "valid_to_ch": self.valid_to_ch,
            "status": self.status,
            "source_chapter": self.source_chapter,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TemporalFact":
        return cls(
            content=d["content"],
            category=d.get("category", "plot"),
            valid_from_ch=d.get("valid_from_ch", 0),
            valid_to_ch=d.get("valid_to_ch"),
            status=d.get("status", "candidate"),
            source_chapter=d.get("source_chapter", 0),
            id=d.get("id", ""),
        )


@dataclass
class ContinuityEnvelope:
    """章末快照：位置、情绪、进行中动作、未解决冲突 + 偏差 + 保护块"""

    handoff: str = ""  # 章末状态：位置、情绪、进行中的动作、未解决冲突
    plan_delta: str = ""  # 章纲节拍 vs 实际内容的偏差
    protected: str = ""  # 需要严格保持的设定/事实（用 #PROTECTED 标记）
    chapter_num: int = 0

    def to_dict(self) -> dict:
        return {
            "handoff": self.handoff,
            "plan_delta": self.plan_delta,
            "protected": self.protected,
            "chapter_num": self.chapter_num,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ContinuityEnvelope":
        return cls(
            handoff=d.get("handoff", ""),
            plan_delta=d.get("plan_delta", ""),
            protected=d.get("protected", ""),
            chapter_num=d.get("chapter_num", 0),
        )


# ─────────────────────────────────────────────────────────────
# Pydantic response models for LLM structured output
# ─────────────────────────────────────────────────────────────

class FactItem(BaseModel):
    content: str = Field(description="事实内容（≤80字）")
    category: str = Field(description="分类: character/plot/world/item")
    valid_from_ch: int = Field(description="从第几章开始有效")
    valid_to_ch: Optional[int] = Field(default=None, description="到第几章失效，None=至今有效")

class FactList(BaseModel):
    facts: list[FactItem] = Field(default_factory=list)

class EnvelopeOutput(BaseModel):
    handoff: str = Field(description="章末状态：角色当前位置、情绪、进行中的动作、未解决冲突（≤200字）")
    plan_delta: str = Field(description="章纲节拍 vs 实际内容的偏差简述（≤100字）")
    protected: str = Field(description="#PROTECTED 标记的关键设定/事实（≤200字）")


# ─────────────────────────────────────────────────────────────
# FactLedger
# ─────────────────────────────────────────────────────────────

class FactLedger:
    """
    Structured fact tracker and context injector.

    Stores facts in workspace.raw_state.dynamic_context. Uses the
    workspace's context_cache for short-term access and JSON-persisted
    fact_ledger.json for long-term storage.
    """

    def __init__(self, workspace):
        self._workspace = workspace
        self._state = workspace.raw_state
        # Backward-compat: load existing facts from dynamic_context
        self._facts: list[TemporalFact] = []
        self._load_from_state()

    # ── Lifecycle ─────────────────────────────────────────────

    def _load_from_state(self):
        """Load facts from dynamic_context or context_cache."""
        ctx = self._state.dynamic_context
        if ctx and hasattr(ctx, "facts") and ctx.facts:
            self._facts = [TemporalFact.from_dict(f) for f in ctx.facts]
        # Also check context_cache for persisted ledger
        cached = self._workspace.context_cache.get("fact_ledger_facts")
        if cached:
            try:
                loaded = json.loads(cached) if isinstance(cached, str) else cached
                self._facts = [TemporalFact.from_dict(f) for f in loaded]
            except Exception:
                pass

    def _persist_to_state(self):
        """Write facts back to dynamic_context and context_cache."""
        fact_dicts = [f.to_dict() for f in self._facts]
        ctx = self._state.dynamic_context
        if ctx:
            ctx.facts = fact_dicts
        self._workspace.context_cache["fact_ledger_facts"] = json.dumps(
            fact_dicts, ensure_ascii=False
        )

    def _persist_to_disk(self):
        """Write facts to fact_ledger.json in project dir."""
        if not hasattr(self._workspace, "_project_dir") or not self._workspace._project_dir:
            return
        from pathlib import Path
        try:
            path = Path(self._workspace._project_dir) / "fact_ledger.json"
            data = {
                "facts": [f.to_dict() for f in self._facts],
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.debug("fact_ledger disk persist failed: %s", e)

    def save(self):
        """Persist to both state and disk."""
        self._persist_to_state()
        self._persist_to_disk()

    # ── Fact CRUD ─────────────────────────────────────────────

    def extract_facts(self, chapter_content: str, chapter_num: int,
                      llm=None) -> list[TemporalFact]:
        """
        LLM-based fact extraction with structured output (MD_JSON).
        On timeout/error (60s), falls back to regex scanning.

        Returns list of new TemporalFact objects (not yet persisted).
        """
        if not chapter_content:
            return []

        t0 = time.time()

        try:
            new_facts = self._llm_extract(chapter_content, chapter_num, llm)
            elapsed = (time.time() - t0) * 1000
            logger.info(
                "[fact_ledger.extract] ch=%d facts=%d method=llm elapsed=%.0fms",
                chapter_num, len(new_facts), elapsed,
            )
            return new_facts
        except Exception as e:
            elapsed = (time.time() - t0) * 1000
            logger.warning(
                "[fact_ledger.extract] ch=%d llm_failed=%s elapsed=%.0fms, falling back to regex",
                chapter_num, e, elapsed,
            )
            return self._regex_extract(chapter_content, chapter_num)

    def _llm_extract(self, chapter_content: str, chapter_num: int,
                     llm=None) -> list[TemporalFact]:
        """LLM structured output for fact extraction."""
        from ..utils.llm import create_llm_client
        if llm is None:
            llm = create_llm_client()

        # Truncate to avoid token bloat
        snippet = chapter_content[:4000]

        prompt = (
            "从以下章节正文中提取关键事实。一个事实是角色状态变化、重要情节节点、"
            "世界观规则、或关键物品设定。\n\n"
            f"## 第{chapter_num}章正文（前4000字）\n\n{snippet}\n\n"
            "## 规则\n"
            "1. category 必须为: character | plot | world | item\n"
            "2. valid_from_ch 设为本章编号\n"
            "3. valid_to_ch 留空（null）除非明确知道事实何时失效\n"
            "4. 每条事实 content ≤ 80 字，核心信息精炼\n"
            "5. 只输出本章**新引入或变化**的事实，不重复旧事实\n"
            "6. 若无值得记录的事实，返回空列表"
        )

        try:
            result = llm.complete_structured(
                prompt, output_class=FactList,
                temperature=0.3, max_tokens=2048, timeout=60, max_retries=0,
            )
            facts = []
            for item in result.facts:
                facts.append(TemporalFact(
                    content=item.content,
                    category=item.category,
                    valid_from_ch=chapter_num,
                    valid_to_ch=item.valid_to_ch,
                    status="candidate",
                    source_chapter=chapter_num,
                ))
            return facts
        except Exception:
            raise  # let caller handle fallback

    def _regex_extract(self, chapter_content: str, chapter_num: int) -> list[TemporalFact]:
        """
        Regex fallback: scan for character names + key action patterns.
        Extracts names and action keywords as candidate facts.
        """
        facts = []
        # Pattern 1: Character name + action verb patterns
        # Matches patterns like "张三(修炼|突破|获得|遇到|发现|击败|离开|进入)"
        name_pattern = re.compile(
            r'([\u4e00-\u9fff]{2,4})(?:的|地|，|。|、|\s){0,5}'
            r'(修炼|突破|晋升|进阶|获得|得到|发现|遇到|击败|战胜|离开|进入|觉醒|领悟|参透|掌握|成为|当上|继承|失去|牺牲|死亡|受伤|恢复|治愈|炼制|锻造|布置|施展|释放|爆发)'
        )
        seen_contents = set()
        for m in name_pattern.finditer(chapter_content):
            name = m.group(1)
            action = m.group(2)
            content = f"{name}{action}"
            if content not in seen_contents and len(content) <= 80:
                seen_contents.add(content)
                facts.append(TemporalFact(
                    content=content,
                    category="character",
                    valid_from_ch=chapter_num,
                    status="candidate",
                    source_chapter=chapter_num,
                ))

        # Pattern 2: World/location patterns
        loc_pattern = re.compile(
            r'(?:位于|来到|抵达|进入|离开|前往)([\u4e00-\u9fff]{2,8}(?:城|国|宗|门|派|山|谷|林|海|界|域|殿|阁|楼|塔|洞|府|院|市|镇|村))'
        )
        for m in loc_pattern.finditer(chapter_content):
            content = f"地点：{m.group(1)}"
            if content not in seen_contents:
                seen_contents.add(content)
                facts.append(TemporalFact(
                    content=content,
                    category="world",
                    valid_from_ch=chapter_num,
                    status="candidate",
                    source_chapter=chapter_num,
                ))

        logger.info(
            "[fact_ledger.regex] ch=%d facts=%d",
            chapter_num, len(facts),
        )
        return facts

    def confirm_fact(self, fact_id: str) -> bool:
        """Mark a fact as confirmed. Returns True if found."""
        for f in self._facts:
            if f.id == fact_id:
                f.status = "confirmed"
                self.save()
                return True
        return False

    def deny_fact(self, fact_id: str) -> bool:
        """Mark a fact as denied. Returns True if found."""
        for f in self._facts:
            if f.id == fact_id:
                f.status = "denied"
                self.save()
                return True
        return False

    def add_fact(self, fact: TemporalFact):
        """Add a single fact (dedup by ID)."""
        if not any(f.id == fact.id for f in self._facts):
            self._facts.append(fact)
            self.save()

    def add_facts(self, facts: list[TemporalFact]):
        """Add multiple facts (dedup by ID)."""
        existing_ids = {f.id for f in self._facts}
        new = [f for f in facts if f.id not in existing_ids]
        if new:
            self._facts.extend(new)
            self.save()
            logger.info("[fact_ledger] added %d new facts (total=%d)", len(new), len(self._facts))

    def get_active_facts(self, up_to_chapter: int) -> list[TemporalFact]:
        """Return confirmed facts valid up to the given chapter."""
        return [
            f for f in self._facts
            if f.status == "confirmed"
            and f.valid_from_ch <= up_to_chapter
            and (f.valid_to_ch is None or f.valid_to_ch > up_to_chapter)
        ]

    def get_facts_by_category(self, category: str = "",
                               up_to_chapter: int = 0) -> list[TemporalFact]:
        """Filter facts by category, optionally by chapter range."""
        active = self._facts if up_to_chapter <= 0 else self.get_active_facts(up_to_chapter)
        if category:
            return [f for f in active if f.category == category]
        return active

    def get_all_facts(self) -> list[TemporalFact]:
        """Return all facts regardless of status."""
        return list(self._facts)

    def invalidate_chapter_facts(self, chapter_num: int):
        """Mark all facts from a chapter as candidate (for re-extraction)."""
        count = 0
        for f in self._facts:
            if f.source_chapter == chapter_num and f.status == "confirmed":
                f.status = "candidate"
                count += 1
        if count > 0:
            self.save()
            logger.info("[fact_ledger] invalidated %d facts from ch=%d", count, chapter_num)

    # ── Prompt Injection ──────────────────────────────────────

    def inject_into_prompt(self, facts: list[TemporalFact],
                            max_tokens: int = 1000) -> str:
        """
        Format facts as a bullet list, truncated to max_tokens.
        Approx 1 token ≈ 2 CJK chars.
        """
        if not facts:
            return ""

        max_chars = max_tokens * 2  # conservative CJK estimate
        lines = []
        used = 0
        category_labels = {
            "character": "角色",
            "plot": "情节",
            "world": "世界",
            "item": "物品",
        }

        for f in facts:
            label = category_labels.get(f.category, f.category)
            line = f"- [{label}] Ch{f.source_chapter}: {f.content}"
            if used + len(line) > max_chars:
                break
            lines.append(line)
            used += len(line)

        if not lines:
            return ""

        header = "## 已确认事实（Fact Ledger）\n"
        return header + "\n".join(lines)

    # ── Continuity Envelope ───────────────────────────────────

    @staticmethod
    def extract_envelope(chapter_content: str, chapter_outline: str,
                         chapter_num: int, llm=None) -> ContinuityEnvelope:
        """
        LLM extracts handoff state, plan delta, and protected blocks.
        Falls back to simple regex-based extraction on failure.
        """
        if not chapter_content:
            return ContinuityEnvelope(chapter_num=chapter_num)

        t0 = time.time()
        try:
            return FactLedger._llm_extract_envelope(
                chapter_content, chapter_outline, chapter_num, llm
            )
        except Exception as e:
            elapsed = (time.time() - t0) * 1000
            logger.warning(
                "[fact_ledger.envelope] ch=%d llm_failed=%s elapsed=%.0fms, using regex",
                chapter_num, e, elapsed,
            )
            return FactLedger._regex_extract_envelope(
                chapter_content, chapter_outline, chapter_num
            )

    @staticmethod
    def _llm_extract_envelope(chapter_content: str, chapter_outline: str,
                               chapter_num: int, llm=None) -> ContinuityEnvelope:
        from ..utils.llm import create_llm_client
        if llm is None:
            llm = create_llm_client()

        # Take last 1500 chars + first 200 for handoff context
        tail = chapter_content[-1500:] if len(chapter_content) > 1500 else chapter_content
        head = chapter_content[:200]

        outline_section = ""
        if chapter_outline:
            outline_section = f"\n## 本章章纲\n{chapter_outline[:500]}\n"

        prompt = (
            "Analyze the ending of chapter " + str(chapter_num) + " and extract three info blocks:\n\n"
            "## Chapter opening (first 200 chars)\n" + head + "\n\n"
            "## Chapter ending (last 1500 chars)\n" + tail +
            outline_section +
            "\n## Extraction Requirements\n"
            "1. handoff: Character location, emotional state, ongoing actions, unresolved conflicts at chapter end (<=200 chars)\n"
            "2. plan_delta: Difference between outline expectation vs actual content (<=100 chars, use 'matches outline' if no delta)\n"
            "3. protected: #PROTECTED marked facts/settings that next chapter MUST preserve (<=200 chars), prefix each with #PROTECTED\n"
            "Leave protected empty if nothing needs protection."
        )

        try:
            result = llm.complete_structured(
                prompt, output_class=EnvelopeOutput,
                temperature=0.3, max_tokens=1024, timeout=60, max_retries=0,
            )
            elapsed = (time.time() - time.time())  # approximate
            logger.info(
                "[fact_ledger.envelope] ch=%d handoff_len=%d plan_len=%d prot_len=%d",
                chapter_num,
                len(result.handoff), len(result.plan_delta), len(result.protected),
            )
            return ContinuityEnvelope(
                handoff=result.handoff,
                plan_delta=result.plan_delta,
                protected=result.protected,
                chapter_num=chapter_num,
            )
        except Exception:
            raise

    @staticmethod
    def _regex_extract_envelope(chapter_content: str, chapter_outline: str,
                                 chapter_num: int) -> ContinuityEnvelope:
        """Regex fallback for envelope extraction."""
        tail = chapter_content[-800:] if len(chapter_content) > 800 else chapter_content

        # Extract last location mention
        loc_match = re.search(
            r'(?:位于|在|回到|来到|抵达|离开|站在|坐在|躺在|躲在|藏身于)([\u4e00-\u9fff]{2,15}(?:城|国|宗|门|派|山|谷|林|海|界|域|殿|阁|楼|塔|洞|府|院|市|镇|村|中|内|外|里|上|下|前|后|间|边))',
            tail
        )
        location = loc_match.group(0) if loc_match else ""

        # Extract last character + emotion
        emotion_match = re.search(
            r'([\u4e00-\u9fff]{2,4})(?:感到|觉得|心中|内心|暗自|不禁){0,3}'
            r'(愤怒|激动|紧张|恐惧|欣喜|悲伤|忧虑|兴奋|期待|绝望|坚定|犹豫|痛苦|喜悦|焦急|不安|满足|失望|震惊)',
            tail
        )
        emotion = ""
        if emotion_match:
            emotion = f"{emotion_match.group(1)}感到{emotion_match.group(2)}"

        # Extract ongoing action (last sentence)
        last_sent = ""
        sentences = re.split(r'[。！？\n]', tail)
        for s in reversed(sentences):
            s = s.strip()
            if len(s) > 10:
                last_sent = s[:60]
                break

        handoff_parts = []
        if location:
            handoff_parts.append(f"位置：{location}")
        if emotion:
            handoff_parts.append(emotion)
        if last_sent:
            handoff_parts.append(f"末句：{last_sent}")

        handoff = "；".join(handoff_parts) if handoff_parts else "（章末状态待确认）"

        return ContinuityEnvelope(
            handoff=handoff[:200],
            plan_delta="（手动检查偏差）",
            protected="",
            chapter_num=chapter_num,
        )

    @staticmethod
    def inject_envelope_into_writer(envelope: ContinuityEnvelope) -> str:
        """Format ContinuityEnvelope for writer prompt injection."""
        if not envelope or (not envelope.handoff and not envelope.protected):
            return ""

        parts = []
        parts.append("## 上章衔接（Continuity Envelope）\n")

        if envelope.handoff:
            parts.append(f"### 章末状态\n{envelope.handoff}\n")

        if envelope.protected:
            parts.append(f"### 必须保持的设定\n{envelope.protected}\n")
            parts.append(
                "\n**硬约束：在正文前40%必须逐项落实以上 #PROTECTED 块中的事实。**\n"
            )

        if envelope.plan_delta:
            parts.append(f"### 章纲偏差\n{envelope.plan_delta}\n")

        return "\n".join(parts)

    # ── Context Budget ────────────────────────────────────────

    def get_envelope_for_chapter(self, chapter_num: int) -> Optional[ContinuityEnvelope]:
        """Retrieve the envelope from the chapter before the given one."""
        prev_ch = chapter_num - 1
        if prev_ch < 1:
            return None
        cache_key = f"continuity_envelope_ch{prev_ch}"
        cached = self._workspace.context_cache.get(cache_key)
        if cached:
            try:
                data = json.loads(cached) if isinstance(cached, str) else cached
                return ContinuityEnvelope.from_dict(data)
            except Exception:
                pass
        return None

    def store_envelope(self, envelope: ContinuityEnvelope):
        """Store envelope in context_cache."""
        cache_key = f"continuity_envelope_ch{envelope.chapter_num}"
        self._workspace.context_cache[cache_key] = json.dumps(
            envelope.to_dict(), ensure_ascii=False
        )


# ─────────────────────────────────────────────────────────────
# Context Budget (B0-B3 layering for writer prompts only)
# ─────────────────────────────────────────────────────────────

class ContextBudget:
    """
    B0-B3 上下文预算分层系统。
    用于 assemble writer prompt 中的上下文片段，按优先级分层。

    B0 = 保护块：当前章纲 + 创作规则（永不裁剪）
    B1 = 角色状态 + 活跃事实
    B2 = 近3章摘要 + 伏笔状态
    B3 = 原文检索结果 + 远距离上下文
    """

    B0: int = 2000  # 保护块
    B1: int = 3000  # 角色状态 + 活跃事实
    B2: int = 2000  # 近3章摘要 + 伏笔状态
    B3: int = 3000  # 远距离上下文
    total: int = 10000

    def __init__(self, b0=None, b1=None, b2=None, b3=None):
        if b0 is not None:
            self.B0 = b0
        if b1 is not None:
            self.B1 = b1
        if b2 is not None:
            self.B2 = b2
        if b3 is not None:
            self.B3 = b3
        self.total = self.B0 + self.B1 + self.B2 + self.B3

    def assemble(self, state, chapter_num: int,
                 ledger: Optional[FactLedger] = None) -> str:
        """
        按优先级分层装配上下文，超出预算时裁 B3→B2→B1。
        B0 永不裁剪。

        Returns formatted string for writer prompt context injection.
        """
        parts_b0 = self._build_b0(state, chapter_num)
        parts_b1 = self._build_b1(state, chapter_num, ledger)
        parts_b2 = self._build_b2(state, chapter_num)
        parts_b3 = self._build_b3(state, chapter_num)

        # Assemble in priority order with budget trimming
        assembled = []
        budgets = [
            ("B0", self.B0, parts_b0, True),   # never trim
            ("B1", self.B1, parts_b1, False),
            ("B2", self.B2, parts_b2, False),
            ("B3", self.B3, parts_b3, False),
        ]

        for label, budget, parts, never_trim in budgets:
            if not parts:
                continue
            content = "\n\n".join(parts)
            if never_trim:
                assembled.append(content)
            else:
                if len(content) > budget:
                    # Trim from B3→B2→B1, favoring first part
                    trimmed = self._trim_to_budget(parts, budget)
                    assembled.append(trimmed)
                else:
                    assembled.append(content)

        return "\n\n---\n\n".join(assembled) if assembled else ""

    def _trim_to_budget(self, parts: list[str], budget: int) -> str:
        """Trim parts to fit within budget, keeping the first ones."""
        result = []
        used = 0
        for p in parts:
            if used + len(p) <= budget:
                result.append(p)
                used += len(p)
            else:
                remaining = budget - used
                if remaining > 50:
                    result.append(p[:remaining] + "…")
                break
        return "\n\n".join(result) if result else ""

    def _build_b0(self, state, chapter_num: int) -> list[str]:
        """B0: 保护块 — 当前章纲 + 创作规则"""
        parts = []
        data = state.get("data") if isinstance(state, dict) else state
        if hasattr(data, "chapter_outline") and data.chapter_outline:
            for ch in data.chapter_outline.chapters:
                if ch.chapter_number == chapter_num:
                    outline_text = (
                        f"## B0 当前章纲\n"
                        f"第{ch.chapter_number}章 {ch.chapter_title}\n"
                        f"核心事件：{ch.core_event}\n"
                        f"人物状态：{ch.character_states}\n"
                        f"故事推进：{ch.story_progression}\n"
                        f"POV：{ch.pov}\n"
                        f"节奏：{ch.pace}\n"
                        f"结尾钩子：{ch.hook_at_end or '（无）'}"
                    )
                    if len(outline_text) > self.B0:
                        outline_text = outline_text[:self.B0]
                    parts.append(outline_text)
                    break
        return parts

    def _build_b1(self, state, chapter_num: int,
                   ledger: Optional[FactLedger] = None) -> list[str]:
        """B1: 角色状态 + 活跃事实"""
        parts = []
        data = state.get("data") if isinstance(state, dict) else state
        ctx = getattr(data, "dynamic_context", None)

        if ctx and ctx.character_snapshot:
            parts.append(f"## B1 角色状态\n{ctx.character_snapshot}")

        if ledger:
            facts = ledger.get_active_facts(chapter_num)
            if facts:
                parts.append(ledger.inject_into_prompt(facts, max_tokens=800))

        return parts

    def _build_b2(self, state, chapter_num: int) -> list[str]:
        """B2: 近3章摘要 + 伏笔状态"""
        parts = []
        data = state.get("data") if isinstance(state, dict) else state
        ctx = getattr(data, "dynamic_context", None)
        if not ctx:
            return parts

        if ctx.recent_chapters_summary:
            parts.append(f"## B2 前章回顾\n{ctx.recent_chapters_summary}")

        if ctx.unresolved_foreshadows:
            fores = "\n".join(f"- {f}" for f in ctx.unresolved_foreshadows[:5])
            parts.append(f"## B2 未收伏笔\n{fores}")

        return parts

    def _build_b3(self, state, chapter_num: int) -> list[str]:
        """B3: 远距离上下文 — 一致性提醒 + 全书进度"""
        parts = []
        data = state.get("data") if isinstance(state, dict) else state
        ctx = getattr(data, "dynamic_context", None)
        if not ctx:
            return parts

        if ctx.world_consistency_notes:
            parts.append(f"## B3 一致性注意\n{ctx.world_consistency_notes}")

        if ctx.world_changes:
            parts.append(f"## B3 世界格局\n{ctx.world_changes}")

        if ctx.plot_progress:
            parts.append(f"## B3 全书进度\n{ctx.plot_progress}")

        if ctx.pacing_state:
            parts.append(f"## B3 节奏状态\n{ctx.pacing_state}")

        return parts


# ─────────────────────────────────────────────────────────────
# Async helper for fire-and-forget extraction
# ─────────────────────────────────────────────────────────────

async def extract_facts_async(ledger: FactLedger, content: str,
                               chapter_num: int):
    """Fire-and-forget async wrapper for fact extraction."""
    try:
        loop = asyncio.get_running_loop()
        new_facts = await loop.run_in_executor(
            None, ledger.extract_facts, content, chapter_num
        )
        ledger.add_facts(new_facts)
        logger.info(
            "[fact_ledger.async] ch=%d extracted=%d facts (total=%d)",
            chapter_num, len(new_facts), len(ledger.get_all_facts()),
        )
    except Exception as e:
        logger.warning("[fact_ledger.async] ch=%d failed: %s", chapter_num, e)


async def extract_envelope_async(workspace, content: str, outline: str,
                                  chapter_num: int, ledger: FactLedger):
    """Fire-and-forget async wrapper for envelope extraction."""
    try:
        loop = asyncio.get_running_loop()
        envelope = await loop.run_in_executor(
            None, FactLedger.extract_envelope, content, outline, chapter_num
        )
        ledger.store_envelope(envelope)
        logger.info(
            "[fact_ledger.envelope.async] ch=%d handoff_len=%d",
            chapter_num, len(envelope.handoff),
        )
    except Exception as e:
        logger.warning("[fact_ledger.envelope.async] ch=%d failed: %s", chapter_num, e)
