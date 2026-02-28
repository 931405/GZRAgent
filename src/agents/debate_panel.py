"""
debate_panel.py — 评审专家辩论面板

架构：
  第一轮：多个专家并行独立评审（红脸/蓝脸/方法论/创新性评委）
  第二轮：每位专家看到他人意见后发表辩论观点（赞同/反驳/补充）
  仲裁：  综合所有辩论意见，输出最终裁决结论和是否需要修改

设计原则：
- 每个专家角色对应固定 persona 和评审侧重点
- 辩论最多 2 轮，防止无限循环
- 加权投票：拿到"高分多数"则通过，否则需要修改
"""
import json
import re
import concurrent.futures
from typing import Dict, Any, List

from langchain_core.prompts import ChatPromptTemplate
from src.state import GraphState
from src.llm import get_llm

# ─────────────────────── Reviewer Personas ───────────────────────

REVIEWERS = [
    {
        "id": "red",
        "name": "红脸专家（严格挑刺型）",
        "weight": 0.30,
        "system": """\
你是国家自然科学基金委员会的严格评审专家，擅长发现申请书中的逻辑漏洞和内容不足。
评审侧重点：问题的科学性、研究目标的精准性、技术方案的可行性。
整体风格：严苛但公正，专注于找出关键不足，给出具体改进建议。
评分标准：90+为优秀，75-89为良好，60-74为合格，60以下为不合格。
""",
    },
    {
        "id": "blue",
        "name": "蓝脸专家（建设支持型）",
        "weight": 0.25,
        "system": """\
你是国家自然科学基金委员会的资深支持型评审专家，擅长发现申请书的亮点和潜力。
评审侧重点：研究意义、实验设计的创造性、研究团队基础。
整体风格：鼓励创新，在认可优点的同时给出提升建议。
评分标准：90+为优秀，75-89为良好，60-74为合格，60以下为不合格。
""",
    },
    {
        "id": "method",
        "name": "方法论专家",
        "weight": 0.25,
        "system": """\
你是方法论领域的评审专家，专注于研究方法和技术路线的科学性。
评审侧重点：研究方法选择是否恰当、技术路线是否清晰、实验设计是否严谨可重复。
整体风格：技术导向，关注方法细节，对方法不严谨的地方严格标注。
评分标准：90+为优秀，75-89为良好，60-74为合格，60以下为不合格。
""",
    },
    {
        "id": "innovation",
        "name": "创新性专家",
        "weight": 0.20,
        "system": """\
你是专注于研究创新性评估的基金委专家，擅长判断研究是否具有原创价值。
评审侧重点：研究问题的前沿性、创新点的独特性、与国际研究的差异性。
整体风格：追求前沿，对"老生常谈"的研究持批判态度，鼓励真正的学术突破。
评分标准：90+为优秀，75-89为良好，60-74为合格，60以下为不合格。
""",
    },
]

# ─────────────────────── Prompts ───────────────────────

_REVIEW_PROMPT = """\
请对以下国自然申请书进行专业评审，输出 JSON 格式的评审意见。

章节名：{focus}
草稿内容：
{draft}

输出 JSON：
{{
  "overall_score": 整体打分(0-100),
  "innovation_score": 创新性打分(0-100),
  "logic_score": 逻辑性打分(0-100),
  "feasibility_score": 可行性打分(0-100),
  "strengths": ["亮点1", "亮点2"],
  "problems": [
    {{"description": "问题描述", "severity": "high|medium|low", "suggestion": "改进建议"}}
  ],
  "revision_needed": true/false,
  "overall_comment": "综合评语（3-5句话）"
}}
"""

_DEBATE_PROMPT = """\
你是 {persona}，正在参与国自然申请书的专家评审辩论。

申请书章节：{focus}

其他专家的评审意见：
{other_opinions}

你在第一轮的评审意见：
{my_opinion}

请就其他专家的观点发表辩论意见，输出 JSON：
{{
  "stance": "agree|partially_agree|disagree|supplement",
  "argument": "你的辩论论点（150字以内）",
  "revised_score": 修正后的整体评分(0-100，可与第一轮不同),
  "key_points": ["最终坚持的关键问题1", "关键问题2"]
}}

stance 说明：
- agree: 同意其他专家主要观点
- partially_agree: 部分同意，有补充
- disagree: 不同意某些观点，给出理由
- supplement: 补充其他专家未提及的重要问题
"""

_ARBITRATION_PROMPT = """\
你是国家自然科学基金评审委员会的首席仲裁专家。
你需要综合所有评审专家的两轮评审意见，给出最终裁决。

申请书章节：{focus}
研究主题：{topic}

第一轮各专家评分：
{round1_scores}

辩论过程：
{debate_history}

第二轮各专家修正评分：
{round2_scores}

请输出最终裁决 JSON：
{{
  "final_score": 综合评分(0-100，加权平均后可微调),
  "consensus_points": ["各专家达成共识的问题1", "共识问题2"],
  "disputed_points": ["存在争议但需关注的问题1"],
  "revision_required": true/false,
  "revision_priority": "high|medium|low",
  "conclusion": "最终裁决结论（200-300字），包括主要问题、修改方向、整体评价",
  "approved_aspects": ["值得肯定的方面1", "方面2"]
}}
"""

# ─────────────────────── Core Functions ───────────────────────

def _run_single_review(state: GraphState, reviewer: Dict) -> Dict[str, Any]:
    """单专家评审（适合并发调用）"""
    config = state.get("model_config") or {}
    provider = config.get("reviewer", config.get("writer", "deepseek"))
    llm = get_llm(provider_override=provider, temperature=0.15, is_json_mode=True)

    focus = state.get("current_focus", "全文")
    drafts = state.get("draft_sections") or {}
    doms = state.get("document_dom") or {}

    # 如果是"全文模式"，拼接所有章节
    # V2 架构：优先使用 DOM 树渲染出待审阅的结构化文本
    if focus == "全文" or focus not in drafts:
        parts = []
        for k in drafts.keys():
            if k in doms:
                sec_text = ""
                for el in doms[k].elements:
                    if el.type == "text": sec_text += el.content + "\n"
                    elif el.type == "table": sec_text += f"\n[数据表]\n{el.content}\n"
                    elif el.type == "formula": sec_text += f"\n[推导公式]: {el.content}\n"
                parts.append(f"## {k}\n{sec_text[:600]}") # 保留前600作为兼容，后续可优化
            else:
                parts.append(f"## {k}\n{drafts.get(k, '')[:600]}")
        draft = "\n\n".join(parts)[:4000]
    else:
        if focus in doms:
             sec_text = ""
             for el in doms[focus].elements:
                  if el.type == "text": sec_text += el.content + "\n"
                  elif el.type == "table": sec_text += f"\n[数据表]\n{el.content}\n"
                  elif el.type == "formula": sec_text += f"\n[推导公式]: {el.content}\n"
             draft = sec_text[:3000]
        else:
             draft = drafts.get(focus, "")[:3000]

    prompt = ChatPromptTemplate.from_messages([
        ("system", reviewer["system"]),
        ("user", _REVIEW_PROMPT),
    ])

    try:
        raw = (prompt | llm).invoke({"focus": focus, "draft": draft})
        raw_text = raw.content if hasattr(raw, "content") else str(raw)
        result = _parse_json(raw_text) or {}
        result["reviewer_id"] = reviewer["id"]
        result["reviewer_name"] = reviewer["name"]
        result["weight"] = reviewer["weight"]
        return result
    except Exception as e:
        print(f"[Debate] {reviewer['name']} 评审失败: {e}")
        return {
            "reviewer_id": reviewer["id"],
            "reviewer_name": reviewer["name"],
            "weight": reviewer["weight"],
            "overall_score": 70,
            "revision_needed": False,
            "overall_comment": f"评审执行失败：{e}",
        }


def _run_debate_round(state: GraphState, reviewer: Dict, my_review: Dict, all_reviews: List[Dict]) -> Dict[str, Any]:
    """辩论轮次：每位专家看到其他人的意见后发言"""
    config = state.get("model_config") or {}
    provider = config.get("reviewer", config.get("writer", "deepseek"))
    llm = get_llm(provider_override=provider, temperature=0.25, is_json_mode=True)

    focus = state.get("current_focus", "全文")

    # 整理其他专家观点
    other_parts = []
    for r in all_reviews:
        if r.get("reviewer_id") != reviewer["id"]:
            score = r.get("overall_score", "?")
            comment = r.get("overall_comment", "")
            problems = "; ".join(
                p.get("description", "") for p in r.get("problems", [])[:3]
            )
            other_parts.append(
                f"【{r.get('reviewer_name', '?')}】评分{score}: {comment}"
                + (f" 主要问题：{problems}" if problems else "")
            )
    other_opinions = "\n".join(other_parts) if other_parts else "（无其他意见）"

    my_opinion_str = (
        f"评分{my_review.get('overall_score', '?')}: "
        f"{my_review.get('overall_comment', '')}; "
        f"主要问题：{'; '.join(p.get('description', '') for p in my_review.get('problems', [])[:3])}"
    )

    prompt = ChatPromptTemplate.from_messages([
        ("system", reviewer["system"]),
        ("user", _DEBATE_PROMPT),
    ])

    try:
        raw = (prompt | llm).invoke({
            "persona": reviewer["name"],
            "focus": focus,
            "other_opinions": other_opinions,
            "my_opinion": my_opinion_str,
        })
        raw_text = raw.content if hasattr(raw, "content") else str(raw)
        result = _parse_json(raw_text) or {}
        result["reviewer_id"] = reviewer["id"]
        result["reviewer_name"] = reviewer["name"]
        result["weight"] = reviewer["weight"]
        return result
    except Exception as e:
        print(f"[Debate] {reviewer['name']} 辩论失败: {e}")
        return {
            "reviewer_id": reviewer["id"],
            "reviewer_name": reviewer["name"],
            "stance": "agree",
            "argument": f"辩论执行失败：{e}",
            "revised_score": my_review.get("overall_score", 70),
            "weight": reviewer["weight"],
        }


def _arbitrate(state: GraphState, round1: List[Dict], debate_round: List[Dict]) -> Dict[str, Any]:
    """仲裁：综合两轮意见给出最终裁决"""
    config = state.get("model_config") or {}
    provider = config.get("reviewer", config.get("writer", "deepseek"))
    llm = get_llm(provider_override=provider, temperature=0.1, is_json_mode=True)

    focus = state.get("current_focus", "全文")
    topic = state.get("research_topic", "")

    # 整理第一轮评分
    r1_lines = [f"- {r.get('reviewer_name')}: {r.get('overall_score', '?')}分, 修改建议={r.get('revision_needed', False)}" for r in round1]

    # 整理辩论过程
    debate_lines = [
        f"- {d.get('reviewer_name')} [{d.get('stance')}]: {d.get('argument', '')} → 修正分{d.get('revised_score', '?')}"
        for d in debate_round
    ]

    # 整理第二轮评分
    r2_lines = [f"- {d.get('reviewer_name')}: {d.get('revised_score', '?')}分" for d in debate_round]

    prompt = ChatPromptTemplate.from_messages([
        ("user", _ARBITRATION_PROMPT),
    ])

    try:
        raw = (prompt | llm).invoke({
            "focus": focus,
            "topic": topic,
            "round1_scores": "\n".join(r1_lines),
            "debate_history": "\n".join(debate_lines),
            "round2_scores": "\n".join(r2_lines),
        })
        raw_text = raw.content if hasattr(raw, "content") else str(raw)
        return _parse_json(raw_text) or {}
    except Exception as e:
        print(f"[Debate] 仲裁失败: {e}")
        # fallback：加权平均
        weighted_score = _weighted_avg_score(round1, debate_round)
        return {
            "final_score": weighted_score,
            "revision_required": weighted_score < 80,
            "conclusion": f"仲裁环节执行失败（{e}），按加权平均分{weighted_score:.1f}判断。",
        }


# ─────────────────────── Main Entry ───────────────────────

def run_debate_panel(state: GraphState) -> Dict[str, Any]:
    """
    评审专家辩论面板主函数

    流程：
    1. 4位专家并行独立评审
    2. 每位专家看他人意见后进行辩论（并发）
    3. 仲裁专家综合两轮结果给出最终裁决
    """
    log_start = "[DebatePanel] 启动评审专家辩论..."
    print(log_start)

    # ── Round 1: 并发独立评审 ──
    round1_results: List[Dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(_run_single_review, state, r): r for r in REVIEWERS}
        for fut in concurrent.futures.as_completed(futures):
            result = fut.result()
            round1_results.append(result)

    round1_log = (
        "[DebatePanel] 第1轮评审完成: "
        + " | ".join(f"{r.get('reviewer_name', '?')}={r.get('overall_score', '?')}" for r in round1_results)
    )
    print(round1_log)

    # 构建评审反馈（兼容旧版 review_feedbacks 格式）
    review_feedbacks = []
    for r in round1_results:
        for p in r.get("problems", []):
            review_feedbacks.append({
                "reviewer_persona": r.get("reviewer_name", ""),
                "overall_score": r.get("overall_score", 70),
                "innovation_score": r.get("innovation_score", 70),
                "logic_score": r.get("logic_score", 70),
                "feasibility_score": r.get("feasibility_score", 70),
                "problem_description": p.get("description", ""),
                "improvement_direction": p.get("suggestion", ""),
                "severity": p.get("severity", "medium"),
            })

    # ── Round 2: 辩论轮次（并发）──
    debate_results: List[Dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = {}
        for r in REVIEWERS:
            my_review = next((x for x in round1_results if x.get("reviewer_id") == r["id"]), {})
            fut = executor.submit(_run_debate_round, state, r, my_review, round1_results)
            futures[fut] = r
        for fut in concurrent.futures.as_completed(futures):
            debate_results.append(fut.result())

    debate_log = (
        "[DebatePanel] 辩论轮次完成: "
        + " | ".join(f"{d.get('reviewer_name', '?')}[{d.get('stance', '?')}]→{d.get('revised_score', '?')}" for d in debate_results)
    )
    print(debate_log)

    # ── Arbitration ──
    arbitration = _arbitrate(state, round1_results, debate_results)
    final_score: float = arbitration.get("final_score", 0)
    revision_required: bool = arbitration.get("revision_required", final_score < 80)
    conclusion: str = arbitration.get("conclusion", "")

    arb_log = f"[DebatePanel] 仲裁完成 | 最终评分: {final_score:.1f} | 需要修改: {revision_required}"
    print(arb_log)

    # ── 构建 debate_rounds 记录 ──
    debate_rounds_records = []
    for i, r in enumerate(round1_results):
        debate_rounds_records.append({
            "round": 1,
            "reviewer": r.get("reviewer_name", ""),
            "stance": "initial",
            "argument": r.get("overall_comment", ""),
            "score": r.get("overall_score", 0),
        })
    for d in debate_results:
        debate_rounds_records.append({
            "round": 2,
            "reviewer": d.get("reviewer_name", ""),
            "stance": d.get("stance", ""),
            "argument": d.get("argument", ""),
            "score": d.get("revised_score", 0),
        })

    return {
        "review_feedbacks": review_feedbacks,
        "prev_review_feedbacks": list(state.get("review_feedbacks") or []),
        "reviewer_score": float(final_score),
        "debate_rounds": debate_rounds_records,
        "debate_conclusion": conclusion,
        "revision_required": revision_required,
        "current_phase": "debating",
        "status": "DEBATING",
        "discussion_history": [log_start, round1_log, debate_log, arb_log],
    }


# ─────────────────────── Helpers ───────────────────────

def _parse_json(raw_text: str) -> Dict:
    try:
        return json.loads(raw_text)
    except Exception:
        pass
    match = re.search(r'\{.*\}', raw_text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except Exception:
            pass
    return {}


def _weighted_avg_score(round1: List[Dict], round2: List[Dict]) -> float:
    """加权平均评分，第一轮40% + 第二轮60%"""
    total_weight = sum(r.get("weight", 0.25) for r in round1)
    if total_weight == 0:
        return 70.0

    r1_weighted = sum(r.get("overall_score", 70) * r.get("weight", 0.25) for r in round1) / total_weight

    r2_map = {d.get("reviewer_id"): d for d in round2}
    r2_scores = []
    for r in round1:
        rid = r.get("reviewer_id", "")
        r2 = r2_map.get(rid)
        r2_scores.append((
            (r2.get("revised_score", r.get("overall_score", 70)) if r2 else r.get("overall_score", 70)),
            r.get("weight", 0.25),
        ))
    r2_weighted = sum(s * w for s, w in r2_scores) / total_weight

    return r1_weighted * 0.4 + r2_weighted * 0.6
