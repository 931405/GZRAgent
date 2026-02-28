from src.state import GraphState
from src.llm import get_llm
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

def run_coherence_check(state: GraphState) -> dict:
    """全文连贯性审计节点 (Coherence Checker Agent)
    
    优化五：在全量生成结束后调用，检查所有章节之间的：
    1. 术语一致性（同一概念不同章节叫法是否统一）
    2. 逻辑衔接（前后章节是否有矛盾或断裂）
    3. 交叉引用正确性（"研究方案"是否回应了"研究目标"）
    4. 重复冗余（不同章节重复表达的段落）
    """
    draft_sections = state.get("draft_sections", {})
    topic = state.get("research_topic", "")
    project_type = state.get("project_type", "基金申请")
    
    if not draft_sections or len(draft_sections) < 2:
        return {
            "discussion_history": ["CoherenceChecker: 章节数量不足 2，跳过连贯性审计。"]
        }
    
    # 拼接全文
    full_text_parts = []
    for section_name, content in draft_sections.items():
        full_text_parts.append(f"## {section_name}\n{content}")
    full_text = "\n\n---\n\n".join(full_text_parts)
    
    config = state.get("model_config", {})
    llm_provider = config.get("reviewer", None)  # 复用 Reviewer 的模型做审计
    
    llm = get_llm(provider_override=llm_provider, temperature=0.2)
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", """你是一位资深的 NSFC 基金申请书全稿审计专家。你的任务是审查一份完整的基金申请书（包含多个章节），找出**跨章节**的问题。

请重点检查以下维度：
1. **术语一致性**：同一个概念或方法在不同章节中的称呼是否统一？如果不统一，指出不一致之处并建议统一用语。
2. **逻辑衔接**：各章节之间的论述逻辑是否连贯？"研究方案"是否确实在解决"立项依据"中提出的问题？"特色创新"是否有效呼应了"研究目标"？
3. **交叉引用正确性**：如果某章节引用了其他章节的内容，引用是否准确？
4. **重复冗余**：不同章节中是否存在内容大量重复？

请用结构化的格式输出审计报告，对每个发现的问题给出：
- 涉及章节
- 问题描述
- 修改建议"""),
        ("user", """项目类型: {project_type}
研究主题: {topic}

【完整申请书全文】:
{full_text}

请输出跨章节连贯性审计报告：""")
    ])
    
    report = (prompt | llm | StrOutputParser()).invoke({
        "project_type": project_type,
        "topic": topic,
        "full_text": full_text
    })
    
    from src.utils.context_manager import make_entry
    return {
        "discussion_history": [make_entry("CoherenceChecker", "全文", "finding",
            f"全文连贯性审计完成。\n{report}", priority=8)]
    }
