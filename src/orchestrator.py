"""
orchestrator.py — 新版多 Agent 动态调度工作流

架构：
  START
    ↓
  decision_agent         ← 分析当前状态，生成 pending_tasks
    ↓
  multi_worker           ← 并发执行 pending_tasks 中的各 Agent
    ↓ (条件路由)
  ├─ [内容不足] → decision_agent    （继续派发任务）
  ├─ [内容充足] → review_panel
  └─ [达到上限] → layout_agent
    ↓
  review_panel           ← 4位专家并发评审 + 2轮辩论
    ↓
  final_decision         ← 决策Agent解读辩论裁决
    ├─ [revise] → decision_agent       （带修改目标，重新规划）
    └─ [finalize] → layout_agent
    ↓
  layout_agent           ← 排版优化
    ↓
  END
"""
import concurrent.futures
import copy
from typing import Dict, Any, List

from langgraph.graph import StateGraph, END
from src.state import GraphState

from src.agents.decision_agent import run_decision_agent, run_final_decision
from src.agents.innovation_agent import run_innovation_agent
from src.agents.diagram_agent import run_diagram_agent
from src.agents.layout_agent import run_layout_agent
from src.agents.debate_panel import run_debate_panel

# ──────────────────────────────────────────────────────────────────
# Multi-Worker: 并发执行 pending_tasks
# ──────────────────────────────────────────────────────────────────

ALL_SECTIONS = ["立项依据", "研究目标与内容", "研究方案与可行性", "特色与创新", "研究基础"]
_MIN_SECTION_CHARS = 800   # 章节至少多少字才算写完


def _run_task(state: GraphState, task: Dict[str, Any]) -> Dict[str, Any]:
    """执行单个任务（适合 ThreadPoolExecutor 并发调用）"""
    agent_type = task.get("agent_type", "")
    section = task.get("section", "")
    instructions = task.get("instructions", "")

    # 为每个任务拷贝状态，避免并发写冲突
    task_state: GraphState = {**state}  # type: ignore[assignment]
    if section:
        task_state = {**task_state, "current_focus": section}  # type: ignore[assignment]

    try:
        if agent_type == "searcher":
            from src.agents.searcher import run_searcher
            return run_searcher(task_state)

        elif agent_type == "innovation":
            return run_innovation_agent(task_state)

        elif agent_type == "writer":
            if not section:
                return {}
            from src.agents.writer import run_writer
            return run_writer(task_state)

        elif agent_type == "diagram":
            return run_diagram_agent(task_state, section=section, instructions=instructions)

        elif agent_type == "layout":
            return run_layout_agent(task_state)

        elif agent_type == "data":
            from src.agents.data_agent import run_data_agent
            parts = instructions.split("|", 1)
            pid = parts[0] if len(parts) > 0 else f"tbl_{section}"
            pdesc = parts[1] if len(parts) > 1 else instructions
            return run_data_agent(task_state, section=section, placeholder_id=pid, placeholder_desc=pdesc)
            
        elif agent_type == "formula":
            from src.agents.formula_agent import run_formula_agent
            parts = instructions.split("|", 1)
            pid = parts[0] if len(parts) > 0 else f"eq_{section}"
            pdesc = parts[1] if len(parts) > 1 else instructions
            return run_formula_agent(task_state, section=section, placeholder_id=pid, placeholder_desc=pdesc)

        else:
            msg = f"[MultiWorker] 未知 agent_type: {agent_type}，跳过"
            print(msg)
            return {"discussion_history": [msg]}

    except Exception as e:
        err = f"[MultiWorker] 任务 {agent_type}({section}) 执行失败: {e}"
        print(err)
        return {"discussion_history": [err]}


def _merge_results(base: GraphState, results: List[Dict]) -> Dict[str, Any]:  # type: ignore[override]
    """将多个任务结果安全合并回主状态"""
    state: Dict[str, Any] = dict(base)  # type: ignore[arg-type]

    for result in results:
        if not result:
            continue

        # draft_sections: 用新内容覆盖同名章节
        if "draft_sections" in result:
            current = dict(state.get("draft_sections") or {})
            current.update(result["draft_sections"])
            state["draft_sections"] = current
            
            # 自动转入 V2 DOM
            from src.state import SectionDOM, TextElement
            existing_dom = dict(state.get("document_dom") or {})
            for sec, content in result["draft_sections"].items():
                if sec not in existing_dom:
                    existing_dom[sec] = SectionDOM(title=sec, elements=[])
                existing_dom[sec].elements.append(TextElement(id=f"{sec}_text", content=content))
            state["document_dom"] = existing_dom
            
        # document_dom: 新图表/公式元素增量合并
        if "document_dom" in result:
            from src.state import SectionDOM
            existing_dom = dict(state.get("document_dom") or {})
            for sec, updates in result["document_dom"].items():
                if sec not in existing_dom:
                    existing_dom[sec] = SectionDOM(title=sec, elements=[])
                if "element_updates" in updates:
                    existing_dom[sec].elements.extend(updates["element_updates"])
            state["document_dom"] = existing_dom

        # reference_documents: 追加去重
        if "reference_documents" in result:
            existing = list(state.get("reference_documents") or [])
            state["reference_documents"] = existing + result["reference_documents"]

        # reference_dict: 合并
        if "reference_dict" in result:
            existing = dict(state.get("reference_dict") or {})
            existing.update(result["reference_dict"])
            state["reference_dict"] = existing

        # discussion_history: 追加
        if "discussion_history" in result:
            existing = list(state.get("discussion_history") or [])
            state["discussion_history"] = existing + result["discussion_history"]

        # completed_tasks: 追加
        if "completed_tasks" in result:
            existing = list(state.get("completed_tasks") or [])
            state["completed_tasks"] = existing + result["completed_tasks"]

        # generated_images: 合并
        if "generated_images" in result:
            existing = dict(state.get("generated_images") or {})
            existing.update(result["generated_images"])
            state["generated_images"] = existing

        # innovation_points: 替换
        if result.get("innovation_points"):
            state["innovation_points"] = result["innovation_points"]

        # layout_notes: 替换
        if result.get("layout_notes"):
            state["layout_notes"] = result["layout_notes"]

    return state


def run_multi_worker(state: GraphState) -> Dict[str, Any]:
    """并发执行 pending_tasks 中的全部任务，结果合并后返回状态更新"""
    tasks: List[Dict] = list(state.get("pending_tasks") or [])
    if not tasks:
        msg = "[MultiWorker] 没有待执行任务，跳过"
        print(msg)
        return {"discussion_history": [msg], "pending_tasks": [], "current_phase": "executing"}

    # 按优先级排序（高优先级先启动）
    tasks_sorted = sorted(tasks, key=lambda t: -t.get("priority", 5))

    log_msg = (
        f"[MultiWorker] 并发执行 {len(tasks_sorted)} 个任务: "
        + ", ".join(
            f"{t.get('agent_type')}({t.get('section', '-')})"
            for t in tasks_sorted
        )
    )
    print(log_msg)

    # 并发执行
    results: List[Dict] = []
    max_workers = min(len(tasks_sorted), 6)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_run_task, state, t) for t in tasks_sorted]
        for fut in concurrent.futures.as_completed(futures):
            try:
                results.append(fut.result())
            except Exception as e:
                results.append({"discussion_history": [f"[MultiWorker] 任务未知异常: {e}"]})

    # 合并所有结果
    merged = _merge_results(state, results)

    # 记录已完成任务
    newly_done = [{
        "task_id": t.get("task_id", ""),
        "agent_type": t.get("agent_type", ""),
        "section": t.get("section", ""),
        "result": "done",
    } for t in tasks_sorted]
    merged["completed_tasks"] = list(state.get("completed_tasks") or []) + newly_done
    merged["pending_tasks"] = []
    merged["status"] = "EXECUTING"

    done_msg = f"[MultiWorker] 全部 {len(tasks_sorted)} 个任务完成"
    print(done_msg)
    msgs = list(merged.get("discussion_history") or [])
    msgs.insert(0, log_msg)
    msgs.append(done_msg)
    merged["discussion_history"] = msgs

    # 只返回状态变更字段（不传递 model_config 等只读字段以避免 reducer 冲突）
    excluded = {"model_config", "project_type", "research_topic", "max_iterations"}
    return {k: v for k, v in merged.items() if k not in excluded}


# ──────────────────────────────────────────────────────────────────
# Edge Logic (Routing)
# ──────────────────────────────────────────────────────────────────

def _sections_ready(state: GraphState) -> bool:
    """判断是否有足够内容进入评审（3个以上章节达到最低字数）"""
    drafts = state.get("draft_sections") or {}
    done = [s for s in ALL_SECTIONS if len(drafts.get(s, "")) >= _MIN_SECTION_CHARS]
    return len(done) >= 3


def route_after_worker(state: GraphState) -> str:
    """MultiWorker 完成后路由"""
    iteration = state.get("iteration_count", 0)
    max_iter = state.get("max_iterations", 3)

    if iteration >= max_iter:
        print("[Router] 达到最大迭代，强制排版定稿")
        return "layout_agent"

    if _sections_ready(state):
        print("[Router] 内容充足，进入评审辩论面板")
        return "review_panel"

    print("[Router] 内容不足，返回决策 Agent 继续规划")
    return "decision_agent"


def route_after_decision(state: GraphState) -> str:
    """final_decision 后路由"""
    revision_required = state.get("revision_required", False)
    phase = state.get("current_phase", "")

    if revision_required and phase == "revising":
        print("[Router] 裁决：需要修改，返回决策 Agent 重新调度")
        return "decision_agent"

    print("[Router] 裁决：定稿，进入排版优化")
    return "layout_agent"


# ──────────────────────────────────────────────────────────────────
# Graph Assembly
# ──────────────────────────────────────────────────────────────────

def build_orchestrator():
    """构建并返回编译好的多 Agent 动态调度图"""
    workflow = StateGraph(GraphState)

    # 注册节点
    workflow.add_node("decision_agent", run_decision_agent)
    workflow.add_node("multi_worker", run_multi_worker)
    workflow.add_node("review_panel", run_debate_panel)
    workflow.add_node("final_decision", run_final_decision)
    workflow.add_node("layout_agent", run_layout_agent)

    # 入口
    workflow.set_entry_point("decision_agent")

    # 决策 → 并发工作
    workflow.add_edge("decision_agent", "multi_worker")

    # 工作完成后 → 三路判断
    workflow.add_conditional_edges(
        "multi_worker",
        route_after_worker,
        {
            "review_panel": "review_panel",
            "decision_agent": "decision_agent",
            "layout_agent": "layout_agent",
        },
    )

    # 评审 → 最终裁决
    workflow.add_edge("review_panel", "final_decision")

    # 裁决 → 修改/定稿
    workflow.add_conditional_edges(
        "final_decision",
        route_after_decision,
        {
            "decision_agent": "decision_agent",
            "layout_agent": "layout_agent",
        },
    )

    # 排版完成 → END
    workflow.add_edge("layout_agent", END)

    return workflow.compile()
