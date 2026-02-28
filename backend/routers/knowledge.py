"""
knowledge.py — 知识库管理 API
"""
import os
import tempfile
from fastapi import APIRouter, UploadFile, File, Form
from pydantic import BaseModel
from src.utils.rag_engine import add_document_to_kb, get_kb_stats

router = APIRouter()

SUPPORTED_EXTS = {".pdf", ".docx", ".txt", ".md"}


@router.get("/stats")
def stats():
    return get_kb_stats()


@router.post("/upload")
async def upload_files(files: list[UploadFile] = File(...)):
    results = []
    for file in files:
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in SUPPORTED_EXTS:
            results.append({"filename": file.filename, "status": "skipped", "reason": "unsupported format"})
            continue
        content = await file.read()
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        try:
            chunks = add_document_to_kb(tmp_path)
            results.append({"filename": file.filename, "status": "ok", "chunks": chunks})
        except Exception as e:
            results.append({"filename": file.filename, "status": "error", "reason": str(e)})
        finally:
            os.unlink(tmp_path)
    return {"results": results}


class ScanRequest(BaseModel):
    folder_path: str


@router.post("/scan")
def scan_folder(req: ScanRequest):
    """同步扫描（兼容旧接口）"""
    folder = req.folder_path
    if not os.path.isdir(folder):
        return {"error": f"目录不存在: {folder}"}
    
    all_files = [
        os.path.join(root, f)
        for root, _, files in os.walk(folder)
        for f in files
        if os.path.splitext(f)[1].lower() in SUPPORTED_EXTS
    ]
    
    if not all_files:
        return {"total_files": 0, "total_chunks": 0, "skipped": 0}
    
    total_chunks, skipped = 0, 0
    file_results = []
    for fp in all_files:
        try:
            c = add_document_to_kb(fp)
            total_chunks += c
            if c == 0:
                skipped += 1
            file_results.append({"file": os.path.basename(fp), "chunks": c})
        except Exception as e:
            skipped += 1
            file_results.append({"file": os.path.basename(fp), "error": str(e)})
    
    return {"total_files": len(all_files), "total_chunks": total_chunks, "skipped": skipped, "details": file_results}


@router.post("/scan_stream")
def scan_folder_stream(req: ScanRequest):
    """SSE 流式扫描知识库 — 逐文件推送进度"""
    import json
    from fastapi.responses import StreamingResponse

    folder = req.folder_path
    if not os.path.isdir(folder):
        def err_gen():
            yield f"data: {json.dumps({'type': 'error', 'message': f'目录不存在: {folder}'}, ensure_ascii=False)}\n\n"
        return StreamingResponse(err_gen(), media_type="text/event-stream")

    all_files = [
        os.path.join(root, f)
        for root, _, files in os.walk(folder)
        for f in files
        if os.path.splitext(f)[1].lower() in SUPPORTED_EXTS
    ]

    def gen():
        total = len(all_files)
        yield f"data: {json.dumps({'type': 'start', 'total': total}, ensure_ascii=False)}\n\n"

        total_chunks = 0
        skipped = 0
        for idx, fp in enumerate(all_files):
            filename = os.path.basename(fp)
            try:
                c = add_document_to_kb(fp)
                total_chunks += c
                if c == 0:
                    skipped += 1
                yield f"data: {json.dumps({'type': 'progress', 'current': idx + 1, 'total': total, 'filename': filename, 'chunks': c}, ensure_ascii=False)}\n\n"
            except Exception as e:
                skipped += 1
                yield f"data: {json.dumps({'type': 'progress', 'current': idx + 1, 'total': total, 'filename': filename, 'error': str(e)}, ensure_ascii=False)}\n\n"

        yield f"data: {json.dumps({'type': 'done', 'total_files': total, 'total_chunks': total_chunks, 'skipped': skipped}, ensure_ascii=False)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
