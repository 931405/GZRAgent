"""
tool_sandbox.py — 工具执行沙箱

借鉴 OpenClaw 的工具执行安全机制，实现：
1. 执行隔离：所有外部工具调用（arXiv API, 本地 RAG, 图片生成）
   在隔离的沙箱环境中运行，防止一个工具的异常影响整体工作流
2. 超时控制：每个工具调用有独立的超时时间限制
3. 输出捕获：标准化工具返回格式，带执行时长和异常追踪
4. 权限分级：工具按风险等级分为 readonly / write / dangerous，
   高危操作需人类审批（预留接口）

使用方式：
  from src.utils.tool_sandbox import sandbox_call
  result = sandbox_call("arxiv_search", fn=search_arxiv, args={"query": "..."}, timeout=30)
"""
import time
import threading
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional
from enum import Enum
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError


class ToolPermission(str, Enum):
    """工具权限等级"""
    READONLY = "readonly"    # 只读操作（搜索、检索、读取文件）
    WRITE = "write"          # 写操作（生成文件、修改状态）
    DANGEROUS = "dangerous"  # 高危操作（执行代码、HTTP 外发、删除文件）


# 工具权限注册表
_TOOL_PERMISSIONS: Dict[str, ToolPermission] = {
    # 只读
    "arxiv_search": ToolPermission.READONLY,
    "local_kb_search": ToolPermission.READONLY,
    "search_local_kb": ToolPermission.READONLY,
    # 写
    "generate_diagram": ToolPermission.WRITE,
    "generate_formula": ToolPermission.WRITE,
    "add_document_to_kb": ToolPermission.WRITE,
    # 高危（预留）
    "execute_code": ToolPermission.DANGEROUS,
}

# 高危工具黑名单（这些工具无论如何不允许执行）
_TOOL_BLACKLIST = {"execute_code", "shell_exec", "rm_rf"}

# 超时配置（秒）
_TIMEOUT_DEFAULTS = {
    ToolPermission.READONLY: 30,
    ToolPermission.WRITE: 60,
    ToolPermission.DANGEROUS: 10,  # 默认很短，需人工审批后扩展
}


@dataclass
class SandboxResult:
    """沙箱执行结果"""
    tool_name: str
    success: bool
    output: Any = None
    error: Optional[str] = None
    error_type: Optional[str] = None
    execution_time_ms: float = 0.0
    timed_out: bool = False
    permission: str = ""
    
    def to_dict(self) -> dict:
        return {
            "tool_name": self.tool_name,
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "error_type": self.error_type,
            "execution_time_ms": round(self.execution_time_ms, 1),
            "timed_out": self.timed_out,
            "permission": self.permission,
        }


# ============= 沙箱执行引擎 =============

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="sandbox")


def sandbox_call(
    tool_name: str,
    fn: Callable,
    args: dict = None,
    timeout: int = None,
    allow_dangerous: bool = False,
) -> SandboxResult:
    """在沙箱中执行工具调用。
    
    Args:
        tool_name: 工具名称（用于权限查找和日志）
        fn: 要执行的函数
        args: 函数参数字典
        timeout: 超时秒数（None 则使用默认值）
        allow_dangerous: 是否允许高危工具（需人工审批后设为 True）
    
    Returns:
        SandboxResult 包含执行结果、耗时、异常信息
    """
    args = args or {}
    permission = _TOOL_PERMISSIONS.get(tool_name, ToolPermission.READONLY)
    
    # 黑名单检查
    if tool_name in _TOOL_BLACKLIST:
        return SandboxResult(
            tool_name=tool_name,
            success=False,
            error=f"工具 '{tool_name}' 在黑名单中，禁止执行",
            error_type="BlacklistError",
            permission=permission.value,
        )
    
    # 高危操作拦截
    if permission == ToolPermission.DANGEROUS and not allow_dangerous:
        return SandboxResult(
            tool_name=tool_name,
            success=False,
            error=f"工具 '{tool_name}' 为高危操作，需要人工审批",
            error_type="PermissionDenied",
            permission=permission.value,
        )
    
    # 确定超时时间
    if timeout is None:
        timeout = _TIMEOUT_DEFAULTS.get(permission, 30)
    
    # 在线程池中执行（隔离异常、控制超时）
    start_time = time.time()
    try:
        future = _executor.submit(fn, **args)
        result = future.result(timeout=timeout)
        elapsed = (time.time() - start_time) * 1000
        
        return SandboxResult(
            tool_name=tool_name,
            success=True,
            output=result,
            execution_time_ms=elapsed,
            permission=permission.value,
        )
    
    except FuturesTimeoutError:
        elapsed = (time.time() - start_time) * 1000
        print(f"[Sandbox] 工具 '{tool_name}' 超时 ({timeout}s)")
        return SandboxResult(
            tool_name=tool_name,
            success=False,
            error=f"工具执行超时 ({timeout}s)",
            error_type="TimeoutError",
            execution_time_ms=elapsed,
            timed_out=True,
            permission=permission.value,
        )
    
    except Exception as e:
        elapsed = (time.time() - start_time) * 1000
        tb = traceback.format_exc()
        print(f"[Sandbox] 工具 '{tool_name}' 异常: {type(e).__name__}: {e}")
        return SandboxResult(
            tool_name=tool_name,
            success=False,
            error=str(e),
            error_type=type(e).__name__,
            execution_time_ms=elapsed,
            permission=permission.value,
        )


def register_tool(tool_name: str, permission: ToolPermission):
    """注册新工具的权限等级"""
    _TOOL_PERMISSIONS[tool_name] = permission


def blacklist_tool(tool_name: str):
    """将工具加入黑名单"""
    _TOOL_BLACKLIST.add(tool_name)


def get_tool_permissions() -> Dict[str, str]:
    """获取所有已注册工具的权限等级（供前端展示）"""
    return {name: perm.value for name, perm in _TOOL_PERMISSIONS.items()}
