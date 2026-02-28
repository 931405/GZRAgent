"""
typst_exporter.py — PDF 渲染引擎
基于 Typst 和 DocumentDOM，生成高品质学术排版 PDF (包含严格的数学公式和复杂三线表格)。
"""

import os
import re
import time
import typst
from typing import Dict, Any, Optional

SECTION_ORDER = [
    "立项依据",
    "研究目标与内容",
    "研究方案与可行性",
    "特色与创新",
    "研究基础",
    "参考文献",
]

def export_to_typst(
    project_type: str,
    topic: str,
    drafts: Dict[str, Any],
    output_dir: str = "data",
    images: Optional[Dict[str, str]] = None,
) -> str:
    """
    根据 DocumentDOM 导出为 Typst 源码，并调用 Typst CLI (Python 绑定) 编译为 PDF。

    Args:
        project_type: 项目类型（面上项目 / 青年基金 等）
        topic: 研究主题
        drafts: 包含 document_dom 或纯文本的状态字典
        output_dir: 导出目录
        images: 配图映射表 {section: image_path}
    """
    os.makedirs(output_dir, exist_ok=True)
    images = images or {}
    
    ts = int(time.time())
    safe_type = re.sub(r"[^\w\u4e00-\u9fff]", "_", project_type)
    typst_path = os.path.join(output_dir, f"NSFC_{safe_type}_{ts}.typ")
    pdf_path = os.path.join(output_dir, f"NSFC_{safe_type}_{ts}.pdf")
    
    # 尝试加载 DOM
    dom_cache = {}
    if isinstance(drafts, dict):
        if "_dom_cache" in drafts:
            dom_cache = drafts["_dom_cache"]
        elif "document_dom" in drafts:
            dom_cache = drafts["document_dom"]

    # 生成 typst 源码
    content_lines = [
        '#import "../templates/nsfc_template.typ": conf',
        f'#show: doc => conf(title: "{topic}", project_type: "{project_type}", doc)',
        ''
    ]

    section_keys = SECTION_ORDER + [k for k in (drafts.get("draft_sections", drafts) if isinstance(drafts, dict) else drafts) if k not in SECTION_ORDER and k != "_dom_cache" and k != "document_dom"]

    for sec in section_keys:
        # 获取对应的内容（优先 DOM，次选纯文本）
        content_lines.append(f"= {sec}")
        content_lines.append("")
        
        # 插入该章节可能的配图
        img_path = images.get(sec)
        if img_path and os.path.exists(img_path):
            # Typst 图片使用规范：转义路径的反斜杠
            safe_img_path = img_path.replace("\\", "/")
            content_lines.append(f'#figure(')
            content_lines.append(f'  image("{safe_img_path}", width: 80%),')
            content_lines.append(f'  caption: [图：{sec}技术路线图]')
            content_lines.append(f')')
            content_lines.append("")

        if sec in dom_cache:
            dom_node = dom_cache[sec]
            for element in dom_node.get("elements", []):
                el_type = element.get("type", "text") if isinstance(element, dict) else "text"
                el_content = element.get("content", "") if isinstance(element, dict) else str(element)
                if el_type == "text":
                    content_lines.append(_clean_typst_text(el_content))
                elif el_type == "table":
                    content_lines.append(_convert_markdown_table_to_typst(el_content))
                elif el_type == "formula":
                    formula_clean = el_content.strip().strip("$").strip()
                    content_lines.append(f"$ {formula_clean} $")
                elif el_type == "image":
                    if os.path.exists(el_content):
                        safe_path = el_content.replace("\\", "/")
                        content_lines.append(f'#figure(image("{safe_path}", width: 80%))')
                content_lines.append("")
        else:
            # Fallback 文本
            raw_text = drafts["draft_sections"].get(sec, "") if "draft_sections" in drafts else drafts.get(sec, "")
            content_lines.append(_clean_typst_text(raw_text))
            content_lines.append("")

    # 将 Typst 源码写入文件
    typst_source = "\n".join(content_lines)
    with open(typst_path, "w", encoding="utf-8") as f:
        f.write(typst_source)
        
    print(f"[TypstExporter] 成功生成 Typst 源文件: {typst_path}")
    
    # 编译 PDF
    try:
        print(f"[TypstExporter] 正在使用 Typst 引擎进行原生编译...")
        # 设置 root 为当前工作目录，以便跨目录引用模板
        typst.compile(typst_path, output=pdf_path, root=".")
        print(f"[TypstExporter] 编译成功，输出: {pdf_path}")
        return pdf_path
    except Exception as e:
        print(f"[TypstExporter] 编译失败: {e}")
        raise e

def _clean_typst_text(text: str) -> str:
    """清理并适配 Typst 中的 Markdown 文本"""
    # 暂时保持简单适配，因为 Typst 本身兼容很多 md 格式，如 **加粗** 和 - 列表
    # 如果文本中有大块 HTML 或未经转义的特殊字符，可能需要进一步处理 (#, $, _)
    return text

def _convert_markdown_table_to_typst(md_table: str) -> str:
    """将 Markdown 表格尝试转换为 Typst 本地表格"""
    lines = md_table.strip().split("\n")
    if len(lines) < 2:
        return md_table # 失败则原样返回
        
    # 取出表头
    headers = [col.strip() for col in lines[0].strip("|").split("|")]
    
    # 构建 #table(...)
    typst_table = [f"#table(columns: {len(headers)},"]
    
    for h in headers:
        typst_table.append(f"  [{h}],")
        
    # 跳过对齐行 (e.g. |---|---|)
    start_idx = 2 if "---" in lines[1] else 1
    
    for row in lines[start_idx:]:
        cols = [col.strip() for col in row.strip("|").split("|")]
        if not cols or all(not c for c in cols):
             continue
        for c in cols:
             # typst text escaping might be needed inside arrays
             typst_table.append(f"  [{c}],")
            
    typst_table.append(")")
    return "\n".join(typst_table)
