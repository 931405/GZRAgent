from src.state import GraphState
from src.llm import get_llm
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

ALL_SECTIONS = ["立项依据", "研究目标与内容", "研究方案与可行性", "特色与创新", "研究基础"]


def run_outline_planner(state: GraphState) -> dict:
    """全文大纲规划器 (Outline Planner)
    
    在全文模式(mode=all)开始前调用，生成完整的申请书大纲：
    - 每个章节的核心论点（2-3条）
    - 章节间的逻辑连接关系
    - 全文的创新叙事主线
    
    大纲存入 state.document_outline，供所有后续章节的 Designer 和 Writer 参考。
    """
    topic = state.get("research_topic", "")
    project_type = state.get("project_type", "基金申请")
    
    # 读取检索文献（Searcher 已完成第一轮检索）
    docs = state.get("reference_documents", [])
    doc_preview = "\n".join([f"- {d.get('title', '')}: {d.get('content', '')[:150]}" for d in docs[:5]]) if docs else "（暂无文献）"
    
    config = state.get("model_config", {})
    llm_provider = config.get("designer", None)
    llm = get_llm(provider_override=llm_provider, temperature=0.6)
    
    print(f"-> [OutlinePlanner]: 正在生成全文大纲...")
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", """你是一位资深的 NSFC 基金申请书全文架构师。
你的任务是在逐章起草之前，先为整份申请书制定一个**内部一致、逻辑严密**的完整大纲。

大纲要求：
1. 为每个章节列出 2-3 个核心论点（不超过一句话/论点）
2. 明确各章节之间的逻辑衔接关系（如："立项依据中提出的问题X，在研究方案中通过方法Y解决"）
3. 提炼出贯穿全文的**创新叙事主线**（1-2句话）
4. 标注各章节中哪些论点需要文献支撑

格式要求：使用 Markdown，章节名作为二级标题。"""),
        ("user", """项目类型: {project_type}
研究主题: {topic}
章节列表: {sections}

【初步检索到的相关文献】:
{doc_preview}

请生成完整的申请书全文大纲：""")
    ])
    
    outline = (prompt | llm | StrOutputParser()).invoke({
        "project_type": project_type,
        "topic": topic,
        "sections": " → ".join(ALL_SECTIONS),
        "doc_preview": doc_preview
    })
    
    print(f"-> [OutlinePlanner]: 全文大纲生成完毕（{len(outline)} 字）")
    
    from src.utils.context_manager import make_entry
    return {
        "document_outline": outline,
        "discussion_history": [make_entry("OutlinePlanner", "全文", "strategy",
            f"全文大纲已生成，将约束各章节写作。\n\n{outline[:500]}...", priority=9)]
    }
