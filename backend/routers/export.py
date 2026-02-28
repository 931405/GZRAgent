"""
export.py — 文档导出 API

POST /api/export/word           → 生成 Word（自动生成配图 + 自动查找模板）
POST /api/export/word/no-image  → 生成 Word（不生成配图，速度快）
POST /api/export/upload-template → 上传 Word 模板到 templates/ 目录
GET  /api/export/templates       → 列出已有模板
"""
import os
import shutil
import time

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from typing import Dict, Optional

from src.utils.exporter import export_to_word
from src.utils.typst_exporter import export_to_typst

router = APIRouter()

TEMPLATES_DIR = "templates"


class ExportRequest(BaseModel):
    project_type: str = "面上项目"
    research_topic: str
    draft_sections: Dict[str, str]
    generate_images: bool = True          # 是否调用大模型生成配图
    template_name: Optional[str] = None  # templates/ 下的模板文件名（不含路径）
    model_provider: Optional[str] = None # 生成配图时使用的 LLM provider


@router.post("/word")
def export_word(req: ExportRequest):
    """生成 Word 文档，默认自动生成配图并自动匹配模板。"""
    template_path = None
    if req.template_name:
        candidate = os.path.abspath(os.path.join(TEMPLATES_DIR, req.template_name))
        if os.path.exists(candidate):
            template_path = candidate

    path = export_to_word(
        project_type=req.project_type,
        topic=req.research_topic,
        drafts=req.draft_sections,
        output_dir="data",
        template_path=template_path,
        images=None,
        generate_images=req.generate_images,
        model_provider=req.model_provider,
    )
    return FileResponse(
        path=path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=f"{req.project_type}_申请书.docx",
    )


@router.post("/pdf")
def export_pdf(req: ExportRequest):
    """生成原生排版的学术 PDF 文档 (基于 Typst 引擎)。"""
    try:
        path = export_to_typst(
            project_type=req.project_type,
            topic=req.research_topic,
            drafts=req.draft_sections,
            output_dir="data",
            images=None,  # 如果有配套生成图可以在这里传入
        )
        return FileResponse(
            path=path,
            media_type="application/pdf",
            filename=f"{req.project_type}_申请书.pdf",
        )
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"PDF 导出失败: {str(e)}"})


@router.post("/word/no-image")
def export_word_no_image(req: ExportRequest):
    """快速导出（不生成配图）。"""
    req.generate_images = False
    return export_word(req)


@router.post("/upload-template")
async def upload_template(file: UploadFile = File(...)):
    """上传 Word 模板文件到 templates/ 目录。"""
    os.makedirs(TEMPLATES_DIR, exist_ok=True)
    if not file.filename.endswith(".docx"):
        return JSONResponse(
            status_code=400,
            content={"error": "仅支持 .docx 格式的模板文件"}
        )
    save_path = os.path.join(TEMPLATES_DIR, file.filename)
    content = await file.read()
    with open(save_path, "wb") as f:
        f.write(content)

    # 解析章节列表，告知前端
    try:
        from src.utils.word_template_parser import parse_word_template, invalidate_template_cache
        invalidate_template_cache(save_path)          # 清除旧缓存，强制重新识别
        result = parse_word_template(save_path, use_llm=True)
        sections = [s["name"] for s in result["sections"]]
    except Exception:
        sections = []

    return {
        "message": "模板上传成功",
        "filename": file.filename,
        "detected_sections": sections,
    }


@router.get("/templates")
def list_templates():
    """列出 templates/ 目录中的可用模板。"""
    os.makedirs(TEMPLATES_DIR, exist_ok=True)
    files = [
        f for f in os.listdir(TEMPLATES_DIR)
        if f.endswith(".docx") and not f.startswith("~")
    ]
    templates = []
    for fname in files:
        fpath = os.path.join(TEMPLATES_DIR, fname)
        try:
            from src.utils.word_template_parser import parse_word_template
            result = parse_word_template(fpath)
            sections = [s["name"] for s in result["sections"]]
        except Exception:
            sections = []
        templates.append({
            "filename": fname,
            "detected_sections": sections,
            "mtime": int(os.path.getmtime(fpath)),
        })
    return {"templates": templates}

