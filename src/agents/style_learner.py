"""
Style Learner — Phase 6 文风画像模块 (PURE STATISTICS only, no LLM)

Extracts from confirmed chapters:
- avg/max/min sentence length
- word frequency distribution (top 50 words)
- dialogue ratio (% of lines starting with quotes)
- description density (% of paragraphs without dialogue)
- avg paragraph length
"""

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("writesync")


# ─────────────────────────────────────────────────────────────
# StyleProfile
# ─────────────────────────────────────────────────────────────

@dataclass
class StyleProfile:
    """文风量化画像"""

    sentence_lengths: dict = field(default_factory=lambda: {"avg": 0, "max": 0, "min": 0})
    word_frequency: list[tuple] = field(default_factory=list)   # [(word, count), ...] top 50
    dialogue_ratio: float = 0.0      # 0.0 ~ 1.0
    description_density: float = 0.0  # ratio of paragraphs without dialogue
    avg_paragraph_length: float = 0.0
    sample_size_chars: int = 0
    chapter_count: int = 0

    def to_dict(self) -> dict:
        return {
            "sentence_lengths": self.sentence_lengths,
            "word_frequency": self.word_frequency[:50],
            "dialogue_ratio": round(self.dialogue_ratio, 3),
            "description_density": round(self.description_density, 3),
            "avg_paragraph_length": round(self.avg_paragraph_length, 1),
            "sample_size_chars": self.sample_size_chars,
            "chapter_count": self.chapter_count,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "StyleProfile":
        p = cls()
        if "sentence_lengths" in d:
            p.sentence_lengths = d["sentence_lengths"]
        if "word_frequency" in d:
            p.word_frequency = d["word_frequency"]
        if "dialogue_ratio" in d:
            p.dialogue_ratio = d["dialogue_ratio"]
        if "description_density" in d:
            p.description_density = d["description_density"]
        if "avg_paragraph_length" in d:
            p.avg_paragraph_length = d["avg_paragraph_length"]
        if "sample_size_chars" in d:
            p.sample_size_chars = d["sample_size_chars"]
        if "chapter_count" in d:
            p.chapter_count = d["chapter_count"]
        return p


# ─────────────────────────────────────────────────────────────
# StyleLearner
# ─────────────────────────────────────────────────────────────

class StyleLearner:
    """纯统计文风分析器。不调用 LLM。"""

    # Chinese punctuation that ends a sentence
    SENTENCE_ENDS = re.compile(r'[。！？?!！\n]{1,2}')

    # Dialogue markers: lines starting with these
    DIALOGUE_PATTERN = re.compile(r'^["""「『\'"](.+)[""」』\'"]')
    # Also match Chinese quote patterns: "xxx" or "xxx"
    DIALOGUE_PATTERN_CN = re.compile(r'["""「『](.+?)[""」』]')

    # Words: CJK characters are counted individually, ASCII words by spaces
    CJK_WORD = re.compile(r'[\u4e00-\u9fff]')
    LATIN_WORD = re.compile(r'[a-zA-Z]+')

    @classmethod
    def analyze_chapter(cls, chapter_content: str) -> StyleProfile:
        """Analyze a single chapter and return a StyleProfile."""
        if not chapter_content or not chapter_content.strip():
            return StyleProfile()

        text = chapter_content.strip()

        # ── Sentence length ──
        sentences = cls._split_sentences(text)
        sent_lens = [len(s.strip()) for s in sentences if s.strip()]
        if sent_lens:
            avg_sl = sum(sent_lens) / len(sent_lens)
            max_sl = max(sent_lens)
            min_sl = min(sent_lens)
        else:
            avg_sl = max_sl = min_sl = 0

        # ── Word frequency ──
        words = cls._tokenize_words(text)
        word_freq = Counter(words).most_common(50)

        # ── Dialogue ratio ──
        paragraphs = [p.strip() for p in text.split('\n') if p.strip()]
        dialogue_count = 0
        for para in paragraphs:
            # Check if paragraph starts with or contains significant dialogue
            stripped = para.lstrip()
            if stripped:
                first_char = stripped[0]
                if first_char in ('"', '"', '"', '「', '『', '\'', '"'):
                    dialogue_count += 1
                elif cls.DIALOGUE_PATTERN_CN.search(para):
                    dialogue_count += 1

        dialogue_ratio = dialogue_count / max(len(paragraphs), 1)

        # ── Description density ──
        no_dialogue_paras = 0
        for para in paragraphs:
            stripped = para.lstrip()
            has_dialogue = False
            if stripped:
                first_char = stripped[0]
                if first_char in ('"', '"', '"', '「', '『', '\'', '"'):
                    has_dialogue = True
                elif cls.DIALOGUE_PATTERN_CN.search(para):
                    has_dialogue = True
            if not has_dialogue:
                no_dialogue_paras += 1

        description_density = no_dialogue_paras / max(len(paragraphs), 1)

        # ── Avg paragraph length ──
        para_lens = [len(p) for p in paragraphs]
        avg_para_len = sum(para_lens) / max(len(para_lens), 1)

        return StyleProfile(
            sentence_lengths={"avg": round(avg_sl, 1), "max": max_sl, "min": min_sl},
            word_frequency=[(w, c) for w, c in word_freq],
            dialogue_ratio=dialogue_ratio,
            description_density=description_density,
            avg_paragraph_length=round(avg_para_len, 1),
            sample_size_chars=len(text),
            chapter_count=1,
        )

    @classmethod
    def merge_profiles(cls, profiles: list[StyleProfile]) -> StyleProfile:
        """Merge multiple chapter profiles into one combined profile."""
        if not profiles:
            return StyleProfile()
        if len(profiles) == 1:
            return profiles[0]

        n = len(profiles)

        # Sentence lengths: weighted average
        total_chars = sum(p.sample_size_chars for p in profiles)
        if total_chars > 0:
            avg_sl = sum(p.sentence_lengths.get("avg", 0) * p.sample_size_chars for p in profiles) / total_chars
        else:
            avg_sl = sum(p.sentence_lengths.get("avg", 0) for p in profiles) / n

        max_sl = max(p.sentence_lengths.get("max", 0) for p in profiles)
        min_sl = min((p.sentence_lengths.get("min", 99999) for p in profiles if p.sentence_lengths.get("min", 0) > 0), default=0)

        # Word frequency: merge counters
        merged_freq = Counter()
        for p in profiles:
            for word, count in p.word_frequency:
                merged_freq[word] += count
        top_words = merged_freq.most_common(50)

        # Dialogue ratio: weighted average
        dialogue_ratio = sum(p.dialogue_ratio * p.sample_size_chars for p in profiles) / max(total_chars, 1)

        # Description density: weighted average
        description_density = sum(p.description_density * p.sample_size_chars for p in profiles) / max(total_chars, 1)

        # Avg paragraph length: weighted average
        avg_para_len = sum(p.avg_paragraph_length * p.sample_size_chars for p in profiles) / max(total_chars, 1)

        return StyleProfile(
            sentence_lengths={"avg": round(avg_sl, 1), "max": max_sl, "min": min_sl},
            word_frequency=top_words,
            dialogue_ratio=round(dialogue_ratio, 3),
            description_density=round(description_density, 3),
            avg_paragraph_length=round(avg_para_len, 1),
            sample_size_chars=total_chars,
            chapter_count=sum(p.chapter_count for p in profiles),
        )

    @classmethod
    def inject_into_prompt(cls, style_profile: StyleProfile) -> str:
        """Format a StyleProfile as a prompt string for the writer agent."""
        if not style_profile or style_profile.chapter_count == 0:
            return ""

        parts = ["【文风参考】"]
        sl = style_profile.sentence_lengths
        parts.append(f"- 句长：平均{sl['avg']}字 / 最长{sl['max']}字 / 最短{sl['min']}字")
        parts.append(f"- 对话占比：{style_profile.dialogue_ratio:.1%}")
        parts.append(f"- 描述段落占比：{style_profile.description_density:.1%}")
        parts.append(f"- 平均段落长度：{style_profile.avg_paragraph_length:.0f}字")

        if style_profile.word_frequency:
            top10 = style_profile.word_frequency[:10]
            freq_str = '、'.join(w for w, _ in top10)
            parts.append(f"- 高频词汇（Top10）：{freq_str}")

        parts.append(f"- 样本：{style_profile.chapter_count}章 {style_profile.sample_size_chars}字")

        return '\n'.join(parts)

    # ── Internal helpers ──

    @classmethod
    def _split_sentences(cls, text: str) -> list[str]:
        """Split text into sentences."""
        # Replace newlines temporarily
        cleaned = text.replace('\n', '。')
        parts = cls.SENTENCE_ENDS.split(cleaned)
        # Filter empty
        return [p.strip() for p in parts if p.strip()]

    @classmethod
    def _tokenize_words(cls, text: str) -> list[str]:
        """Tokenize Chinese text into words (character-level for CJK, word-level for Latin)."""
        result = []
        buffer = ""
        for ch in text:
            if ch.isalpha() and ch.isascii():
                buffer += ch
            else:
                if buffer:
                    if len(buffer) >= 2:
                        result.append(buffer.lower())
                    buffer = ""
                if cls.CJK_WORD.match(ch):
                    result.append(ch)
                elif ch.isdigit():
                    result.append(ch)
        if buffer and len(buffer) >= 2:
            result.append(buffer.lower())
        return result
