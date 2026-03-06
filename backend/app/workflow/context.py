"""
Context Engineering Utilities for the PD-MAWS Writing Workflow.

Provides:
  1. Global paper context injection (all nodes share a unified context block)
  2. Smart truncation (head-tail preserving, not hard cut)
  3. Evidence formatting for writer prompts
  4. JSON parsing from LLM responses (handles code fences, etc.)
  5. Rolling summary generation
"""
from __future__ import annotations

import json
import re
from typing import Any


def build_paper_context_block(state: dict[str, Any]) -> str:
    """Build the global paper context block for prompt injection.

    This block is prepended to every agent's prompt so all agents
    share the same understanding of the paper's core arguments,
    terminology, and progress.
    """
    ctx = state.get("paper_context", {})
    if not ctx:
        topic = state.get("paper_topic", "")
        return f"【论文主题】{topic}" if topic else ""

    parts = ["【论文全局背景 — 所有输出须与以下信息保持一致】"]
    parts.append(f"- 主题：{ctx.get('topic', '')}")
    parts.append(f"- 学科领域：{ctx.get('domain', '未指定')}")

    args = ctx.get("key_arguments", [])
    if args:
        parts.append(f"- 核心论点：{'；'.join(args)}")

    terms = ctx.get("terminology", {})
    if terms:
        term_str = "；".join(f"{k} = {v}" for k, v in terms.items())
        parts.append(f"- 统一术语表：{term_str}")

    summary = ctx.get("completed_summary", "")
    if summary:
        parts.append(f"- 已完成章节概要：{summary}")

    return "\n".join(parts)


def smart_truncate(
    text: str,
    max_chars: int,
    strategy: str = "head_tail",
) -> str:
    """Truncate text while preserving context at both ends.

    Strategies:
      head_tail: Keep head 60% + tail 30%, note the gap (default).
      head:      Keep beginning only, with clear marker.
    """
    if not text or len(text) <= max_chars:
        return text

    if strategy == "head_tail":
        head_size = int(max_chars * 0.6)
        tail_size = int(max_chars * 0.3)
        gap = len(text) - head_size - tail_size
        return (
            text[:head_size]
            + f"\n\n[...此处省略约 {gap} 字...]\n\n"
            + text[-tail_size:]
        )
    # strategy == "head"
    return text[:max_chars] + f"\n\n[...余下约 {len(text) - max_chars} 字已省略...]"


def format_evidence_for_writer(
    section_id: str,
    evidence_map: dict[str, list[dict]],
    max_items: int = 5,
) -> str:
    """Format evidence references for injection into writer prompts.

    Handles both real-paper data (from EvidenceService) and
    LLM-suggestion-only data (fallback).
    """
    items = evidence_map.get(section_id, [])
    if not items:
        return "暂无预先检索的文献建议，请根据专业知识适当引用相关理论和方法。"

    has_real = any(
        item.get("source") in ("semantic_scholar", "arxiv", "crossref", "qdrant")
        for item in items
    )

    if has_real:
        lines = ["以下是通过学术数据库检索到的真实文献：\n"]
    else:
        lines = ["以下是为本章节推荐的文献参考：\n"]

    for i, item in enumerate(items[:max_items], 1):
        # Rich format for real papers
        if item.get("evidence_block"):
            lines.append(item["evidence_block"])
            lines.append("")
        elif item.get("title") and item.get("source") != "llm_suggestion":
            parts = [f"[文献{i}] {item['title']}"]
            if item.get("authors_short"):
                parts.append(f"  作者：{item['authors_short']}")
            if item.get("year"):
                parts.append(f"  年份：{item['year']}")
            if item.get("doi"):
                parts.append(f"  DOI：{item['doi']}")
            if item.get("citation_key"):
                parts.append(f"  引用格式：{item['citation_key']}")
            lines.append("\n".join(parts))
            lines.append("")
        else:
            # Fallback: plain suggestion text
            suggestion = item.get("suggestion", "")
            lines.append(f"[文献{i}] {suggestion}\n")

    if has_real:
        lines.append(
            "上述文献来自 Semantic Scholar / arXiv / CrossRef 真实数据库。"
            "请在写作时使用 [作者, 年份] 格式引用，选择最相关的 3-5 篇即可。"
        )
    else:
        lines.append(
            "请在写作时自然引用上述文献（使用 [作者, 年份] 格式），"
            "无需全部使用，选择最相关的即可。"
        )
    return "\n".join(lines)


def parse_json_response(text: str) -> dict[str, Any]:
    """Extract and parse JSON from LLM response.

    Handles common cases:
      - Pure JSON
      - JSON wrapped in ```json ... ``` code fences
      - JSON preceded/followed by explanatory text

    Returns empty dict on failure and logs a warning so callers
    can detect parse failures in logs.
    """
    import logging
    _logger = logging.getLogger(__name__)

    if not text or not text.strip():
        _logger.warning("parse_json_response: received empty input")
        return {}

    # Try to find JSON in code fences first
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if match:
        candidate = match.group(1).strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as e:
            _logger.debug("JSON parse failed in code fence: %s", e)

    # Try direct parse
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    # Try to extract the outermost { ... } block
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    start = -1

    _logger.warning(
        "parse_json_response: failed to extract JSON from LLM output (length=%d, preview=%.100s...)",
        len(text), text[:100],
    )
    return {}


def build_rolling_summary(
    existing_summary: str,
    section_title: str,
    section_content: str,
    max_summary_chars: int = 500,
) -> str:
    """Update the rolling summary as sections are written.

    Keeps a compact summary of what's been written so far,
    so later sections can maintain coherence with earlier ones.
    """
    snippet = section_content[:200].replace("\n", " ")
    new_entry = f"[{section_title}]: {snippet}..."

    if existing_summary:
        combined = f"{existing_summary}\n{new_entry}"
    else:
        combined = new_entry

    if len(combined) > max_summary_chars:
        combined = combined[-max_summary_chars:]
        first_newline = combined.find("\n")
        if first_newline > 0:
            combined = combined[first_newline + 1 :]

    return combined
