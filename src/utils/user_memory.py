"""
user_memory.py — 文件系统长期记忆

跨 Session 持久化用户偏好、研究方向、写作风格等信息。
原则: Start simple — 用 JSON 文件即可，验证有效后再考虑更复杂方案。
"""
import os
import json
from typing import Dict, Any, Optional

# 默认存储路径
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")
MEMORY_FILE = os.path.join(DATA_DIR, "user_preferences.json")

# 默认偏好模板
DEFAULT_PREFERENCES = {
    "research_field": "",           # 研究领域（如: "计算化学", "NLP"）
    "writing_style": "",            # 写作风格偏好（如: "简洁精炼", "详实论证"）
    "frequent_keywords": [],        # 常用关键词
    "preferred_journals": [],       # 偏好引用的期刊/来源
    "avoided_patterns": [],         # 避免使用的表述（如: "众所周知"）
    "custom_instructions": "",      # 自定义写作指令
    "past_topics": [],              # 历史研究主题
    "notes": ""                     # 其他备注
}


def _ensure_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def load_preferences() -> Dict[str, Any]:
    """加载用户偏好，如果文件不存在则返回默认值。"""
    if not os.path.exists(MEMORY_FILE):
        return dict(DEFAULT_PREFERENCES)
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # 合并默认值（处理新增字段）
        merged = dict(DEFAULT_PREFERENCES)
        merged.update(data)
        return merged
    except Exception as e:
        print(f"[UserMemory]: 加载偏好失败 ({e})，使用默认值。")
        return dict(DEFAULT_PREFERENCES)


def save_preferences(prefs: Dict[str, Any]) -> bool:
    """保存用户偏好。"""
    _ensure_dir()
    try:
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(prefs, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"[UserMemory]: 保存偏好失败 ({e})")
        return False


def update_preference(key: str, value: Any) -> bool:
    """更新单个偏好字段。"""
    prefs = load_preferences()
    prefs[key] = value
    return save_preferences(prefs)


def add_to_list(key: str, item: str) -> bool:
    """向列表类偏好追加（去重）。"""
    prefs = load_preferences()
    if key in prefs and isinstance(prefs[key], list):
        if item not in prefs[key]:
            prefs[key].append(item)
        return save_preferences(prefs)
    return False


def record_topic(topic: str) -> bool:
    """记录一次使用过的研究主题。"""
    return add_to_list("past_topics", topic)


def build_preference_context(prefs: Optional[Dict[str, Any]] = None) -> str:
    """将用户偏好构建为可注入 Agent prompt 的上下文。
    
    只输出非空字段，减少 token 消耗。
    """
    if prefs is None:
        prefs = load_preferences()
    
    lines = []
    if prefs.get("research_field"):
        lines.append(f"- 研究领域: {prefs['research_field']}")
    if prefs.get("writing_style"):
        lines.append(f"- 写作风格偏好: {prefs['writing_style']}")
    if prefs.get("frequent_keywords"):
        lines.append(f"- 常用关键词: {', '.join(prefs['frequent_keywords'])}")
    if prefs.get("preferred_journals"):
        lines.append(f"- 偏好引用来源: {', '.join(prefs['preferred_journals'])}")
    if prefs.get("avoided_patterns"):
        lines.append(f"- 避免使用的表述: {', '.join(prefs['avoided_patterns'])}")
    if prefs.get("custom_instructions"):
        lines.append(f"- 自定义指令: {prefs['custom_instructions']}")
    if prefs.get("past_topics"):
        recent = prefs["past_topics"][-3:]
        lines.append(f"- 近期研究主题: {', '.join(recent)}")
    
    if not lines:
        return ""
    
    return "【用户偏好（长期记忆）】:\n" + "\n".join(lines)
