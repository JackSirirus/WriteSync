"""
test_doc_importer.py — 文档导入解析器测试

测试 DocumentParser 的 Markdown / Plaintext / DOCX 解析、
设定检测、材料回落、边界情况。
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

from src.utils.doc_importer import (
    DocumentParser,
    ImportResult,
    _Section,
    _classify_sections,
    _auto_tag,
    _is_setting,
    _looks_like_chapter,
    _split_by_markdown_headings,
    _split_by_chapter_patterns,
    _split_by_blank_lines,
)

# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def parser():
    return DocumentParser()


# ═══════════════════════════════════════════════════════════════
# ImportResult dataclass
# ═══════════════════════════════════════════════════════════════

class TestImportResult:
    def test_to_dict_roundtrip(self):
        result = ImportResult(
            chapters=[{"title": "第一章", "content": "正文", "chapter_num": 1}],
            settings=[{"type": "worldbuilding", "name": "力量体系", "content": "九级"}],
            materials=[{"title": "参考", "content": "灵感笔记", "tags": ["灵感"]}],
            metadata={"source_filename": "test.md", "total_chars": 100},
        )
        d = result.to_dict()
        restored = ImportResult.from_dict(d)
        assert restored.chapters == result.chapters
        assert restored.settings == result.settings
        assert restored.materials == result.materials
        assert restored.metadata == result.metadata

    def test_from_dict_empty(self):
        result = ImportResult.from_dict({})
        assert result.chapters == []
        assert result.settings == []
        assert result.materials == []
        assert result.metadata == {}

    def test_is_empty(self):
        assert ImportResult().is_empty()
        assert not ImportResult(
            chapters=[{"title": "x", "content": "y", "chapter_num": 1}]
        ).is_empty()


# ═══════════════════════════════════════════════════════════════
# Markdown Parsing
# ═══════════════════════════════════════════════════════════════

class TestMarkdownParsing:
    def test_multiple_h1_chapters(self, parser):
        content = """# 第一章 开端

这是一章的内容。

# 第二章 发展

这是二章的内容。

# 第三章 结局

这是三章的内容。"""
        result = parser.parse(content, "story.md")
        assert len(result.chapters) == 3
        assert result.chapters[0]["title"] == "第一章 开端"
        assert result.chapters[0]["chapter_num"] == 1
        assert "这是一章的内容" in result.chapters[0]["content"]
        assert result.chapters[1]["title"] == "第二章 发展"
        assert result.chapters[1]["chapter_num"] == 2
        assert result.chapters[2]["title"] == "第三章 结局"
        assert result.chapters[2]["chapter_num"] == 3

    def test_h2_headings_become_chapters(self, parser):
        content = """# 我的小说

## 第一章

正文一。

## 第二章

正文二。"""
        result = parser.parse(content, "novel.md")
        # H1 "我的小说" 是书名（not a chapter），H2 是章节
        assert len(result.chapters) == 2
        assert result.chapters[0]["title"] == "第一章"
        assert result.chapters[1]["title"] == "第二章"
        # H1 "我的小说" 成为材料
        material_titles = [m["title"] for m in result.materials]
        assert "我的小说" in material_titles

    def test_settings_detection_in_markdown(self, parser):
        content = """# 世界观设定

这个世界有三大种族：人类、精灵、矮人。
力量体系分为九级。"""
        result = parser.parse(content, "world.md")
        assert len(result.settings) == 1
        assert result.settings[0]["type"] == "worldbuilding"
        assert "世界观设定" in result.settings[0]["name"]

    def test_mixed_chapters_and_settings(self, parser):
        content = """# 角色设定

主角林风，坚韧果敢。

# 力量体系

修炼分为九级。

# 第一章 觉醒

林风在末世中觉醒了能力。"""
        result = parser.parse(content, "mixed.md")
        assert len(result.chapters) == 1  # "第一章 觉醒" 是章节
        assert len(result.settings) >= 1  # "力量体系" 是设定
        assert len(result.materials) >= 0  # "角色设定" 可能是材料
        # 验证章节
        chapter_titles = [c["title"] for c in result.chapters]
        assert "第一章 觉醒" in chapter_titles
        # 验证设定
        setting_names = [s["name"] for s in result.settings]
        assert any("力量体系" in n for n in setting_names)

    def test_single_heading_no_chapter_pattern(self, parser):
        content = """# 灵感笔记

这是我在路上想到的一些点子。"""
        result = parser.parse(content, "note.md")
        # 没有章节特征 → 应该是材料
        assert len(result.materials) >= 1
        material_titles = [m["title"] for m in result.materials]
        assert "灵感笔记" in material_titles


# ═══════════════════════════════════════════════════════════════
# Plaintext Parsing
# ═══════════════════════════════════════════════════════════════

class TestPlaintextParsing:
    def test_di_x_zhang_pattern(self, parser):
        content = """第1章 序章

这个世界已经毁灭了三次。

第2章 觉醒

林风睁开眼睛，发现自己躺在一片废墟中。

第3章 逃离

他必须在天黑之前离开这里。"""
        result = parser.parse(content, "story.txt")
        assert len(result.chapters) == 3
        assert "第1章 序章" in result.chapters[0]["title"]
        assert result.chapters[0]["chapter_num"] == 1
        assert result.chapters[1]["chapter_num"] == 2
        assert result.chapters[2]["chapter_num"] == 3

    def test_chinese_numeral_sections(self, parser):
        content = """一、项目背景

这是背景描述。

二、核心目标

这是目标描述。"""
        result = parser.parse(content, "plan.txt")
        assert len(result.chapters) >= 2
        titles = [c["title"] for c in result.chapters]
        assert any("一、" in t for t in titles)
        assert any("二、" in t for t in titles)

    def test_no_structure_fallback_to_materials(self, parser):
        content = """这是一段没有任何章节结构的纯文本。
它可能是一些笔记或者灵感记录。
需要被归类为参考资料。"""
        result = parser.parse(content, "notes.txt")
        # 无章节 → 应为 materials
        assert len(result.chapters) == 0
        assert len(result.materials) >= 1

    def test_blank_line_grouping(self, parser):
        content = """项目简介

这是项目的简单介绍。

参考资料

一些重要的参考链接和文档。"""
        result = parser.parse(content, "info.txt")
        # 应有 section（通过空行分割）
        assert (len(result.chapters) + len(result.materials) + len(result.settings)) >= 1

    def test_metadata_txt(self, parser):
        content = "Hello World"
        result = parser.parse(content, "test.txt")
        assert result.metadata["source_filename"] == "test.txt"
        assert result.metadata["detected_format"] == "txt"
        assert result.metadata["total_chars"] == 11


# ═══════════════════════════════════════════════════════════════
# Settings Detection
# ═══════════════════════════════════════════════════════════════

class TestSettingsDetection:
    def test_worldbuilding_keyword(self, parser):
        content = """# 世界观

这是一个修真世界。灵气充沛，万物有灵。"""
        result = parser.parse(content, "world.md")
        assert len(result.settings) >= 1
        assert result.settings[0]["type"] == "worldbuilding"

    def test_power_system_keyword(self, parser):
        content = """# 力量体系

修炼者分为：炼气、筑基、金丹、元婴、化神。"""
        result = parser.parse(content, "power.md")
        assert len(result.settings) >= 1

    def test_race_keyword(self, parser):
        content = """# 种族设定

这个世界存在三大种族：人族、妖族、魔族。"""
        result = parser.parse(content, "race.md")
        assert len(result.settings) >= 1

    def test_faction_keyword(self, parser):
        content = """# 势力分布

青云宗：正道第一大宗门。
魔教：暗中操控各国朝廷。"""
        result = parser.parse(content, "faction.md")
        assert len(result.settings) >= 1

    def test_is_setting_helper(self):
        assert _is_setting("世界观设定说明")
        assert _is_setting("力量体系简介")
        assert _is_setting("种族与势力划分")
        assert _is_setting("能力等级说明")
        assert not _is_setting("第一章 开端")
        assert not _is_setting("普通笔记内容")


# ═══════════════════════════════════════════════════════════════
# Chapter Detection Helpers
# ═══════════════════════════════════════════════════════════════

class TestChapterDetection:
    def test_looks_like_chapter_true(self):
        assert _looks_like_chapter("第1章", "")
        assert _looks_like_chapter("第一章", "")
        assert _looks_like_chapter("Chapter 1", "")
        assert _looks_like_chapter("Part 3", "")

    def test_looks_like_chapter_false(self):
        assert not _looks_like_chapter("世界观设定", "")
        assert not _looks_like_chapter("参考资料", "")

    def test_split_markdown_headings(self):
        content = """# Title

body1

## Sub

body2"""
        sections = _split_by_markdown_headings(content)
        assert len(sections) == 2
        assert sections[0].title == "Title"
        assert sections[1].title == "Sub"

    def test_split_markdown_no_headings(self):
        content = "Just plain text without headings."
        sections = _split_by_markdown_headings(content)
        assert sections == []

    def test_split_chapter_patterns(self):
        content = """第1章 开始

正文内容

第2章 继续

更多内容"""
        sections = _split_by_chapter_patterns(content)
        assert len(sections) == 2
        assert "第1章" in sections[0].title
        assert "第2章" in sections[1].title
        assert "正文内容" in sections[0].content

    def test_split_chapter_patterns_none(self):
        content = "这是没有任何章节标记的普通文本。"
        sections = _split_by_chapter_patterns(content)
        assert sections == []

    def test_split_blank_lines(self):
        content = """段落一：这是第一部分。

段落二：这是第二部分。

段落三：这是第三部分。"""
        sections = _split_by_blank_lines(content)
        assert len(sections) == 3

    def test_split_blank_lines_single_paragraph(self):
        content = "只有一段文字。"
        sections = _split_by_blank_lines(content)
        assert sections == []


# ═══════════════════════════════════════════════════════════════
# Auto-Tagging
# ═══════════════════════════════════════════════════════════════

class TestAutoTag:
    def test_character_tag(self):
        tags = _auto_tag("主角林风的角色设定，性格坚韧。", "角色卡")
        assert "角色" in tags

    def test_world_tag(self):
        tags = _auto_tag("世界观背景设定，地理环境描述。", "世界")
        assert "世界观" in tags

    def test_plot_tag(self):
        tags = _auto_tag("故事情节推进，冲突转折。", "剧情")
        assert "情节" in tags

    def test_research_tag(self):
        tags = _auto_tag("参考资料和调研数据。", "研究")
        assert "参考" in tags

    def test_inspiration_tag(self):
        tags = _auto_tag("一些灵感想法和创意点子。", "脑洞")
        assert "灵感" in tags

    def test_fallback_tag(self):
        tags = _auto_tag("xyz 123 nothing", "test")
        assert "未分类" in tags


# ═══════════════════════════════════════════════════════════════
# Classify Sections
# ═══════════════════════════════════════════════════════════════

class TestClassifySections:
    def test_classify_into_types(self):
        sections = [
            _Section(title="力量体系", content="九级修炼体系", index=0),
            _Section(title="第1章 开端", content="正文内容", index=1),
            _Section(title="灵感笔记", content="一些想法", index=2),
        ]
        result = _classify_sections(sections)
        assert len(result.settings) >= 1
        assert len(result.chapters) >= 1
        assert len(result.materials) >= 1

    def test_all_materials_when_no_chapter_no_setting(self):
        sections = [
            _Section(title="笔记一", content="内容一", index=0),
            _Section(title="笔记二", content="内容二", index=1),
        ]
        result = _classify_sections(sections)
        assert result.chapters == []
        assert result.settings == []
        assert len(result.materials) == 2

    def test_promote_materials_to_chapters(self):
        sections = [
            _Section(title="第1章", content="第一章内容", index=0),
            _Section(title="第2章", content="第二章内容", index=1),
        ]
        result = _classify_sections(sections)
        assert len(result.chapters) == 2
        # 被提升为章节后，materials 应为空
        assert len(result.materials) == 0


# ═══════════════════════════════════════════════════════════════
# Edge Cases
# ═══════════════════════════════════════════════════════════════

class TestEdgeCases:
    def test_empty_content(self, parser):
        result = parser.parse("", "empty.txt")
        assert result.chapters == []
        assert result.settings == []
        assert result.materials == []
        assert result.is_empty()

    def test_whitespace_only(self, parser):
        result = parser.parse("   \n\n  \n", "blank.txt")
        assert result.chapters == []
        assert result.settings == []
        assert result.materials == []

    def test_missing_filename(self, parser):
        result = parser.parse("Hello World")
        assert result.metadata["source_filename"] == "(raw text)"
        assert result.metadata["detected_format"] == "text"

    def test_large_file_warning(self, parser, caplog):
        import logging
        caplog.set_level(logging.WARNING, logger="writesync")
        # 生成 >100KB 的内容
        large_content = "第1章\n" + "x" * (110 * 1024)
        result = parser.parse(large_content, "large.txt")
        assert result.chapters or result.materials  # 应有产出
        # 检查警告日志
        warnings = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
        assert any(">100KB" in str(w) for w in warnings)

    def test_parse_file_not_found(self, parser):
        result = parser.parse_file("/nonexistent/file.md")
        assert "error" in result.metadata

    def test_parse_file_unsupported_type(self, parser):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF-1.4")
            fpath = f.name
        try:
            result = parser.parse_file(fpath)
            assert "error" in result.metadata
            assert "不支持" in result.metadata["error"]
        finally:
            os.unlink(fpath)

    def test_non_docx_binary(self, parser):
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
            f.write(b"\x00\x01\x02")
            fpath = f.name
        try:
            result = parser.parse_file(fpath)
            assert "error" in result.metadata
        finally:
            os.unlink(fpath)


# ═══════════════════════════════════════════════════════════════
# File-based Parsing (parse_file)
# ═══════════════════════════════════════════════════════════════

class TestParseFile:
    def test_parse_md_file(self, parser):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8",
        ) as f:
            f.write("# 第一章\n\n内容。\n\n# 世界观设定\n\n这是设定。")
            fpath = f.name
        try:
            result = parser.parse_file(fpath)
            assert result.metadata["source_filename"].endswith(".md")
            assert result.metadata["detected_format"] == "md"
        finally:
            os.unlink(fpath)

    def test_parse_txt_file(self, parser):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8",
        ) as f:
            f.write("第1章 序\n\n正文")
            fpath = f.name
        try:
            result = parser.parse_file(fpath)
            assert result.metadata["detected_format"] == "txt"
        finally:
            os.unlink(fpath)


# ═══════════════════════════════════════════════════════════════
# DOCX Parsing (with zipfile fallback)
# ═══════════════════════════════════════════════════════════════

class TestDocxParsing:
    def test_invalid_zip_as_docx(self, parser):
        """非 ZIP 的 .docx 文件返回错误。"""
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
            f.write(b"This is not a valid docx zip file")
            fpath = f.name
        try:
            result = parser._parse_docx_via_zipfile(fpath, Path(fpath), 100)
            assert "error" in result.metadata
        finally:
            os.unlink(fpath)

    def test_valid_docx_zipfile(self, parser):
        """模拟 docx 内部结构的最小 ZIP。"""
        # 构造最小 docx: 含 word/document.xml
        import zipfile
        doc_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:body>'
            '<w:p><w:r><w:t>第一章</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>正文内容</w:t></w:r></w:p>'
            '</w:body>'
            '</w:document>'
        )
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
            with zipfile.ZipFile(f, "w") as zf:
                zf.writestr("word/document.xml", doc_xml)
            fpath = f.name
        try:
            result = parser._parse_docx_via_zipfile(fpath, Path(fpath), 500)
            # 应成功解析（标题启发式可能将其识别为章节或材料）
            assert not result.is_empty() or "error" not in result.metadata
        finally:
            os.unlink(fpath)

    def test_docx_fallback_no_document_xml(self, parser):
        """ZIP 中没有 word/document.xml。"""
        import zipfile
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
            with zipfile.ZipFile(f, "w") as zf:
                zf.writestr("some_other_file.txt", "hello")
            fpath = f.name
        try:
            result = parser._parse_docx_via_zipfile(fpath, Path(fpath), 500)
            assert "error" in result.metadata
            assert "缺少" in result.metadata["error"]
        finally:
            os.unlink(fpath)

    def test_docx_empty_content(self, parser):
        """ZIP 中的 word/document.xml 无正文。"""
        import zipfile
        doc_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:body></w:body>'
            '</w:document>'
        )
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
            with zipfile.ZipFile(f, "w") as zf:
                zf.writestr("word/document.xml", doc_xml)
            fpath = f.name
        try:
            result = parser._parse_docx_via_zipfile(fpath, Path(fpath), 500)
            assert result.is_empty()
        finally:
            os.unlink(fpath)

    def test_docx_multiple_paragraphs(self, parser):
        """多段落 docx 解析，标题启发式。"""
        import zipfile
        doc_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:body>'
            '<w:p><w:r><w:t>世界观设定</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>这是一个奇幻世界。</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>第一章 序</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>很长很长的正文内容，足够长以使其不被标题启发式误判。</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>继续写正文，让它看起来更像段落而不是标题。</w:t></w:r></w:p>'
            '</w:body>'
            '</w:document>'
        )
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
            with zipfile.ZipFile(f, "w") as zf:
                zf.writestr("word/document.xml", doc_xml)
            fpath = f.name
        try:
            result = parser._parse_docx_via_zipfile(fpath, Path(fpath), 500)
            # 应有产出（章节或材料）
            total = len(result.chapters) + len(result.settings) + len(result.materials)
            assert total > 0
        finally:
            os.unlink(fpath)


# ═══════════════════════════════════════════════════════════════
# Metadata & Edge Counting
# ═══════════════════════════════════════════════════════════════

class TestMetadata:
    def test_metadata_fields(self, parser):
        content = "# 测试\n\n正文\n"
        result = parser.parse(content, "test.md")
        assert "source_filename" in result.metadata
        assert "total_chars" in result.metadata
        assert "detected_format" in result.metadata
        assert "word_count" in result.metadata
        assert "file_size" in result.metadata

    def test_chapter_num_sequential(self, parser):
        content = """# 第一章

内容一

# 第二章

内容二

# 第三章

内容三"""
        result = parser.parse(content, "book.md")
        nums = [c["chapter_num"] for c in result.chapters]
        assert nums == [1, 2, 3]


# ═══════════════════════════════════════════════════════════════
# real-world edge: mixed headings and no chapters detected
# ═══════════════════════════════════════════════════════════════

class TestRealWorldEdgeCases:
    def test_only_settings_no_chapters(self, parser):
        content = """# 世界观设定

灵气复苏的世界。

# 力量体系

炼气、筑基、金丹。"""
        result = parser.parse(content, "world.md")
        assert len(result.chapters) == 0
        assert len(result.settings) >= 2
        assert all(s["type"] == "worldbuilding" for s in result.settings)

    def test_only_materials_no_structure(self, parser):
        content = "随手写的灵感记录，没有任何章节结构。"
        result = parser.parse(content, "scribble.txt")
        assert len(result.chapters) == 0
        assert len(result.settings) == 0
        assert len(result.materials) >= 1

    def test_chapter_with_settings_mixed(self, parser):
        content = """# 种族设定

三个种族。

# 第一章

故事开始。"""
        result = parser.parse(content, "mixed.md")
        # "种族设定" → setting
        # "第一章" → chapter
        assert len(result.settings) >= 1
        assert len(result.chapters) == 1
