"""
formula_agent.py — 数学公式专员
负责从当前章节草稿的 DOM 树中提取 [PLACEHOLDER: FORMULA: xxx]，推导并生成严格的 LaTeX 公式。
"""
import uuid
from typing import Dict, Any
from langchain_core.prompts import ChatPromptTemplate

from src.state import GraphState, FormulaElement
from src.llm import get_llm

_FORMULA_AGENT_SYSTEM = """\
你是一个高级数学与科研公式专员（Formula Agent）。
你的任务是根据提供的占位符和上下文，推导并生成精美严谨的 Typst 数学公式源码（Typst Math Syntax）。
由于系统将直接使用 Typst 渲染引擎，请不要使用复杂的 LaTeX (`\\begin{equation}`) 环境序列，直接输出干净的公式部分。
例如：爱因斯坦著名公式只需输出 `E = m c^2`；积分可输出 `integral_0^1 x^2 dif x`。

输出 JSON 格式要求：
{
  "typst_math_code": "E = m c^2",
  "explanation": "对公式各个变量的说明"
}
"""

_FORMULA_AGENT_USER = """\
项目主题: {topic}
对应章节: {section}
公式要求: {placeholder_desc}
请输出严谨的公式代码以及变量说明：
"""

def run_formula_agent(state: GraphState, section: str, placeholder_id: str, placeholder_desc: str) -> Dict[str, Any]:
    print(f"-> [FormulaAgent]: 正在生成LaTeX公式 ({placeholder_desc}) ...")
    config = state.get("model_config") or {}
    llm = get_llm(provider_override=config.get("writer", "deepseek"), temperature=0.1, is_json_mode=True)
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", _FORMULA_AGENT_SYSTEM),
        ("user", _FORMULA_AGENT_USER),
    ])
    
    try:
        raw = (prompt | llm).invoke({
            "topic": state.get("research_topic", ""),
            "section": section,
            "placeholder_desc": placeholder_desc,
        })
        
        import json, re
        raw_text = raw.content if hasattr(raw, "content") else str(raw)
        data = {}
        try:
            data = json.loads(raw_text)
        except:
            match = re.search(r'\{.*\}', raw_text, re.DOTALL)
            if match:
                data = json.loads(match.group())
                
        typst_code = data.get("typst_math_code", "E = m c^2")
        explanation = data.get("explanation", "")
        
        element = FormulaElement(
            id=placeholder_id,
            content=typst_code,
            metadata={"explanation": explanation, "prompt": placeholder_desc}
        )
        
        return {
            "document_dom": {
                section: {"element_updates": [element]}
            },
            "discussion_history": [f"[FormulaAgent] 成功生成公式: {placeholder_desc}."]
        }
    except Exception as e:
        print(f"[FormulaAgent] 失败: {e}")
        return {"discussion_history": [f"[FormulaAgent] 失败: {e}"]}
