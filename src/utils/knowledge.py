"""
WriteSync 知识库加载工具

加载知识库文件（templates / standards / techniques / platforms），
供各 Agent 在生成内容时引用。
"""

from pathlib import Path
from typing import Optional

# 项目根目录（向上两级找到 docs/）
_PROJECT_ROOT = Path(__file__).parent.parent.parent
_DOCS_DIR = _PROJECT_ROOT / "docs"


class KnowledgeBase:
    """
    知识库加载器

    提供只读访问：
    - platforms/：平台特性数据
    - templates/：写作模板
    - standards/：质量标准
    - techniques/：技法参考
    """

    def __init__(self, docs_dir: Optional[Path] = None):
        self.docs_dir = docs_dir or _DOCS_DIR

    # =====================================================================
    # 平台知识
    # =====================================================================

    def load_platform(self, platform: str) -> str:
        """
        加载指定平台的知识库文件。

        参数：
            platform: 平台名称，如"起点"、"番茄"、"飞卢"、"纵横"
        返回：
            平台文件的完整文本内容
        """
        platform_file = self.docs_dir / "platforms" / f"{platform}.md"
        if not platform_file.exists():
            raise FileNotFoundError(f"未找到平台知识库文件: {platform_file}")
        return platform_file.read_text(encoding="utf-8")

    def list_platforms(self) -> list[str]:
        """列出所有可用的平台"""
        platforms_dir = self.docs_dir / "platforms"
        if not platforms_dir.exists():
            return []
        return [p.stem for p in platforms_dir.glob("*.md")]

    # =====================================================================
    # 模板
    # =====================================================================

    def load_template(self, name: str) -> str:
        """
        加载指定模板。

        参数：
            name: 模板名称，如"选题卡"、"摘要"、"角色卡"、"世界观"、"章纲"
        返回：
            模板文件的完整文本内容
        """
        template_file = self.docs_dir / "templates" / f"{name}模板.md"
        if not template_file.exists():
            raise FileNotFoundError(f"未找到模板文件: {template_file}")
        return template_file.read_text(encoding="utf-8")

    def load_all_templates(self) -> dict[str, str]:
        """加载所有模板"""
        templates_dir = self.docs_dir / "templates"
        if not templates_dir.exists():
            return {}
        return {
            p.stem.replace("模板", ""): p.read_text(encoding="utf-8")
            for p in templates_dir.glob("*模板.md")
        }

    # =====================================================================
    # 质量标准
    # =====================================================================

    def load_standard(self, name: str) -> str:
        """
        加载指定的质量标准。

        参数：
            name: 标准名称，如"选题检查清单"、"检查Agent评估标准"、"节奏评估标准"、"校对清单"
        返回：
            标准文件的完整文本内容
        """
        # 尝试多种文件名匹配
        candidates = [
            self.docs_dir / "standards" / f"{name}.md",
            self.docs_dir / "standards" / f"{name}清单.md",
            self.docs_dir / "standards" / f"{name}标准.md",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate.read_text(encoding="utf-8")
        raise FileNotFoundError(f"未找到质量标准文件: {name}")

    def load_all_standards(self) -> dict[str, str]:
        """加载所有质量标准"""
        standards_dir = self.docs_dir / "standards"
        if not standards_dir.exists():
            return {}
        return {
            p.stem: p.read_text(encoding="utf-8")
            for p in standards_dir.glob("*.md")
        }

    # =====================================================================
    # 技法参考
    # =====================================================================

    def load_technique(self, name: str) -> str:
        """
        加载指定的技法参考。

        参数：
            name: 技法名称，如"开篇三章"、"爽点设计"、"钩子技法"、"人物弧线写法"
        返回：
            技法文件的完整文本内容
        """
        technique_file = self.docs_dir / "techniques" / f"{name}.md"
        if not technique_file.exists():
            raise FileNotFoundError(f"未找到技法文件: {technique_file}")
        return technique_file.read_text(encoding="utf-8")

    def load_all_techniques(self) -> dict[str, str]:
        """加载所有技法参考"""
        techniques_dir = self.docs_dir / "techniques"
        if not techniques_dir.exists():
            return {}
        return {
            p.stem: p.read_text(encoding="utf-8")
            for p in techniques_dir.glob("*.md")
        }

    # =====================================================================
    # 动态知识库（写作过程中逐步构建）
    # =====================================================================

    def _dynamic_dir(self) -> Path:
        d = self.docs_dir / "dynamic"
        d.mkdir(exist_ok=True)
        (d / "chapters").mkdir(exist_ok=True)
        return d

    def save_dynamic(self, name: str, content: str, append: bool = False) -> None:
        """
        保存动态知识。
        append=True 时追加到现有文件（用 --- 分隔），否则覆盖。
        """
        dyn_dir = self._dynamic_dir()
        path = dyn_dir / f"{name}.md"
        if append and path.exists():
            existing = path.read_text(encoding="utf-8").strip()
            content = existing + "\n\n---\n\n" + content
        path.write_text(content, encoding="utf-8")

    def load_dynamic(self, name: str) -> str:
        """加载动态知识"""
        path = self._dynamic_dir() / f"{name}.md"
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""

    def load_all_dynamic(self) -> dict[str, str]:
        """加载所有动态知识"""
        dyn_dir = self._dynamic_dir()
        result = {}
        for p in sorted(dyn_dir.glob("*.md")):
            if p.stem != "chapters":
                result[p.stem] = p.read_text(encoding="utf-8")
        # 加载章节动态
        ch_dir = dyn_dir / "chapters"
        if ch_dir.exists():
            chapters = []
            for p in sorted(ch_dir.glob("*.md")):
                chapters.append(f"## 第{p.stem}章\n\n{p.read_text(encoding='utf-8')}")
            if chapters:
                result["chapters"] = "\n\n".join(chapters)
        return result


def update_dynamic_knowledge(state_data) -> None:
    """
    从当前状态提取已确认的信息，更新动态知识库。
    在每次用户确认后调用。
    """
    from ..state.state_types import WriteSyncState
    if not isinstance(state_data, WriteSyncState):
        return

    kb = get_knowledge_base()
    parts = []

    # 故事核心
    if state_data.story and state_data.story.confirmed_at:
        s1 = state_data.story.step1
        s2 = state_data.story.step2
        parts.append(f"**一句话**：{s1.one_sentence}（{s1.tag}）")
        parts.append(f"**五句话**：")
        parts.append(f"  1. {s2.setup}")
        parts.append(f"  2. {s2.inciting}")
        parts.append(f"  3. {s2.rising}")
        parts.append(f"  4. {s2.climax_prep}")
        parts.append(f"  5. {s2.resolution}")
        if s2.theme:
            parts.append(f"**主题**：{s2.theme}")
        if state_data.story.expanded_paragraphs:
            parts.append(f"**扩展段落**：")
            for i, p in enumerate(state_data.story.expanded_paragraphs):
                parts.append(f"  第{i+1}段：{p[:200]}...")
        kb.save_dynamic("story", "\n".join(parts))

    # 角色
    if state_data.characters and state_data.characters.confirmed_at:
        char_lines = []
        for c in state_data.characters.characters:
            char_lines.append(f"### {c.name}（{c.role}）")
            char_lines.append(f"- 身份：{c.identity}")
            char_lines.append(f"- 性格：{c.personality}")
            char_lines.append(f"- 目标：{c.goal}")
            char_lines.append(f"- 冲突：{c.conflict}")
            if c.gold_finger:
                char_lines.append(f"- 金手指：{c.gold_finger}")
            if c.arc:
                char_lines.append(f"- 弧线：{c.arc.start_state} → {c.arc.end_state}")
            char_lines.append("")
        kb.save_dynamic("characters", "\n".join(char_lines))

    # 世界观
    if state_data.world and state_data.world.confirmed_at:
        w = state_data.world
        world_lines = [f"**力量体系**：{w.power_system.system_name}"]
        world_lines.append(f"**等级**：{'、'.join(w.power_system.tiers)}")
        world_lines.append(f"**修炼规则**：{w.power_system.cultivation_rules}")
        if w.geography.major_locations:
            world_lines.append(f"\n**地理**：")
            for loc in w.geography.major_locations:
                world_lines.append(f"- {loc.get('name', '?')}：{loc.get('description', '')[:80]}")
        if w.society.factions:
            world_lines.append(f"\n**势力**：")
            for f in w.society.factions:
                world_lines.append(f"- {f.get('name', '?')}（{f.get('align', '')}）")
        kb.save_dynamic("world", "\n".join(world_lines))

    # 章纲
    if state_data.chapter_outline and state_data.chapter_outline.confirmed_at:
        o = state_data.chapter_outline
        ol_lines = [f"**总章数**：{o.total_chapters}"]
        ol_lines.append(f"**计划字数**：{o.word_count_plan}")
        for ch in o.chapters[:10]:  # 前10章
            ol_lines.append(f"- 第{ch.chapter_number}章：{ch.chapter_title} — {ch.core_event[:60]}")
        if o.pov_strategy_note:
            ol_lines.append(f"\n**POV 策略**：{o.pov_strategy_note}")
        kb.save_dynamic("outline", "\n".join(ol_lines))

    # 已完成的章节（逐章追加）
    if state_data.drafts and state_data.drafts.chapters:
        ch_dir = kb._dynamic_dir() / "chapters"
        for ch_num, cd in state_data.drafts.chapters.items():
            if cd.stage == "final":
                content = cd.final.content if cd.final else ""
                if content:
                    preview = content[:500].replace("\n", "\n  ")
                    ch_content = f"字数：{cd.word_count}\n\n{preview}..."
                    (ch_dir / f"{ch_num:03d}.md").write_text(ch_content, encoding="utf-8")


# 全局实例
_kb: Optional[KnowledgeBase] = None


def get_knowledge_base() -> KnowledgeBase:
    """获取全局知识库实例"""
    global _kb
    if _kb is None:
        _kb = KnowledgeBase()
    return _kb
