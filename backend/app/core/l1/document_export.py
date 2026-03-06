"""
Document Export Service — convert Markdown papers to LaTeX / PDF / DOCX.

Export pipeline:
  1. Markdown → LaTeX (built-in converter)
  2. LaTeX → PDF (requires pdflatex or xelatex on system)
  3. Markdown → DOCX (requires pandoc on system)

Falls back gracefully if external tools are not available.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import tempfile
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ExportResult(BaseModel):
    """Result of a document export operation."""
    success: bool = False
    format: str = ""
    file_path: str = ""
    file_size_bytes: int = 0
    error: str = ""


# ---------------------------------------------------------------------------
# Markdown → LaTeX converter (built-in, no external deps)
# ---------------------------------------------------------------------------

def markdown_to_latex(
    markdown_text: str,
    title: str = "",
    author: str = "",
) -> str:
    """Convert Markdown paper to a LaTeX document string."""
    lines = markdown_text.split("\n")
    latex_lines: list[str] = []

    # Preamble
    latex_lines.append(r"\documentclass[12pt,a4paper]{article}")
    latex_lines.append(r"\usepackage[utf8]{inputenc}")
    latex_lines.append(r"\usepackage[T1]{fontenc}")
    latex_lines.append(r"\usepackage{amsmath,amssymb}")
    latex_lines.append(r"\usepackage{graphicx}")
    latex_lines.append(r"\usepackage{hyperref}")
    latex_lines.append(r"\usepackage{geometry}")
    latex_lines.append(r"\geometry{margin=2.5cm}")
    latex_lines.append(r"\usepackage{natbib}")
    latex_lines.append(r"\bibliographystyle{plainnat}")
    latex_lines.append("")

    if title:
        latex_lines.append(f"\\title{{{_escape_latex(title)}}}")
    if author:
        latex_lines.append(f"\\author{{{_escape_latex(author)}}}")
    latex_lines.append(r"\date{\today}")
    latex_lines.append("")
    latex_lines.append(r"\begin{document}")
    if title:
        latex_lines.append(r"\maketitle")
    latex_lines.append("")

    in_code_block = False
    for line in lines:
        if line.strip().startswith("```"):
            if in_code_block:
                latex_lines.append(r"\end{verbatim}")
                in_code_block = False
            else:
                latex_lines.append(r"\begin{verbatim}")
                in_code_block = True
            continue

        if in_code_block:
            latex_lines.append(line)
            continue

        # Headings
        if line.startswith("# "):
            latex_lines.append(f"\\section{{{_escape_latex(line[2:].strip())}}}")
        elif line.startswith("## "):
            latex_lines.append(f"\\section{{{_escape_latex(line[3:].strip())}}}")
        elif line.startswith("### "):
            latex_lines.append(f"\\subsection{{{_escape_latex(line[4:].strip())}}}")
        elif line.startswith("#### "):
            latex_lines.append(f"\\subsubsection{{{_escape_latex(line[5:].strip())}}}")
        elif line.startswith("**关键词**") or line.startswith("**Keywords**"):
            content = line.replace("**关键词**", "").replace("**Keywords**", "").strip(": ：")
            latex_lines.append(f"\\textbf{{关键词}}：{_escape_latex(content)}")
        elif line.strip() == "":
            latex_lines.append("")
        else:
            converted = _convert_inline_markdown(line)
            latex_lines.append(converted)

    if in_code_block:
        latex_lines.append(r"\end{verbatim}")

    latex_lines.append("")
    latex_lines.append(r"\end{document}")
    return "\n".join(latex_lines)


def _escape_latex(text: str) -> str:
    """Escape special LaTeX characters."""
    replacements = {
        "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
        "_": r"\_", "{": r"\{", "}": r"\}",
        "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
    }
    for char, replacement in replacements.items():
        text = text.replace(char, replacement)
    return text


def _convert_inline_markdown(line: str) -> str:
    """Convert inline Markdown formatting to LaTeX."""
    line = re.sub(r"\*\*(.+?)\*\*", r"\\textbf{\1}", line)
    line = re.sub(r"\*(.+?)\*", r"\\textit{\1}", line)
    line = re.sub(r"`(.+?)`", r"\\texttt{\1}", line)
    line = re.sub(r"\[(\d+)\]", r"~\\cite{\1}", line)
    return line


# ---------------------------------------------------------------------------
# Export to file
# ---------------------------------------------------------------------------

async def export_to_latex(
    markdown_text: str,
    output_path: str | None = None,
    title: str = "",
    author: str = "",
) -> ExportResult:
    """Export Markdown paper to a .tex file."""
    try:
        latex_content = markdown_to_latex(markdown_text, title=title, author=author)

        if not output_path:
            fd, output_path = tempfile.mkstemp(suffix=".tex", prefix="pdmaws_")
            os.close(fd)

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(latex_content)

        return ExportResult(
            success=True,
            format="latex",
            file_path=output_path,
            file_size_bytes=os.path.getsize(output_path),
        )
    except Exception as e:
        logger.error("LaTeX export failed: %s", e)
        return ExportResult(success=False, format="latex", error=str(e))


async def export_to_pdf(
    markdown_text: str,
    output_path: str | None = None,
    title: str = "",
    author: str = "",
) -> ExportResult:
    """Export Markdown paper to PDF via LaTeX compilation.

    Requires pdflatex or xelatex on the system PATH.
    """
    latex_compiler = shutil.which("xelatex") or shutil.which("pdflatex")
    if not latex_compiler:
        return ExportResult(
            success=False, format="pdf",
            error="No LaTeX compiler found (install xelatex or pdflatex)",
        )

    try:
        tmp_dir = tempfile.mkdtemp(prefix="pdmaws_pdf_")
        tex_path = os.path.join(tmp_dir, "paper.tex")

        latex_content = markdown_to_latex(markdown_text, title=title, author=author)
        with open(tex_path, "w", encoding="utf-8") as f:
            f.write(latex_content)

        proc = await asyncio.create_subprocess_exec(
            latex_compiler, "-interaction=nonstopmode", "-output-directory", tmp_dir, tex_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=60)

        pdf_path = os.path.join(tmp_dir, "paper.pdf")
        if os.path.exists(pdf_path):
            if output_path:
                shutil.copy2(pdf_path, output_path)
                final_path = output_path
            else:
                final_path = pdf_path

            return ExportResult(
                success=True,
                format="pdf",
                file_path=final_path,
                file_size_bytes=os.path.getsize(final_path),
            )
        else:
            return ExportResult(
                success=False, format="pdf",
                error="LaTeX compilation did not produce PDF",
            )
    except asyncio.TimeoutError:
        return ExportResult(success=False, format="pdf", error="LaTeX compilation timed out")
    except Exception as e:
        logger.error("PDF export failed: %s", e)
        return ExportResult(success=False, format="pdf", error=str(e))


async def export_to_docx(
    markdown_text: str,
    output_path: str | None = None,
    title: str = "",
) -> ExportResult:
    """Export Markdown paper to DOCX via pandoc.

    Requires pandoc on the system PATH.
    """
    pandoc = shutil.which("pandoc")
    if not pandoc:
        return ExportResult(
            success=False, format="docx",
            error="pandoc not found (install pandoc for DOCX export)",
        )

    try:
        tmp_dir = tempfile.mkdtemp(prefix="pdmaws_docx_")
        md_path = os.path.join(tmp_dir, "paper.md")
        if not output_path:
            output_path = os.path.join(tmp_dir, "paper.docx")

        with open(md_path, "w", encoding="utf-8") as f:
            if title:
                f.write(f"---\ntitle: \"{title}\"\n---\n\n")
            f.write(markdown_text)

        proc = await asyncio.create_subprocess_exec(
            pandoc, md_path, "-o", output_path,
            "--from=markdown", "--to=docx",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)

        if proc.returncode == 0 and os.path.exists(output_path):
            return ExportResult(
                success=True,
                format="docx",
                file_path=output_path,
                file_size_bytes=os.path.getsize(output_path),
            )
        else:
            return ExportResult(
                success=False, format="docx",
                error=stderr.decode("utf-8", errors="replace")[:500],
            )
    except asyncio.TimeoutError:
        return ExportResult(success=False, format="docx", error="pandoc conversion timed out")
    except Exception as e:
        logger.error("DOCX export failed: %s", e)
        return ExportResult(success=False, format="docx", error=str(e))
