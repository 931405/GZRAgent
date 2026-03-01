"""
rag_engine.py — 本地 RAG 知识库引擎（FAISS 向量存储）

替代原 ChromaDB 方案，解决：
- SQLite 文件锁 ("database is locked") 
- HNSW 索引损坏
- 并发读写安全性

使用 FAISS（Facebook AI Similarity Search）作为向量后端，
支持增量添加、持久化到磁盘、以及语义检索。
"""

import os
import hashlib
import json
import threading
from dotenv import load_dotenv

load_dotenv()
from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader, TextLoader
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

# 持久化存储路径
PERSIST_DIRECTORY = os.path.join(os.path.dirname(__file__), "..", "..", "data", "knowledge_base")
FAISS_INDEX_PATH = os.path.join(PERSIST_DIRECTORY, "faiss_index")
FINGERPRINT_FILE = os.path.join(PERSIST_DIRECTORY, "processed_docs.json")

# ============= OCR Fallback（扫描 PDF） =============

def _ocr_pdf_fallback(file_path: str) -> list:
    """对扫描件 PDF 进行多线程 OCR 提取文字（PyMuPDF 渲染 + RapidOCR 并行识别）。
    
    适用于无可选择文字的纯图片 PDF。
    页面渲染在主线程完成（PyMuPDF 非线程安全），OCR 识别并发执行。
    返回 langchain Document 列表。
    """
    try:
        import fitz  # PyMuPDF
        from rapidocr_onnxruntime import RapidOCR
        from langchain_core.documents import Document
        import numpy as np
        from PIL import Image
        import io
        from concurrent.futures import ThreadPoolExecutor, as_completed
    except ImportError as e:
        print(f"[RAG-OCR] OCR 依赖缺失: {e}，跳过 OCR。")
        return []

    documents = []
    
    # 共享一个 OCR 引擎（避免每线程重复加载模型）
    _shared_ocr = RapidOCR()
    _ocr_lock = threading.Lock()
    
    def _ocr_single_page(page_img_bytes, page_num, total, src_path):
        """单页 OCR 工作函数"""
        img = Image.open(io.BytesIO(page_img_bytes))
        img_array = np.array(img)
        with _ocr_lock:
            result, _ = _shared_ocr(img_array)
        page_text = "\n".join([line[1] for line in result]) if result else ""
        chars = len(page_text.strip())
        if chars > 0:
            print(f"  [OCR] 第 {page_num + 1}/{total} 页: {chars} 字符")
            return Document(
                page_content=page_text,
                metadata={"source": src_path, "page": page_num, "method": "ocr"}
            )
        return None

    try:
        pdf = fitz.open(file_path)
        total_pages = len(pdf)
        
        # 自适应 DPI：大文件降低分辨率以节省内存和时间
        dpi = 150 if total_pages > 20 else 300
        print(f"[RAG-OCR] 扫描件 PDF 检测到 {total_pages} 页，DPI={dpi}，分批 OCR 启动...")
        
        # 分批渲染+OCR（每批最多 8 页，避免一次性渲染 128 页撑爆内存）
        BATCH_SIZE = 8
        max_workers = min(BATCH_SIZE, 4)

        for batch_start in range(0, total_pages, BATCH_SIZE):
            batch_end = min(batch_start + BATCH_SIZE, total_pages)
            print(f"  [OCR 批次] 渲染第 {batch_start+1}-{batch_end}/{total_pages} 页...")
            
            # 主线程渲染本批次页面
            page_images = []
            for i in range(batch_start, batch_end):
                pix = pdf[i].get_pixmap(dpi=dpi)
                page_images.append((pix.tobytes("png"), i))
            
            # 多线程 OCR 本批次
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                futures = {
                    pool.submit(_ocr_single_page, img, idx, total_pages, file_path): idx
                    for img, idx in page_images
                }
                for fut in as_completed(futures):
                    doc = fut.result()
                    if doc:
                        documents.append(doc)
        
        pdf.close()
        
        # 按页码排序
        documents.sort(key=lambda d: d.metadata.get("page", 0))
        print(f"[RAG-OCR] OCR 完成，共提取 {len(documents)} 页有效文字")
        
    except Exception as e:
        print(f"[RAG-OCR] OCR 处理失败: {e}")
    
    return documents

# ============= Embedding 配置 =============

def get_embeddings():
    """使用硅基流动 (SiliconFlow) 的 Qwen/Qwen3-Embedding-8B 模型。"""
    api_key = os.getenv("SILICONFLOW_API_KEY")
    base_url = os.getenv("SILICONFLOW_API_BASE", "https://api.siliconflow.cn/v1")
    model_name = os.getenv("EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-8B")
    
    if not api_key:
        raise ValueError(
            "未找到 SILICONFLOW_API_KEY。请在 .env 文件中配置：\n"
            'SILICONFLOW_API_KEY="your_siliconflow_api_key_here"'
        )
    
    return OpenAIEmbeddings(
        api_key=api_key,
        base_url=base_url,
        model=model_name,
    )

# ============= 向量数据库（FAISS 持久化） =============

_faiss_store = None
_faiss_lock = threading.Lock()

def init_vectorstore():
    """初始化或加载本地 FAISS 向量数据库。
    
    如果磁盘上存在已保存的索引则加载，否则返回 None（延迟到第一次添加文档时创建）。
    """
    global _faiss_store
    with _faiss_lock:
        if _faiss_store is not None:
            return _faiss_store

        persist_dir = os.path.abspath(PERSIST_DIRECTORY)
        index_path = os.path.abspath(FAISS_INDEX_PATH)
        if not os.path.exists(persist_dir):
            os.makedirs(persist_dir)

        # ── 一致性检查：若索引文件不存在但指纹文件有记录，清除指纹以允许重新嵌入 ──
        index_file = os.path.join(index_path, "index.faiss")
        fp_path = os.path.abspath(FINGERPRINT_FILE)
        if not os.path.exists(index_file) and os.path.exists(fp_path):
            fps = _load_fingerprints()
            if fps:
                print(f"[RAG] ⚠️ FAISS 索引不存在但指纹记录了 {len(fps)} 个文件，清除指纹以允许重建。")
                _save_fingerprints({})

        embeddings = get_embeddings()

        # 尝试加载已有索引
        if os.path.exists(index_path):
            try:
                store = FAISS.load_local(
                    index_path, embeddings,
                    allow_dangerous_deserialization=True
                )
                _faiss_store = store
                print(f"[RAG] FAISS 索引加载成功: {index_path}")
                return store
            except Exception as e:
                print(f"[RAG] FAISS 索引加载失败 ({e})，将在添加文档时重建。")

        # 不创建空索引，返回 None，延迟到第一次 add 时创建
        return None


def _save_faiss_index():
    """将 FAISS 索引持久化到磁盘"""
    global _faiss_store
    if _faiss_store is None:
        return
    index_path = os.path.abspath(FAISS_INDEX_PATH)
    try:
        os.makedirs(index_path, exist_ok=True)
        _faiss_store.save_local(index_path)
        print(f"[RAG] FAISS 索引已保存: {index_path}")
    except Exception as e:
        print(f"[RAG] FAISS 索引保存失败: {e}")


# ============= 文档指纹（增量更新） =============

def _load_fingerprints() -> dict:
    fp_path = os.path.abspath(FINGERPRINT_FILE)
    if os.path.exists(fp_path):
        with open(fp_path, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}

def _save_fingerprints(fps: dict):
    fp_path = os.path.abspath(FINGERPRINT_FILE)
    fp_dir = os.path.dirname(fp_path)
    if not os.path.exists(fp_dir):
        os.makedirs(fp_dir)
    with open(fp_path, "w", encoding="utf-8") as f:
        json.dump(fps, f, ensure_ascii=False, indent=2)

def _file_fingerprint(file_path: str) -> str:
    hasher = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()

# ============= 核心功能 =============

def add_document_to_kb(file_path: str, provider: str = None) -> int:
    """解析并增量添加文档到本地知识库（跳过已处理的相同文件）"""
    global _faiss_store
    
    fingerprint = _file_fingerprint(file_path)
    fps = _load_fingerprints()
    
    filename = os.path.basename(file_path)
    if fingerprint in fps.values():
        print(f"-> [RAG]: 文件 '{filename}' 内容未变化，跳过重复嵌入。")
        return 0
    
    # 加载文档
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".pdf":
        loader = PyPDFLoader(file_path)
    elif ext == ".docx":
        loader = Docx2txtLoader(file_path)
    elif ext in [".txt", ".md"]:
        loader = TextLoader(file_path, encoding='utf-8')
    else:
        raise ValueError(f"不支持的文件格式: {ext}")
    
    raw_docs = loader.load()
    
    # OCR Fallback: 若 PDF 提取到 0 文字（扫描件），自动使用 OCR
    total_text = sum(len(d.page_content.strip()) for d in raw_docs)
    if ext == ".pdf" and total_text == 0:
        print(f"[RAG] '{filename}' 为扫描件 PDF（0 文字），启动 OCR...")
        raw_docs = _ocr_pdf_fallback(file_path)
        if not raw_docs:
            print(f"-> [RAG]: '{filename}' OCR 后仍无内容，跳过。")
            return 0
    
    # 分块（语义与层级感知分割器）
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=150,
        separators=[
            "\n\n", "\n#", "```", "$$", "\n",
            "。", "！", "？", "；", ". ", " ", ""
        ],
        keep_separator=True
    )
    documents = splitter.split_documents(raw_docs)
    
    if not documents:
        print(f"-> [RAG]: 文件 '{filename}' 解析后无内容，跳过。")
        return 0
    
    # 写入 FAISS 向量数据库（延迟创建）
    with _faiss_lock:
        embeddings = get_embeddings()
        if _faiss_store is None:
            # 第一次添加文档 — 用真实文档初始化 FAISS
            _faiss_store = FAISS.from_documents(documents, embeddings)
            print(f"[RAG] 从 '{filename}' 创建新 FAISS 索引 ({len(documents)} 片段)")
        else:
            _faiss_store.add_documents(documents)
        _save_faiss_index()
    
    # 记录指纹
    fps[filename] = fingerprint
    _save_fingerprints(fps)
    
    print(f"-> [RAG]: 成功将 '{filename}' 的 {len(documents)} 个片段嵌入到 FAISS。")
    return len(documents)

def search_local_kb(query: str, k: int = 3, provider: str = None) -> list:
    """从本地知识库中针对 query 进行语义检索"""
    try:
        vectorstore = init_vectorstore()
        if vectorstore is None:
            print("[RAG] 知识库为空，请先添加文档。")
            return []
        results = vectorstore.similarity_search(query, k=k)
        return [
            {
                "title": f"Local KB: {doc.metadata.get('source', 'unknown')}",
                "content": doc.page_content
            }
            for doc in results
        ]
    except Exception as e:
        print(f"[RAG Error]: {e}")
        return []

def get_kb_stats() -> dict:
    """获取知识库统计信息（供前端展示）"""
    fps = _load_fingerprints()
    index_path = os.path.abspath(FAISS_INDEX_PATH)
    index_exists = os.path.exists(index_path)
    return {
        "total_files": len(fps),
        "file_names": list(fps.keys()),
        "db_persisted": index_exists,
        "persist_path": os.path.abspath(PERSIST_DIRECTORY)
    }
