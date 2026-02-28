import os
import time
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()


def get_llm(provider_override: str = None, temperature: float = 0.7, is_json_mode: bool = False) -> ChatOpenAI:
    """
    获取配置好的 LLM 实例（基于 OpenAI 兼容接口）。
    支持的 provider: 'deepseek', 'moonshot', 'doubao'
    所有 LLM 调用自动支持指数退避重试（通过 langchain_core 的内置回调）。
    """
    provider = provider_override or os.getenv("PRIMARY_PROVIDER", "deepseek").lower()
    
    if provider == "deepseek":
        api_key = os.getenv("DEEPSEEK_API_KEY")
        base_url = os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com/v1")
        model = os.getenv("PRIMARY_MODEL", "deepseek-chat")
    elif provider == "moonshot":
        api_key = os.getenv("MOONSHOT_API_KEY")
        base_url = os.getenv("MOONSHOT_API_BASE", "https://api.moonshot.cn/v1")
        model = os.getenv("PRIMARY_MODEL", "moonshot-v1-8k")
    elif provider == "doubao":
        api_key = os.getenv("DOUBAO_API_KEY")
        base_url = os.getenv("DOUBAO_API_BASE", "https://ark.cn-beijing.volces.com/api/v3")
        model = os.getenv("DOUBAO_MODEL_ENDPOINT", "")
    else:
        raise ValueError(f"Unsupported provider: {provider}")

    kwargs = {
        "api_key": api_key,
        "base_url": base_url,
        "model": model,
        "temperature": temperature,
        "max_tokens": 4096,
        # 内置重试：最多 3 次，适应速率限制和网络抖动
        "max_retries": 3,
    }
    
    if is_json_mode and provider == "deepseek":
        kwargs["model_kwargs"] = {"response_format": {"type": "json_object"}}
        
    return ChatOpenAI(**kwargs)


def call_with_retry(chain, inputs: dict, max_attempts: int = 3, base_delay: float = 2.0):
    """
    带指数退避的链调用包装器。
    适用于不支持 max_retries 的场景，或需要更细粒度控制时。
    
    Args:
        chain: LangChain 链（prompt | llm | parser）
        inputs: 输入字典
        max_attempts: 最大尝试次数
        base_delay: 初始等待秒数，每次翻倍
    """
    last_error = None
    for attempt in range(max_attempts):
        try:
            return chain.invoke(inputs)
        except Exception as e:
            last_error = e
            if attempt < max_attempts - 1:
                delay = base_delay * (2 ** attempt)
                print(f"[LLM Retry] 第 {attempt + 1} 次失败: {e}，{delay:.0f}s 后重试...")
                time.sleep(delay)
            else:
                print(f"[LLM Error] 已重试 {max_attempts} 次仍失败: {e}")
    raise last_error
