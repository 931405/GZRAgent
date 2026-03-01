---
name: searcher
description: >
  文献检索专员。根据研究主题和当前章节的检索意图，生成多角度英文关键词，
  并发检索 arXiv 和本地知识库，通过 LLM Rerank 过滤低质量结果，
  输出结构化引用编号。适用于需要"最新文献/研究现状/对比分析"的场景。
agent_type: searcher
triggers:
  - "文献"
  - "检索"
  - "引用"
  - "参考"
  - "最新研究"
  - "研究现状"
requires:
  tools: [llm, arxiv, rag_engine]
---

# Search Skill — 文献检索专员

## 职责
1. 根据章节意图生成 2-3 个多角度检索关键词
2. 并发检索 arXiv（多关键词）+ 本地知识库
3. LLM 相关性评估 (Rerank)，过滤低质量结果
4. 结构化引用编号

## 章节检索意图映射

| 章节 | 检索意图 |
|------|---------|
| 立项依据 | 综述型文献和前沿进展 |
| 研究目标与内容 | 方法论型文献 |
| 研究方案与可行性 | 技术方案型文献 |
| 特色与创新 | 对比型文献 |
| 研究基础 | 团队相关成果和领域基础 |

## References
- `references/section_search_intent.md` — 章节检索意图详细说明

## 调用入口
`src.agents.searcher.run_searcher`
