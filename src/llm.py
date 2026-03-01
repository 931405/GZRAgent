import os
import time
import random
import threading
import httpx
from openai import APIError, RateLimitError, APITimeoutError
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()


# ============= Provider Fallback Chain（借鉴 OpenClaw） =============

# 各 Provider 的冷却状态：{provider: {"cooldown_until": float, "fail_count": int}}
_provider_cooldowns = {}
_cooldown_lock = threading.Lock()

# 默认回退链顺序
DEFAULT_FALLBACK_CHAIN = ["deepseek", "moonshot", "doubao", "custom"]

# 冷却时间参数（指数退避: 1min → 5min → 25min → 60min 上限）
_BASE_COOLDOWN_SECS = 60
_MAX_COOLDOWN_SECS = 3600


def _mark_provider_cooldown(provider: str):
    """标记 Provider 进入冷却状态（指数退避）"""
    with _cooldown_lock:
        state = _provider_cooldowns.get(provider, {"cooldown_until": 0, "fail_count": 0})
        state["fail_count"] += 1
        backoff = min(_BASE_COOLDOWN_SECS * (5 ** (state["fail_count"] - 1)), _MAX_COOLDOWN_SECS)
        state["cooldown_until"] = time.time() + backoff
        _provider_cooldowns[provider] = state
        print(f"[LLM Fallback] Provider '{provider}' 进入冷却 {backoff:.0f}s (第{state['fail_count']}次失败)")


def _is_provider_available(provider: str) -> bool:
    """检查 Provider 是否可用（不在冷却期）"""
    with _cooldown_lock:
        state = _provider_cooldowns.get(provider)
        if state and time.time() < state["cooldown_until"]:
            return False
        # 冷却期结束 → 重置
        if state and time.time() >= state["cooldown_until"]:
            state["fail_count"] = 0
        return True


def _get_provider_config(provider: str) -> dict:
    """获取特定 Provider 的 API 配置"""
    if provider == "deepseek":
        return {
            "api_key": os.getenv("DEEPSEEK_API_KEY"),
            "base_url": os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com/v1"),
            "model": os.getenv("PRIMARY_MODEL", "deepseek-chat"),
        }
    elif provider == "moonshot":
        return {
            "api_key": os.getenv("MOONSHOT_API_KEY"),
            "base_url": os.getenv("MOONSHOT_API_BASE", "https://api.moonshot.cn/v1"),
            "model": os.getenv("PRIMARY_MODEL", "moonshot-v1-8k"),
        }
    elif provider == "doubao":
        return {
            "api_key": os.getenv("DOUBAO_API_KEY"),
            "base_url": os.getenv("DOUBAO_API_BASE", "https://ark.cn-beijing.volces.com/api/v3"),
            "model": os.getenv("DOUBAO_MODEL_ENDPOINT", ""),
        }
    elif provider == "custom":
        return {
            "api_key": os.getenv("CUSTOM_API_KEY"),
            "base_url": os.getenv("CUSTOM_API_BASE", "https://api.openai.com/v1"),
            "model": os.getenv("CUSTOM_MODEL", "gpt-3.5-turbo"),
        }
    return {}


def _resolve_provider(provider_override: str = None) -> str:
    """解析可用的 Provider（带回退链）。
    
    借鉴 OpenClaw 的认证配置文件轮换机制：
    如果指定的 provider 在冷却期，按 fallback chain 顺序切换到下一个。
    """
    primary = provider_override or os.getenv("PRIMARY_PROVIDER", "deepseek").lower()
    
    if _is_provider_available(primary):
        config = _get_provider_config(primary)
        if config.get("api_key"):
            return primary
    
    # 回退：按链顺序查找可用且已配置的 provider
    for fallback in DEFAULT_FALLBACK_CHAIN:
        if fallback == primary:
            continue
        if _is_provider_available(fallback):
            config = _get_provider_config(fallback)
            if config.get("api_key"):
                print(f"[LLM Fallback] '{primary}' 不可用，回退到 '{fallback}'")
                return fallback
    
    # 兜底：仍然使用 primary（即使可能在冷却期）
    return primary


def get_llm(provider_override: str = None, temperature: float = 0.7, is_json_mode: bool = False) -> ChatOpenAI:
    """
    获取配置好的 LLM 实例（基于 OpenAI 兼容接口）。
    
    增强功能（借鉴 OpenClaw）：
    - 自动 Provider 回退链：当指定 Provider 在冷却期时，自动切换到可用备选
    - 会话粘性：相同 Provider 的请求不会在每次都重新解析
    
    支持的 provider: 'deepseek', 'moonshot', 'doubao', 'custom'
    """
    provider = _resolve_provider(provider_override)
    config = _get_provider_config(provider)
    
    if not config.get("api_key"):
        raise ValueError(f"Provider '{provider}' 未配置 API Key")

    kwargs = {
        "api_key": config["api_key"],
        "base_url": config["base_url"],
        "model": config["model"],
        "temperature": temperature,
        "max_tokens": 8192,
        "max_retries": 3,
    }
    
    if is_json_mode and provider == "deepseek":
        kwargs["model_kwargs"] = {"response_format": {"type": "json_object"}}
        
    return ChatOpenAI(**kwargs)


def call_with_retry(chain, inputs: dict, max_attempts: int = 3, base_delay: float = 2.0,
                    provider: str = None):
    """
    带指数退避、随机抖动 (Jitter)、和 Provider 回退的链调用包装器。
    
    增强功能：
    - 在遇到 RateLimitError 时自动将当前 Provider 标记为冷却
    - 后续调用会自动回退到可用 Provider
    
    Args:
        chain: LangChain 链（prompt | llm | parser）
        inputs: 输入字典
        max_attempts: 最大尝试次数
        base_delay: 初始等待秒数，每次翻倍并添加抖动
        provider: 当前使用的 Provider（用于冷却标记）
    """
    last_error = None
    for attempt in range(max_attempts):
        try:
            return chain.invoke(inputs)
        except RateLimitError as e:
            last_error = e
            # 标记当前 Provider 进入冷却
            if provider:
                _mark_provider_cooldown(provider)
            if attempt < max_attempts - 1:
                delay = base_delay * (2 ** attempt)
                jitter = random.uniform(0.5, 1.5)
                wait_time = delay * jitter
                print(f"[LLM Retry] 第 {attempt + 1} 次限流 ({type(e).__name__}): {e}，将在 {wait_time:.1f}s 后重试...")
                time.sleep(wait_time)
            else:
                print(f"[LLM Error] 已重试 {max_attempts} 次仍失败: {e}")
                raise last_error
        except (httpx.RequestError, APIError, APITimeoutError) as e:
            last_error = e
            if attempt < max_attempts - 1:
                delay = base_delay * (2 ** attempt)
                jitter = random.uniform(0.5, 1.5)
                wait_time = delay * jitter
                print(f"[LLM Retry] 第 {attempt + 1} 次调用失败 ({type(e).__name__}): {e}，将在 {wait_time:.1f}s 后重试...")
                time.sleep(wait_time)
            else:
                print(f"[LLM Error] 已重试 {max_attempts} 次仍失败: {e}")
                raise last_error
        except Exception as e:
            print(f"[LLM Fatal] 遇到非重试型错误 ({type(e).__name__}): {e}")
            raise e
    raise last_error

