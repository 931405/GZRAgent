"""
workflow.py — 撰写工作流 API (新版)

POST /api/workflow/start       → 启动工作流，返回 run_id
GET  /api/workflow/stream/{id} → SSE 实时推送工作流进度
GET  /api/workflow/result/{id} → 获取最终结果
POST /api/workflow/stop/{id}   → 停止工作流

新增 SSE 事件类型：
  task_dispatch   - 决策 Agent 派发的任务列表
  debate_update   - 评审专家辩论轮次更新
  debate_verdict  - 辩论最终裁决
  innovation      - 创新点内容就绪
  layout_done     - 排版审查完成
"""
import asyncio
import json
import uuid
import threading
from typing import AsyncGenerator, Dict, Optional
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

router = APIRouter()

# 全局运行状态（生产环境建议 Redis）
_runs: Dict[str, dict] = {}


def cancel_all_runs():
    """优雅地取消所有正在运行的工作流（应用关闭时调用）"""
    for run_id, run_data in _runs.items():
        if run_data.get("status") in ("pending", "running"):
            with run_data["lock"]:
                run_data["cancelled"] = True
                run_data["status"] = "stopped"

ALL_SECTIONS = ["立项依据", "研究目标与内容", "研究方案与可行性", "特色与创新", "研究基础"]


# ─────────────────────── Request Schema ───────────────────────

class WorkflowStartRequest(BaseModel):
    project_type: str = "面上项目"
    research_topic: str
    current_focus: str = "全文"         # 新架构默认写全文
    max_iterations: int = 2
    mode: str = "all"                   # "all"=新多Agent全文模式 | "single"=兼容旧版单章节模式
    template_hint: str = ""
    draft_sections: Dict[str, str] = Field(default_factory=dict)
    model_config_: Dict[str, str] = Field(default_factory=lambda: {
        "decision": "deepseek",
        "searcher": "deepseek",
        "writer": "deepseek",
        "innovation": "deepseek",
        "reviewer": "deepseek",
        "layout": "deepseek",
        "embeddings": "doubao",
    }, alias="model_config")

    class Config:
        populate_by_name = True


# ─────────────────────── State Builder ───────────────────────

def _make_graph_state(req: WorkflowStartRequest, focus: str, draft_sections: Optional[dict] = None) -> dict:
    return {
        # 基础
        "project_type": req.project_type,
        "research_topic": req.research_topic,
        "current_focus": focus,
        "draft_sections": dict(draft_sections or {}),
        "document_dom": {},
        "innovation_points": "",
        "layout_notes": "",
        # 检索
        "reference_documents": [],
        "reference_dict": {},
        # 评审
        "review_feedbacks": [],
        "prev_review_feedbacks": [],
        "discussion_history": [],
        # 系统控制
        "iteration_count": 0,
        "max_iterations": req.max_iterations,
        "status": "INITIALIZED",
        "reviewer_score": 0.0,
        # 决策系统
        "pending_tasks": [],
        "completed_tasks": [],
        "decision_log": [],
        "current_phase": "planning",
        # 辩论
        "debate_rounds": [],
        "debate_conclusion": "",
        "revision_required": False,
        "revision_targets": [],
        # 知识传递
        "completed_section_summaries": {},
        "document_outline": "",
        # 结果
        "final_document_path": None,
        "model_config": req.model_config_,
        "generated_images": {},
    }


# ─────────────────────── REST Endpoints ───────────────────────

@router.post("/start")
def start_workflow(req: WorkflowStartRequest):
    """启动工作流，立即返回 run_id"""
    run_id = str(uuid.uuid4())
    _runs[run_id] = {
        "status": "pending",
        "request": req,
        "draft_sections": dict(req.draft_sections),
        "review_feedbacks": [],
        "messages": [],
        "cancelled": False,
        "lock": threading.Lock(),
    }
    return {"run_id": run_id, "mode": req.mode}


@router.post("/stop/{run_id}")
async def stop_workflow(run_id: str):
    run = _runs.get(run_id)
    if not run:
        return {"error": "run_id not found", "status": "not_found"}
    with run.get("lock", threading.Lock()):
        run["cancelled"] = True
        run["status"] = "stopped"
    # 真正取消 asyncio 任务（中断正在运行的 LLM 调用）
    task: asyncio.Task = run.get("_async_task")
    if task and not task.done():
        task.cancel()
    # 清理 Gateway 队列
    from backend.gateway import cleanup_queue
    cleanup_queue(run_id)
    return {"status": "stopped", "run_id": run_id}


# ─────────────────────── Gateway 消息注入端点 ───────────────────────

class SteerRequest(BaseModel):
    """Steer 打断请求"""
    content: str
    priority: int = 9

class CollectRequest(BaseModel):
    """Collect 收集请求"""
    content: str
    target_section: str = ""


@router.post("/steer/{run_id}")
def steer_workflow(run_id: str, req: SteerRequest):
    """注入 Steer 消息：打断当前流程，在下一个安全检查点注入优先指令。
    
    典型用途：
    - "跳过文献检索，直接开始写作"
    - "不要修改立项依据，保持原样"
    """
    run = _runs.get(run_id)
    if not run or run.get("status") not in ("pending", "running"):
        return {"error": "run_id not found or not running", "status": "error"}
    
    from backend.gateway import push_steer
    push_steer(run_id, req.content, priority=req.priority)
    return {"status": "queued", "strategy": "steer", "run_id": run_id}


@router.post("/collect/{run_id}")
def collect_feedback(run_id: str, req: CollectRequest):
    """注入 Collect 消息：收集修改意见到缓冲区，等待合并后统一提交。
    
    典型用途：连续多条修改建议（如"把第三段数据更新"+"在方案中增加实验"）
    """
    run = _runs.get(run_id)
    if not run or run.get("status") not in ("pending", "running"):
        return {"error": "run_id not found or not running", "status": "error"}
    
    from backend.gateway import push_collect
    push_collect(run_id, req.content, target_section=req.target_section)
    return {"status": "buffered", "strategy": "collect", "run_id": run_id}


@router.post("/flush/{run_id}")
def flush_collected(run_id: str):
    """手动刷新 Collect 缓冲区，立即合并提交所有已缓冲的修改意见。"""
    from backend.gateway import flush_collect
    result = flush_collect(run_id)
    if result:
        return {"status": "flushed", "merged_count": result["count"]}
    return {"status": "empty", "message": "缓冲区为空"}


@router.get("/queue/{run_id}")
def get_queue_info(run_id: str):
    """获取 Gateway 队列状态（供前端展示）。"""
    from backend.gateway import get_queue_status
    return get_queue_status(run_id)


# ─────────────────────── SSE Generator ───────────────────────

async def _run_workflow_generator(run_id: str, request: Request) -> AsyncGenerator[str, None]:
    """异步 SSE 生成器：执行工作流并实时推送事件"""
    run = _runs.get(run_id)
    if not run:
        yield f"data: {json.dumps({'type': 'error', 'message': 'run_id not found'})}\n\n"
        return

    run["status"] = "running"
    req: WorkflowStartRequest = run["request"]

    def _sse(payload: dict) -> str:
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    import time
    last_heartbeat = time.time()
    HEARTBEAT_INTERVAL = 10

    # ── 新版全文多 Agent 模式 ──
    if req.mode in ("all", "full"):
        # 小延迟给 EventSource 接入时间
        await asyncio.sleep(0.3)
        yield _sse({"type": "log", "node": "system", "message": "🚀 启动多Agent动态调度工作流..."})
        yield _sse({"type": "workflow_mode", "mode": "multi_agent"})

        from src.orchestrator import build_orchestrator
        app = build_orchestrator()
        graph_state = _make_graph_state(req, "全文", draft_sections=run["draft_sections"])

        try:
            async for output in app.astream(graph_state):
                # Check cancellation before processing each node output
                if run.get("cancelled"):
                    yield _sse({"type": "stopped", "message": "工作流已被用户中止"})
                    with run["lock"]:
                        run["status"] = "stopped"
                    return

                if await request.is_disconnected():
                    print(f"[Workflow] 客户端已断开，主动中止运行: {run_id}")
                    with run["lock"]:
                        run["cancelled"] = True
                        run["status"] = "stopped"
                    return

                for node_name, state_update in output.items():
                    # ── 通用日志推送 ──
                    with run["lock"]:
                        for msg in state_update.get("discussion_history") or []:
                            # 尝试解析结构化 JSON 条目，提取可读消息
                            display_msg = msg
                            detected_node = node_name
                            try:
                                import json as _json
                                entry = _json.loads(msg)
                                if isinstance(entry, dict) and "agent" in entry and "content" in entry:
                                    agent = entry["agent"]
                                    content = entry["content"]
                                    section = entry.get("section", "")
                                    # 根据 agent 名称添加 emoji 前缀，使 LogPanel 能正确解析
                                    agent_lower = agent.lower()
                                    if "decision" in agent_lower or "orchestrat" in agent_lower:
                                        display_msg = f"🧠 [DecisionAgent] {content}"
                                        detected_node = "decision_agent"
                                    elif "search" in agent_lower:
                                        display_msg = f"[{section} / searcher] {content}" if section else f"[searcher] {content}"
                                        detected_node = "multi_worker"
                                    elif "writer" in agent_lower:
                                        display_msg = f"[{section} / writer] {content}" if section else f"[writer] {content}"
                                        detected_node = "multi_worker"
                                    elif "reviewer" in agent_lower:
                                        display_msg = f"[{section} / reviewer] {content}" if section else f"[reviewer] {content}"
                                        detected_node = "review_panel"
                                    elif "innovat" in agent_lower:
                                        display_msg = f"💡 [InnovationAgent] {content}"
                                        detected_node = "multi_worker"
                                    elif "design" in agent_lower:
                                        display_msg = f"[{section} / designer] {content}" if section else f"[designer] {content}"
                                        detected_node = "multi_worker"
                                    elif "layout" in agent_lower:
                                        display_msg = f"📐 [LayoutAgent] {content}"
                                        detected_node = "layout_agent"
                                    elif "coherence" in agent_lower:
                                        display_msg = f"[{section} / coherence_checker] {content}" if section else f"[coherence_checker] {content}"
                                    elif "outline" in agent_lower:
                                        display_msg = f"[全文 / outline_planner] {content}"
                                    else:
                                        display_msg = f"[{section or '-'} / {agent}] {content}"
                            except (ValueError, TypeError):
                                # 纯文本格式，原样使用
                                display_msg = f"[{node_name}] {msg}"
                            
                            run["messages"].append(display_msg)
                            yield _sse({"type": "log", "node": detected_node, "message": display_msg})

                    # ── 决策日志 ──
                    for dmsg in state_update.get("decision_log") or []:
                        yield _sse({"type": "decision_log", "node": node_name, "message": dmsg})

                    # ── 任务派发 ──
                    pending = state_update.get("pending_tasks")
                    if pending:
                        yield _sse({"type": "task_dispatch", "tasks": pending,
                                    "count": len(pending)})

                    # ── 草稿更新 ──
                    if "draft_sections" in state_update:
                        with run["lock"]:
                            for sec, content in (state_update["draft_sections"] or {}).items():
                                if content:
                                    run["draft_sections"][sec] = content
                                    yield _sse({"type": "draft_update", "section": sec,
                                                "content": content})

                    # ── 评审反馈 ──
                    if "review_feedbacks" in state_update:
                        with run["lock"]:
                            feedbacks = state_update["review_feedbacks"] or []
                            run["review_feedbacks"] = feedbacks
                            yield _sse({"type": "feedback_update", "feedbacks": feedbacks})

                    # ── 评分 ──
                    if "reviewer_score" in state_update:
                        score = state_update["reviewer_score"]
                        yield _sse({"type": "reviewer_direct", "score": score,
                                    "iteration": state_update.get("iteration_count", 0)})

                    # ── 辩论轮次 ──
                    new_rounds = state_update.get("debate_rounds")
                    if new_rounds:
                        yield _sse({"type": "debate_update", "rounds": new_rounds})

                    # ── 辩论裁决 ──
                    conclusion = state_update.get("debate_conclusion")
                    if conclusion:
                        revision = state_update.get("revision_required", False)
                        targets = state_update.get("revision_targets", [])
                        yield _sse({"type": "debate_verdict", "conclusion": conclusion,
                                    "revision_required": revision, "targets": targets})

                    # ── 创新点就绪 ──
                    if state_update.get("innovation_points"):
                        yield _sse({"type": "innovation", "content": state_update["innovation_points"]})

                    # ── 排版审查结果 ──
                    if state_update.get("layout_notes"):
                        yield _sse({"type": "layout_done", "notes": state_update["layout_notes"]})

                await asyncio.sleep(0)

                # ── Gateway 安全检查点：消费队列中的 steer/collect 消息 ──
                from backend.gateway import consume as gw_consume
                gw_msg = gw_consume(run_id)
                if gw_msg:
                    yield _sse({
                        "type": "gateway_inject",
                        "strategy": gw_msg["strategy"],
                        "instructions": gw_msg["instructions"],
                        "count": gw_msg["count"],
                    })
                    # 将 gateway 指令注入到 discussion_history 供下一个节点消费
                    with run["lock"]:
                        inject_msg = f"🔀 [用户指令/{gw_msg['strategy']}] {gw_msg['instructions']}"
                        run["messages"].append(inject_msg)

                # Heartbeat
                now = time.time()
                if now - last_heartbeat >= HEARTBEAT_INTERVAL:
                    yield _sse({"type": "heartbeat"})
                    last_heartbeat = now

        except asyncio.CancelledError:
            yield _sse({"type": "stopped", "message": "工作流已被用户强制中止"})
            with run["lock"]:
                run["status"] = "stopped"
            return
        except Exception as e:
            yield _sse({"type": "error", "message": str(e)})

    # ── 旧版兼容模式（单章节） ──
    else:
        yield _sse({"type": "log", "node": "system", "message": "启动单章节模式（兼容旧版）..."})
        yield _sse({"type": "workflow_mode", "mode": "single"})

        from src.orchestrator import build_orchestrator
        app = build_orchestrator()

        sections = [req.current_focus]
        graph_state = _make_graph_state(
            req, req.current_focus, draft_sections=run["draft_sections"]
        )

        for sec in sections:
            if run.get("cancelled"):
                yield _sse({"type": "stopped", "message": f"已在 '{sec}' 前中止"})
                run["status"] = "stopped"
                return

            graph_state["current_focus"] = sec
            graph_state["iteration_count"] = 0
            yield _sse({"type": "section_start", "section": sec})

            try:
                async for output in app.astream(graph_state):
                    if await request.is_disconnected():
                        print(f"[Workflow] 客户端已断开，单章节流主动中止: {run_id}")
                        with run["lock"]:
                            run["cancelled"] = True
                            run["status"] = "stopped"
                        return

                    for node_name, state_update in output.items():
                        with run["lock"]:
                            for msg in state_update.get("discussion_history") or []:
                                full_msg = f"[{sec}/{node_name}] {msg}"
                                run["messages"].append(full_msg)
                                yield _sse({"type": "log", "section": sec, "node": node_name,
                                            "message": full_msg})

                        if "draft_sections" in state_update:
                            with run["lock"]:
                                for s, c in (state_update["draft_sections"] or {}).items():
                                    if c:
                                        run["draft_sections"][s] = c
                                        yield _sse({"type": "draft_update", "section": s, "content": c})

                        if "review_feedbacks" in state_update:
                            with run["lock"]:
                                feedbacks = state_update["review_feedbacks"] or []
                                run["review_feedbacks"] = feedbacks
                                yield _sse({"type": "feedback_update", "feedbacks": feedbacks})

                        if "reviewer_score" in state_update:
                            yield _sse({"type": "reviewer_direct", "section": sec,
                                        "score": state_update["reviewer_score"]})

                    await asyncio.sleep(0)
                    now = time.time()
                    if now - last_heartbeat >= HEARTBEAT_INTERVAL:
                        yield _sse({"type": "heartbeat"})
                        last_heartbeat = now

            except Exception as e:
                yield _sse({"type": "error", "message": str(e)})

            yield _sse({"type": "section_done", "section": sec})

    # ── 收尾：参考文献整理 ──
    import re
    drafts = run.get("draft_sections") or {}
    if drafts:
        ref_dict = run.get("ref_dict") or {}
        used_refs = set()
        for _c in drafts.values():
            used_refs.update(re.findall(r"\[(Ref-\d+)\]", _c))
        if used_refs:
            with run["lock"]:
                sorted_refs = sorted(list(used_refs), key=lambda x: int(x.split("-")[1]))
                ref_mapping = {r: f"[{i+1}]" for i, r in enumerate(sorted_refs)}
                bib_lines = [f"{ref_mapping[r]} {ref_dict.get(r, 'Unknown Reference')}" for r in sorted_refs]
                for _s, _c in drafts.items():
                    for old_id, new_id in ref_mapping.items():
                        _c = _c.replace(f"[{old_id}]", new_id)
                    drafts[_s] = _c
                drafts["参考文献"] = "\n".join(bib_lines)
                run["draft_sections"] = drafts
                yield _sse({"type": "draft_update", "section": "参考文献",
                            "content": drafts["参考文献"]})
                yield _sse({"type": "log", "node": "reference_compiler",
                            "message": f"整理了 {len(used_refs)} 条参考文献"})

    # ── 自动保存历史 ──
    try:
        from src.utils.history_manager import save_history
        save_state = {
            "project_type": req.project_type,
            "research_topic": req.research_topic,
            "draft_sections": run["draft_sections"],
            "discussion_history": run["messages"],
        }
        p_name = req.research_topic[:10]
        save_history(save_state, f"{req.project_type}_{p_name}")
        yield _sse({"type": "log", "node": "system", "message": "历史记录已自动保存"})
    except Exception as e:
        print(f"[Auto-save Error]: {e}")

    run["status"] = "done"
    yield _sse({"type": "done", "draft_sections": run["draft_sections"]})


# ─────────────────────── Stream & Result Endpoints ───────────────────────

@router.get("/stream/{run_id}")
async def stream_workflow(run_id: str, request: Request):
    """SSE 订阅端点"""
    async def _wrapper():
        """Wraps generator and stores the asyncio task for cancellation"""
        run = _runs.get(run_id)
        if run:
            run["_async_task"] = asyncio.current_task()
        try:
            async for chunk in _run_workflow_generator(run_id, request):
                yield chunk
        except asyncio.CancelledError:
            # Task was cancelled by stop_workflow — emit final stopped event
            yield f"data: {json.dumps({'type': 'stopped', 'message': '工作流已被用户强制中止'}, ensure_ascii=False)}\n\n"
    return StreamingResponse(
        _wrapper(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/result/{run_id}")
def get_result(run_id: str):
    """获取最终结果"""
    run = _runs.get(run_id)
    if not run:
        return {"error": "not found"}
    return {
        "status": run["status"],
        "draft_sections": run.get("draft_sections", {}),
        "review_feedbacks": run.get("review_feedbacks", []),
        "messages": run.get("messages", []),
    }
