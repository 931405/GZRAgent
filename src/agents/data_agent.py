"""
data_agent.py — 数据与表格分析员
负责从当前章节草稿的 DOM 树中提取 [PLACEHOLDER: TABLE: xxx]，并生成对应的真实数据表格结构。
"""
import uuid
from typing import Dict, Any
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser

from src.state import GraphState, TableElement
from src.llm import get_llm

_DATA_AGENT_SYSTEM = """\
你是一个数据与表格分析专家（Data Agent）。
你的任务是根据提供的占位符描述和研究主题，生成一张符合要求的真实、严谨的表格数据。
由于大模型容易产生幻觉，请根据你的知识生成合理的数据集或框架，输出格式为 Markdown 表格，并补充相应的数据说明（源于真实财报或合理预估）。

输出 JSON 格式要求：
{
  "table_markdown": "| 列1 | 列2 |\n|---|---|\n| 数据1 | 数据2 |",
  "data_source_note": "数据来源说明或生成理由"
}
"""

_DATA_AGENT_USER = """\
项目主题: {topic}
对应章节: {section}
表格需求: {placeholder_desc}
请提供该表格的数据：
"""

def run_data_agent(state: GraphState, section: str, placeholder_id: str, placeholder_desc: str) -> Dict[str, Any]:
    print(f"-> [DataAgent]: 正在生成表格数据 ({placeholder_desc}) ...")
    config = state.get("model_config") or {}
    llm = get_llm(provider_override=config.get("writer", "deepseek"), temperature=0.1, is_json_mode=True)
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", _DATA_AGENT_SYSTEM),
        ("user", _DATA_AGENT_USER),
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
                
        table_md = data.get("table_markdown", "*生成表格失败*")
        note = data.get("data_source_note", "")
        
        element = TableElement(
            id=placeholder_id,
            content=table_md,
            metadata={"source_note": note, "prompt": placeholder_desc}
        )
        
        # 将结果存入 DOM 树增量
        return {
            "document_dom": {
                section: {"element_updates": [element]} # 稍后由于 reducer 需要特殊处理，我们在 Orchestrator 中处理合并
            },
            "discussion_history": [f"[DataAgent] 成功生成表格: {placeholder_desc}."]
        }
    except Exception as e:
        print(f"[DataAgent] 失败: {e}")
        return {"discussion_history": [f"[DataAgent] 失败: {e}"]}
