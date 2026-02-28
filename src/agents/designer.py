from src.state import GraphState
from src.llm import get_llm
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

# 章节策略指导要点
SECTION_STRATEGY = {
    "立项依据": "需要从'为什么重要→现在缺什么→我们怎么解决'的逻辑链出发，重点论证科学问题的紧迫性和本方案的独特切入点。",
    "研究目标与内容": "需要确保目标→内容→关键问题三层对齐，不能出现目标里提了但内容没展开的悬空项。",
    "研究方案与可行性": "需要提供可操作的技术路线，每个步骤要有明确的输入输出和验证指标，避免空泛描述。",
    "特色与创新": "需要与前文严格对应，每个创新点必须在前文中有论证支撑，不能凭空出现新概念。",
    "研究基础": "需要体现团队实力与本课题的紧密关联性，而非列举不相关的成果。",
}

def run_designer(state: GraphState) -> dict:
    """基金策略师 (Designer Agent) — 结构化建议版
    
    消费 Searcher 文献 + Reviewer 宏观反馈，输出结构化策略建议。
    """
    topic = state.get("research_topic", "")
    focus = state.get("current_focus", "")
    project_type = state.get("project_type", "基金申请")
    
    docs = state.get("reference_documents", [])
    doc_summaries = "\n".join([f"- [{d.get('title', '未知')}]: {d.get('content', '')[:300]}" for d in docs]) if docs else "（暂无文献检索结果）"
    
    # 读取 Reviewer 反馈 — 适配新字段
    feedbacks = state.get("review_feedbacks", [])
    feedback_text = ""
    if feedbacks:
        feedback_items = []
        for fb in feedbacks[-5:]:
            persona = fb.get('reviewer_persona', '评审专家')
            problem = fb.get('problem_description', fb.get('reason', ''))
            direction = fb.get('improvement_direction', '')
            score = fb.get('overall_score', fb.get('score', 0))
            feedback_items.append(
                f"- [{persona}, 综合分{score}] 问题: {problem}"
                + (f" | 建议方向: {direction}" if direction else "")
            )
        feedback_text = f"\n\n【评审专家团队反馈（需从战略角度回应）】:\n" + "\n".join(feedback_items)
    
    # 跨章节上下文
    completed_summaries = state.get("completed_section_summaries", {})
    prior_chapters_text = ""
    if completed_summaries:
        items = [f"- 【{sec}】: {summary}" for sec, summary in completed_summaries.items()]
        prior_chapters_text = "\n\n【已完成章节摘要（确保当前章节与这些内容保持一致，避免重复或矛盾）】:\n" + "\n".join(items)
    
    document_outline = state.get("document_outline", "")
    outline_text = f"\n\n【全文大纲】:\n{document_outline}" if document_outline else ""
    
    # 获取章节策略要点
    strategy_hint = SECTION_STRATEGY.get(focus, "请从宏观角度提供策略建议。")
    
    # 用户长期偏好
    from src.utils.user_memory import build_preference_context
    user_pref_text = build_preference_context()
    if user_pref_text:
        prior_chapters_text = user_pref_text + "\n" + prior_chapters_text
    
    print(f"-> [Designer]: 正在为 '{focus}' 提供结构化策略建议（已参考 {len(docs)} 篇文献）...")
    
    config = state.get("model_config", {})
    llm_provider = config.get("designer", None)
    llm = get_llm(provider_override=llm_provider, temperature=0.7)
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", """你是国家自然科学基金的资深策略辅导专家。
你需要根据文献支撑材料和评审反馈，为正在起草的章节提供**结构化的高水平策略建议**。

你的输出必须包含以下几个方面（每个方面 2-3 句话即可）：
1. **论证角度建议**：本章节应该从什么理论视角或方法论框架切入
2. **重点引用文献**：在已检索文献中，哪 2-3 篇最值得在本章节重点引用，为什么
3. **段落结构建议**：建议的段落组织顺序和每段核心论点
4. **创新叙事策略**：如何在本章节中巧妙地体现创新性

如果收到了评审反馈，你需要针对每条反馈给出战略性的应对方案。
语言精炼、切中要害，不要空话套话。"""),
        ("user", """项目类型: {project_type}
研究主题: {topic}
目标章节: {focus}

【本章节策略要点】:
{strategy_hint}

【已检索文献摘要】:
{doc_summaries}
{feedback_text}

请给出结构化的策略建议：""")
    ])
    
    advice = (prompt | llm | StrOutputParser()).invoke({
        "project_type": project_type,
        "topic": topic,
        "focus": focus,
        "strategy_hint": strategy_hint,
        "doc_summaries": doc_summaries,
        "feedback_text": feedback_text + prior_chapters_text + outline_text
    })
    
    from src.utils.context_manager import make_entry
    return {
        "status": "DESIGNING",
        "discussion_history": [make_entry("Designer", focus, "strategy",
            f"结构化策略建议（基于 {len(docs)} 篇文献）：\n{advice}", priority=8)]
    }
