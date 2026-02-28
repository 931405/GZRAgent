import json
import os
import re
import time

HISTORY_DIR = "data/history"

def save_history(graph_state: dict, project_name: str = "未命名项目"):
    """
    将当前的运行状态（草稿、历史、评审建议）持久化到本地 JSON 文件中。
    """
    if not os.path.exists(HISTORY_DIR):
        os.makedirs(HISTORY_DIR)
    
    # 清理文件名：移除换行、斜杠、特殊字符等
    safe_name = re.sub(r'[\n\r\t/\\:*?"<>|【】]', '', project_name)
    safe_name = safe_name.replace(" ", "_").strip()[:30]  # 限制长度
    if not safe_name:
        safe_name = "unnamed"
        
    timestamp = int(time.time())
    filename = f"{HISTORY_DIR}/history_{safe_name}_{timestamp}.json"
    
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(graph_state, f, ensure_ascii=False, indent=2)
        
    return filename

def load_history_list():
    """读取所有历史记录文件名"""
    if not os.path.exists(HISTORY_DIR):
        return []
    
    files = [f for f in os.listdir(HISTORY_DIR) if f.endswith(".json")]
    files.sort(reverse=True) # 最近的文件排前面
    return files

def load_history_data(filename: str):
    """读取特定的历史记录 JSON 文件内容"""
    filepath = os.path.join(HISTORY_DIR, filename)
    if not os.path.exists(filepath):
        return None
        
    with open(filepath, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
            return data
        except json.JSONDecodeError:
            return None
