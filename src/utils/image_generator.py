"""
大模型绘图生成器
==============
支持两种图表生成策略：

1. **Mermaid 流程图**（首选）
   - 调用 LLM 生成 Mermaid 语法代码
   - 通过 mermaid.ink 在线服务渲染为 PNG
   - 无需安装额外依赖，仅需网络

2. **SiliconFlow 文生图**（可选，fallback）
   - 兼容 OpenAI /images/generations 接口
   - 需在 .env 中配置 SILICONFLOW_API_KEY 和 IMAGE_GEN_MODEL

需要生成图表的章节及类型由 SECTION_DIAGRAM_CONFIG 决定。
"""

import base64
import os
import re
import time
from typing import Dict, List, Optional

import requests

# ============================================================
# 章节 → 图表配置映射
# ============================================================
SECTION_DIAGRAM_CONFIG: Dict[str, Dict] = {
    "研究方案与可行性": {
        "diagram_type": "flowchart",
        "caption": "技术路线图",
        "prompt_hint": (
            "展示本研究的技术路线：包括数据/方法输入、核心算法/模型、"
            "关键步骤、评估指标等，突出创新点"
        ),
    },
    "研究目标与内容": {
        "diagram_type": "mindmap",
        "caption": "研究目标与内容框架图",
        "prompt_hint": (
            "以研究总目标为根节点，展开研究内容的层次结构，"
            "包括子目标、关键科学问题等"
        ),
    },
}

# ============================================================
# 主入口
# ============================================================

def generate_diagram_for_section(
    section_name: str,
    section_content: str,
    topic: str,
    model_provider: Optional[str] = None,
) -> Optional[str]:
    """
    为指定章节生成配图，返回本地图片绝对路径；失败则返回 None。

    Args:
        section_name   : 章节名
        section_content: 该章节生成的正文
        topic          : 研究主题
        model_provider : 使用的 LLM provider（None = 全局默认）
    """
    cfg = SECTION_DIAGRAM_CONFIG.get(section_name)
    if not cfg:
        return None

    print(f"-> [ImageGen]: 为 '{section_name}' 生成{cfg['caption']}...")

    # 策略1：Mermaid 图（首选）
    img_path = _generate_mermaid_diagram(section_name, section_content, topic, cfg, model_provider)
    if img_path:
        return img_path

    # 策略2：SiliconFlow 文生图（fallback）
    img_path = _generate_via_siliconflow(section_name, topic, cfg)
    return img_path


def generate_all_diagrams(
    draft_sections: Dict[str, str],
    topic: str,
    model_provider: Optional[str] = None,
) -> Dict[str, str]:
    """
    为所有需要配图的章节批量生成图片。

    Returns:
        dict: {section_name: local_image_path}
    """
    results: Dict[str, str] = {}
    for section_name in SECTION_DIAGRAM_CONFIG:
        content = draft_sections.get(section_name, "")
        if not content:
            continue
        path = generate_diagram_for_section(section_name, content, topic, model_provider)
        if path:
            results[section_name] = path
    return results


# ============================================================
# 策略1：Mermaid 图
# ============================================================

def _build_mermaid_prompt(
    diagram_type: str,
    topic: str,
    content_summary: str,
    prompt_hint: str,
) -> str:
    """构造让 LLM 生成 Mermaid 代码的 prompt。"""

    if diagram_type == "flowchart":
        return f"""你是一位科研图表专家，请根据以下国自然申请书章节内容，生成一段 **Mermaid flowchart TD** 图代码。

严格要求：
- 以 `flowchart TD` 开头
- 节点 ID 使用英文：A, B, C … 或 A1, B1 …
- 节点标签用方括号 `[中文文字]`，每个标签不超过 15 字
- 使用 `-->` 表示数据流 / 步骤流
- 重要步骤可用 `{{判断框}}` 或 `([椭圆])` 区分
- 节点总数控制在 8～16 个
- **只输出 Mermaid 代码块**，不要任何解释

研究主题：{topic}
图表要点：{prompt_hint}
章节摘要：
{content_summary}

```mermaid
flowchart TD
"""
    else:  # mindmap
        return f"""你是一位科研图表专家，请根据以下国自然申请书章节内容，生成一段 **Mermaid mindmap** 图代码。

严格要求：
- 以 `mindmap` 开头
- 根节点为研究主题
- 层次不超过 3 层
- 每个节点文字不超过 12 字
- **只输出 Mermaid 代码块**，不要任何解释

研究主题：{topic}
图表要点：{prompt_hint}
章节摘要：
{content_summary}

```mermaid
mindmap
"""


def _call_llm_for_mermaid(prompt: str, provider: Optional[str]) -> Optional[str]:
    """调用 LLM 生成 Mermaid 代码，返回清洁后的代码字符串。"""
    try:
        from src.llm import get_llm
        llm = get_llm(provider_override=provider or "deepseek", temperature=0.2)
        result = llm.invoke(prompt)
        raw_text = result.content if hasattr(result, "content") else str(result)

        # 尝试提取 ```mermaid ... ``` 代码块
        match = re.search(r"```(?:mermaid)?\s*([\s\S]+?)```", raw_text)
        if match:
            return match.group(1).strip()

        # 没有代码块标记，但含 flowchart / mindmap 关键词
        if re.search(r"^(flowchart|mindmap)", raw_text.strip(), re.IGNORECASE):
            return re.sub(r"```[a-z]*", "", raw_text).strip()

        # LLM 只输出了开头部分（prompt 里已包含 ``` 开头）
        lines = raw_text.strip().split("\n")
        for i, line in enumerate(lines):
            if re.match(r"^(flowchart|mindmap)", line, re.IGNORECASE):
                return "\n".join(lines[i:]).strip()

        return None

    except Exception as e:
        print(f"[ImageGen] LLM 生成 Mermaid 代码失败: {e}")
        return None


def _render_mermaid_via_ink(mermaid_code: str) -> Optional[bytes]:
    """
    通过 mermaid.ink 在线渲染接口将 Mermaid 代码转换为 PNG 字节流。
    """
    try:
        # mermaid.ink 接受 base64url 编码的代码
        encoded = base64.urlsafe_b64encode(mermaid_code.encode("utf-8")).decode("utf-8")
        url = f"https://mermaid.ink/img/{encoded}?theme=default&bgColor=white"

        resp = requests.get(url, timeout=30)
        if resp.status_code == 200 and resp.headers.get("Content-Type", "").startswith("image"):
            return resp.content

        print(f"[ImageGen] mermaid.ink 返回 {resp.status_code}，尝试备用参数...")

        # 备用：不带参数
        url2 = f"https://mermaid.ink/img/{encoded}"
        resp2 = requests.get(url2, timeout=30)
        if resp2.status_code == 200:
            return resp2.content

    except Exception as e:
        print(f"[ImageGen] mermaid.ink 请求失败: {e}")
    return None


def _save_image(data: bytes, section_name: str, prefix: str = "diagram") -> str:
    """将图片字节保存到 data/images/ 目录，返回绝对路径。"""
    output_dir = os.path.join("data", "images")
    os.makedirs(output_dir, exist_ok=True)
    safe_name = re.sub(r"[^\w\u4e00-\u9fff]", "_", section_name)
    filename = f"{prefix}_{safe_name}_{int(time.time())}.png"
    filepath = os.path.abspath(os.path.join(output_dir, filename))
    with open(filepath, "wb") as f:
        f.write(data)
    print(f"[ImageGen] 图表已保存: {filepath}")
    return filepath


def _generate_mermaid_diagram(
    section_name: str,
    section_content: str,
    topic: str,
    cfg: dict,
    provider: Optional[str],
) -> Optional[str]:
    """生成 Mermaid 图表并保存，返回图片路径或 None。"""
    diagram_type = cfg["diagram_type"]
    content_summary = section_content[:1000]

    prompt = _build_mermaid_prompt(
        diagram_type, topic, content_summary, cfg["prompt_hint"]
    )
    mermaid_code = _call_llm_for_mermaid(prompt, provider)
    if not mermaid_code:
        print(f"[ImageGen] Mermaid 代码生成失败，跳过该章节配图。")
        return None

    print(f"[ImageGen] Mermaid 代码已生成（{len(mermaid_code)} 字符），正在渲染...")

    img_bytes = _render_mermaid_via_ink(mermaid_code)
    if not img_bytes:
        print(f"[ImageGen] 渲染失败，尝试简化 Mermaid 代码后重试...")
        # 尝试去掉多余样式，重新渲染
        simplified = _simplify_mermaid(mermaid_code)
        img_bytes = _render_mermaid_via_ink(simplified)

    if not img_bytes:
        print(f"[ImageGen] Mermaid 图表渲染最终失败，跳过。")
        return None

    return _save_image(img_bytes, section_name, prefix="mermaid")


def _simplify_mermaid(code: str) -> str:
    """移除可能导致渲染失败的额外样式/注释，保留核心逻辑。"""
    lines = []
    for line in code.split("\n"):
        stripped = line.strip()
        # 跳过 classDef / style / click 等装饰指令
        if re.match(r"^(classDef|style|click|subgraph end)\b", stripped, re.IGNORECASE):
            continue
        lines.append(line)
    return "\n".join(lines)


# ============================================================
# 策略2：SiliconFlow 文生图
# ============================================================

def _generate_via_siliconflow(
    section_name: str,
    topic: str,
    cfg: dict,
) -> Optional[str]:
    """通过 SiliconFlow 文生图 API 生成图片，返回图片路径或 None。"""
    api_key = os.getenv("SILICONFLOW_API_KEY", "")
    if not api_key or api_key.startswith("your_"):
        print("[ImageGen] SiliconFlow API Key 未配置，跳过文生图。")
        return None

    # 构建英文 prompt（图生文模型通常对英文 prompt 效果更好）
    image_prompt = (
        f"A clean professional scientific research diagram for a Chinese NSFC grant proposal. "
        f"Topic: {topic[:60]}. "
        f"{cfg['prompt_hint']}. "
        f"Style: academic flowchart, white background, clear arrows, Chinese text labels, "
        f"professional technical illustration."
    )

    try:
        import openai

        client = openai.OpenAI(
            api_key=api_key,
            base_url=os.getenv("SILICONFLOW_API_BASE", "https://api.siliconflow.cn/v1"),
        )
        model = os.getenv("IMAGE_GEN_MODEL", "stabilityai/stable-diffusion-3-5-large")

        print(f"[ImageGen] 通过 SiliconFlow ({model}) 生成图片...")
        response = client.images.generate(
            model=model,
            prompt=image_prompt,
            n=1,
            size="1024x768",
        )
        image_url = response.data[0].url

        # 下载图片
        img_resp = requests.get(image_url, timeout=60)
        if img_resp.status_code != 200:
            return None

        return _save_image(img_resp.content, section_name, prefix="sfimg")

    except Exception as e:
        print(f"[ImageGen] SiliconFlow 文生图失败: {e}")
        return None


# ============================================================
# 工具函数
# ============================================================

def get_sections_needing_diagrams() -> List[str]:
    """返回需要生成配图的章节名列表。"""
    return list(SECTION_DIAGRAM_CONFIG.keys())


