"""
写作规则模块 — WritingRules 数据类 + WritingRulesManager

项目级创作规则管理：视角、基调、禁忌、参考作品、自定义规则。
可注入到 Agent 系统提示中，确保所有子 Agent 遵循统一的创作规范。
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

logger = logging.getLogger("writesync")

PerspectiveType = Literal["first_person", "third_person_limited", "third_person_omniscient"]

PERSPECTIVE_LABELS: dict[str, str] = {
    "first_person": "第一人称",
    "third_person_limited": "第三人称限知",
    "third_person_omniscient": "第三人称全知",
}


@dataclass
class WritingRules:
    """项目级创作规则"""
    project_id: str = ""
    perspective: PerspectiveType = "third_person_omniscient"
    tone: str = ""                          # 基调描述
    taboos: list[str] = field(default_factory=list)       # 禁忌列表
    reference_works: list[str] = field(default_factory=list)  # 参考作品
    custom_rules: str = ""                  # 自定义规则（多行文本）

    def to_dict(self) -> dict:
        return {
            "project_id": self.project_id,
            "perspective": self.perspective,
            "tone": self.tone,
            "taboos": self.taboos,
            "reference_works": self.reference_works,
            "custom_rules": self.custom_rules,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "WritingRules":
        return cls(
            project_id=d.get("project_id", ""),
            perspective=d.get("perspective", "third_person_omniscient"),
            tone=d.get("tone", ""),
            taboos=d.get("taboos", []),
            reference_works=d.get("reference_works", []),
            custom_rules=d.get("custom_rules", ""),
        )


class WritingRulesManager:
    """写作规则管理器 — 持久化存储 + prompt 注入"""

    def __init__(self, project_dir: str):
        self._project_dir = Path(project_dir)
        self._rules_path = self._project_dir / "writing_rules.json"

    # ── CRUD ──

    def get(self, project_id: str) -> WritingRules:
        """读取规则，不存在时返回默认值"""
        if self._rules_path.exists():
            try:
                with open(self._rules_path, "r", encoding="utf-8") as f:
                    data = json.loads(f.read())
                return WritingRules.from_dict(data)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("读取写作规则失败: %s，使用默认值", e)
        return WritingRules(project_id=project_id)

    def save(self, rules: WritingRules) -> bool:
        """保存规则到磁盘"""
        try:
            self._rules_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._rules_path, "w", encoding="utf-8") as f:
                json.dump(rules.to_dict(), f, ensure_ascii=False, indent=2)
            logger.info("写作规则已保存: %s", self._rules_path)
            return True
        except OSError as e:
            logger.error("保存写作规则失败: %s", e)
            return False

    def delete(self) -> bool:
        """删除规则文件"""
        try:
            if self._rules_path.exists():
                self._rules_path.unlink()
                logger.info("写作规则已删除: %s", self._rules_path)
            return True
        except OSError as e:
            logger.error("删除写作规则失败: %s", e)
            return False

    # ── Prompt 注入 ──

    def inject_into_prompt(self, rules: WritingRules) -> str:
        """将写作规则格式化为 Agent 系统提示片段"""
        parts = []
        parts.append("## 创作规则")

        perspective_label = PERSPECTIVE_LABELS.get(rules.perspective, rules.perspective)
        parts.append(f"- 视角：{perspective_label}")

        if rules.tone:
            parts.append(f"- 基调：{rules.tone}")

        if rules.taboos:
            taboos_str = "、".join(rules.taboos)
            parts.append(f"- 禁忌：{taboos_str}")

        if rules.reference_works:
            refs_str = "、".join(rules.reference_works)
            parts.append(f"- 参考作品：{refs_str}")

        if rules.custom_rules:
            parts.append(f"- 额外规则：\n{rules.custom_rules}")

        return "\n".join(parts)

    def get_prompt_snippet(self, project_id: str) -> str:
        """快捷方法：读取规则并生成 prompt 片段"""
        rules = self.get(project_id)
        # 如果没有任何规则填充，返回空字符串（避免注入无效提示）
        if (not rules.tone and not rules.taboos
                and not rules.reference_works and not rules.custom_rules):
            return ""
        return self.inject_into_prompt(rules)
