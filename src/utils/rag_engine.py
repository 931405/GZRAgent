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
from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader, TextLoader
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

# 持久化存储路径
PERSIST_DIRECTORY = os.path.join(os.path.dirname(__file__), "..", "..", "data", "knowledge_base")
FAISS_INDEX_PATH = os.path.join(PERSIST_DIRECTORY, "faiss_index")
FINGERPRINT_FILE = os.path.join(PERSIST_DIRECTORY, "processed_docs.json")

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
    """初始化或加载本地 FAISS 向量数据库（自动持久化到磁盘）。
    
    FAISS 不依赖 SQLite，没有文件锁和 HNSW 损坏问题。
    带有全局缓存和读写锁保证线程安全。
    """
    global _faiss_store
    with _faiss_lock:
        if _faiss_store is not None:
            return _faiss_store

        persist_dir = os.path.abspath(PERSIST_DIRECTORY)
        index_path = os.path.abspath(FAISS_INDEX_PATH)
        if not os.path.exists(persist_dir):
            os.makedirs(persist_dir)

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
                print(f"[RAG] FAISS 索引加载失败 ({e})，将重建空索引。")

        # 创建空的 FAISS 向量库（需要至少一个文档才能初始化）
        # 使用一个占位文档初始化
        from langchain_core.documents import Document
        placeholder = Document(page_content="placeholder", metadata={"source": "__init__"})
        store = FAISS.from_documents([placeholder], embeddings)
        _faiss_store = store
        print(f"[RAG] 已创建新 FAISS 索引")
        return store


def _save_faiss_index():
    """将 FAISS 索引持久化到磁盘"""
    global _faiss_store
    if _faiss_store is None:
        return
    index_path = os.path.abspath(FAISS_INDEX_PATH)
    try:
        _faiss_store.save_local(index_path)
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
    
    # 分块（语义与层级感知分割器）
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=150,
        separators=[
            "\n\n",
            "\n#",
            "```",
            "$$",
            "\n",
            "。", "！", "？", "；",
            ". ",
            " ", ""
        ],
        keep_separator=True
    )
    documents = splitter.split_documents(raw_docs)
    
    # 写入 FAISS 向量数据库
    vectorstore = init_vectorstore()
    with _faiss_lock:
        vectorstore.add_documents(documents)
        _save_faiss_index()
    
    # 记录指纹
    fps[filename] = fingerprint
    _save_fingerprints(fps)
    
    print(f"-> [RAG]: 成功将 '{filename}' 的 {len(documents)} 个片段嵌入到 FAISS（Qwen3-Embedding-8B）。")
    return len(documents)

def search_local_kb(query: str, k: int = 3, provider: str = None) -> list:
    """从本地知识库中针对 query 进行语义检索"""
    try:
        vectorstore = init_vectorstore()
        results = vectorstore.similarity_search(query, k=k)
        return [
            {
                "title": f"Local KB: {doc.metadata.get('source', 'unknown')}",
                "content": doc.page_content
            }
            for doc in results
            if doc.metadata.get("source") != "__init__"  # 排除占位文档
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
