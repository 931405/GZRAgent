from src.state import GraphState
from src.llm import get_llm
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser, JsonOutputParser

# 章节写作规范
SECTION_GUIDELINES = {
    "立项依据": """本章节是整个申请书的灵魂，需要包含以下结构：
1. **研究背景** (约300字)：领域总体发展态势，从大到小聚焦
2. **关键科学问题** (约200字)：明确指出当前的瓶颈/未解决问题
3. **国内外研究现状** (约500字)：系统梳理已有工作，指出不足，必须有文献支撑 [Ref-X]
4. **本项目切入点** (约200字)：为什么你的方法能解决上述问题
要求：逻辑链条紧密，从"领域重要→现有不足→本项目方案"层层递进。""",

    "研究目标与内容": """本章节需要清晰阐述：
1. **研究目标** (约150字)：用1-2句话概括总目标，再分解为2-3个子目标
2. **研究内容** (约400字)：围绕子目标展开，每个内容点对应一个明确的研究问题
3. **拟解决的关键科学问题** (约200字)：提炼2-3个核心问题
要求：目标→内容→关键问题三者逻辑一致，不能出现断裂。""",

    "研究方案与可行性": """本章节需要展示技术力和工程能力：
1. **技术路线总览** (约100字)：整体框架描述
2. **分步骤研究方案** (约600字)：每个步骤的输入→方法→输出→验证指标
3. **可行性分析** (约200字)：从理论基础、技术条件、前期工作三个角度论证
要求：方案必须具体到可执行层面，避免空泛描述。""",

    "特色与创新": """本章节是评审重点关注区：
1. **理论创新** (约150字)：说明在理论上的突破点
2. **方法创新** (约150字)：说明技术/方法上的新颖性
3. **应用创新** (约100字)：说明潜在应用价值
要求：每个创新点必须与前文内容严格对应，不能凭空出现新概念。""",

    "研究基础": """本章节用于展示团队实力：
1. **工作基础** (约300字)：已有的相关研究成果、发表论文、专利等
2. **实验条件** (约100字)：设备、平台、数据资源
3. **团队简介** (约100字)：核心成员的专长互补性
要求：要体现与本课题的紧密关联性。"""
}


def run_writer(state: GraphState) -> dict:
    """首席研究员 (Writer Agent)
    
    双模式写作：
    - 全文撰写模式：有章节结构规范指导
    - 精修模式：消费 Reviewer 的宏观反馈 (problem_description + improvement_direction)
    """
    topic = state.get("research_topic", "")
    focus = state.get("current_focus", "")
    project_type = state.get("project_type", "基金申请")
    
    docs = state.get("reference_documents", [])
    
    # 限制参考资料长度和数量，避免巨大的 Token 开销
    safe_docs = docs[-12:] if len(docs) > 12 else docs
    doc_parts = []
    for d in safe_docs:
        title = d.get('title', '未知文献')
        content_str = str(d.get('content', ''))
        doc_parts.append(f"[{title}]\n{content_str[:500]}...")
    doc_text = "\n\n".join(doc_parts)
    
    # 结构化上下文管理（替代简单截断）
    all_discussions = state.get("discussion_history", [])
    from src.utils.context_manager import build_structured_context, compress_history, make_entry
    compressed = compress_history(all_discussions, keep_recent=5)
    discussions = build_structured_context(compressed, max_entries=8)
    
    # 专门提取最新的 Designer 建议（兼容结构化 + 旧格式）
    designer_advice = ""
    for msg in reversed(all_discussions):
        msg_str = str(msg)
        # 结构化格式: JSON 含 "agent": "Designer"
        import json as _json
        try:
            # 尝试解析可能包含 JSON 的字符串
            if msg_str.strip().startswith("{"):
                entry = _json.loads(msg_str)
                if entry.get("agent") == "Designer" or "strategy" in entry:
                    designer_advice = entry.get("content", str(entry))
                    break
            elif "Designer" in msg_str and "{" in msg_str:
                 start_idx = msg_str.find("{")
                 entry = _json.loads(msg_str[start_idx:])
                 if entry.get("agent") == "Designer" or "strategy" in entry:
                     designer_advice = entry.get("content", str(entry))
                     break
        except Exception:
            pass
            
        # 旧格式兼容
        if msg_str.startswith("Designer:") or "Designer:" in msg_str[:50]:
            designer_advice = msg_str
            break
    
    # 用户长期偏好
    from src.utils.user_memory import build_preference_context
    user_pref_text = build_preference_context()
    
    feedbacks = state.get("review_feedbacks", [])
    
    current_drafts = state.get("draft_sections", {})
    old_draft = current_drafts.get(focus, "")
    
    config = state.get("model_config", {})
    llm_provider = config.get("writer", None)
    llm = get_llm(provider_override=llm_provider, temperature=0.7)
    
    # 获取章节写作规范
    section_guide = SECTION_GUIDELINES.get(focus, "请按照学术规范撰写该章节。")
    
    has_old_draft = bool(old_draft and old_draft.strip())
    has_feedbacks = bool(feedbacks)
    
    if has_old_draft and has_feedbacks:
        # ========== 精修模式：消费宏观反馈 ==========
        print(f"-> [Writer]: 进入精修模式 '{focus}'（{len(feedbacks)} 条宏观反馈待处理）...")
        
        # 构建反馈列表 — 适配新字段
        feedback_items = []
        for i, fb in enumerate(feedbacks):
            persona = fb.get('reviewer_persona', '评审专家')
            problem = fb.get('problem_description', fb.get('original_text', ''))
            direction = fb.get('improvement_direction', fb.get('suggested_text', ''))
            reason = fb.get('reason', '')
            score = fb.get('overall_score', fb.get('score', 0))
            
            feedback_items.append(
                f"[反馈 #{i+1}] ({persona}, 综合分 {score})\n"
                f"  问题: {problem}\n"
                f"  改进方向: {direction}\n"
                f"  理由: {reason}"
            )
        feedback_block = "\n\n".join(feedback_items)
        
        revision_prompt = ChatPromptTemplate.from_messages([
            ("system", """你是一位资深的首席研究员 (PI)，正在根据评审专家团队的宏观反馈对 NSFC 申请书草稿进行修订。

你的修订原则：
1. 评审反馈聚焦的是**方法论、研究方向、逻辑结构**等大方向问题，而非遣词造句。
2. 你需要对每条宏观反馈做出独立的学术判断：
   - **接受 (accept)**：认可该问题并修改相关段落
   - **部分采纳 (partial)**：认可问题的合理部分，但用你自己的方式解决
   - **拒绝 (reject)**：如果该反馈不合理，保持原文并简述理由
3. **重要**：对于没有被指出问题的段落，严格保持原文不变。
4. 修订时要注意保持全文的逻辑连贯性，不能只改局部导致前后矛盾。
5. 如果引用了参考文献的事实、数据或观点，必须在句尾标注 `[Ref-X]`。

输出格式：
在正文之前，先输出你对每条反馈的决策：
[反馈 #1] accept/partial/reject: <简短理由>
[反馈 #2] accept/partial/reject: <简短理由>
...
---
<完整修改后正文>"""),
            ("user", """项目类型: {project_type}
研究主题: {topic}
当前章节: {focus}

【章节写作规范】:
{section_guide}

【当前草稿全文】:
{old_draft}

【评审专家宏观反馈】:
{feedback_block}

【策略师最新建议】:
{designer_advice}

{user_pref_text}

【近期讨论记录】:
{discussions}

请先输出决策摘要，然后输出修改后的完整正文：""")
        ])
        
        result = (revision_prompt | llm | StrOutputParser()).invoke({
            "project_type": project_type,
            "topic": topic,
            "focus": focus,
            "section_guide": section_guide,
            "old_draft": old_draft,
            "feedback_block": feedback_block,
            "designer_advice": designer_advice or "（无策略师建议）",
            "user_pref_text": user_pref_text or "",
            "discussions": discussions
        })
        
        if "---" in result:
            decision_part, new_draft = result.split("---", 1)
            new_draft = new_draft.strip()
            decision_summary = decision_part.strip()
        else:
            new_draft = result.strip()
            decision_summary = "（未能解析出独立决策摘要）"
        
        current_drafts[focus] = new_draft
        
        return {
            "status": "DRAFTING",
            "draft_sections": current_drafts,
            "discussion_history": [
                make_entry("Writer", focus, "revision",
                    f"精修完成（处理 {len(feedbacks)} 条宏观反馈）。决策摘要：\n{decision_summary}", priority=8)
            ]
        }
    
    else:
        # ========== 全文撰写模式 ==========
        print(f"-> [Writer]: 进入全文撰写模式 '{focus}'...")
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", """你是一位资深的首席研究员 (PI)，擅长撰写国家自然科学基金 (NSFC) 申请书。
你的任务是根据研究主题、检索文献、专家建议，撰写指定的申请书章节。

写作要求：
1. 严格按照【章节写作规范】的结构和字数要求组织内容
2. 每个段落都要有明确的论证目的，段落间逻辑衔接要自然
3. 直接输出 Markdown 格式正文，不要客套话
4. **引用规范**：凡使用了检索文献中的信息，必须在该句末尾标注 `[Ref-X]`"""),
            ("user", """项目类型: {project_type}
研究主题: {topic}
当前撰写章节: {focus}

【章节写作规范】:
{section_guide}

【参考资料 / 文献检索结果】:
{doc_text}

【团队讨论记录】:
{discussions}

请严格按照章节结构规范，生成高质量的 Markdown 正文：""")
        ])
        
        new_draft = (prompt | llm | StrOutputParser()).invoke({
            "project_type": project_type,
            "topic": topic,
            "focus": focus,
            "section_guide": section_guide,
            "doc_text": doc_text,
            "discussions": discussions,
        })
        
        current_drafts[focus] = new_draft
        
        return {
            "status": "DRAFTING",
            "draft_sections": current_drafts,
            "discussion_history": [make_entry("Writer", focus, "decision",
                f"已完成 '{focus}' 的全文初稿撰写（含章节结构规范）。", priority=7)]
        }
