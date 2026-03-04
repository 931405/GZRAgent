"""
LangGraph Workflow — Map-Reduce academic writing orchestration.

Implements real LLM API calls via the L1 provider layer.
Each workflow node:
  1. Gets the appropriate LLM provider for the agent
  2. Calls the LLM with task-specific prompts
  3. Broadcasts progress via WebSocket to connected clients

Flow:
  decompose -> write -> evidence -> diagrams -> integrate
  -> review --(pass)--> format -> END
           --(fail)--> revise -> write (loop)
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any, TypedDict

from langgraph.graph import StateGraph, END

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LLM Helper
# ---------------------------------------------------------------------------

def _get_llm_for_agent(agent_name: str):
    """Get the configured LLM provider instance for a given agent.

    Reads agent -> provider mapping from Settings, then creates a provider.
    """
    from app.config import get_settings
    from app.core.l1.llm_provider import LLMProviderFactory

    settings = get_settings()
    provider_type, model_override = settings.get_agent_llm_config(agent_name)
    provider_config = settings.get_provider_config(provider_type)

    provider = LLMProviderFactory.create(
        provider_type.value,
        api_key=provider_config.api_key,
        base_url=provider_config.base_url,
        default_model=model_override or provider_config.default_model,
        timeout=provider_config.timeout,
        max_retries=provider_config.max_retries,
    )
    return provider


# ---------------------------------------------------------------------------
# WebSocket event helper
# ---------------------------------------------------------------------------

async def _broadcast_event(
    session_id: str,
    source: str,
    intent: str,
    message: str,
    agent_id: str | None = None,
    agent_status: str | None = None,
) -> None:
    """Send a telemetry event and optional agent state change to all WebSocket clients."""
    from app.api.websocket import manager

    await manager.broadcast(session_id, {
        "type": "telemetry",
        "data": {
            "id": str(uuid.uuid4()),
            "timestamp": int(time.time() * 1000),
            "source": source,
            "intent": intent,
            "message": message,
        },
    })

    if agent_id and agent_status:
        await manager.broadcast(session_id, {
            "type": "agent_state_change",
            "agent_id": agent_id,
            "status": agent_status,
        })


async def _broadcast_draft(session_id: str, content: str) -> None:
    """Push draft content update to connected clients."""
    from app.api.websocket import manager
    await manager.broadcast(session_id, {
        "type": "draft_update",
        "content": content,
    })


# ---------------------------------------------------------------------------
# Workflow State
# ---------------------------------------------------------------------------

class WritingState(TypedDict, total=False):
    """State passed through the LangGraph workflow."""
    session_id: str
    paper_topic: str
    outline: list[dict[str, Any]]

    sub_tasks: list[dict[str, Any]]
    current_task_idx: int

    draft_sections: dict[str, str]
    evidence_map: dict[str, list[dict]]

    integrated_draft: str
    diagrams: list[dict[str, Any]]

    review_findings: list[dict[str, Any]]
    review_passed: bool

    final_document: str
    status: str
    error: str


# ---------------------------------------------------------------------------
# Node functions — real LLM calls
# ---------------------------------------------------------------------------

async def decompose_task(state: WritingState) -> WritingState:
    """Node 1: PI Agent decomposes the outline into sub-tasks."""
    session_id = state.get("session_id", "")
    topic = state.get("paper_topic", "")
    outline = state.get("outline", [])
    logger.info("Workflow: decompose_task for session %s", session_id)

    await _broadcast_event(
        session_id, "PI_Agent", "TASK_ASSIGNED",
        "PI Agent 正在分析论文大纲并分解子任务...",
        agent_id="pi", agent_status="EXECUTE",
    )

    from app.core.l1.llm_provider import ChatMessage
    llm = _get_llm_for_agent("pi")

    outline_text = "\n".join(
        f"{i+1}. {s.get('title', f'Section {i}')}" for i, s in enumerate(outline)
    )

    messages = [
        ChatMessage(
            role="system",
            content=(
                "你是一名学术论文写作的 PI（首席研究员），负责编排和分解写作任务。"
                "你需要将论文大纲分解为具体的写作子任务，每个子任务包含明确的写作目标和要求。"
                "请用中文回复。"
            ),
        ),
        ChatMessage(
            role="user",
            content=(
                f"论文主题：{topic}\n\n"
                f"大纲：\n{outline_text}\n\n"
                "请为每个章节制定详细的写作指令，包括：\n"
                "1. 该章节的核心论点\n"
                "2. 需要涵盖的关键概念\n"
                "3. 建议的篇幅（字数）\n"
                "4. 写作注意事项\n\n"
                "请直接输出每个章节的写作指令，用 --- 分隔不同章节。"
            ),
        ),
    ]

    response = await llm.complete(messages, temperature=0.5, max_tokens=2000)

    # Parse response into sub_tasks
    sections = response.content.split("---")
    sub_tasks = []
    for i, section_text in enumerate(sections):
        section_text = section_text.strip()
        if not section_text:
            continue
        title = outline[i].get("title", f"Section {i}") if i < len(outline) else f"Section {i}"
        sub_tasks.append({
            "task_id": f"sec_{i}",
            "section_title": title,
            "writing_instructions": section_text,
            "assigned_writer": "writer",
        })

    # Ensure sub_tasks matches outline if parsing was imperfect
    if len(sub_tasks) < len(outline):
        for i in range(len(sub_tasks), len(outline)):
            title = outline[i].get("title", f"Section {i}")
            sub_tasks.append({
                "task_id": f"sec_{i}",
                "section_title": title,
                "writing_instructions": f"请撰写关于「{title}」的学术内容。",
                "assigned_writer": "writer",
            })

    task_list = ", ".join(t["section_title"] for t in sub_tasks)
    await _broadcast_event(
        session_id, "PI_Agent", "DELIVER_CONTENT",
        f"大纲已分解为 {len(sub_tasks)} 个子任务: {task_list}",
        agent_id="pi", agent_status="DONE",
    )

    return {
        **state,
        "sub_tasks": sub_tasks,
        "current_task_idx": 0,
        "status": "decomposed",
    }


async def write_sections(state: WritingState) -> WritingState:
    """Node 2: Writer Agent composes each section using LLM."""
    session_id = state.get("session_id", "")
    topic = state.get("paper_topic", "")
    logger.info("Workflow: write_sections")

    await _broadcast_event(
        session_id, "Writer_Agent", "TASK_ASSIGNED",
        "学术写手开始撰写各章节草稿...",
        agent_id="writer", agent_status="EXECUTE",
    )

    from app.core.l1.llm_provider import ChatMessage
    llm = _get_llm_for_agent("writer")

    draft_sections = {}
    for task in state.get("sub_tasks", []):
        section_id = task["task_id"]
        title = task["section_title"]
        instructions = task.get("writing_instructions", f"撰写关于 {title} 的学术内容。")

        await _broadcast_event(
            session_id, "Writer_Agent", "TASK_ASSIGNED",
            f"正在撰写: {title}...",
        )

        messages = [
            ChatMessage(
                role="system",
                content=(
                    "你是一名资深学术论文写手。请撰写高质量的学术文章章节。"
                    "要求：\n"
                    "- 使用正式的学术写作风格\n"
                    "- 逻辑清晰，论证充分\n"
                    "- 适当引用相关理论和方法\n"
                    "- 使用中文撰写\n"
                    "- 直接输出章节内容，不要加多余标题"
                ),
            ),
            ChatMessage(
                role="user",
                content=(
                    f"论文主题：{topic}\n"
                    f"章节标题：{title}\n\n"
                    f"写作指令：\n{instructions}\n\n"
                    f"请撰写该章节的完整内容（800-1500字）："
                ),
            ),
        ]

        try:
            response = await llm.complete(messages, temperature=0.7, max_tokens=3000)
            draft_sections[section_id] = response.content
            await _broadcast_event(
                session_id, "Writer_Agent", "DELIVER_CONTENT",
                f"已完成章节草稿: {title} ({len(response.content)} 字)",
            )
        except Exception as e:
            logger.error("Writer failed for %s: %s", section_id, e)
            draft_sections[section_id] = f"[写作失败: {e}]"
            await _broadcast_event(
                session_id, "Writer_Agent", "ERROR",
                f"章节 {title} 写作失败: {str(e)[:100]}",
            )

    await _broadcast_event(
        session_id, "Writer_Agent", "DELIVER_CONTENT",
        f"全部 {len(draft_sections)} 个章节草稿已完成",
        agent_id="writer", agent_status="DONE",
    )

    return {
        **state,
        "draft_sections": draft_sections,
        "status": "drafting",
    }


async def gather_evidence(state: WritingState) -> WritingState:
    """Node 3: Researcher Agent searches for evidence to support each section."""
    session_id = state.get("session_id", "")
    topic = state.get("paper_topic", "")
    logger.info("Workflow: gather_evidence")

    await _broadcast_event(
        session_id, "Researcher_Agent", "TASK_ASSIGNED",
        "文献研究员开始为各章节查找支撑文献...",
        agent_id="researcher", agent_status="EXECUTE",
    )

    from app.core.l1.llm_provider import ChatMessage
    llm = _get_llm_for_agent("researcher")

    evidence_map = {}
    for section_id, content in state.get("draft_sections", {}).items():
        title = section_id
        for task in state.get("sub_tasks", []):
            if task["task_id"] == section_id:
                title = task["section_title"]
                break

        messages = [
            ChatMessage(
                role="system",
                content=(
                    "你是一名学术文献研究员。根据论文章节内容，"
                    "提出该章节需要引用的关键参考文献建议。"
                    "对每个建议的引用,说明：\n"
                    "1. 建议引用的论文/著作（可以是虚构但合理的）\n"
                    "2. 引用的理由\n"
                    "3. 应插入到文中的位置\n"
                    "请用中文回答,每条建议用 --- 分隔。"
                ),
            ),
            ChatMessage(
                role="user",
                content=(
                    f"论文主题：{topic}\n"
                    f"章节标题：{title}\n\n"
                    f"章节内容摘要（前500字）：\n{content[:500]}\n\n"
                    "请提供 3-5 条参考文献建议："
                ),
            ),
        ]

        try:
            response = await llm.complete(messages, temperature=0.3, max_tokens=1500)
            refs = [
                {"suggestion": ref.strip(), "section": section_id}
                for ref in response.content.split("---")
                if ref.strip()
            ]
            evidence_map[section_id] = refs
            await _broadcast_event(
                session_id, "Researcher_Agent", "DELIVER_CONTENT",
                f"已为「{title}」找到 {len(refs)} 条文献建议",
            )
        except Exception as e:
            logger.error("Researcher failed for %s: %s", section_id, e)
            evidence_map[section_id] = []
            await _broadcast_event(
                session_id, "Researcher_Agent", "ERROR",
                f"文献检索失败 ({title}): {str(e)[:100]}",
            )

    total_refs = sum(len(v) for v in evidence_map.values())
    await _broadcast_event(
        session_id, "Researcher_Agent", "DELIVER_CONTENT",
        f"文献检索完成，共找到 {total_refs} 条参考文献建议",
        agent_id="researcher", agent_status="DONE",
    )

    return {
        **state,
        "evidence_map": evidence_map,
        "status": "evidence_gathered",
    }


async def generate_diagrams(state: WritingState) -> WritingState:
    """Node 4: Generate diagram suggestions based on the draft content."""
    session_id = state.get("session_id", "")
    topic = state.get("paper_topic", "")
    logger.info("Workflow: generate_diagrams")

    await _broadcast_event(
        session_id, "System", "TASK_ASSIGNED",
        "正在分析论文内容并生成图表建议...",
    )

    from app.core.l1.llm_provider import ChatMessage

    # Use PI agent's LLM for diagram suggestions
    llm = _get_llm_for_agent("pi")

    all_content = "\n".join(
        f"## {sid}\n{content[:300]}"
        for sid, content in state.get("draft_sections", {}).items()
    )

    messages = [
        ChatMessage(
            role="system",
            content=(
                "你是一名学术图表设计专家。根据论文内容，"
                "建议需要的图表（如架构图、流程图、对比表等），"
                "并用 Mermaid 语法生成图表代码。"
                "请用中文说明图表用途，Mermaid代码用代码块标记。"
            ),
        ),
        ChatMessage(
            role="user",
            content=(
                f"论文主题：{topic}\n\n"
                f"各章节内容摘要：\n{all_content}\n\n"
                "请建议 1-2 张最重要的图表，并给出 Mermaid 代码："
            ),
        ),
    ]

    try:
        response = await llm.complete(messages, temperature=0.5, max_tokens=1500)
        diagrams = [{"type": "mermaid", "description": response.content}]
        await _broadcast_event(
            session_id, "System", "DELIVER_CONTENT",
            "图表建议已生成",
        )
    except Exception as e:
        logger.error("Diagram generation failed: %s", e)
        diagrams = []
        await _broadcast_event(
            session_id, "System", "ERROR",
            f"图表生成失败: {str(e)[:100]}",
        )

    return {
        **state,
        "diagrams": diagrams,
        "status": "diagrams_generated",
    }


async def integrate_draft(state: WritingState) -> WritingState:
    """Node 5: PI Agent integrates all sections into a coherent draft."""
    session_id = state.get("session_id", "")
    topic = state.get("paper_topic", "")
    logger.info("Workflow: integrate_draft")

    await _broadcast_event(
        session_id, "PI_Agent", "TASK_ASSIGNED",
        "PI Agent 正在整合所有章节为连贯的论文初稿...",
        agent_id="pi", agent_status="EXECUTE",
    )

    from app.core.l1.llm_provider import ChatMessage
    llm = _get_llm_for_agent("pi")

    # Build the raw combined draft
    sections = state.get("draft_sections", {})
    sub_tasks = state.get("sub_tasks", [])

    raw_combined = ""
    for task in sub_tasks:
        sid = task["task_id"]
        title = task["section_title"]
        content = sections.get(sid, "[无内容]")
        raw_combined += f"\n## {title}\n\n{content}\n"

    messages = [
        ChatMessage(
            role="system",
            content=(
                "你是论文 PI（首席研究员），负责整合各章节为一篇连贯的论文。"
                "任务：\n"
                "1. 确保各章节之间的逻辑衔接顺畅\n"
                "2. 统一术语和写作风格\n"
                "3. 添加必要的过渡段落\n"
                "4. 保持每个章节的核心内容不变\n"
                "5. 输出完整的整合后论文\n"
                "请用中文输出。"
            ),
        ),
        ChatMessage(
            role="user",
            content=(
                f"论文主题：{topic}\n\n"
                f"以下是各章节的草稿内容，请整合为一篇连贯的论文：\n"
                f"{raw_combined}"
            ),
        ),
    ]

    try:
        response = await llm.complete(messages, temperature=0.4, max_tokens=6000)
        integrated = response.content
        await _broadcast_event(
            session_id, "PI_Agent", "DELIVER_CONTENT",
            f"论文初稿整合完成 ({len(integrated)} 字)",
            agent_id="pi", agent_status="DONE",
        )
    except Exception as e:
        logger.error("Integration failed: %s", e)
        # Fallback: just concatenate
        integrated = raw_combined
        await _broadcast_event(
            session_id, "PI_Agent", "ERROR",
            f"整合失败，使用原始拼接: {str(e)[:100]}",
            agent_id="pi", agent_status="DONE",
        )

    await _broadcast_draft(session_id, integrated)

    return {
        **state,
        "integrated_draft": integrated,
        "status": "integrated",
    }


async def red_team_review(state: WritingState) -> WritingState:
    """Node 6: Red Team Agent reviews the integrated draft."""
    session_id = state.get("session_id", "")
    topic = state.get("paper_topic", "")
    integrated = state.get("integrated_draft", "")
    logger.info("Workflow: red_team_review")

    await _broadcast_event(
        session_id, "RedTeam_Agent", "TASK_ASSIGNED",
        "红队审稿人开始严格审查论文初稿...",
        agent_id="reviewer", agent_status="EXECUTE",
    )

    from app.core.l1.llm_provider import ChatMessage
    llm = _get_llm_for_agent("red_team")

    messages = [
        ChatMessage(
            role="system",
            content=(
                "你是一名严格的学术论文审稿专家（红队角色）。"
                "你的任务是找出论文中的以下问题：\n"
                "1. 逻辑漏洞或论证不充分\n"
                "2. 学术不严谨之处\n"
                "3. 缺少必要的数据支撑\n"
                "4. 写作质量问题（重复、冗余、不清晰）\n"
                "5. 结构性问题\n\n"
                "请逐条列出问题和建议。最后给出总体评分（1-10分）和是否通过的结论。\n"
                "如果评分 >= 7，视为通过（PASS）；否则为不通过（FAIL）。\n"
                "请用中文回答。"
            ),
        ),
        ChatMessage(
            role="user",
            content=(
                f"论文主题：{topic}\n\n"
                f"以下是待审查的论文初稿：\n\n{integrated[:4000]}\n\n"
                "请开始审查："
            ),
        ),
    ]

    try:
        response = await llm.complete(messages, temperature=0.3, max_tokens=2000)
        review_content = response.content

        # Try to determine pass/fail from response
        review_passed = "PASS" in review_content.upper() or "通过" in review_content
        # If the review mentions a score >= 7, also consider it passed
        import re
        score_match = re.search(r'(\d+)\s*/?\s*10', review_content)
        if score_match:
            score = int(score_match.group(1))
            review_passed = score >= 7

        findings = [{"review": review_content, "passed": review_passed}]

        status_msg = "审查通过" if review_passed else "审查未通过，需要修订"
        await _broadcast_event(
            session_id, "RedTeam_Agent", "DELIVER_CONTENT",
            f"{status_msg}\n{review_content[:200]}...",
            agent_id="reviewer", agent_status="DONE",
        )
    except Exception as e:
        logger.error("Red team review failed: %s", e)
        findings = []
        review_passed = True  # Default pass on error to avoid infinite loop
        await _broadcast_event(
            session_id, "RedTeam_Agent", "ERROR",
            f"审查出错，默认通过: {str(e)[:100]}",
            agent_id="reviewer", agent_status="DONE",
        )

    return {
        **state,
        "review_findings": findings,
        "review_passed": review_passed,
        "status": "reviewed",
    }


def should_revise(state: WritingState) -> str:
    """Conditional edge: revise or proceed to formatting."""
    if not state.get("review_passed", False):
        return "revise"
    return "format"


async def revise_draft(state: WritingState) -> WritingState:
    """Node 7a: Revise draft based on Red Team findings."""
    session_id = state.get("session_id", "")
    topic = state.get("paper_topic", "")
    integrated = state.get("integrated_draft", "")
    findings = state.get("review_findings", [])
    logger.info("Workflow: revise_draft")

    await _broadcast_event(
        session_id, "Writer_Agent", "TASK_ASSIGNED",
        "根据红队审查反馈修订论文...",
        agent_id="writer", agent_status="EXECUTE",
    )

    from app.core.l1.llm_provider import ChatMessage
    llm = _get_llm_for_agent("writer")

    review_text = findings[0].get("review", "") if findings else "无具体反馈"

    messages = [
        ChatMessage(
            role="system",
            content=(
                "你是学术论文修订专家。根据审稿人的反馈意见修订论文。"
                "要求：\n"
                "1. 逐条解决审稿人提出的问题\n"
                "2. 保持论文的核心论点不变\n"
                "3. 改善论证的严谨性\n"
                "4. 输出修订后的完整论文\n"
                "请用中文输出。"
            ),
        ),
        ChatMessage(
            role="user",
            content=(
                f"论文主题：{topic}\n\n"
                f"审稿人反馈：\n{review_text[:2000]}\n\n"
                f"原始论文：\n{integrated[:4000]}\n\n"
                "请根据反馈修订论文："
            ),
        ),
    ]

    try:
        response = await llm.complete(messages, temperature=0.5, max_tokens=6000)
        revised = response.content
        await _broadcast_event(
            session_id, "Writer_Agent", "DELIVER_CONTENT",
            f"论文修订完成 ({len(revised)} 字)",
            agent_id="writer", agent_status="DONE",
        )
        await _broadcast_draft(session_id, revised)
    except Exception as e:
        logger.error("Revision failed: %s", e)
        revised = integrated
        await _broadcast_event(
            session_id, "Writer_Agent", "ERROR",
            f"修订失败: {str(e)[:100]}",
            agent_id="writer", agent_status="DONE",
        )

    # Update draft_sections with revised content for next iteration
    return {
        **state,
        "integrated_draft": revised,
        "draft_sections": {"revised": revised},
        "status": "revising",
    }


async def format_document(state: WritingState) -> WritingState:
    """Node 7b: Apply formatting and produce the final document."""
    session_id = state.get("session_id", "")
    topic = state.get("paper_topic", "")
    integrated = state.get("integrated_draft", "")
    logger.info("Workflow: format_document")

    await _broadcast_event(
        session_id, "System", "TASK_ASSIGNED",
        "开始应用学术论文格式化...",
    )

    from app.core.l1.llm_provider import ChatMessage
    llm = _get_llm_for_agent("format")

    messages = [
        ChatMessage(
            role="system",
            content=(
                "你是学术论文格式化专家。对论文进行最终格式化：\n"
                "1. 添加摘要（Abstract）\n"
                "2. 添加关键词\n"
                "3. 规范章节编号\n"
                "4. 添加参考文献列表\n"
                "5. 确保格式统一\n"
                "输出格式化后的完整论文。请用中文输出。"
            ),
        ),
        ChatMessage(
            role="user",
            content=(
                f"论文主题：{topic}\n\n"
                f"以下是待格式化的论文：\n\n{integrated[:5000]}\n\n"
                "请输出格式化后的完整论文："
            ),
        ),
    ]

    try:
        response = await llm.complete(messages, temperature=0.3, max_tokens=6000)
        final = response.content
        await _broadcast_event(
            session_id, "System", "DELIVER_CONTENT",
            f"格式化完成，论文已就绪 ({len(final)} 字)",
        )
    except Exception as e:
        logger.error("Formatting failed: %s", e)
        final = integrated
        await _broadcast_event(
            session_id, "System", "ERROR",
            f"格式化失败: {str(e)[:100]}",
        )

    await _broadcast_draft(session_id, final)

    from app.api.websocket import manager
    await manager.broadcast(session_id, {
        "type": "workflow_complete",
        "status": "completed",
    })

    return {
        **state,
        "final_document": final,
        "status": "completed",
    }


# ---------------------------------------------------------------------------
# Build the graph
# ---------------------------------------------------------------------------

def build_workflow() -> StateGraph:
    """Construct the LangGraph StateGraph for the writing workflow."""
    graph = StateGraph(WritingState)

    graph.add_node("decompose", decompose_task)
    graph.add_node("write", write_sections)
    graph.add_node("evidence", gather_evidence)
    graph.add_node("diagrams", generate_diagrams)
    graph.add_node("integrate", integrate_draft)
    graph.add_node("review", red_team_review)
    graph.add_node("revise", revise_draft)
    graph.add_node("format", format_document)

    graph.set_entry_point("decompose")
    graph.add_edge("decompose", "write")
    graph.add_edge("write", "evidence")
    graph.add_edge("evidence", "diagrams")
    graph.add_edge("diagrams", "integrate")
    graph.add_edge("integrate", "review")

    graph.add_conditional_edges(
        "review",
        should_revise,
        {"revise": "revise", "format": "format"},
    )
    graph.add_edge("revise", "write")
    graph.add_edge("format", END)

    return graph


def compile_workflow() -> Any:
    """Compile the workflow for execution."""
    graph = build_workflow()
    return graph.compile()
