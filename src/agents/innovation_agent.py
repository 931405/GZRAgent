"""
innovation_agent.py — 创新点提炼 Agent

职责：
- 综合分析文献背景、研究主题和已有草稿
- 提炼 3-5 个核心创新点，输出结构化内容
- 同时为"特色与创新"章节提供直接可用的写作素材
"""
from typing import Dict, Any

from langchain_core.prompts import ChatPromptTemplate
from src.state import GraphState
from src.llm import get_llm

_SYSTEM_PROMPT = """\
你是国家自然科学基金申请书的创新点提炼专家。

你的任务：根据研究主题、文献背景以及现有草稿，提炼并结构化呈现该项目的核心创新点。

创新点要求：
1. 每个创新点需突出"与现有研究的差异性"和"本项目的独特贡献"
2. 创新点分类：理论创新 / 方法创新 / 应用创新
3. 每个创新点包含：创新点名称（15字以内）、详细阐述（100-200字）、支撑依据（引用文献或已有积累）
4. 语言精练，符合国自然申请书的学术规范
5. 不要编造未在草稿或文献中体现的内容

输出格式（Markdown）：
## 核心创新点

### 创新点1：[名称]（[类型]）
[详细阐述]
**支撑依据**：[...]

### 创新点2：[名称]（[类型]）
...（共3-5个）

## 特色与创新（章节草稿）
[根据上述创新点，直接输出可放入申请书"特色与创新"章节的完整正文，1000字以上]
"""

_USER_PROMPT = """\
项目类型：{project_type}
研究主题：{research_topic}
文献资料摘要（前3000字）：
{references_summary}

已完成章节草稿摘要：
{draft_summary}

请提炼创新点并生成"特色与创新"章节草稿：
"""


def run_innovation_agent(state: GraphState) -> Dict[str, Any]:
    """创新点提炼 Agent"""
    config = state.get("model_config") or {}
    provider = config.get("innovation", config.get("writer", "deepseek"))
    llm = get_llm(provider_override=provider, temperature=0.3)

    topic = state.get("research_topic", "")
    project_type = state.get("project_type", "面上项目")

    # 整理文献摘要
    refs = state.get("reference_documents") or []
    ref_texts = []
    for i, r in enumerate(refs[:8]):
        title = r.get("title") or r.get("source", f"文献{i+1}")
        abstract = r.get("abstract") or r.get("content") or r.get("summary", "")
        if abstract:
            ref_texts.append(f"[{i+1}] {title}: {abstract[:300]}")
    references_summary = "\n".join(ref_texts) if ref_texts else "（暂无文献资料）"

    # 已完成章节摘要
    drafts = state.get("draft_sections") or {}
    draft_parts = []
    for sec, content in drafts.items():
        if content and len(content) > 50:
            draft_parts.append(f"《{sec}》（前200字）: {content[:200]}")
    draft_summary = "\n".join(draft_parts) if draft_parts else "（暂无草稿）"

    prompt = ChatPromptTemplate.from_messages([
        ("system", _SYSTEM_PROMPT),
        ("user", _USER_PROMPT),
    ])

    try:
        raw = (prompt | llm).invoke({
            "project_type": project_type,
            "research_topic": topic,
            "references_summary": references_summary,
            "draft_summary": draft_summary,
        })
        innovation_content = raw.content if hasattr(raw, "content") else str(raw)

        # 将"特色与创新"章节草稿提取出来单独存入 draft_sections
        chapter_content = _extract_chapter(innovation_content)
        new_drafts = dict(drafts)
        if chapter_content and len(chapter_content) > 100:
            new_drafts["特色与创新"] = chapter_content

        log_msg = f"[InnovationAgent] 创新点提炼完成，字数：{len(innovation_content)}"
        print(log_msg)

        return {
            "innovation_points": innovation_content,
            "draft_sections": new_drafts,
            "discussion_history": [log_msg],
            "completed_tasks": [{
                "task_id": "innovation-" + str(len(state.get("completed_tasks") or [])),
                "agent_type": "innovation",
                "section": "特色与创新",
                "result": "success",
            }],
        }
    except Exception as e:
        err_msg = f"[InnovationAgent] 执行失败: {e}"
        print(err_msg)
        return {
            "discussion_history": [err_msg],
            "innovation_points": f"创新点生成失败，请重试。错误：{e}",
        }


def _extract_chapter(full_text: str) -> str:
    """从创新点报告中提取'特色与创新'章节正文"""
    import re
    # 寻找"## 特色与创新" 之后的内容
    match = re.search(r'##\s*特色与创新（章节草稿）\s*\n(.*)', full_text, re.DOTALL)
    if match:
        return match.group(1).strip()
    # 没有标记时，取后半部分
    lines = full_text.split("\n")
    trigger = False
    result = []
    for line in lines:
        if "特色与创新" in line and "章节" in line:
            trigger = True
            continue
        if trigger:
            result.append(line)
    return "\n".join(result).strip() if result else ""
