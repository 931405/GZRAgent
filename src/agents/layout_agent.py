"""
layout_agent.py — 排版优化 Agent

职责：
- 检查并优化全文草稿的排版细节
  * 标题层级一致性（##/###/####）
  * 段落序号格式统一（1.1 / 1.2 或 一、二、三）
  * 参考文献序号连续性
  * 标点符号中英文混用
  * 各章节字数均衡建议
- 输出 layout_notes 字段（给人看的审查报告）
- 同时对各章节内容做轻量级格式修正（写回 draft_sections）
"""
import re
from typing import Dict, Any, List, Tuple

from langchain_core.prompts import ChatPromptTemplate
from src.state import GraphState
from src.llm import get_llm

_SYSTEM_PROMPT = """\
你是国家自然科学基金申请书的专业排版审核专家。

任务：审查申请书草稿的排版和格式，指出问题，给出修正版本。

检查项目：
1. 标题层级是否规范（一级##、二级###、三级####）
2. 段落首行缩进是否一致
3. 序号格式是否统一（避免混用"一、"和"1."等）
4. 参考文献序号是否从[1]开始连续排列
5. 关键术语首次出现是否有英文注释
6. 全文各章节字数是否合理（立项依据≥2000字，各章节合计≥8000字）
7. 中英文混排标点（逗号、句号等是否统一使用中文标点）

输出格式（JSON）：
{{
  "issues": [
    {{"section": "章节名", "type": "格式类型", "description": "问题描述", "severity": "high|medium|low"}}
  ],
  "word_count_summary": {{"章节名": 字数}},
  "overall_assessment": "整体评价（1-2句话）",
  "revised_sections": {{
    "章节名": "修正后的完整内容（仅对格式做轻量修正，不改变实质内容）"
  }}
}}

注意：revised_sections 只包含实际做了修改的章节，未修改的章节不要放入。
"""

_USER_PROMPT = """\
项目类型：{project_type}
研究主题：{research_topic}

各章节草稿（截取前3000字供分析）：
{sections_preview}

请输出排版审查报告（JSON）：
"""


def run_layout_agent(state: GraphState) -> Dict[str, Any]:
    """排版优化 Agent"""
    config = state.get("model_config") or {}
    provider = config.get("layout", config.get("writer", "deepseek"))
    llm = get_llm(provider_override=provider, temperature=0.05, is_json_mode=True)

    dom = state.get("document_dom") or {}
    drafts = state.get("draft_sections") or {}
    
    if not dom and not drafts:
        msg = "[LayoutAgent] 无草稿或 DOM 内容，跳过排版检查"
        print(msg)
        return {"discussion_history": [msg], "layout_notes": msg}

    # 构建预览文本（截断防止 token 超限）
    sections_preview_parts = []
    
    if dom:
        for sec, section_dom in dom.items():
            elements = section_dom.get("elements", [])
            content_parts = []
            for el in elements:
                t = el.get("type", "text")
                if t == "text":
                    content_parts.append(el.get("content", ""))
                elif t == "table":
                    content_parts.append(f"[表格: {el.get('id')}]")
                elif t == "formula":
                    content_parts.append(f"[公式: {el.get('id')}]")
                elif t == "image":
                    content_parts.append(f"[配图: {el.get('id')}]")
            content = "\n\n".join(content_parts)
            if content:
                preview = content[:600]
                wc = len(content)
                sections_preview_parts.append(f"### {sec}（{wc}字）\n{preview}\n...")
    else:
        # Fallback to drafts
        for sec, content in drafts.items():
            if content:
                preview = content[:600]
                wc = len(content)
                sections_preview_parts.append(f"### {sec}（{wc}字）\n{preview}\n...")
                
    sections_preview = "\n\n".join(sections_preview_parts[:8])  # 最多8章

    prompt = ChatPromptTemplate.from_messages([
        ("system", _SYSTEM_PROMPT),
        ("user", _USER_PROMPT),
    ])

    log_msg = f"[LayoutAgent] 开始排版审查，共 {len(drafts)} 个章节..."
    print(log_msg)

    try:
        raw = (prompt | llm).invoke({
            "project_type": state.get("project_type", "面上项目"),
            "research_topic": state.get("research_topic", ""),
            "sections_preview": sections_preview,
        })
        raw_text = raw.content if hasattr(raw, "content") else str(raw)
        result = _parse_result(raw_text)

        issues: List[Dict] = result.get("issues", [])
        overall = result.get("overall_assessment", "")
        revised: Dict[str, str] = result.get("revised_sections", {})
        wc_summary: Dict = result.get("word_count_summary", {})

        # 生成 layout_notes 报告
        notes_lines = [f"## 排版审查报告\n", f"**整体评价**：{overall}\n"]
        if wc_summary:
            notes_lines.append("**各章节字数**：")
            for sec, wc in wc_summary.items():
                notes_lines.append(f"  - {sec}: {wc} 字")
        if issues:
            notes_lines.append(f"\n**发现问题（{len(issues)}条）**：")
            for iss in issues:
                severity_label = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(iss.get("severity", "low"), "⚪")
                notes_lines.append(
                    f"  {severity_label} [{iss.get('section', '全文')}] "
                    f"{iss.get('type', '')}：{iss.get('description', '')}"
                )
        else:
            notes_lines.append("\n✅ 未发现明显排版问题")

        layout_notes = "\n".join(notes_lines)

        # 合并修正内容到 draft_sections
        new_drafts = dict(drafts)
        if revised:
            new_drafts.update(revised)
            notes_lines.append(f"\n**已自动修正** {len(revised)} 个章节的格式问题")

        success_msg = f"[LayoutAgent] 排版审查完成，发现 {len(issues)} 个问题，自动修正 {len(revised)} 章"
        print(success_msg)

        return {
            "layout_notes": layout_notes,
            "draft_sections": new_drafts,
            "discussion_history": [log_msg, success_msg],
            "completed_tasks": [{
                "task_id": "layout-final",
                "agent_type": "layout",
                "section": "全文",
                "result": "success",
                "issues_found": len(issues),
                "sections_revised": len(revised),
            }],
        }

    except Exception as e:
        err_msg = f"[LayoutAgent] 排版审查失败: {e}"
        print(err_msg)
        return {
            "layout_notes": f"排版审查执行失败：{e}",
            "discussion_history": [log_msg, err_msg],
        }


def _parse_result(raw_text: str) -> Dict:
    """解析 LLM 输出的 JSON"""
    import json
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
