import concurrent.futures
from langchain_community.utilities import ArxivAPIWrapper
from src.state import GraphState
from src.llm import get_llm
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

# 章节检索意图
SECTION_SEARCH_INTENT = {
    "立项依据": "综述型文献和前沿进展，用于论证领域重要性和现有不足",
    "研究目标与内容": "方法论型文献，用于支撑研究目标的合理性",
    "研究方案与可行性": "技术方案型文献，用于论证方法的可行性和先进性",
    "特色与创新": "对比型文献，用于凸显本方案与现有方法的差异和创新点",
    "研究基础": "团队相关成果和领域基础文献",
}


def _search_arxiv(query: str) -> list:
    """arXiv 检索"""
    arxiv = ArxivAPIWrapper(top_k_results=3, doc_content_chars_max=1000)
    try:
        arxiv_docs = arxiv.run(query)
        papers = arxiv_docs.split("\n\n")
        results = []
        for p in papers:
            if not p.strip(): continue
            results.append({"source": "arXiv", "content": p})
        return results
    except Exception as e:
        print(f"-> [Searcher-arXiv]: 检索失败 ('{query}'): {e}")
        return []


def _search_local_kb(query: str, provider: str = None) -> list:
    """本地知识库检索"""
    from src.utils.rag_engine import search_local_kb
    try:
        docs = search_local_kb(query, k=3, provider=provider)
        for d in docs:
            d["source"] = "本地知识库"
        return docs
    except Exception as e:
        print(f"-> [Searcher-KB]: 本地检索失败: {e}")
        return []


def run_searcher(state: GraphState) -> dict:
    """文献专员 (Searcher Agent) — 多关键词 + 章节意图感知版
    
    1. 根据章节意图生成 2-3 个多角度关键词
    2. 并发检索 arXiv（多关键词） + 本地 KB
    3. LLM 相关性评估，过滤低质量结果
    4. 结构化引用编号
    """
    topic = state.get("research_topic", "")
    focus = state.get("current_focus", "")
    project_type = state.get("project_type", "基金申请")
    config = state.get("model_config", {})
    llm_provider = config.get("searcher", None)
    embed_provider = config.get("embeddings", None)
    
    search_intent = SECTION_SEARCH_INTENT.get(focus, "通用学术文献")
    
    print(f"-> [Searcher]: 正在为 '{focus}' 生成多角度检索关键词...")
    
    llm = get_llm(provider_override=llm_provider, temperature=0.3)
    
    # 1. 生成 2-3 个多角度关键词
    kw_prompt = ChatPromptTemplate.from_messages([
        ("system", """你是一个资深科研文献检索专家。根据用户的研究主题和当前章节的检索意图，生成 2-3 个不同角度的英文检索关键词。

规则：
- 每个关键词是一个精确的英文短语（3-5个词），适合在 arXiv 上搜索
- 关键词之间角度要不同：一个偏综述/survey，一个偏方法/method，一个偏应用/application
- 每行一个关键词，不要编号，不要其他废话"""),
        ("user", f"研究主题: {project_type} - {topic}\n当前章节: {focus}\n检索意图: {search_intent}\n\n生成检索关键词:")
    ])
    
    kw_result = (kw_prompt | llm | StrOutputParser()).invoke({})
    keywords = [kw.strip().strip("'").strip('"').strip('-').strip() for kw in kw_result.strip().split('\n') if kw.strip()]
    keywords = keywords[:3]  # 最多3个
    
    if not keywords:
        keywords = [topic[:50]]
    
    print(f"-> [Searcher]: 生成 {len(keywords)} 个关键词: {keywords}")
    
    # 2. 并发检索：每个关键词查 arXiv + 本地 KB
    all_arxiv_results = []
    local_results = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        # 各关键词并发查 arXiv
        arxiv_futures = {executor.submit(_search_arxiv, kw): kw for kw in keywords}
        # 同时查本地 KB（用第一个关键词）
        local_future = executor.submit(_search_local_kb, keywords[0], embed_provider)
        
        for future in concurrent.futures.as_completed(arxiv_futures, timeout=30):
            try:
                results = future.result()
                all_arxiv_results.extend(results)
            except Exception as e:
                kw = arxiv_futures[future]
                print(f"-> [Searcher]: arXiv 检索 '{kw}' 异常: {e}")
        
        try:
            local_results = local_future.result(timeout=30)
        except Exception as e:
            print(f"-> [Searcher]: 本地KB 异常: {e}")
    
    # 3. 去重（基于内容前100字符）
    seen = set()
    unique_arxiv = []
    for item in all_arxiv_results:
        key = item["content"][:100]
        if key not in seen:
            seen.add(key)
            unique_arxiv.append(item)
    
    all_raw_docs = unique_arxiv + [{"source": "本地知识库", "content": d.get("content", ""), "title": d.get("title", "")} for d in local_results]
    
    print(f"-> [Searcher]: 检索完毕 — 原始 {len(all_raw_docs)} 篇，正在 Rerank...")
    
    # 4. LLM Rerank — 批量评估文献相关性，大幅降低 Token 消耗和延迟
    ranked_docs = []
    if all_raw_docs:
        doc_previews = []
        for i, doc in enumerate(all_raw_docs):
            doc_previews.append(f"[{i}] {doc.get('content', '')[:300]}")
        doc_text = "\n\n".join(doc_previews)

        rerank_prompt = ChatPromptTemplate.from_messages([
            ("system", "你是文献相关性评估专家。评估以下列表中每个文献与研究主题的相关性（0-10分）。\n严格返回JSON字典，格式为：{{\"0\": 8, \"1\": 5}}。不要输出任何其他文字和Markdown标记。"),
            ("user", "研究主题: {topic}\n章节类型: {focus}\n检索意图: {intent}\n\n文献列表:\n{docs}\n\nJSON格式结果:")
        ])
        
        try:
            raw_res = (rerank_prompt | llm | StrOutputParser()).invoke({
                "topic": topic, "focus": focus, "intent": search_intent, "docs": doc_text
            })
            import json, re
            # 尝试提取 JSON
            match = re.search(r'\{.*?\}', raw_res, re.DOTALL)
            scores_dict = json.loads(match.group()) if match else json.loads(raw_res)
            
            for i_str, score in scores_dict.items():
                idx = int(i_str)
                score_val = int(score)
                if score_val >= 5 and 0 <= idx < len(all_raw_docs):
                    ranked_docs.append({"doc": all_raw_docs[idx], "score": score_val})
        except Exception as e:
            print(f"-> [Searcher]: 批量 Rerank 解析失败: {e}. 回退保留前5篇。")
            ranked_docs = [{"doc": d, "score": 5} for d in all_raw_docs[:5]]
        
        # 按分数降序排列，最多取前5篇
        ranked_docs.sort(key=lambda x: x["score"], reverse=True)
        ranked_docs = ranked_docs[:5]
    
    final_docs = [rd["doc"] for rd in ranked_docs]
    print(f"-> [Searcher]: Rerank 完成，保留 {len(final_docs)} 篇高相关性文献（原始 {len(all_raw_docs)} 篇）")
    
    # 5. 分配引用编号
    ref_dict = state.get("reference_dict", {}) or {}
    reference_docs = []
    
    for doc in final_docs:
        ref_idx = len(ref_dict) + 1
        ref_id = f"Ref-{ref_idx}"
        content = doc.get("content", "")
        title = doc.get("title", "")
        source = doc.get("source", "unknown")
        
        if source == "arXiv":
            ref_dict[ref_id] = f"[arXiv] {content[:200].replace(chr(10), ' ')}..."
            reference_docs.append({"title": f"arXiv - {ref_id}", "content": content})
        else:
            ref_dict[ref_id] = f"[本地知识库] {title} - 摘要: {content[:100].replace(chr(10), ' ')}..."
            reference_docs.append({"title": f"{title} - {ref_id}", "content": content})
    
    from src.utils.context_manager import make_entry
    msg = make_entry("Searcher", focus, "finding",
        f"Rerank 检索完成 — 关键词 {keywords}，从 {len(all_raw_docs)} 篇中保留 {len(final_docs)} 篇高相关文献，生成 {len(reference_docs)} 个引用标号。",
        priority=6)
        
    return {
        "status": "SEARCHING",
        "reference_documents": reference_docs,
        "reference_dict": ref_dict,
        "discussion_history": [msg]
    }
