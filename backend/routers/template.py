"""
template.py — 模板管理 API
"""
import os
from fastapi import APIRouter, File, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from src.utils.template_manager import (
    get_template_list, get_template, save_custom_template,
    parse_docx_as_template, parse_txt_as_template,
)

router = APIRouter()


@router.get("/list")
def list_templates():
    return {"templates": get_template_list()}


@router.get("/{name}")
def get_one_template(name: str):
    tpl = get_template(name)
    if tpl is None:
        return {"error": "not found"}
    return tpl


class SaveTemplateRequest(BaseModel):
    name: str
    description: str
    sections: dict


@router.post("/save")
def save_template(req: SaveTemplateRequest):
    path = save_custom_template(req.name, req.description, req.sections)
    return {"path": path}


@router.post("/upload-file")
async def upload_template_file(file: UploadFile = File(...)):
    """
    上传模板文件（支持 .json / .docx / .txt），自动解析后保存为写作提示模板。
    返回: { name, sections_count, templates }
    """
    filename = file.filename or "未命名模板"
    stem = os.path.splitext(filename)[0]  # 去掉扩展名作模板名
    ext = os.path.splitext(filename)[1].lower()
    content = await file.read()

    try:
        if ext == ".json":
            data = __import__("json").loads(content.decode("utf-8"))
            if not isinstance(data.get("sections"), dict):
                return JSONResponse(status_code=400, content={"error": "JSON 中缺少 sections 字段"})
            tpl = {"name": data.get("name", stem), "description": data.get("description", ""), "sections": data["sections"]}

        elif ext in (".docx", ".doc"):
            tpl = parse_docx_as_template(content, stem)

        elif ext in (".txt", ".md"):
            tpl = parse_txt_as_template(content.decode("utf-8", errors="ignore"), stem)

        else:
            return JSONResponse(status_code=400, content={"error": f"不支持的文件格式: {ext}，请上传 .json / .docx / .txt"})

        save_custom_template(tpl["name"], tpl["description"], tpl["sections"])
        return {
            "name": tpl["name"],
            "sections_count": len(tpl["sections"]),
            "detected_sections": list(tpl["sections"].keys()),
            "templates": get_template_list(),
        }

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
