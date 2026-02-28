import os
import hashlib
import json
from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader, TextLoader
try:
    from langchain_chroma import Chroma
except ImportError:
    from langchain_community.vectorstores import Chroma
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

# ChromaDB 持久化存储路径（嵌入结果自动持久化到此目录）
PERSIST_DIRECTORY = os.path.join(os.path.dirname(__file__), "..", "..", "data", "knowledge_base")
# 已处理文档指纹记录（防止重复嵌入）
FINGERPRINT_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "data", "knowledge_base", "processed_docs.json")

# ============= Embedding 配置 =============

def get_embeddings():
    """使用硅基流动 (SiliconFlow) 的 Qwen/Qwen3-Embedding-8B 模型。
    
    SiliconFlow 提供 OpenAI 兼容的 API 接口，因此直接通过
    langchain_openai.OpenAIEmbeddings 接入即可。
    """
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

# ============= 向量数据库（持久化） =============

def init_vectorstore():
    """初始化或加载本地 Chroma 向量数据库（自动持久化到磁盘）
    
    如果 HNSW 索引损坏，自动删除并重建。
    """
    import shutil
    persist_dir = os.path.abspath(PERSIST_DIRECTORY)
    if not os.path.exists(persist_dir):
        os.makedirs(persist_dir)
    
    embeddings = get_embeddings()
    
    try:
        store = Chroma(
            persist_directory=persist_dir,
            embedding_function=embeddings,
            collection_name="nsfc_knowledge_base"
        )
        # 测试索引是否可用
        store.similarity_search("test", k=1)
        return store
    except Exception as e:
        print(f"[RAG]: Chroma 索引损坏 ({e})，正在尝试重建...")
        try:
            # 删除损坏的数据库文件
            chroma_db = os.path.join(persist_dir, "chroma.sqlite3")
            if os.path.exists(chroma_db):
                os.remove(chroma_db)
            # 删除 HNSW 索引目录
            for item in os.listdir(persist_dir):
                item_path = os.path.join(persist_dir, item)
                if os.path.isdir(item_path) and item != '__pycache__':
                    shutil.rmtree(item_path)
            # 清除指纹记录，允许重新嵌入
            _save_fingerprints({})
            print(f"[RAG]: 已清除损坏索引，将在下次添加文档时重建。")
            return Chroma(
                persist_directory=persist_dir,
                embedding_function=embeddings,
                collection_name="nsfc_knowledge_base"
            )
        except (PermissionError, OSError) as lock_err:
            print(f"[RAG]: 文件被锁定无法删除 ({lock_err})，本次跳过本地 KB。")
            # 返回一个内存中的空向量库，不写磁盘
            return Chroma(
                embedding_function=embeddings,
                collection_name="nsfc_fallback"
            )

# ============= 文档指纹（增量更新） =============

def _load_fingerprints() -> dict:
    """加载已处理文档的指纹记录"""
    fp_path = os.path.abspath(FINGERPRINT_FILE)
    if os.path.exists(fp_path):
        with open(fp_path, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}

def _save_fingerprints(fps: dict):
    """保存文档指纹记录"""
    fp_path = os.path.abspath(FINGERPRINT_FILE)
    fp_dir = os.path.dirname(fp_path)
    if not os.path.exists(fp_dir):
        os.makedirs(fp_dir)
    with open(fp_path, "w", encoding="utf-8") as f:
        json.dump(fps, f, ensure_ascii=False, indent=2)

def _file_fingerprint(file_path: str) -> str:
    """计算文件内容的 MD5 指纹"""
    hasher = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()

# ============= 核心功能 =============

def add_document_to_kb(file_path: str, provider: str = None) -> int:
    """解析并增量添加文档到本地知识库（跳过已处理的相同文件）
    
    Args:
        file_path: 文档路径
        provider: 保留参数（兼容旧接口），实际已不使用
        
    Returns:
        新增的文档片段数量（如果文件已存在则返回 0）
    """
    # 1. 检查文件指纹，如果已处理过则跳过
    fingerprint = _file_fingerprint(file_path)
    fps = _load_fingerprints()
    
    filename = os.path.basename(file_path)
    if fingerprint in fps.values():
        print(f"-> [RAG]: 文件 '{filename}' 内容未变化，跳过重复嵌入。")
        return 0
    
    # 2. 加载文档
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
    
    # 3. 分块（使用递归字符分割器，适合中文学术文本）
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=800,
        chunk_overlap=100,
        separators=["\n\n", "\n", "。", "；", " ", ""]
    )
    documents = splitter.split_documents(raw_docs)
    
    # 4. 写入向量数据库（ChromaDB 自动持久化到 PERSIST_DIRECTORY）
    vectorstore = init_vectorstore()
    vectorstore.add_documents(documents)
    
    # 5. 记录指纹
    fps[filename] = fingerprint
    _save_fingerprints(fps)
    
    print(f"-> [RAG]: 成功将 '{filename}' 的 {len(documents)} 个片段嵌入到 Chroma（Qwen3-Embedding-8B）。")
    return len(documents)

def search_local_kb(query: str, k: int = 3, provider: str = None) -> list:
    """从本地知识库中针对 query 进行语义检索
    
    Args:
        query: 查询文本
        k: 返回 Top-K 结果
        provider: 保留参数（兼容旧接口）
        
    Returns:
        匹配到的文档列表
    """
    try:
        vectorstore = init_vectorstore()
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
    persist_dir = os.path.abspath(PERSIST_DIRECTORY)
    db_exists = os.path.exists(os.path.join(persist_dir, "chroma.sqlite3"))
    return {
        "total_files": len(fps),
        "file_names": list(fps.keys()),
        "db_persisted": db_exists,
        "persist_path": persist_dir
    }
