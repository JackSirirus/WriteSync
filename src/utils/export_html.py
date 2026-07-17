"""
HTML Export (Phase 5)

Export all chapters as a formatted HTML book with CSS styling.

Usage:
    from src.utils.export_html import export_to_html
    export_to_html(ws_state, "my_novel.html")
"""

import os
from datetime import datetime
from ..state.state_types import WriteSyncState


_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@400;700&display=swap');

  * {{ margin: 0; padding: 0; box-sizing: border-box; }}

  body {{
    font-family: "Noto Serif SC", "Source Han Serif SC", "SimSun", serif;
    max-width: 800px;
    margin: 0 auto;
    padding: 2em 1.5em;
    background: #fdfbf7;
    color: #2c2c2c;
    line-height: 1.8;
  }}

  h1 {{
    text-align: center;
    font-size: 2em;
    margin-bottom: 0.5em;
    letter-spacing: 0.05em;
  }}

  .meta {{
    text-align: center;
    color: #888;
    font-size: 0.9em;
    margin-bottom: 3em;
  }}

  h2 {{
    margin-top: 2.5em;
    padding-bottom: 0.3em;
    border-bottom: 2px solid #d4a574;
    font-size: 1.5em;
    color: #8b5e3c;
  }}

  .chapter-content {{
    text-indent: 2em;
    margin-top: 1em;
    line-height: 2;
  }}

  .chapter-content p {{
    margin: 0.5em 0;
  }}

  .chapter-meta {{
    font-size: 0.85em;
    color: #999;
    text-align: right;
    margin-bottom: 1em;
  }}

  .toc {{
    margin: 2em 0;
    padding: 1em;
    background: #faf5ef;
    border-radius: 8px;
  }}

  .toc h3 {{
    text-align: center;
    color: #8b5e3c;
    margin-bottom: 0.5em;
  }}

  .toc ul {{
    list-style: none;
    padding: 0;
  }}

  .toc li {{
    padding: 0.2em 0;
    border-bottom: 1px dotted #e0d5c8;
  }}

  .toc li a {{
    color: #5a3e2b;
    text-decoration: none;
  }}

  .toc li a:hover {{
    text-decoration: underline;
  }}

  .divider {{
    text-align: center;
    margin: 2em 0;
    color: #ccc;
    font-size: 1.2em;
  }}

  @media print {{
    body {{ background: white; }}
    h2 {{ page-break-before: always; }}
    h2:first-of-type {{ page-break-before: avoid; }}
  }}
</style>
</head>
<body>
<h1>{title}</h1>
<div class="meta">作者: {author} · 平台: {platform} · 导出时间: {exported_at}</div>

<div class="toc">
  <h3>目录</h3>
  <ul>
    {toc_items}
  </ul>
</div>

{chapters}

<div class="divider">— 全书完 —</div>
</body>
</html>"""


def export_to_html(state: WriteSyncState, output_path: str = "") -> str:
    """Export all chapters as a formatted HTML document.

    Args:
        state: WriteSyncState with drafts
        output_path: Target file path (auto-generated if empty)

    Returns:
        The output file path
    """
    if not output_path:
        name = state.metadata.name or "novel"
        output_path = f"{name}_{datetime.now().strftime('%Y%m%d')}.html"

    title = state.metadata.name or "未命名作品"
    author = "WriteSync"
    platform = state.metadata.platform or "—"
    exported_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Build TOC
    toc_items = []
    chapters_html = []

    if state.drafts and state.drafts.chapters:
        for ch_num in sorted(state.drafts.chapters.keys()):
            cd = state.drafts.chapters[ch_num]
            content = ""
            if cd.final and cd.final.content:
                content = cd.final.content
            elif cd.draft and cd.draft.content:
                content = cd.draft.content

            # Chapter title from chapter_outline if available
            ch_title = f"第{ch_num}章"
            if state.chapter_outline and state.chapter_outline.chapters:
                for ch in state.chapter_outline.chapters:
                    if ch.chapter_number == ch_num and ch.chapter_title:
                        ch_title = f"第{ch_num}章 {ch.chapter_title}"
                        break

            toc_items.append(
                f'<li><a href="#ch{ch_num}">{ch_title}</a> '
                f'<span style="color:#999;font-size:0.85em;">({cd.word_count}字)</span></li>'
            )

            # Format content: split paragraphs by double newlines, wrap in <p>
            paragraphs = content.split("\n\n") if content else []
            formatted_paras = []
            for para in paragraphs:
                stripped = para.strip()
                if stripped:
                    formatted_paras.append(f"<p>{stripped}</p>")

            chapters_html.append(f"""<h2 id="ch{ch_num}">{ch_title}</h2>
<div class="chapter-meta">字数: {cd.word_count}</div>
<div class="chapter-content">
{chr(10).join(formatted_paras)}
</div>""")

    # Chapter outline entries without drafts
    if state.chapter_outline and state.chapter_outline.chapters:
        for ch in state.chapter_outline.chapters:
            ch_num = ch.chapter_number
            ch_title = f"第{ch_num}章 {ch.chapter_title}" if ch.chapter_title else f"第{ch_num}章"
            # Only add to TOC if not already covered by drafts
            existing_toc_ids = {f'id="ch{n}"' for n in state.drafts.chapters.keys()} if state.drafts else set()
            ch_id = f'id="ch{ch_num}"'
            if ch_id not in existing_toc_ids:
                toc_items.append(
                    f'<li>{ch_title} <span style="color:#999;font-size:0.85em;">(章纲)</span></li>'
                )

    html = _HTML_TEMPLATE.format(
        title=title,
        author=author,
        platform=platform,
        exported_at=exported_at,
        toc_items="\n    ".join(toc_items) if toc_items else "<li>暂无内容</li>",
        chapters="\n".join(chapters_html) if chapters_html else "<p style='text-align:center;color:#999;'>暂无正文</p>",
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    return output_path
