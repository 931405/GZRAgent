"""
context_manager.py — 结构化上下文管理器（增强版）

借鉴 OpenClaw 的上下文治理机制，实现：
1. 结构化条目格式（make_entry / parse_entry）
2. 按优先级构建紧凑上下文（build_structured_context）
3. Token 感知的 Compaction（压缩策略）
4. 工具结果修剪 Pruning（软修剪 + 硬清除）
5. 自动压缩触发钩子（auto_compact_state）
"""
import json
import copy
from typing import List, Dict, Any, Optional


# ============= 配置 =============

# 压缩高水位：discussion_history 条目数超过此值时触发压缩
COMPACT_HIGH_WATER = 12
# 压缩低水位：压缩后目标保留的条目数
COMPACT_LOW_WATER = 6
# 保护最近 N 条完整条目不被压缩
COMPACT_KEEP_RECENT = 4
# 修剪：保护最近 N 条 assistant 消息涉及的工具结果
PRUNE_PROTECT_RECENT = 3
# 修剪：工具结果超过此字符数时触发软修剪
PRUNE_RESULT_THRESHOLD = 1500
# 软修剪：保留头部和尾部各 N 字符
PRUNE_HEAD_CHARS = 300
PRUNE_TAIL_CHARS = 200


# ============= 结构化消息格式 =============

def make_entry(agent: str, section: str, category: str, content: str, priority: int = 5) -> str:
    """创建结构化 discussion_history 条目。
    
    Args:
        agent: Agent 名称 (Searcher / Designer / Writer / Reviewer / Orchestrator / SkillLoader ...)
        section: 章节名称
        category: 条目分类 (decision / finding / score / strategy / revision / error / compaction)
        content: 具体内容
        priority: 重要度 1-10 (10=最重要)
    
    Returns:
        JSON 字符串格式的条目
    """
    entry = {
        "agent": agent,
        "section": section,
        "category": category,
        "content": content,
        "priority": priority
    }
    return json.dumps(entry, ensure_ascii=False)


def parse_entry(raw: str) -> Optional[Dict[str, Any]]:
    """解析结构化条目，兼容纯文本旧格式。"""
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict) and "agent" in obj:
            return obj
    except (json.JSONDecodeError, TypeError):
        pass
    # 兼容旧格式: "AgentName: 内容..."
    for prefix in ["Searcher:", "Designer:", "Writer:", "Reviewer:", "Orchestrator:", "OutlinePlanner:", "SkillLoader:"]:
        if isinstance(raw, str) and raw.startswith(prefix):
            return {
                "agent": prefix.rstrip(":"),
                "section": "",
                "category": "legacy",
                "content": raw[len(prefix):].strip(),
                "priority": 5
            }
    return {
        "agent": "unknown",
        "section": "",
        "category": "legacy",
        "content": str(raw) if raw else "",
        "priority": 3
    }


# ============= 结构化摘要生成 =============

def build_structured_context(history: List[str], max_entries: int = 6) -> str:
    """将 discussion_history 转为结构化上下文注入 prompt。
    
    按 priority 排序后截取 top-N:
    - decision / strategy / score 类优先保留
    - legacy / finding 类低优先
    
    输出格式:
    ## 会议纪要
    ### 关键决策
    - [Designer] ...
    ### 评审评分
    - [Reviewer] ...
    ### 检索发现
    - [Searcher] ...
    """
    entries = [parse_entry(h) for h in history]
    # 按 priority 降序
    entries.sort(key=lambda e: e.get("priority", 3), reverse=True)
    top = entries[:max_entries]
    
    # 分类聚合
    categories = {
        "关键决策": [],
        "策略建议": [],
        "评审评分": [],
        "检索与发现": [],
        "修订记录": [],
        "其他": []
    }
    
    CAT_MAP = {
        "decision": "关键决策",
        "strategy": "策略建议",
        "score": "评审评分",
        "finding": "检索与发现",
        "revision": "修订记录",
        "compaction": "其他",
    }
    
    for e in top:
        cat_key = CAT_MAP.get(e.get("category", ""), "其他")
        agent = e.get("agent", "?")
        content = e.get("content", "")
        section = e.get("section", "")
        prefix = f"[{agent}]" if not section else f"[{agent}·{section}]"
        categories[cat_key].append(f"- {prefix} {content}")
    
    # 构建输出
    lines = ["## 会议纪要"]
    for cat_name, items in categories.items():
        if items:
            lines.append(f"### {cat_name}")
            lines.extend(items)
    
    return "\n".join(lines)


# ============= Compaction（压缩） =============

def should_compress(history: List[str], threshold: int = COMPACT_HIGH_WATER) -> bool:
    """判断是否需要压缩历史。"""
    return len(history) > threshold


def compress_history(history: List[str], keep_recent: int = COMPACT_KEEP_RECENT) -> List[str]:
    """压缩历史：保留高优先级 + 最近 N 条，引入时间衰减。
    
    借鉴 OpenClaw 的 Compaction 机制：
    1. 最近 keep_recent 条保留原文
    2. 更早的条目只保留 priority >= 7 的（关键决策/评审评分/错误）
    3. 高优先级条目也限制最多保留 5 条（最新的）
    4. 被折叠的条目计数统计为一条系统摘要
    """
    if len(history) <= keep_recent:
        return history
    
    recent = history[-keep_recent:]
    older = history[:-keep_recent]
    
    # 保留高优先级条目
    important = []
    compressed_count = 0
    categories_compressed = {}
    
    for h in older:
        e = parse_entry(h)
        prio = e.get("priority", 3) if e else 3
        cat = e.get("category", "unknown") if e else "unknown"
        
        if prio >= 7:
            important.append(h)
        else:
            compressed_count += 1
            categories_compressed[cat] = categories_compressed.get(cat, 0) + 1
            
    # 增加时间衰减截断
    if len(important) > 5:
        compressed_count += (len(important) - 5)
        important = important[-5:]
    
    if compressed_count > 0:
        # 生成带分类统计的折叠摘要
        cat_summary = ", ".join(f"{cat}×{cnt}" for cat, cnt in categories_compressed.items())
        summary_text = f"（已折叠 {compressed_count} 条早期历史: {cat_summary}。关键决策已保留。）"
        summary_entry = make_entry(
            agent="System",
            section="",
            category="compaction",
            content=summary_text,
            priority=2
        )
        return [summary_entry] + important + recent
    
    return important + recent


# ============= Pruning（工具结果修剪） =============

def prune_tool_results(reference_documents: List[Dict[str, Any]], 
                       protect_recent: int = PRUNE_PROTECT_RECENT,
                       threshold: int = PRUNE_RESULT_THRESHOLD) -> List[Dict[str, Any]]:
    """修剪检索/工具返回的长文本结果。
    
    借鉴 OpenClaw 的两级 Pruning 策略：
    - 软修剪：保留头部 + 尾部并插入省略标记（对长文本）
    - 保护最近 protect_recent 个文档不被修剪
    
    Args:
        reference_documents: 文献/文档列表
        protect_recent: 保护最近 N 个文档不修剪
        threshold: 超过此字符数的文档内容触发软修剪
    
    Returns:
        修剪后的文档列表（深拷贝，不修改原数据）
    """
    if not reference_documents:
        return []
    
    result = copy.deepcopy(reference_documents)
    
    # 保护最近的文档
    protected_count = min(protect_recent, len(result))
    
    for i in range(len(result) - protected_count):
        doc = result[i]
        content = doc.get("content", "")
        
        if len(content) > threshold:
            # 软修剪：保留头部 + 尾部
            head = content[:PRUNE_HEAD_CHARS]
            tail = content[-PRUNE_TAIL_CHARS:]
            trimmed_chars = len(content) - PRUNE_HEAD_CHARS - PRUNE_TAIL_CHARS
            doc["content"] = f"{head}\n\n[... 已省略 {trimmed_chars} 字符 ...]\n\n{tail}"
            doc["_pruned"] = True
    
    return result


def prune_draft_for_context(draft_sections: Dict[str, str],
                            max_chars_per_section: int = 2000) -> Dict[str, str]:
    """修剪草稿内容用于上下文注入（避免全文塞进 prompt）。
    
    Args:
        draft_sections: {章节名: 内容}
        max_chars_per_section: 每个章节最多保留的字符数
    
    Returns:
        修剪后的草稿字典
    """
    pruned = {}
    for section, content in draft_sections.items():
        if not content:
            pruned[section] = ""
            continue
        if len(content) <= max_chars_per_section:
            pruned[section] = content
        else:
            half = max_chars_per_section // 2
            pruned[section] = (
                content[:half] 
                + f"\n\n[... 已省略 {len(content) - max_chars_per_section} 字符 ...]\n\n" 
                + content[-half:]
            )
    return pruned


# ============= 自动压缩钩子 =============

def auto_compact_state(state: Dict[str, Any]) -> Dict[str, Any]:
    """自动压缩钩子：在每次 multi_worker 完成后调用。
    
    检查 discussion_history 和 reference_documents 是否需要压缩/修剪，
    如果需要则返回状态更新字典。
    
    借鉴 OpenClaw 的做法：在每次 LLM 调用之前自动触发修剪，
    这里在每轮 worker 完成后触发，避免上下文持续膨胀。
    
    Args:
        state: 当前 GraphState
        
    Returns:
        状态更新字典（仅包含被修改的字段），如果无需更新则为空字典
    """
    updates = {}
    
    # 1. 压缩 discussion_history
    history = state.get("discussion_history") or []
    if should_compress(history):
        compressed = compress_history(history)
        old_len = len(history)
        new_len = len(compressed)
        print(f"[ContextManager] Compaction 触发: {old_len} → {new_len} 条历史")
        updates["discussion_history"] = compressed
    
    # 2. 修剪 reference_documents
    ref_docs = state.get("reference_documents") or []
    if ref_docs and len(ref_docs) > PRUNE_PROTECT_RECENT:
        pruned = prune_tool_results(ref_docs)
        pruned_count = sum(1 for d in pruned if d.get("_pruned"))
        if pruned_count > 0:
            print(f"[ContextManager] Pruning 触发: 修剪了 {pruned_count} 个文档的长文本")
            updates["reference_documents"] = pruned
    
    return updates

