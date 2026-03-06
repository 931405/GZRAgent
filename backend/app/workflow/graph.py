"""
LangGraph Workflow — Map-Reduce academic writing orchestration.

Optimized with Context Engineering + Prompt Engineering:
  - Global PaperContext shared across all nodes
  - Smart truncation (head-tail) instead of hard [:N] cuts
  - Evidence gathered BEFORE writing (correct dependency order)
  - CoT reasoning + structured output in all prompts
  - Self-check instructions embedded in writer prompt
  - Structured scoring rubric for Red Team review
  - Rolling summary keeps later sections coherent with earlier ones

Flow (optimized):
  decompose -> evidence -> write -> diagrams -> integrate
  -> review --(pass)--> format -> END
           --(fail)--> revise -> integrate (loop, max 2)
"""
from __future__ import annotations

import logging
import re
import time
import uuid
from typing import Any, TypedDict

from langgraph.graph import StateGraph, END

from app.workflow.context import (
    build_paper_context_block,
    build_rolling_summary,
    format_evidence_for_writer,
    parse_json_response,
    smart_truncate,
)
from app.workflow.prompts import (
    decompose_system,
    diagram_system,
    evidence_system,
    format_system,
    integrate_system,
    red_team_system,
    revise_system,
    writer_system,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Token tracking helper
# ---------------------------------------------------------------------------

async def _record_token_usage(
    agent_name: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> None:
    """Record token usage in the circuit breaker (global + per-agent)."""
    try:
        from app.main import get_circuit_breaker
        cb = get_circuit_breaker()
        await cb.record_global_usage(prompt_tokens, completion_tokens)
        await cb.record_agent_usage(agent_name, prompt_tokens + completion_tokens)
    except Exception as e:
        logger.debug("Token recording skipped (circuit breaker unavailable): %s", e)


# ---------------------------------------------------------------------------
# LLM Helper
# ---------------------------------------------------------------------------

def _get_llm_for_agent(agent_name: str):
    """Get the configured LLM provider instance for a given agent."""
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
    return _TrackedProvider(provider, agent_name)


class _TrackedProvider:
    """Wrapper that records token usage in circuit breaker after each call."""

    def __init__(self, inner, agent_name: str) -> None:
        self._inner = inner
        self._agent_name = agent_name

    async def complete(self, messages, **kwargs):
        response = await self._inner.complete(messages, **kwargs)
        await _record_token_usage(
            self._agent_name,
            response.prompt_tokens,
            response.completion_tokens,
        )
        return response

    def __getattr__(self, name):
        return getattr(self._inner, name)


# ---------------------------------------------------------------------------
# WebSocket event helpers
# ---------------------------------------------------------------------------

async def _broadcast_event(
    session_id: str,
    source: str,
    intent: str,
    message: str,
    agent_id: str | None = None,
    agent_status: str | None = None,
    details: dict | None = None,
) -> None:
    """Send a telemetry event and optional agent state change via WebSocket."""
    from app.api.websocket import manager

    event_data = {
        "id": str(uuid.uuid4()),
        "timestamp": int(time.time() * 1000),
        "source": source,
        "intent": intent,
        "message": message,
    }
    if details:
        event_data["details"] = details

    await manager.broadcast(session_id, {
        "type": "telemetry",
        "data": event_data,
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

    # Global paper context — shared by all nodes
    paper_context: dict[str, Any]

    sub_tasks: list[dict[str, Any]]
    current_task_idx: int

    draft_sections: dict[str, str]
    evidence_map: dict[str, list[dict]]

    integrated_draft: str
    diagrams: list[dict[str, Any]]

    review_findings: list[dict[str, Any]]
    review_passed: bool
    revision_count: int

    final_document: str
    status: str
    error: str


# ---------------------------------------------------------------------------
# Node 1: Decompose (PI Agent)
# ---------------------------------------------------------------------------

async def decompose_task(state: WritingState) -> WritingState:
    """PI Agent decomposes outline into structured sub-tasks + PaperContext."""
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
        ChatMessage(role="system", content=decompose_system()),
        ChatMessage(
            role="user",
            content=(
                f"论文主题：{topic}\n\n"
                f"大纲：\n{outline_text}\n\n"
                "请分析并输出结构化的任务分解 JSON："
            ),
        ),
    ]

    t0 = time.time()
    response = await llm.complete(messages, temperature=0.5, max_tokens=3000)
    elapsed = int((time.time() - t0) * 1000)

    parsed = parse_json_response(response.content)

    # Build paper_context from LLM structured output
    paper_context: dict[str, Any] = {
        "topic": topic,
        "domain": parsed.get("domain", ""),
        "key_arguments": parsed.get("key_arguments", []),
        "terminology": parsed.get("terminology", {}),
        "completed_summary": "",
    }

    # Build sub_tasks from parsed JSON, with fallback
    raw_tasks = parsed.get("tasks", [])
    sub_tasks = []

    if raw_tasks:
        for task_data in raw_tasks:
            sub_tasks.append({
                "task_id": task_data.get("task_id", f"sec_{len(sub_tasks)}"),
                "section_title": task_data.get("section_title", f"Section {len(sub_tasks)}"),
                "writing_instructions": _build_instructions_from_task(task_data),
                "evidence_needed": task_data.get("evidence_needed", ""),
                "key_points": task_data.get("key_points", []),
                "estimated_words": task_data.get("estimated_words", 800),
                "assigned_writer": "writer",
            })

    # Fallback: if JSON parsing failed, split by --- like before
    if not sub_tasks:
        logger.warning("JSON parsing failed for decompose, falling back to text split")
        sections = response.content.split("---")
        for i, section_text in enumerate(sections):
            section_text = section_text.strip()
            if not section_text:
                continue
            title = (
                outline[i].get("title", f"Section {i}")
                if i < len(outline)
                else f"Section {i}"
            )
            sub_tasks.append({
                "task_id": f"sec_{i}",
                "section_title": title,
                "writing_instructions": section_text,
                "evidence_needed": "",
                "key_points": [],
                "estimated_words": 800,
                "assigned_writer": "writer",
            })

    # CRITICAL: Ensure EVERY outline section has a corresponding sub_task.
    # If LLM produced fewer tasks than outline sections, fill from outline.
    # If LLM produced tasks with wrong IDs, rebuild the mapping.
    existing_titles = {t["section_title"].lower().strip() for t in sub_tasks}

    for i, section in enumerate(outline):
        title = section.get("title", f"Section {i+1}")
        if title.lower().strip() not in existing_titles:
            # Find if there's a sub_task that roughly matches
            matched = False
            for st in sub_tasks:
                if title.lower() in st["section_title"].lower() or st["section_title"].lower() in title.lower():
                    matched = True
                    break
            if not matched:
                sub_tasks.append({
                    "task_id": f"sec_{i}",
                    "section_title": title,
                    "writing_instructions": f"请撰写关于「{title}」的学术内容。",
                    "evidence_needed": "",
                    "key_points": [],
                    "estimated_words": 800,
                    "assigned_writer": "writer",
                })

    # If we still have no sub_tasks at all (total LLM failure), generate from outline
    if not sub_tasks and outline:
        logger.warning("Complete decompose failure, generating tasks directly from outline")
        for i, section in enumerate(outline):
            title = section.get("title", f"Section {i+1}")
            sub_tasks.append({
                "task_id": f"sec_{i}",
                "section_title": title,
                "writing_instructions": f"请撰写关于「{title}」的学术内容。主题：{topic}",
                "evidence_needed": "",
                "key_points": [],
                "estimated_words": 800,
                "assigned_writer": "writer",
            })

    task_list = ", ".join(t["section_title"] for t in sub_tasks)
    ctx_info = f"领域: {paper_context['domain']}" if paper_context["domain"] else ""
    await _broadcast_event(
        session_id, "PI_Agent", "DELIVER_CONTENT",
        f"大纲已分解为 {len(sub_tasks)} 个子任务: {task_list}。{ctx_info}",
        agent_id="pi", agent_status="DONE",
        details={
            "prompt": messages[-1].content,
            "result": response.content,
            "tokens": response.total_tokens,
            "duration_ms": elapsed,
            "model": response.model,
        },
    )

    return {
        **state,
        "paper_context": paper_context,
        "sub_tasks": sub_tasks,
        "current_task_idx": 0,
        "status": "decomposed",
    }


def _build_instructions_from_task(task_data: dict) -> str:
    """Convert structured task JSON into readable writing instructions."""
    parts = []
    if task_data.get("objective"):
        parts.append(f"写作目标：{task_data['objective']}")
    if task_data.get("key_points"):
        kp = "；".join(task_data["key_points"])
        parts.append(f"关键要点：{kp}")
    if task_data.get("evidence_needed"):
        parts.append(f"所需证据：{task_data['evidence_needed']}")
    if task_data.get("estimated_words"):
        parts.append(f"预估字数：{task_data['estimated_words']} 字")
    return "\n".join(parts) if parts else "请撰写该章节的学术内容。"


# ---------------------------------------------------------------------------
# Node 2: Gather Evidence (Researcher Agent) — NOW BEFORE WRITING
# ---------------------------------------------------------------------------

async def gather_evidence(state: WritingState) -> WritingState:
    """Researcher Agent gathers REAL evidence via tool search + LLM analysis.

    Two-stage pipeline:
      Stage 1 (Tools): Search Semantic Scholar / arXiv / CrossRef / Qdrant
                        for real papers with DOI, authors, citation counts.
      Stage 2 (LLM):   Analyze found papers and suggest how to cite them
                        in each section.
    Fallback: If all tool searches fail, use LLM-only suggestions.
    """
    session_id = state.get("session_id", "")
    topic = state.get("paper_topic", "")
    logger.info("Workflow: gather_evidence")

    await _broadcast_event(
        session_id, "Researcher_Agent", "TASK_ASSIGNED",
        "文献研究员正在检索真实学术文献（Semantic Scholar / arXiv / CrossRef）...",
        agent_id="researcher", agent_status="EXECUTE",
    )

    from app.core.l1.evidence_service import get_evidence_service
    from app.core.l1.llm_provider import ChatMessage

    llm = _get_llm_for_agent("researcher")
    svc = get_evidence_service()
    paper_ctx_block = build_paper_context_block(state)

    evidence_map: dict[str, list[dict]] = {}

    for task in state.get("sub_tasks", []):
        section_id = task["task_id"]
        title = task["section_title"]
        key_points = task.get("key_points", [])
        evidence_needed = task.get("evidence_needed", "")

        # Build search query from task metadata
        query = f"{topic} {title}"
        if key_points:
            query += " " + " ".join(key_points[:2])
        if evidence_needed:
            query += " " + evidence_needed[:60]

        await _broadcast_event(
            session_id, "Researcher_Agent", "TASK_ASSIGNED",
            f"正在为「{title}」检索文献...",
        )

        # ---- Stage 1: Tool-based real search ----
        t0 = time.time()
        try:
            papers = await svc.search(query=query, limit=8)
        except Exception as e:
            logger.error("Evidence service failed for %s: %s", section_id, e)
            papers = []

        search_elapsed = int((time.time() - t0) * 1000)
        real_count = len(papers)

        if papers:
            # ---- Stage 2: LLM analyzes found papers for this section ----
            evidence_blocks = "\n\n".join(
                p["evidence_block"] for p in papers
            )

            messages = [
                ChatMessage(
                    role="system",
                    content=evidence_system(paper_ctx_block),
                ),
                ChatMessage(
                    role="user",
                    content=(
                        f"论文主题：{topic}\n"
                        f"章节标题：{title}\n"
                        f"章节要点：{'；'.join(key_points) if key_points else '见写作目标'}\n\n"
                        f"以下是通过学术数据库检索到的真实文献：\n\n"
                        f"{evidence_blocks}\n\n"
                        f"请从中选出与本章节最相关的 3-5 篇，"
                        f"说明每篇的引用理由和建议插入位置。"
                        f"用 --- 分隔各条建议。"
                    ),
                ),
            ]

            try:
                t1 = time.time()
                response = await llm.complete(messages, temperature=0.3, max_tokens=1500)
                llm_elapsed = int((time.time() - t1) * 1000)

                # Merge real paper metadata + LLM analysis
                llm_suggestions = [
                    s.strip() for s in response.content.split("---") if s.strip()
                ]
                section_evidence = []
                for i, paper in enumerate(papers):
                    entry = {**paper, "section": section_id}
                    if i < len(llm_suggestions):
                        entry["llm_analysis"] = llm_suggestions[i]
                    entry["suggestion"] = _format_paper_suggestion(paper, llm_suggestions[i] if i < len(llm_suggestions) else "")
                    section_evidence.append(entry)

                evidence_map[section_id] = section_evidence

                await _broadcast_event(
                    session_id, "Researcher_Agent", "DELIVER_CONTENT",
                    f"已为「{title}」找到 {real_count} 篇真实文献（检索 {search_elapsed}ms + 分析 {llm_elapsed}ms）",
                    details={
                        "real_papers_found": real_count,
                        "sources": list({p["source"] for p in papers}),
                        "search_ms": search_elapsed,
                        "analysis_ms": llm_elapsed,
                        "tokens": response.total_tokens,
                        "model": response.model,
                    },
                )
            except Exception as e:
                logger.error("LLM analysis failed for %s: %s", section_id, e)
                # Still use raw paper data without LLM analysis
                evidence_map[section_id] = [
                    {**p, "section": section_id, "suggestion": _format_paper_suggestion(p, "")}
                    for p in papers
                ]
        else:
            # ---- Fallback: LLM-only suggestions ----
            logger.warning("No real papers found for %s, falling back to LLM", section_id)
            messages = [
                ChatMessage(
                    role="system",
                    content=evidence_system(paper_ctx_block),
                ),
                ChatMessage(
                    role="user",
                    content=(
                        f"论文主题：{topic}\n章节标题：{title}\n"
                        f"章节要点：{'；'.join(key_points) if key_points else title}\n\n"
                        f"⚠️ 学术数据库检索未返回结果，请根据专业知识建议 3-5 条参考文献。\n"
                        f"尽量建议真实存在的经典文献，用 --- 分隔。"
                    ),
                ),
            ]
            try:
                response = await llm.complete(messages, temperature=0.3, max_tokens=1500)
                refs = [
                    {"suggestion": ref.strip(), "section": section_id, "source": "llm_suggestion"}
                    for ref in response.content.split("---")
                    if ref.strip()
                ]
                evidence_map[section_id] = refs
            except Exception as e:
                logger.error("LLM fallback failed for %s: %s", section_id, e)
                evidence_map[section_id] = []

            await _broadcast_event(
                session_id, "Researcher_Agent", "DELIVER_CONTENT",
                f"「{title}」未找到真实文献，已使用 LLM 建议（共 {len(evidence_map.get(section_id, []))} 条）",
            )

    total_refs = sum(len(v) for v in evidence_map.values())
    real_refs = sum(
        1 for v in evidence_map.values()
        for p in v if p.get("source") in ("semantic_scholar", "arxiv", "crossref", "qdrant")
    )
    await _broadcast_event(
        session_id, "Researcher_Agent", "DELIVER_CONTENT",
        f"文献检索完成：共 {total_refs} 条（其中 {real_refs} 条来自真实数据库）",
        agent_id="researcher", agent_status="DONE",
    )

    return {
        **state,
        "evidence_map": evidence_map,
        "status": "evidence_gathered",
    }


def _format_paper_suggestion(paper: dict, llm_analysis: str) -> str:
    """Format a paper + LLM analysis into a single suggestion string."""
    parts = [f"《{paper.get('title', '')}》"]
    if paper.get("authors_short"):
        parts.append(f"({paper['authors_short']}, {paper.get('year', '')})")
    if paper.get("venue"):
        parts.append(f"发表于 {paper['venue']}")
    if paper.get("doi"):
        parts.append(f"DOI: {paper['doi']}")
    if paper.get("citation_count"):
        parts.append(f"被引 {paper['citation_count']} 次")
    summary = " | ".join(parts)
    if llm_analysis:
        summary += f"\n引用建议：{llm_analysis}"
    return summary


# ---------------------------------------------------------------------------
# Node 3: Write Sections (Writer Agent) — NOW WITH EVIDENCE + SELF-CHECK
# ---------------------------------------------------------------------------

async def write_sections(state: WritingState) -> WritingState:
    """Writer Agent composes each section with evidence and self-check."""
    session_id = state.get("session_id", "")
    topic = state.get("paper_topic", "")
    evidence_map = state.get("evidence_map", {})
    logger.info("Workflow: write_sections")

    await _broadcast_event(
        session_id, "Writer_Agent", "TASK_ASSIGNED",
        "学术写手开始撰写各章节草稿（已获得文献支撑）...",
        agent_id="writer", agent_status="EXECUTE",
    )

    from app.core.l1.llm_provider import ChatMessage
    llm = _get_llm_for_agent("writer")

    paper_ctx_block = build_paper_context_block(state)
    paper_context = state.get("paper_context", {})
    rolling_summary = paper_context.get("completed_summary", "")

    draft_sections: dict[str, str] = {}
    for task in state.get("sub_tasks", []):
        section_id = task["task_id"]
        title = task["section_title"]
        instructions = task.get("writing_instructions", f"撰写关于 {title} 的学术内容。")
        estimated_words = task.get("estimated_words", 800)
        word_range = f"{int(estimated_words * 0.8)}-{int(estimated_words * 1.2)}"

        # Update paper context with rolling summary for coherence
        if rolling_summary:
            updated_ctx = paper_ctx_block + f"\n- 已完成章节概要：{rolling_summary}"
        else:
            updated_ctx = paper_ctx_block

        evidence_block = format_evidence_for_writer(section_id, evidence_map)

        await _broadcast_event(
            session_id, "Writer_Agent", "TASK_ASSIGNED",
            f"正在撰写: {title}（参考 {len(evidence_map.get(section_id, []))} 条文献）...",
        )

        messages = [
            ChatMessage(
                role="system",
                content=writer_system(updated_ctx, word_range),
            ),
            ChatMessage(
                role="user",
                content=(
                    f"论文主题：{topic}\n"
                    f"章节标题：{title}\n\n"
                    f"写作指令：\n{instructions}\n\n"
                    f"可用文献参考：\n{evidence_block}\n\n"
                    f"请撰写该章节的完整内容（{word_range}字）："
                ),
            ),
        ]

        try:
            t0 = time.time()
            response = await llm.complete(messages, temperature=0.7, max_tokens=3000)
            elapsed = int((time.time() - t0) * 1000)
            draft_sections[section_id] = response.content

            rolling_summary = build_rolling_summary(
                rolling_summary, title, response.content,
            )

            await _broadcast_event(
                session_id, "Writer_Agent", "DELIVER_CONTENT",
                f"已完成章节草稿: {title} ({len(response.content)} 字)",
                details={
                    "prompt": instructions[:300] + "..." if len(instructions) > 300 else instructions,
                    "result": response.content,
                    "tokens": response.total_tokens,
                    "duration_ms": elapsed,
                    "model": response.model,
                },
            )
        except Exception as e:
            logger.error("Writer failed for %s: %s", section_id, e)
            draft_sections[section_id] = f"[写作失败: {e}]"
            await _broadcast_event(
                session_id, "Writer_Agent", "ERROR",
                f"章节 {title} 写作失败: {str(e)[:100]}",
            )

    # Persist rolling summary back into paper_context
    updated_paper_ctx = {**state.get("paper_context", {}), "completed_summary": rolling_summary}

    await _broadcast_event(
        session_id, "Writer_Agent", "DELIVER_CONTENT",
        f"全部 {len(draft_sections)} 个章节草稿已完成",
        agent_id="writer", agent_status="DONE",
    )

    return {
        **state,
        "draft_sections": draft_sections,
        "paper_context": updated_paper_ctx,
        "status": "drafting",
    }


# ---------------------------------------------------------------------------
# Node 4: Generate Diagrams (Diagram Agent)
# ---------------------------------------------------------------------------

async def generate_diagrams(state: WritingState) -> WritingState:
    """Diagram Agent generates chart suggestions based on the draft."""
    session_id = state.get("session_id", "")
    topic = state.get("paper_topic", "")
    logger.info("Workflow: generate_diagrams")

    await _broadcast_event(
        session_id, "Diagram_Agent", "TASK_ASSIGNED",
        "正在分析论文内容并生成图表建议...",
        agent_id="diagram", agent_status="EXECUTE",
    )

    from app.core.l1.llm_provider import ChatMessage

    llm = _get_llm_for_agent("pi")
    paper_ctx_block = build_paper_context_block(state)

    all_content = "\n".join(
        f"## {sid}\n{smart_truncate(content, 400, 'head')}"
        for sid, content in state.get("draft_sections", {}).items()
    )

    messages = [
        ChatMessage(
            role="system",
            content=diagram_system(paper_ctx_block),
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
            session_id, "Diagram_Agent", "DELIVER_CONTENT",
            "图表建议已生成",
            agent_id="diagram", agent_status="DONE",
        )
    except Exception as e:
        logger.error("Diagram generation failed: %s", e)
        diagrams = []
        await _broadcast_event(
            session_id, "Diagram_Agent", "ERROR",
            f"图表生成失败: {str(e)[:100]}",
            agent_id="diagram", agent_status="DONE",
        )

    return {
        **state,
        "diagrams": diagrams,
        "status": "diagrams_generated",
    }


# ---------------------------------------------------------------------------
# Node 5: Integrate Draft (PI Agent)
# ---------------------------------------------------------------------------

async def integrate_draft(state: WritingState) -> WritingState:
    """PI Agent integrates all sections into a coherent draft.

    Handles two scenarios:
      - First pass: combine draft_sections from writer output
      - Revision pass: polish the already-integrated revised draft
    """
    session_id = state.get("session_id", "")
    topic = state.get("paper_topic", "")
    revision_count = state.get("revision_count", 0)
    logger.info("Workflow: integrate_draft (revision_count=%d)", revision_count)

    is_revision_round = revision_count > 0 and state.get("integrated_draft", "").strip()

    await _broadcast_event(
        session_id, "PI_Agent", "TASK_ASSIGNED",
        f"PI Agent 正在{'润色修订后的' if is_revision_round else '整合所有章节为连贯的'}论文初稿...",
        agent_id="pi", agent_status="EXECUTE",
    )

    from app.core.l1.llm_provider import ChatMessage
    llm = _get_llm_for_agent("pi")

    paper_ctx_block = build_paper_context_block(state)

    if is_revision_round:
        # After revision: integrated_draft already has the full revised paper.
        # Just ask PI to polish coherence, don't rebuild from draft_sections.
        raw_combined = state["integrated_draft"]
        user_instruction = (
            f"论文主题：{topic}\n\n"
            f"以下是经过第 {revision_count} 轮修订后的论文全文，"
            f"请检查并确保各章节逻辑连贯、术语统一、过渡自然：\n"
            f"{smart_truncate(raw_combined, 12000)}"
        )
    else:
        # First pass: combine individual sections from writers
        sections = state.get("draft_sections", {})
        sub_tasks = state.get("sub_tasks", [])

        raw_combined = ""
        for task in sub_tasks:
            sid = task["task_id"]
            title = task["section_title"]
            content = sections.get(sid, "[无内容]")
            raw_combined += f"\n## {title}\n\n{content}\n"

        user_instruction = (
            f"论文主题：{topic}\n\n"
            f"以下是各章节的草稿内容，请整合为一篇连贯的论文：\n"
            f"{smart_truncate(raw_combined, 12000)}"
        )

    messages = [
        ChatMessage(
            role="system",
            content=integrate_system(paper_ctx_block),
        ),
        ChatMessage(
            role="user",
            content=user_instruction,
        ),
    ]

    try:
        t0 = time.time()
        response = await llm.complete(messages, temperature=0.4, max_tokens=8000)
        elapsed = int((time.time() - t0) * 1000)
        integrated = response.content
        await _broadcast_event(
            session_id, "PI_Agent", "DELIVER_CONTENT",
            f"论文初稿整合完成 ({len(integrated)} 字)",
            agent_id="pi", agent_status="DONE",
            details={
                "result": integrated[:500] + "..." if len(integrated) > 500 else integrated,
                "tokens": response.total_tokens,
                "duration_ms": elapsed,
                "model": response.model,
            },
        )
    except Exception as e:
        logger.error("Integration failed (attempt 1): %s", e)
        # Retry once with smaller context before falling back
        try:
            logger.info("Integration retry with reduced context...")
            retry_messages = [
                ChatMessage(
                    role="system",
                    content="你是论文 PI，请将以下论文章节整合为连贯的完整论文。保持核心内容不变，统一术语，添加过渡段落。用中文输出。",
                ),
                ChatMessage(
                    role="user",
                    content=f"论文主题：{topic}\n\n{smart_truncate(raw_combined, 6000)}",
                ),
            ]
            response = await llm.complete(retry_messages, temperature=0.4, max_tokens=6000)
            integrated = response.content
            await _broadcast_event(
                session_id, "PI_Agent", "DELIVER_CONTENT",
                f"论文初稿整合完成（重试成功，{len(integrated)} 字）",
                agent_id="pi", agent_status="DONE",
            )
        except Exception as retry_e:
            logger.error("Integration retry also failed: %s", retry_e)
            integrated = raw_combined
            await _broadcast_event(
                session_id, "PI_Agent", "ERROR",
                f"整合失败（含重试），使用原始拼接: {str(retry_e)[:100]}",
                agent_id="pi", agent_status="DONE",
            )

    await _broadcast_draft(session_id, integrated)

    return {
        **state,
        "integrated_draft": integrated,
        "status": "integrated",
    }


# ---------------------------------------------------------------------------
# Node 6: Red Team Review (structured scoring)
# ---------------------------------------------------------------------------

async def red_team_review(state: WritingState) -> WritingState:
    """Red Team Agent reviews the draft with structured scoring rubric."""
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

    paper_ctx_block = build_paper_context_block(state)

    # Use smart_truncate with head_tail to preserve intro + conclusion
    truncated_draft = smart_truncate(integrated, 8000, "head_tail")

    messages = [
        ChatMessage(
            role="system",
            content=red_team_system(paper_ctx_block),
        ),
        ChatMessage(
            role="user",
            content=(
                f"论文主题：{topic}\n\n"
                f"以下是待审查的论文初稿：\n\n{truncated_draft}\n\n"
                "请按评审维度逐项审查，输出结构化 JSON 评审结果："
            ),
        ),
    ]

    try:
        t0 = time.time()
        response = await llm.complete(messages, temperature=0.3, max_tokens=3000)
        elapsed = int((time.time() - t0) * 1000)
        review_content = response.content

        # Try structured JSON parsing first
        parsed_review = parse_json_response(review_content)

        if parsed_review and "weighted_score" in parsed_review:
            weighted_score = float(parsed_review["weighted_score"])
            review_passed = parsed_review.get("passed", weighted_score >= 7.0)
            findings = [{
                "review": review_content,
                "parsed": parsed_review,
                "passed": review_passed,
                "weighted_score": weighted_score,
            }]
        else:
            # Fallback: extract score from text
            review_passed = "PASS" in review_content.upper() or "通过" in review_content
            score_match = re.search(r"(\d+(?:\.\d+)?)\s*/?\s*10", review_content)
            if score_match:
                score = float(score_match.group(1))
                review_passed = score >= 7.0
            findings = [{"review": review_content, "passed": review_passed}]

        status_msg = "审查通过" if review_passed else "审查未通过，需要修订"
        await _broadcast_event(
            session_id, "RedTeam_Agent", "DELIVER_CONTENT",
            status_msg,
            agent_id="reviewer", agent_status="DONE",
            details={
                "result": review_content,
                "tokens": response.total_tokens,
                "duration_ms": elapsed,
                "model": response.model,
            },
        )
    except Exception as e:
        logger.error("Red team review failed: %s", e)
        findings = []
        review_passed = True
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


# ---------------------------------------------------------------------------
# Conditional edge
# ---------------------------------------------------------------------------

MAX_REVISIONS = 2


def should_revise(state: WritingState) -> str:
    """Decide whether to revise or proceed to formatting."""
    revision_count = state.get("revision_count", 0)
    if not state.get("review_passed", False) and revision_count < MAX_REVISIONS:
        return "revise"
    return "format"


# ---------------------------------------------------------------------------
# Node 7a: Revise Draft (structured feedback-driven)
# ---------------------------------------------------------------------------

async def revise_draft(state: WritingState) -> WritingState:
    """Revise draft based on structured Red Team findings."""
    session_id = state.get("session_id", "")
    topic = state.get("paper_topic", "")
    integrated = state.get("integrated_draft", "")
    findings = state.get("review_findings", [])
    revision_count = state.get("revision_count", 0)
    logger.info("Workflow: revise_draft (round %d)", revision_count + 1)

    await _broadcast_event(
        session_id, "Writer_Agent", "TASK_ASSIGNED",
        f"根据红队审查反馈修订论文（第 {revision_count + 1} 轮）...",
        agent_id="writer", agent_status="EXECUTE",
    )

    from app.core.l1.llm_provider import ChatMessage
    llm = _get_llm_for_agent("writer")

    paper_ctx_block = build_paper_context_block(state)

    # Extract structured feedback for the revision prompt
    review_data = findings[0] if findings else {}
    parsed = review_data.get("parsed", {})

    if parsed and "issues" in parsed:
        # Format structured issues for targeted revision
        issue_lines = []
        for issue in parsed["issues"]:
            severity = issue.get("severity", "major")
            location = issue.get("location", "未知位置")
            desc = issue.get("issue", "")
            suggestion = issue.get("suggestion", "")
            issue_lines.append(
                f"[{severity.upper()}] {location}: {desc}\n  建议：{suggestion}"
            )
        review_text = "\n\n".join(issue_lines)

        priorities = parsed.get("revision_priorities", [])
        if priorities:
            review_text += "\n\n【修订优先级】\n" + "\n".join(
                f"{i+1}. {p}" for i, p in enumerate(priorities)
            )
    else:
        review_text = review_data.get("review", "无具体反馈")

    messages = [
        ChatMessage(
            role="system",
            content=revise_system(paper_ctx_block),
        ),
        ChatMessage(
            role="user",
            content=(
                f"论文主题：{topic}\n\n"
                f"审稿人反馈（第 {revision_count + 1} 轮）：\n{smart_truncate(review_text, 3000)}\n\n"
                f"原始论文：\n{smart_truncate(integrated, 8000)}\n\n"
                "请根据反馈逐条修订论文："
            ),
        ),
    ]

    try:
        t0 = time.time()
        response = await llm.complete(messages, temperature=0.5, max_tokens=8000)
        elapsed = int((time.time() - t0) * 1000)

        # Try to extract revised paper from structured output
        revised = _extract_revised_paper(response.content)

        await _broadcast_event(
            session_id, "Writer_Agent", "DELIVER_CONTENT",
            f"论文修订完成 ({len(revised)} 字)",
            agent_id="writer", agent_status="DONE",
            details={
                "result": revised[:500] + "..." if len(revised) > 500 else revised,
                "tokens": response.total_tokens,
                "duration_ms": elapsed,
                "model": response.model,
            },
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

    # Keep original draft_sections intact — integrate_draft will use
    # integrated_draft directly on revision rounds instead of rebuilding.
    return {
        **state,
        "integrated_draft": revised,
        "revision_count": revision_count + 1,
        "status": "revising",
    }


def _extract_revised_paper(content: str) -> str:
    """Extract the revised paper from structured output tags."""
    match = re.search(
        r"<revised_paper>\s*(.*?)\s*</revised_paper>", content, re.DOTALL
    )
    if match:
        return match.group(1).strip()
    return content


# ---------------------------------------------------------------------------
# Node 7b: Format Document (Format Agent)
# ---------------------------------------------------------------------------

async def format_document(state: WritingState) -> WritingState:
    """Apply final academic formatting to the document."""
    session_id = state.get("session_id", "")
    topic = state.get("paper_topic", "")
    integrated = state.get("integrated_draft", "")
    logger.info("Workflow: format_document")

    await _broadcast_event(
        session_id, "Format_Agent", "TASK_ASSIGNED",
        "开始应用学术论文格式化...",
        agent_id="format", agent_status="EXECUTE",
    )

    from app.core.l1.llm_provider import ChatMessage
    llm = _get_llm_for_agent("format")

    paper_ctx_block = build_paper_context_block(state)

    messages = [
        ChatMessage(
            role="system",
            content=format_system(paper_ctx_block),
        ),
        ChatMessage(
            role="user",
            content=(
                f"论文主题：{topic}\n\n"
                f"以下是待格式化的论文：\n\n"
                f"{smart_truncate(integrated, 10000)}\n\n"
                "请输出格式化后的完整论文："
            ),
        ),
    ]

    try:
        t0 = time.time()
        response = await llm.complete(messages, temperature=0.3, max_tokens=8000)
        elapsed = int((time.time() - t0) * 1000)
        final = response.content
        await _broadcast_event(
            session_id, "Format_Agent", "DELIVER_CONTENT",
            f"格式化完成，论文已就绪 ({len(final)} 字)",
            agent_id="format", agent_status="DONE",
            details={
                "result": final[:500] + "..." if len(final) > 500 else final,
                "tokens": response.total_tokens,
                "duration_ms": elapsed,
                "model": response.model,
            },
        )
    except Exception as e:
        logger.error("Formatting failed: %s", e)
        final = integrated
        await _broadcast_event(
            session_id, "Format_Agent", "ERROR",
            f"格式化失败: {str(e)[:100]}",
            agent_id="format", agent_status="DONE",
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
    """Construct the LangGraph StateGraph for the writing workflow.

    Optimized flow:
      decompose -> evidence -> write -> diagrams -> integrate
      -> review --(pass)--> format -> END
               --(fail)--> revise -> integrate (loop)
    """
    graph = StateGraph(WritingState)

    graph.add_node("decompose", decompose_task)
    graph.add_node("evidence", gather_evidence)
    graph.add_node("write", write_sections)
    graph.add_node("diagrams", generate_diagrams)
    graph.add_node("integrate", integrate_draft)
    graph.add_node("review", red_team_review)
    graph.add_node("revise", revise_draft)
    graph.add_node("format", format_document)

    graph.set_entry_point("decompose")
    graph.add_edge("decompose", "evidence")     # Evidence BEFORE writing
    graph.add_edge("evidence", "write")          # Writers get evidence
    graph.add_edge("write", "diagrams")
    graph.add_edge("diagrams", "integrate")
    graph.add_edge("integrate", "review")

    graph.add_conditional_edges(
        "review",
        should_revise,
        {"revise": "revise", "format": "format"},
    )
    graph.add_edge("revise", "integrate")
    graph.add_edge("format", END)

    return graph


def compile_workflow() -> Any:
    """Compile the workflow for execution."""
    graph = build_workflow()
    return graph.compile()
