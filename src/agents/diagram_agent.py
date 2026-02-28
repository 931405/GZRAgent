"""
diagram_agent.py — 绘图 Agent

职责：
- 封装 image_generator.py 中的图表生成能力为 LangGraph 节点
- 接收特定章节内容，生成合适的 Mermaid 图（技术路线、框架图、思维导图等）
- 图片路径写入 generated_images 字段供导出使用
"""
from typing import Dict, Any

from typing import Optional
from src.state import GraphState

# 按需导入，避免在 image_generator 不可用时整个模块报错
def _get_generator():
    from src.utils.image_generator import generate_diagram_for_section
    return generate_diagram_for_section


def run_diagram_agent(state: GraphState, section: Optional[str] = None, instructions: str = "") -> Dict[str, Any]:
    """
    绘图 Agent 主函数

    Args:
        state: 当前全局状态
        section: 要为哪个章节生成图（None 则使用 current_focus）
        instructions: 额外绘图指令（可指定图类型、重点内容等）
    """
    target_section = section or state.get("current_focus", "")
    dom = state.get("document_dom") or {}
    
    if dom and target_section in dom:
        elements = dom[target_section].get("elements", [])
        content_parts = []
        for el in elements:
            if el.get("type") == "text":
                content_parts.append(el.get("content", ""))
            else:
                content_parts.append(f"[{el.get('type')}: {el.get('id')}]")
        content = "\n\n".join(content_parts)
    else:
        drafts = state.get("draft_sections") or {}
        content = drafts.get(target_section, "")

    if not content:
        warn_msg = f"[DiagramAgent] 《{target_section}》无内容，跳过绘图"
        print(warn_msg)
        return {"discussion_history": [warn_msg]}

    config = state.get("model_config") or {}
    provider = config.get("diagram", config.get("writer", "deepseek"))
    topic = state.get("research_topic", "")

    log_msg = f"[DiagramAgent] 开始为《{target_section}》生成示意图..."
    print(log_msg)

    try:
        generate_fn = _get_generator()
        result = generate_fn(
            section_name=target_section,
            section_content=content,
            topic=topic,
            model_provider=provider,
        )

        if result and isinstance(result, dict):
            image_path = result.get("image_path") or result.get("path", "")
        elif result and isinstance(result, str):
            image_path = result
        else:
            image_path = ""

        existing_images = dict(state.get("generated_images") or {})
        if image_path:
            existing_images[target_section] = image_path
            success_msg = f"[DiagramAgent] 《{target_section}》图表已生成: {image_path}"
            print(success_msg)
            return {
                "generated_images": existing_images,
                "discussion_history": [log_msg, success_msg],
                "completed_tasks": [{
                    "task_id": f"diagram-{target_section}",
                    "agent_type": "diagram",
                    "section": target_section,
                    "result": "success",
                    "image_path": image_path,
                }],
            }
        else:
            skip_msg = f"[DiagramAgent] 《{target_section}》图表生成返回空，跳过"
            print(skip_msg)
            return {"discussion_history": [log_msg, skip_msg]}

    except Exception as e:
        err_msg = f"[DiagramAgent] 《{target_section}》绘图失败: {e}"
        print(err_msg)
        return {"discussion_history": [log_msg, err_msg]}


def run_diagram_agent_from_task(state: GraphState, task: Dict[str, Any]) -> Dict[str, Any]:
    """从任务字典中提取参数调用绘图 Agent（供 MultiWorker 统一调用）"""
    section = task.get("section", "")
    instructions = task.get("instructions", "")
    return run_diagram_agent(state, section=section, instructions=instructions)
