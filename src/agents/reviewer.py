import json
import concurrent.futures
from src.state import GraphState
from src.llm import get_llm
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser

def _run_single_reviewer(state: GraphState, persona: str, system_prompt: str) -> list:
    """运行单个 Reviewer 视角"""
    focus = state.get("current_focus", "")
    draft = state.get("draft_sections", {}).get(focus, "")
    if not draft:
        return []
    
    config = state.get("model_config", {})
    llm_provider = config.get("reviewer", None)
    llm = get_llm(provider_override=llm_provider, temperature=0.1, is_json_mode=True)
    parser = JsonOutputParser()
    
    # 注入上一轮反馈，让 Reviewer 追踪历史问题
    prev_feedbacks = state.get("prev_review_feedbacks", []) or []
    history_context = ""
    if prev_feedbacks:
        history_items = []
        for fb in prev_feedbacks[-5:]:
            problem = fb.get('problem_description', fb.get('reason', ''))
            direction = fb.get('improvement_direction', '')
            history_items.append(f"- 问题: {problem}" + (f" | 建议: {direction}" if direction else ""))
        history_context = f"\n\n【上一轮已提出的问题（检查是否已被修正，已修正的问题请在评分中给予肯定）】:\n" + "\n".join(history_items)
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("user", "章节: {focus}\n草稿内容:\n{draft}{history}\n\n请输出完整的 JSON 数组:")
    ])
    
    try:
        raw = (prompt | llm).invoke({"focus": focus, "draft": draft, "history": history_context})
        raw_text = raw.content if hasattr(raw, 'content') else str(raw)

        def _parse_feedbacks(text: str) -> list:
            import re, json
            # 尝试直接用 JsonOutputParser
            try:
                result = parser.parse(text)
                if isinstance(result, list):
                    return result
                if isinstance(result, dict) and "feedbacks" in result:
                    return result["feedbacks"]
                return []
            except Exception:
                # fallback: 用正则抽取 JSON 数组
                match = re.search(r'\[.*\]', text, re.DOTALL)
                if match:
                    return json.loads(match.group())
                return None  # 解析彻底失败

        feedbacks = _parse_feedbacks(raw_text)

        # 解析失败 → 重试一次，附带修复提示
        if feedbacks is None:
            print(f"[Reviewer-{persona}]: JSON 解析失败，正在重试...")
            repair_prompt = ChatPromptTemplate.from_messages([
                ("system", system_prompt),
                ("user", "章节: {focus}\n草稿内容:\n{draft}{history}\n\n请输出完整的 JSON 数组:"),
                ("assistant", raw_text),
                ("user", "你的输出不是合法 JSON 数组。请只输出 JSON 数组，不要任何解释文字，格式: [{...}, {...}]")
            ])
            raw2 = (repair_prompt | llm).invoke({"focus": focus, "draft": draft, "history": history_context})
            raw2_text = raw2.content if hasattr(raw2, 'content') else str(raw2)
            feedbacks = _parse_feedbacks(raw2_text) or []

        for fb in feedbacks:
            fb["reviewer_persona"] = persona
            if "overall_score" not in fb and "score" in fb:
                fb["overall_score"] = fb["score"]
                fb["innovation_score"] = fb.get("innovation_score", fb["score"])
                fb["logic_score"] = fb.get("logic_score", fb["score"])
                fb["feasibility_score"] = fb.get("feasibility_score", fb["score"])
        return feedbacks
    except Exception as e:
        print(f"[Reviewer-{persona} Error]: {e}")
        return []


RED_PROMPT = """你是一个极其严苛的 NSFC 基金评审"红脸专家"。你的职责是从**宏观层面挑刺**：
- 审查研究方向和方法论的根本缺陷
- 指出论证逻辑链条中的因果跳跃和推理漏洞
- 质疑技术路线的可行性和创新性是否真正突破
- 判断是否存在"旧瓶装新酒"、核心创新点不明确的问题
- **你不需要关心具体遣词造句**，语言层面的优化由后续 Writer 负责

**注意：你的反馈应聚焦于方法论、研究方向、逻辑结构等大方向问题，而非语句修改。**
**如果上一轮已提出过的问题在本轮草稿中已被修正，请不要重复提出。**

从三个维度评分：
1. **创新性 (innovation_score)**: 0-100
2. **逻辑性 (logic_score)**: 0-100
3. **可行性 (feasibility_score)**: 0-100

你必须输出 JSON 格式的数组，每个元素包含以下字段：
- "section": 当前章节名
- "problem_description": 你发现的宏观问题描述（如方法论缺陷、逻辑断层、创新不足等）
- "improvement_direction": 你建议的改进方向（宏观策略）
- "reason": 详细的学术论证理由
- "innovation_score": 创新性评分 (0-100)
- "logic_score": 逻辑性评分 (0-100)
- "feasibility_score": 可行性评分 (0-100)
- "overall_score": 综合评分 (0-100)，创新40%+逻辑30%+可行30%

示例：
[
    {{"section": "立项依据", "problem_description": "技术路线缺乏与现有SOTA方法的对比论证", "improvement_direction": "应增加与至少3种主流方法的系统性对比分析", "reason": "缺乏竞品分析是创新性论证的致命弱点", "innovation_score": 55, "logic_score": 60, "feasibility_score": 75, "overall_score": 62}}
]
如果完美无缺，返回空数组 []。"""

BLUE_PROMPT = """你是一个富有建设性的 NSFC 基金评审"蓝脸专家"。你的职责是从**宏观层面提出改进方案**：
- 为薄弱的研究论证提供更有说服力的论证角度和策略
- 建议可以补充的方法论、实验设计或理论支撑
- 提出可以强化创新叙事的宏观思路
- 指出可以借鉴的前沿研究范式或跨学科思路
- **你不需要关心具体遣词造句**，语言层面的优化由后续 Writer 负责

**注意：你的建议应聚焦于方法论升级、论证策略优化、研究设计改进等大方向，而非具体文字修改。**
**如果上一轮已提出过的问题在本轮草稿中已被修正，请在评分中给予肯定。**

从三个维度评分：
1. **创新性 (innovation_score)**: 0-100
2. **逻辑性 (logic_score)**: 0-100
3. **可行性 (feasibility_score)**: 0-100

你必须输出 JSON 格式的数组，每个元素包含以下字段：
- "section": 当前章节名
- "problem_description": 当前可以优化的宏观问题描述
- "improvement_direction": 你建议的改进策略和方向
- "reason": 为什么这个改进方向更好的学术理由
- "innovation_score": 创新性评分 (0-100)
- "logic_score": 逻辑性评分 (0-100)
- "feasibility_score": 可行性评分 (0-100)
- "overall_score": 综合评分 (0-100)，创新40%+逻辑30%+可行30%

示例：
[
    {{"section": "立项依据", "problem_description": "多智能体协作的核心优势论证偏弱", "improvement_direction": "可以从'涌现能力'的理论视角切入论证", "reason": "涌现理论能显著提升创新性论述的学术深度", "innovation_score": 70, "logic_score": 80, "feasibility_score": 85, "overall_score": 77}}
]
如果完美无缺，返回空数组 []。"""


def run_reviewer(state: GraphState) -> dict:
    """科学评论家 (Reviewer Agent) — 红蓝并行审查模式
    
    红脸专家 + 蓝脸专家并行执行，评分红脸加权60%。
    """
    focus = state.get("current_focus", "")
    draft = state.get("draft_sections", {}).get(focus, "")
    
    print(f"-> [Reviewer]: 正在双面并行审查 '{focus}'...")
    
    if not draft:
        return {
            "status": "REVIEWING",
            "review_feedbacks": [],
            "reviewer_score": 0,
            "discussion_history": ["Reviewer: 草稿为空，无法审查。"]
        }
    
    # 红蓝并行执行
    red_feedbacks = []
    blue_feedbacks = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        print(f"-> [Reviewer-红]: 严苛挑刺审查中...")
        future_red = executor.submit(_run_single_reviewer, state, "红脸·挑刺型", RED_PROMPT)
        print(f"-> [Reviewer-蓝]: 建设性改进审查中...")
        future_blue = executor.submit(_run_single_reviewer, state, "蓝脸·建设型", BLUE_PROMPT)
        
        try:
            red_feedbacks = future_red.result(timeout=180)
        except Exception as e:
            print(f"-> [Reviewer-红]: 超时或异常: {e}")
        
        try:
            blue_feedbacks = future_blue.result(timeout=180)
        except Exception as e:
            print(f"-> [Reviewer-蓝]: 超时或异常: {e}")
    
    all_feedbacks = red_feedbacks + blue_feedbacks
    
    if all_feedbacks:
        # 红脸加权 60%，蓝脸加权 40%
        red_scores = [f.get("overall_score", 0) for f in red_feedbacks] if red_feedbacks else [75]
        blue_scores = [f.get("overall_score", 0) for f in blue_feedbacks] if blue_feedbacks else [75]
        
        avg_red = sum(red_scores) / len(red_scores)
        avg_blue = sum(blue_scores) / len(blue_scores)
        avg_overall = avg_red * 0.6 + avg_blue * 0.4  # 红脸主导
        
        avg_innov = sum(f.get("innovation_score", 0) for f in all_feedbacks) / len(all_feedbacks)
        avg_logic = sum(f.get("logic_score", 0) for f in all_feedbacks) / len(all_feedbacks)
        avg_feasib = sum(f.get("feasibility_score", 0) for f in all_feedbacks) / len(all_feedbacks)
    else:
        avg_overall = avg_innov = avg_logic = avg_feasib = 100
        
    current_iter = state.get("iteration_count", 0) + 1
    
    if avg_overall >= 85:
        level = "优秀"
    elif avg_overall >= 60:
        level = "一般，需要 Writer 局部修正"
    else:
        level = "严重不足，需要 Designer 重新规划"
    
    score_detail = f"创新性 {avg_innov:.0f} | 逻辑性 {avg_logic:.0f} | 可行性 {avg_feasib:.0f} | 综合 {avg_overall:.0f} (红{avg_red if red_feedbacks else 'N/A'}×60% + 蓝{avg_blue if blue_feedbacks else 'N/A'}×40%)"
    
    from src.utils.context_manager import make_entry
    return {
        "status": "REVIEWING",
        "review_feedbacks": all_feedbacks,
        "prev_review_feedbacks": all_feedbacks,
        "reviewer_score": avg_overall,
        "iteration_count": current_iter,
        "discussion_history": [
            make_entry("Reviewer-红", focus, "finding",
                f"严苛审查完成，提出 {len(red_feedbacks)} 条问题。", priority=6),
            make_entry("Reviewer-蓝", focus, "finding",
                f"建设性审查完成，提出 {len(blue_feedbacks)} 条改进建议。", priority=6),
            make_entry("Reviewer", focus, "score",
                f"双面会诊完成 [{level}]，{score_detail}，共 {len(all_feedbacks)} 条意见。", priority=9)
        ]
    }
