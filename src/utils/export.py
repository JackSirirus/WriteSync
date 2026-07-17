"""
导出模块 — 将小说导出为 Markdown / TXT

用法：
    from src.utils.export import export_to_markdown
    export_to_markdown(state, "output.md")
"""

import os
from datetime import datetime
from ..state.state_types import WriteSyncState


def export_to_markdown(state: WriteSyncState, output_path: str = "") -> str:
    """将完整项目导出为 Markdown 文件"""
    if not output_path:
        name = state.metadata.name or "novel"
        output_path = f"{name}_{datetime.now().strftime('%Y%m%d')}.md"

    lines = []

    # 标题
    lines.append(f"# {state.metadata.name}")
    lines.append(f"")
    lines.append(f"- **平台**: {state.metadata.platform}")
    lines.append(f"- **状态**: {state.metadata.status.value}")
    lines.append(f"")

    # 选题
    if state.topic and state.topic.selected >= 0:
        t = state.topic.suggestions[state.topic.selected]
        lines.append(f"## 选题")
        lines.append(f"- **标题**: {t.title}")
        lines.append(f"- **题材**: {t.genre} / {t.sub_genre}")
        lines.append(f"- **核心卖点**: {t.core_selling_point}")
        lines.append(f"")

    # 故事核心
    if state.story:
        lines.append(f"## 故事核心")
        lines.append(f"- **一句话**: {state.story.step1.one_sentence}")
        lines.append(f"- **类型**: {state.story.step1.tag}")
        s2 = state.story.step2
        lines.append(f"- **五句话**:")
        lines.append(f"  1. {s2.setup}")
        lines.append(f"  2. {s2.inciting}")
        lines.append(f"  3. {s2.rising}")
        lines.append(f"  4. {s2.climax_prep}")
        lines.append(f"  5. {s2.resolution}")
        lines.append(f"")

    # 角色
    if state.characters and state.characters.characters:
        lines.append(f"## 角色")
        for c in state.characters.characters:
            lines.append(f"### {c.name}（{c.role}）")
            lines.append(f"- **身份**: {c.identity}")
            lines.append(f"- **性格**: {c.personality}")
            lines.append(f"- **目标**: {c.goal}")
            lines.append(f"- **冲突**: {c.conflict}")
            if c.arc:
                lines.append(f"- **弧线**: {c.arc.start_state} → {c.arc.end_state}")
            lines.append(f"")

    # 世界观
    if state.world:
        lines.append(f"## 世界观")
        lines.append(f"- **力量体系**: {state.world.power_system.system_name}")
        lines.append(f"- **等级**: {', '.join(state.world.power_system.tiers)}")
        lines.append(f"")

    # 章纲
    if state.chapter_outline:
        lines.append(f"## 章纲（共{state.chapter_outline.total_chapters}章）")
        for ch in state.chapter_outline.chapters:
            status = "✓" if ch.chapter_number in (state.chapter_outline.written_chapters or []) else " "
            lines.append(f"- [{status}] 第{ch.chapter_number}章：{ch.chapter_title}")
            lines.append(f"  {ch.core_event}")
        lines.append(f"")

    # 正文
    if state.drafts and state.drafts.chapters:
        lines.append(f"## 正文")
        for ch_num in sorted(state.drafts.chapters.keys()):
            cd = state.drafts.chapters[ch_num]
            content = ""
            if cd.final and cd.final.content:
                content = cd.final.content
            elif cd.draft and cd.draft.content:
                content = cd.draft.content
            if content:
                lines.append(f"### 第{ch_num}章")
                lines.append(f"")
                lines.append(content)
                lines.append(f"")

    # 全书审查
    if state.novel_review:
        lines.append(f"## 全书审查")
        lines.append(f"- **结论**: {'通过' if state.novel_review.passed else '需修改'}")
        lines.append(f"- **节奏评估**: {state.novel_review.pacing_assessment}")
        if state.novel_review.recommendations:
            lines.append(f"- **建议**:")
            for r in state.novel_review.recommendations:
                lines.append(f"  - {r}")
        lines.append(f"")

    text = "\n".join(lines)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(text)
    return output_path


def export_to_txt(state: WriteSyncState, output_path: str = "") -> str:
    """仅导出正文到 TXT"""
    if not output_path:
        name = state.metadata.name or "novel"
        output_path = f"{name}_{datetime.now().strftime('%Y%m%d')}.txt"

    lines = []
    if state.drafts and state.drafts.chapters:
        for ch_num in sorted(state.drafts.chapters.keys()):
            cd = state.drafts.chapters[ch_num]
            content = ""
            if cd.final and cd.final.content:
                content = cd.final.content
            elif cd.draft and cd.draft.content:
                content = cd.draft.content
            if content:
                lines.append(f"第{ch_num}章")
                lines.append("=" * 20)
                lines.append(content)
                lines.append("")

    text = "\n".join(lines)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(text)
    return output_path
