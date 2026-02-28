"""
context_manager.py — 结构化上下文管理器

将 discussion_history 从纯文本拼接升级为结构化摘要格式。
每个 Agent 写入结构化条目，读取时按重要度排序、按容量裁剪。
"""
import json
from typing import List, Dict, Any, Optional


# ============= 结构化消息格式 =============

def make_entry(agent: str, section: str, category: str, content: str, priority: int = 5) -> str:
    """创建结构化 discussion_history 条目。
    
    Args:
        agent: Agent 名称 (Searcher / Designer / Writer / Reviewer / Orchestrator / OutlinePlanner)
        section: 章节名称
        category: 条目分类 (decision / finding / score / strategy / revision / error)
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
    for prefix in ["Searcher:", "Designer:", "Writer:", "Reviewer:", "Orchestrator:", "OutlinePlanner:"]:
        if raw.startswith(prefix):
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
        "content": raw,
        "priority": 3
    }


# ============= 结构化摘要生成 =============

def build_structured_context(history: List[str], max_entries: int = 8) -> str:
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
        "revision": "修订记录"
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


# ============= 压缩触发 =============

def should_compress(history: List[str], threshold: int = 10) -> bool:
    """判断是否需要压缩历史。"""
    return len(history) > threshold


def compress_history(history: List[str], keep_recent: int = 5) -> List[str]:
    """压缩历史：保留高优先级 + 最近 N 条。
    
    1. 最近 keep_recent 条保留原文
    2. 更早的条目只保留 priority >= 7 的
    3. 其余压缩为 1 条摘要
    """
    if len(history) <= keep_recent:
        return history
    
    recent = history[-keep_recent:]
    older = history[:-keep_recent]
    
    # 保留高优先级条目
    important = []
    compressed_count = 0
    for h in older:
        e = parse_entry(h)
        if e.get("priority", 3) >= 7:
            important.append(h)
        else:
            compressed_count += 1
    
    if compressed_count > 0:
        summary_entry = make_entry(
            agent="System",
            section="",
            category="decision",
            content=f"（已压缩 {compressed_count} 条低优先级历史记录）",
            priority=2
        )
        return [summary_entry] + important + recent
    
    return important + recent
