"""
Doc Importer — Phase 6 文档导入模块

import_document(file_path, project_id) → dict with:
  {sections: [{title, content, type}], word_count, metadata}

Supports: .md (split by ## headings), .txt (split by blank lines),
           .docx (python-docx if installed, else friendly error)
"""

import logging
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger("writesync")


def import_document(file_path: str, project_id: str = "") -> dict:
    """Import a document file and return structured sections.

    Returns:
        dict with keys: sections, word_count, metadata
    """
    fpath = Path(file_path)
    if not fpath.exists():
        return {"error": f"文件不存在: {file_path}", "sections": [], "word_count": 0, "metadata": {}}

    suffix = fpath.suffix.lower()

    if suffix == ".md" or suffix == ".markdown":
        return _import_markdown(fpath, project_id)
    elif suffix == ".txt":
        return _import_txt(fpath, project_id)
    elif suffix == ".docx":
        return _import_docx(fpath, project_id)
    else:
        return {
            "error": f"不支持的文件类型: {suffix}（支持 .md .txt .docx）",
            "sections": [],
            "word_count": 0,
            "metadata": {"file_name": fpath.name, "file_size": _readable_size(fpath)},
        }


def _import_markdown(fpath: Path, project_id: str) -> dict:
    """Parse .md file: split by ## headings."""
    try:
        content = fpath.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return {"error": f"读取文件失败: {e}", "sections": [], "word_count": 0, "metadata": {}}

    # Split by ## headings (levels 1-3)
    sections = []
    # Pattern: lines starting with #, ##, or ###
    heading_pat = re.compile(r'^(#{1,3})\s+(.*?)$', re.MULTILINE)

    # Find all heading positions
    headings = []
    for m in heading_pat.finditer(content):
        level = len(m.group(1))
        title = m.group(2).strip()
        headings.append((m.start(), level, title))

    if not headings:
        # No headings: entire file as one section
        sections.append({
            "title": fpath.stem,
            "content": content[:5000],
            "type": _guess_type(content, fpath.stem),
        })
    else:
        for i, (pos, level, title) in enumerate(headings):
            # Content from this heading to next heading (or end)
            end = headings[i + 1][0] if i + 1 < len(headings) else len(content)
            body = content[pos:end].strip()

            # Remove the heading line itself
            header_line = '#' * level + ' ' + title
            if body.startswith(header_line):
                body = body[len(header_line):].strip()

            sections.append({
                "title": title,
                "content": body[:5000],
                "type": _guess_type(body + ' ' + title, title),
            })

    total_chars = len(content)
    word_count = _count_chinese_chars(content)

    return {
        "sections": sections,
        "word_count": word_count,
        "metadata": {
            "file_name": fpath.name,
            "file_size": _readable_size(fpath),
            "format": "markdown",
            "total_chars": total_chars,
        },
    }


def _import_txt(fpath: Path, project_id: str) -> dict:
    """Parse .txt file: split by blank lines or fixed chunk size."""
    try:
        content = fpath.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return {"error": f"读取文件失败: {e}", "sections": [], "word_count": 0, "metadata": {}}

    sections = []

    # Try splitting by blank lines (paragraphs)
    paragraphs = [p.strip() for p in re.split(r'\n\s*\n', content) if p.strip()]

    if len(paragraphs) > 1:
        # Group paragraphs into sections of ~2000 chars
        current_section = ""
        section_idx = 1
        for para in paragraphs:
            if len(current_section) + len(para) > 3000 and current_section:
                sections.append({
                    "title": f"{fpath.stem} - 第{section_idx}节",
                    "content": current_section[:5000],
                    "type": _guess_type(current_section, f"{fpath.stem}_{section_idx}"),
                })
                current_section = para
                section_idx += 1
            else:
                if current_section:
                    current_section += "\n\n" + para
                else:
                    current_section = para

        if current_section:
            sections.append({
                "title": f"{fpath.stem} - 第{section_idx}节",
                "content": current_section[:5000],
                "type": _guess_type(current_section, f"{fpath.stem}_{section_idx}"),
            })
    else:
        # Single chunk
        sections.append({
            "title": fpath.stem,
            "content": content[:5000],
            "type": _guess_type(content, fpath.stem),
        })

    word_count = _count_chinese_chars(content)

    return {
        "sections": sections,
        "word_count": word_count,
        "metadata": {
            "file_name": fpath.name,
            "file_size": _readable_size(fpath),
            "format": "text",
            "total_chars": len(content),
        },
    }


def _import_docx(fpath: Path, project_id: str) -> dict:
    """Parse .docx file using python-docx."""
    try:
        from docx import Document
    except ImportError:
        return {
            "error": "需要安装 python-docx 才能导入 .docx 文件。请运行: pip install python-docx",
            "sections": [],
            "word_count": 0,
            "metadata": {"file_name": fpath.name, "file_size": _readable_size(fpath)},
        }

    try:
        doc = Document(str(fpath))
        sections = []
        current_title = fpath.stem
        current_body = ""

        for para in doc.paragraphs:
            text = para.text.strip()
            if not text:
                continue
            # Check if this is a heading-like paragraph
            if para.style and para.style.name and para.style.name.startswith("Heading"):
                if current_body:
                    sections.append({
                        "title": current_title,
                        "content": current_body[:5000],
                        "type": _guess_type(current_body, current_title),
                    })
                current_title = text
                current_body = ""
            else:
                if current_body:
                    current_body += "\n" + text
                else:
                    current_body = text

        if current_body:
            sections.append({
                "title": current_title,
                "content": current_body[:5000],
                "type": _guess_type(current_body, current_title),
            })

        # If no sections found, put whole document as one
        if not sections:
            full_text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
            sections.append({
                "title": fpath.stem,
                "content": full_text[:5000],
                "type": _guess_type(full_text, fpath.stem),
            })

        full_text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        word_count = _count_chinese_chars(full_text)

        return {
            "sections": sections,
            "word_count": word_count,
            "metadata": {
                "file_name": fpath.name,
                "file_size": _readable_size(fpath),
                "format": "docx",
                "total_chars": len(full_text),
            },
        }
    except Exception as e:
        logger.exception("Failed to import docx: %s", fpath)
        return {"error": f"导入 .docx 文件失败: {e}", "sections": [], "word_count": 0, "metadata": {}}


# ── Helpers ──

def _count_chinese_chars(text: str) -> int:
    """Count approximate Chinese word count (characters + spaces)."""
    return len(text.replace('\n', '').replace('\r', ''))


def _readable_size(fpath: Path) -> str:
    """Return human-readable file size."""
    try:
        size = fpath.stat().st_size
        for unit in ['B', 'KB', 'MB']:
            if size < 1024:
                return f"{size:.0f}{unit}"
            size /= 1024
        return f"{size:.1f}GB"
    except Exception:
        return "未知"


def _guess_type(text: str, title: str) -> str:
    """Guess reference type from content hints."""
    hints = {
        "setting": ["世界", "设定", "世界观", "地理", "环境", "背景", "体系", "规则"],
        "character": ["角色", "人物", "主角", "反派", "配角", "性格", "身份", "关系"],
        "plot": ["情节", "剧情", "故事", "事件", "冲突", "转折", "高潮", "结局"],
        "research": ["参考", "研究", "资料", "来源", "数据", "分析", "调研"],
    }
    combined = (text[:200] + ' ' + title).lower()
    for ref_type, keywords in hints.items():
        if any(kw in combined for kw in keywords):
            return ref_type
    return "note"
