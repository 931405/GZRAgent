"""
decision_agent.py — 决策 Agent

职责：
- 分析当前全局状态（已完成内容、待完成内容、历次决策历史）
- 输出结构化任务列表（pending_tasks），告知 Orchestrator 接下来要并发调度哪些 Agent
- 根据辩论结论（debate_conclusion）决定修改目标，或宣告定稿
- 支持同一类 Agent 并行多实例（如同时派发多个 writer 任务）
"""
import json
import uuid
from typing import Dict, Any, List

from langchain_core.prompts import ChatPromptTemplate
from src.state import GraphState
from src.llm import get_llm

# ─────────────────────── Prompts ───────────────────────

_PLAN_SYSTEM = """\
你是一个国家自然科学基金申请书的智能撰写系统的"决策核心（Decision Agent）"。
你的任务是：分析当前写作进度，生成下一步需要各专业Agent执行的任务列表。

可调度的 Agent 类型及说明：
- searcher：文献搜索，负责检索相关领域最新研究、竞争格局、研究空白
- innovation：创新点提炼，分析已有草稿/文献后总结3-5个核心创新点
- writer：内容写作，给定章节名称和指令后输出正文骨架草稿（若需表格数据或数学公式必须使用[PLACEHOLDER: TABLE: 描述]或[PLACEHOLDER: FORMULA: 描述]占位）
- data：数据与表格专员，负责真实数据生成。当草稿中有TABLE占位符时派发，instructions填：ID|占位符描述
- formula：公式推导专员。当草稿中有FORMULA占位符时派发，instructions填：ID|占位符描述
- diagram：绘图，针对特定章节生成技术路线图/框架图/思维导图等示意图
- layout：排版优化，检查标题层级/格式一致性/参考文献序号等排版细节

章节列表（国自然面上项目标准章节）：
立项依据、研究目标与内容、研究方案与可行性、特色与创新、研究基础

规则：
1. 每次输出一个 JSON 任务列表，每个任务包含 task_id、agent_type、section（可选）、instructions、priority
2. 可以同时派发多个同类型任务
3. searcher 和 innovation 任务不需要填 section
4. data, formula, diagram 任务在 writer 完成对应章节，且存在相关占位符后才应派发
5. layout 任务在所有章节都有草稿后才派发（通常是最后一步）
6. 若需修订，请在 instructions 里明确指出上一轮评审/辩论提出的具体问题

请只输出 JSON 数组，不要有任何其他文字。
"""

_PLAN_USER = """\
项目类型：{project_type}
研究主题：{research_topic}

已完成章节：{completed_sections}
当前章节草稿字数：{section_word_counts}
待处理占位符(图表/公式)：{placeholders}
创新点内容已生成：{innovation_done}
已完成任务类型：{completed_agent_types}
迭代次数：{iteration_count}
最大迭代：{max_iterations}

{revision_context}

请生成下一步任务列表（JSON 数组）：
[
  {{
    "task_id": "unique-id",
    "agent_type": "searcher|innovation|writer|data|formula|diagram|layout",
    "section": "章节名",
    "instructions": "具体执行指令（对于data/formula，如果是具体占位符，格式为：ID|占位符描述）",
    "priority": 5
  }}
]
"""

_VERDICT_SYSTEM = """\
你是国自然申请书多Agent写作系统的决策核心。
评审专家群刚完成了辩论并给出了辩论结论。
你需要判断：是否需要修改？如果需要，列出每条修改指令。

输出格式（JSON）：
{{
  "revision_required": true/false,
  "revision_targets": [
    {{
      "section": "章节名",
      "issue": "问题描述",
      "instruction": "具体修改指令（对相应writer的操作指南）",
      "priority": "high|medium|low"
    }}
  ],
  "decision_summary": "决策理由（1-2句话）"
}}

如果 revision_required=false，revision_targets 为空数组。
"""

_VERDICT_USER = """\
项目主题：{research_topic}
迭代次数：{iteration_count}/{max_iterations}

评审专家辩论结论：
{debate_conclusion}

评审意见汇总：
{review_summary}

请输出决策 JSON：
"""


# ─────────────────────── Helpers ───────────────────────

def _summarize_review_feedbacks(feedbacks: List[Dict]) -> str:
    if not feedbacks:
        return "（暂无评审意见）"
    lines = []
    for fb in feedbacks[-10:]:
        persona = fb.get("reviewer_persona", "?")
        score = fb.get("overall_score", "?")
        problem = fb.get("problem_description", fb.get("reason", ""))
        direction = fb.get("improvement_direction", "")
        lines.append(f"[{persona} 评分{score}] {problem}" + (f" → {direction}" if direction else ""))
    return "\n".join(lines)


def _build_revision_context(state: GraphState) -> str:
    """如果是修订轮次，提供上一轮的修订目标给决策 Agent"""
    revision_targets = state.get("revision_targets") or []
    if not revision_targets:
        return ""
    lines = ["上一轮辩论裁定的修改指令（请优先安排对应 writer/diagram 任务）："]
    for t in revision_targets:
        section = t.get("section", "全文")
        issue = t.get("issue", "")
        instruction = t.get("instruction", "")
        priority = t.get("priority", "medium")
        lines.append(f"  [{priority.upper()}] 《{section}》: {issue} | 指令：{instruction}")
    return "\n".join(lines)


def _section_word_counts(draft_sections: Dict[str, str]) -> Dict[str, int]:
    return {k: len(v) for k, v in draft_sections.items() if v}


# ─────────────────────── Main Functions ───────────────────────

def run_decision_agent(state: GraphState) -> Dict[str, Any]:
    """
    规划阶段：生成下一步任务列表
    适用于工作流开始时，以及每次修订循环回到任务派发节点时
    """
    config = state.get("model_config") or {}
    provider = config.get("decision", config.get("writer", "deepseek"))
    llm = get_llm(provider_override=provider, temperature=0.2, is_json_mode=True)

    draft_sections: Dict[str, str] = state.get("draft_sections") or {}
    completed_tasks: List[Dict] = state.get("completed_tasks") or []
    revision_targets: List[Dict] = state.get("revision_targets") or []

    completed_sections = [s for s, c in draft_sections.items() if c and len(c) > 100]
    completed_agent_types = list({t.get("agent_type", "") for t in completed_tasks})
    innovation_done = bool(state.get("innovation_points"))

    revision_context = _build_revision_context(state)
    
    # 提取草稿中的占位符
    import re
    placeholders = []
    dom_state = state.get("document_dom") or {}
    for sec, txt in draft_sections.items():
        if txt:
            # 搜索 [PLACEHOLDER: TABLE|FORMULA: xxx]
            matches = re.finditer(r'\[PLACEHOLDER:\s*(TABLE|FORMULA):\s*(.*?)\]', txt, flags=re.IGNORECASE)
            for m in matches:
                p_type = m.group(1).lower()
                p_desc = m.group(2).strip()
                pid = f"{p_type}_{uuid.uuid4().hex[:4]}"
                
                # Check if this placeholder is already processed in document_dom
                processed = False
                if sec in dom_state:
                    for el in dom_state[sec].elements:
                        if hasattr(el, 'metadata') and el.metadata.get('prompt') == p_desc:
                            processed = True
                        elif isinstance(el, dict) and el.get('metadata', {}).get('prompt') == p_desc:
                            processed = True
                if not processed:
                    placeholders.append(f"《{sec}》未处理任务: {p_type}专员负责解决 '{pid}|{p_desc}'")
                    
    placeholders_str = "\n".join(placeholders) if placeholders else "无"

    prompt = ChatPromptTemplate.from_messages([
        ("system", _PLAN_SYSTEM),
        ("user", _PLAN_USER),
    ])

    try:
        raw = (prompt | llm).invoke({
            "project_type": state.get("project_type", "面上项目"),
            "research_topic": state.get("research_topic", ""),
            "completed_sections": "、".join(completed_sections) if completed_sections else "（尚无）",
            "section_word_counts": json.dumps(_section_word_counts(draft_sections), ensure_ascii=False),
            "placeholders": placeholders_str,
            "innovation_done": "是" if innovation_done else "否",
            "completed_agent_types": "、".join(completed_agent_types) if completed_agent_types else "（尚无）",
            "iteration_count": state.get("iteration_count", 0),
            "max_iterations": state.get("max_iterations", 3),
            "revision_context": revision_context,
        })

        raw_text = raw.content if hasattr(raw, "content") else str(raw)
        tasks = _parse_tasks(raw_text)

        # 为每个任务补充 task_id（如果大模型没给）
        for t in tasks:
            if not t.get("task_id"):
                t["task_id"] = str(uuid.uuid4())[:8]

        log_msg = (
            f"[DecisionAgent] 规划生成 {len(tasks)} 个任务: "
            + ", ".join(f"{t.get('agent_type')}({t.get('section', '')})" for t in tasks)
        )
        print(log_msg)

        return {
            "pending_tasks": tasks,
            "current_phase": "executing",
            "status": "PLANNING",
            "decision_log": [log_msg],
            "discussion_history": [log_msg],
        }

    except Exception as e:
        err_msg = f"[DecisionAgent] 规划失败: {e}，使用默认任务计划"
        print(err_msg)
        default_tasks = _default_task_plan(state)
        return {
            "pending_tasks": default_tasks,
            "current_phase": "executing",
            "status": "PLANNING",
            "decision_log": [err_msg],
            "discussion_history": [err_msg],
        }


def run_final_decision(state: GraphState) -> Dict[str, Any]:
    """
    辩论后裁决：读取 debate_conclusion 决定是否修改、修改哪些地方
    """
    config = state.get("model_config") or {}
    provider = config.get("decision", config.get("writer", "deepseek"))
    llm = get_llm(provider_override=provider, temperature=0.1, is_json_mode=True)

    iteration_count = state.get("iteration_count", 0)
    max_iterations = state.get("max_iterations", 3)

    # 强制定稿条件
    if iteration_count >= max_iterations:
        msg = f"[DecisionAgent] 已达最大迭代 {max_iterations} 次，强制定稿。"
        print(msg)
        return {
            "revision_required": False,
            "revision_targets": [],
            "debate_conclusion": state.get("debate_conclusion", "达到最大迭代次数，自动定稿。"),
            "current_phase": "finalizing",
            "status": "FINALIZING",
            "decision_log": [msg],
            "discussion_history": [msg],
        }

    prompt = ChatPromptTemplate.from_messages([
        ("system", _VERDICT_SYSTEM),
        ("user", _VERDICT_USER),
    ])

    try:
        raw = (prompt | llm).invoke({
            "research_topic": state.get("research_topic", ""),
            "iteration_count": iteration_count,
            "max_iterations": max_iterations,
            "debate_conclusion": state.get("debate_conclusion", "（无辩论结论）"),
            "review_summary": _summarize_review_feedbacks(state.get("review_feedbacks") or []),
        })

        raw_text = raw.content if hasattr(raw, "content") else str(raw)
        verdict = _parse_verdict(raw_text)

        revision_required: bool = verdict.get("revision_required", False)
        revision_targets: List[Dict] = verdict.get("revision_targets", [])
        summary: str = verdict.get("decision_summary", "")

        phase = "revising" if revision_required else "finalizing"
        status = "REVISING" if revision_required else "FINALIZING"

        log_msg = (
            f"[DecisionAgent] 裁决：{'需要修改' if revision_required else '定稿'} | {summary}"
        )
        print(log_msg)
        if revision_targets:
            for t in revision_targets:
                print(f"  修改目标: [{t.get('priority','?')}] 《{t.get('section','?')}》 {t.get('issue','')}")

        return {
            "revision_required": revision_required,
            "revision_targets": revision_targets,
            "current_phase": phase,
            "status": status,
            "iteration_count": iteration_count + 1,
            "decision_log": [log_msg],
            "discussion_history": [log_msg],
        }

    except Exception as e:
        err_msg = f"[DecisionAgent] 裁决失败: {e}，默认定稿"
        print(err_msg)
        return {
            "revision_required": False,
            "revision_targets": [],
            "current_phase": "finalizing",
            "status": "FINALIZING",
            "decision_log": [err_msg],
            "discussion_history": [err_msg],
        }


# ─────────────────────── Parsers ───────────────────────

def _parse_tasks(raw_text: str) -> List[Dict]:
    """从 LLM 输出中解析任务列表"""
    import re
    try:
        import json
        # 尝试直接解析
        result = json.loads(raw_text)
        if isinstance(result, list):
            return result
        if isinstance(result, dict) and "tasks" in result:
            return result["tasks"]
    except Exception:
        pass

    # 正则提取 JSON 数组
    match = re.search(r'\[.*\]', raw_text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except Exception:
            pass

    return []


def _parse_verdict(raw_text: str) -> Dict:
    """从 LLM 输出中解析裁决"""
    import re, json
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
    return {"revision_required": False, "revision_targets": [], "decision_summary": "解析失败，默认定稿"}


def _default_task_plan(state: GraphState) -> List[Dict]:
    """LLM 失败时的兜底任务计划"""
    SECTIONS = ["立项依据", "研究目标与内容", "研究方案与可行性", "特色与创新", "研究基础"]
    draft_sections = state.get("draft_sections") or {}
    revision_targets = state.get("revision_targets") or []

    tasks: List[Dict] = []

    # 如果有修改目标，只处理修改目标
    if revision_targets:
        for t in revision_targets:
            tasks.append({
                "task_id": str(uuid.uuid4())[:8],
                "agent_type": "writer",
                "section": t.get("section", ""),
                "instructions": f"修改指令：{t.get('instruction', '')}（问题：{t.get('issue', '')}）",
                "priority": 8 if t.get("priority") == "high" else 5,
            })
        return tasks

    # 否则：先搜索，再逐章写作
    has_refs = bool(state.get("reference_documents"))
    if not has_refs:
        tasks.append({
            "task_id": str(uuid.uuid4())[:8],
            "agent_type": "searcher",
            "section": "",
            "instructions": f"搜索：{state.get('research_topic', '')} 相关最新研究、研究现状、研究空白",
            "priority": 10,
        })

    if not state.get("innovation_points"):
        tasks.append({
            "task_id": str(uuid.uuid4())[:8],
            "agent_type": "innovation",
            "section": "",
            "instructions": "根据研究主题和文献，提炼3-5个核心创新点",
            "priority": 9,
        })

    for sec in SECTIONS:
        if len(draft_sections.get(sec, "")) < 100:
            tasks.append({
                "task_id": str(uuid.uuid4())[:8],
                "agent_type": "writer",
                "section": sec,
                "instructions": f"撰写《{sec}》完整内容，字数2000字以上",
                "priority": 7,
            })

    return tasks
