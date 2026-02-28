"""
state.py — GraphState 核心状态 Schema
支持新版多Agent动态调度 + 辩论评审架构
"""
from typing import TypedDict, Annotated, List, Dict, Any, Optional, Union
import operator
import copy
from pydantic import BaseModel, Field

# ─────────────────────────── DOM Models ────────────────────────────

class DocumentElement(TypedDict, total=False):
    id: str
    type: str
    content: Any
    metadata: Dict

class TextElement(DocumentElement):
    pass  # type is "text"

class TableElement(DocumentElement):
    pass  # type is "table"

class FormulaElement(DocumentElement):
    pass  # type is "formula"

class ImageElement(DocumentElement):
    pass  # type is "image"

class SectionDOM(TypedDict):
    title: str
    elements: List[Any]

def merge_dom(left: Dict[str, Any], right: Dict[str, Any]) -> Dict[str, Any]:
    """合并 DOM 树（深度复制以防并发污染，安全追加子元素）"""
    if not left:
        return copy.deepcopy(right) if right else {}
    if not right:
        return copy.deepcopy(left)
    result = copy.deepcopy(left)
    for key, val in right.items():
        if key not in result:
            result[key] = copy.deepcopy(val)
        else:
            if isinstance(val, dict) and "element_updates" in val:
                result[key]["elements"].extend(copy.deepcopy(val["element_updates"]))
            elif isinstance(val, dict) and "elements" in val:
                result[key]["elements"].extend(copy.deepcopy(val["elements"]))
    return result


# ─────────────────────────── Reducers ────────────────────────────

def add_documents(left: List[Dict[str, Any]], right: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """追加文档列表（深度复制以防并发污染）"""
    if not left:
        return copy.deepcopy(right) if right else []
    if not right:
        return copy.deepcopy(left)
    return copy.deepcopy(left) + copy.deepcopy(right)


def add_feedbacks(left: List[Dict[str, Any]], right: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """替换模式：只保留最新一次的反馈（深度复制）"""
    if not right:
        return copy.deepcopy(left) if left else []
    return copy.deepcopy(right)


def add_messages(left: List[str], right: List[str]) -> List[str]:
    """追加日志/消息列表"""
    if not left:
        return list(right) if right else []
    if not right:
        return list(left)
    return list(left) + list(right)


def merge_dicts(left: Dict[str, str], right: Dict[str, str]) -> Dict[str, str]:
    """合并字典（浅拷贝字符串字典）"""
    if not left:
        return dict(right) if right else {}
    if not right:
        return dict(left)
    return {**left, **right}


def replace_list(left: List[Any], right: List[Any]) -> List[Any]:
    """替换列表（对于 pending_tasks 我们应该改为智能合并，但为了兼容性暂行彻底覆盖）"""
    # 如果两个节点同时想替换列表，简单的覆盖会丢数据。
    # 这里我们改为：如果是追加新任务，就合并。但这依赖业务逻辑。
    # 暂时保持全量覆盖，但在 orchestrator 级别解决并发覆盖问题。
    if right is None:
        return copy.deepcopy(left) if left else []
    return copy.deepcopy(right)


def update_model_config(left: Dict[str, str], right: Dict[str, str]) -> Dict[str, str]:
    """用于 model_config 的更新，防止 InvalidUpdateError"""
    if not left:
        return dict(right) if right else {}
    if not right:
        return dict(left)
    return {**left, **right}


# ─────────────────────────── GraphState ──────────────────────────

class GraphState(TypedDict):
    """
    核心状态管理 Schema
    ─ 兼容旧版线性流水线
    ─ 支持新版决策Agent动态调度 + 评审专家辩论机制
    """

    # ════════════════════ 基础项目信息 ════════════════════
    project_type: str           # 基金类型：面上项目 / 青年基金 / 重点项目 …
    research_topic: str         # 核心研究主题/思路

    # ════════════════════ 生成内容状态 ════════════════════
    current_focus: str          # 当前章节（单章节模式使用）
    draft_sections: Dict[str, str]   # { 章节名: 内容 }
    document_dom: Annotated[Dict[str, Any], merge_dom]  # V2 架构：{ 章节名: SectionDOM }
    innovation_points: str      # 创新点Agent提炼的结构化创新点
    layout_notes: str           # 排版Agent的优化建议/说明

    # ════════════════════ 检索内容池 ════════════════════
    reference_documents: Annotated[List[Dict[str, Any]], add_documents]
    reference_dict: Annotated[Dict[str, str], merge_dicts]

    # ════════════════════ 评估与讨论记录 ════════════════════
    review_feedbacks: Annotated[List[Dict[str, Any]], add_feedbacks]
    discussion_history: Annotated[List[str], add_messages]

    # ════════════════════ 系统控制 ════════════════════
    iteration_count: int
    max_iterations: int
    status: str
    # 状态枚举: INITIALIZED / PLANNING / EXECUTING / REVIEWING / DEBATING / FINALIZING / COMPLETED
    reviewer_score: float
    prev_review_feedbacks: List[Dict[str, Any]]

    # ════════════════════ 决策Agent任务队列 ════════════════════
    # pending_tasks 格式：
    # [{
    #   "task_id": str,
    #   "agent_type": "searcher" | "innovation" | "writer" | "diagram" | "layout",
    #   "section": str,          # 针对哪个章节（可选）
    #   "instructions": str,     # 额外指令
    #   "priority": int,         # 优先级（越大越先执行）
    # }, ...]
    pending_tasks: Annotated[List[Dict[str, Any]], replace_list]
    completed_tasks: Annotated[List[Dict[str, Any]], add_documents]
    decision_log: Annotated[List[str], add_messages]
    current_phase: str
    # 阶段枚举: planning / executing / reviewing / debating / revising / finalizing

    # ════════════════════ 辩论机制 ════════════════════
    # debate_rounds 格式：
    # [{ "round": int, "reviewer": str, "stance": str, "argument": str }, ...]
    debate_rounds: Annotated[List[Dict[str, Any]], add_documents]
    debate_conclusion: str       # 辩论最终结论文本
    revision_required: bool      # 辩论是否裁定需要修改

    # revision_targets 格式：
    # [{ "section": str, "issue": str, "instruction": str, "priority": "high"|"medium"|"low" }, ...]
    revision_targets: Annotated[List[Dict[str, Any]], replace_list]

    # ════════════════════ 跨章节知识传递 ════════════════════
    completed_section_summaries: Dict[str, str]  # { 章节名: 前200字摘要 }
    document_outline: str

    # ════════════════════ 最终结果 ════════════════════
    final_document_path: Optional[str]

    # ════════════════════ 模型配置 ════════════════════
    # { "decision": "deepseek", "searcher": "deepseek", "writer": "moonshot",
    #   "innovation": "deepseek", "reviewer": "deepseek", "embeddings": "doubao" }
    model_config: Annotated[Dict[str, str], update_model_config]

    # ════════════════════ 配图资产 ════════════════════
    generated_images: Dict[str, str]  # { 章节名: 图片绝对路径 }
