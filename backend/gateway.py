"""
gateway.py — 事件网关队列管理器

借鉴 OpenClaw 的 Gateway 架构，实现：
1. 消息队列（Message Queue）：前端发送的用户指令暂存在队列中，
   由工作流循环在安全检查点（两个 LLM 调用之间）消费
2. 消息插入策略：
   - steer:   打断当前流程，在下一个检查点注入优先指令（如"跳过检索直接写作"）
   - collect: 收集多条修改意见合并提交（如"把立项依据第三段改一下 + 把创新点加一条"）
   - followup: 在当前流程完成后追加新任务
3. 会话隔离：每个 run_id 有独立的消息队列

使用方式：
  POST /api/workflow/steer/{run_id}   → 注入一条 steer 消息
  POST /api/workflow/collect/{run_id} → 注入一条 collect 消息
  在 orchestrator 的每个 LLM 调用之间调用 gateway.consume() 获取待处理指令
"""
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional
from collections import deque


class MessageStrategy(str, Enum):
    """消息插入策略"""
    STEER = "steer"        # 打断：立即在下一个检查点注入
    COLLECT = "collect"    # 收集：合并多条修改意见后统一提交
    FOLLOWUP = "followup"  # 追加：当前流程完成后执行


@dataclass
class GatewayMessage:
    """网关消息"""
    strategy: MessageStrategy
    content: str                      # 用户指令内容
    timestamp: float = field(default_factory=time.time)
    priority: int = 5                 # 1-10, 10=最高
    metadata: dict = field(default_factory=dict)  # 附加信息（如 target_section）


@dataclass
class RunQueue:
    """单个 run 的消息队列"""
    steer_queue: deque = field(default_factory=deque)    # 高优先级打断队列
    collect_buffer: list = field(default_factory=list)   # 收集缓冲区
    followup_queue: deque = field(default_factory=deque)  # 追加任务队列
    lock: threading.Lock = field(default_factory=threading.Lock)
    last_collect_flush: float = field(default_factory=time.time)
    # 收集缓冲区的自动合并时间窗口（秒）
    collect_window: float = 10.0


# ============= 全局网关注册表 =============

_queues: Dict[str, RunQueue] = {}
_global_lock = threading.Lock()

# 收集缓冲区合并的最大等待时间（秒）
COLLECT_MERGE_WINDOW = 10.0


def _get_queue(run_id: str) -> RunQueue:
    """获取或创建运行队列"""
    with _global_lock:
        if run_id not in _queues:
            _queues[run_id] = RunQueue()
        return _queues[run_id]


def cleanup_queue(run_id: str):
    """清理已完成运行的队列"""
    with _global_lock:
        _queues.pop(run_id, None)


# ============= 消息推送 API =============

def push_steer(run_id: str, content: str, priority: int = 9, **metadata):
    """推送一条 Steer 消息（最高优先级打断）。
    
    Steer 消息会在下一个 LLM 安全检查点被消费。
    典型用途：
    - "跳过文献检索，直接开始写作"
    - "不要修改立项依据，保持原样"
    - "把当前章节的重心改为方法对比"
    """
    queue = _get_queue(run_id)
    msg = GatewayMessage(
        strategy=MessageStrategy.STEER,
        content=content,
        priority=priority,
        metadata=metadata,
    )
    with queue.lock:
        queue.steer_queue.append(msg)
    print(f"[Gateway] Steer 消息已入队: run={run_id}, priority={priority}")


def push_collect(run_id: str, content: str, **metadata):
    """推送一条 Collect 消息（收集到缓冲区，等待合并提交）。
    
    Collect 消息会在缓冲区内累积，直到：
    - 超过时间窗口（默认 10s）自动合并
    - 显式调用 flush_collect() 手动合并
    
    典型用途：
    - "把立项依据第三段中的数据更新为2025年"
    - "在研究方案中增加消融实验"
    - 连续多条修改建议
    """
    queue = _get_queue(run_id)
    msg = GatewayMessage(
        strategy=MessageStrategy.COLLECT,
        content=content,
        metadata=metadata,
    )
    with queue.lock:
        queue.collect_buffer.append(msg)
    print(f"[Gateway] Collect 消息已缓冲: run={run_id}, buffer_size={len(queue.collect_buffer)}")


def push_followup(run_id: str, content: str, **metadata):
    """推送一条 Followup 消息（完成后追加）。"""
    queue = _get_queue(run_id)
    msg = GatewayMessage(
        strategy=MessageStrategy.FOLLOWUP,
        content=content,
        metadata=metadata,
    )
    with queue.lock:
        queue.followup_queue.append(msg)


# ============= 消息消费 API =============

def consume(run_id: str) -> Optional[dict]:
    """在安全检查点消费消息队列。
    
    优先级：steer > collect(已合并) > followup
    
    返回格式：
    {
        "strategy": "steer" | "collect" | "followup",
        "instructions": str,          # 合并后的指令文本
        "count": int,                 # 合并了多少条原始消息
        "metadata": dict,             # 附加信息
    }
    
    如果队列为空，返回 None。
    """
    queue = _get_queue(run_id)
    
    with queue.lock:
        # 1. 最高优先级：steer
        if queue.steer_queue:
            msg = queue.steer_queue.popleft()
            return {
                "strategy": "steer",
                "instructions": msg.content,
                "count": 1,
                "metadata": msg.metadata,
            }
        
        # 2. 检查 collect 缓冲区是否需要合并
        if queue.collect_buffer:
            elapsed = time.time() - queue.last_collect_flush
            if elapsed >= queue.collect_window or len(queue.collect_buffer) >= 5:
                # 合并所有 collect 消息
                merged = _merge_collect_messages(queue.collect_buffer)
                count = len(queue.collect_buffer)
                queue.collect_buffer.clear()
                queue.last_collect_flush = time.time()
                return {
                    "strategy": "collect",
                    "instructions": merged,
                    "count": count,
                    "metadata": {},
                }
        
        # 3. 追加任务
        if queue.followup_queue:
            msg = queue.followup_queue.popleft()
            return {
                "strategy": "followup",
                "instructions": msg.content,
                "count": 1,
                "metadata": msg.metadata,
            }
    
    return None


def flush_collect(run_id: str) -> Optional[dict]:
    """手动刷新 collect 缓冲区（立即合并提交）。"""
    queue = _get_queue(run_id)
    with queue.lock:
        if not queue.collect_buffer:
            return None
        merged = _merge_collect_messages(queue.collect_buffer)
        count = len(queue.collect_buffer)
        queue.collect_buffer.clear()
        queue.last_collect_flush = time.time()
        return {
            "strategy": "collect",
            "instructions": merged,
            "count": count,
            "metadata": {},
        }


def has_pending(run_id: str) -> bool:
    """检查是否有待处理的消息"""
    queue = _get_queue(run_id)
    with queue.lock:
        return bool(queue.steer_queue or queue.collect_buffer or queue.followup_queue)


def get_queue_status(run_id: str) -> dict:
    """获取队列状态（供前端展示）"""
    queue = _get_queue(run_id)
    with queue.lock:
        return {
            "steer_count": len(queue.steer_queue),
            "collect_buffer_count": len(queue.collect_buffer),
            "followup_count": len(queue.followup_queue),
        }


# ============= 内部工具 =============

def _merge_collect_messages(messages: List[GatewayMessage]) -> str:
    """将多条 collect 消息合并为一条结构化指令。
    
    合并格式：
    用户修改意见（共N条）：
    1. [内容1]
    2. [内容2]
    ...
    请根据以上修改意见统一调整相关章节。
    """
    if len(messages) == 1:
        return messages[0].content
    
    lines = [f"用户修改意见（共{len(messages)}条）："]
    for i, msg in enumerate(messages, 1):
        section = msg.metadata.get("target_section", "")
        prefix = f"[{section}] " if section else ""
        lines.append(f"{i}. {prefix}{msg.content}")
    lines.append("\n请根据以上修改意见统一调整相关章节。")
    
    return "\n".join(lines)
