---
name: diagram
description: >
  绘图专员。为指定章节生成技术路线图、框架图、思维导图等 Mermaid 示意图。
  当需要可视化研究方案、技术架构或流程时触发。
agent_type: diagram
triggers:
  - "绘图"
  - "流程图"
  - "技术路线"
  - "框架图"
  - "思维导图"
requires:
  tools: [llm, image_generator]
---

# Diagram Skill — 绘图专员

## 职责
封装 `image_generator.py` 中的图表生成能力，接收特定章节内容，
生成合适的 Mermaid 图（技术路线图、框架图、思维导图等）。

## 规则
1. 优先从 Document DOM 中读取章节元素内容
2. DOM 不可用时回退到 `draft_sections` 纯文本
3. 无内容的章节直接跳过
4. 图片路径写入 `generated_images` 字段供导出使用

## 调用入口
`src.agents.diagram_agent.run_diagram_agent`
