# D-MAWS 系统设计与技术栈规范 (Design & Tech Stack Specification)

## 1. 架构定位
本系统定位为“生产级、可审计、高并发”的多智能体学术写作系统（Protocol-Driven Multi-Agent Academic Writing System, PD-MAWS）。
其前后端技术栈和存储组件的选型严格遵循“可靠、低延迟、可追踪”的原则。

## 2. 前端架构 (Frontend)
前端主要负责承载复杂的文献知识图谱交互、Agent辩论流的全息展示、多层级任务树看板以及长篇草稿的编辑体验。

**核心技术栈：**
- **框架**：React 18 / Next.js (App Router)
- **语言**：TypeScript (严格的类型安全，适配后端复杂的数据 Schema)
- **状态管理**：Zustand (用于管理会话配置、草稿编辑状态等轻量级状态) + React Query (用于处理服务端 API 请求和缓存)
- **UI 组件库**：Tailwind CSS + Shadcn UI (提供高度定制化的学术风界面组件)
- **长文本编辑器**：Tiptap / ProseMirror (支持基于 CRDT 的多人或人机并发协作，适配 Document Blackboard 的 Patch 协议)
- **流视图与图表**：React Flow (用于展示 Agent 通信与任务编排层级拓扑图) + Mermaid.js (内嵌支持预览 Agent 生成的图表代码)

**关键模块：**
1. **统一工作台 (Studio)**：包含草稿区、证据看板、Agent 聊天流面板。
2. **审计回放 (Audit Replay)**：图形化重现某次写作冲突的仲裁过程。
3. **人类干预台 (Human-in-the-loop CLI)**：支持 `FORCE_UPDATE_DRAFT`、`COMPRESS_CONTEXT` 等高权限操作的控制面板。

## 3. 后端架构 (Backend)
后端是系统的中枢神经，不仅承载 L1-L4 的四层协议控制流，还要处理长下文大模型的调度逻辑。

**核心技术栈：**
- **主框架**：Python 3.11+ / FastAPI (异步高性能，原生支持 Pydantic 进行 A2A Schema 校验)
- **Agent 编排框架**：LangGraph (极为贴合系统状态机的要求，天然支持环状拓扑和持久化状态机 L2-ACP) 
- **LLM/工具集成基座**：LangChain (用于构建文献检索器、结构化输出等 Tool 能力层 L1)
- **通讯中间件 (消息总线)**：
  - 数据面（草稿同步与轻量事件）：Redis Pub/Sub 或 WebSocket (FastAPI WebSockets API)
  - 控制面（关键状态流转、仲裁指令）：RabbitMQ 或 Kafka (提供持久化、消息 ACK 和 DLQ 机制，确保消息不丢)
- **并发与后台任务**：Celery (配合 RabbitMQ/Redis 用于执行离线图表生成、长时间数据分析等耗时操作)

## 4. 存储与数据库架构 (Database & Storage)
系统的存储需要分离业务元数据、知识库嵌入以及会话会控状态。

### 4.1 关系型数据库 (RDBMS) - 业务核心
**选型：PostgreSQL 16+**
**用途**：
- 用户管理、权限 (RBAC)。
- `ANP.SessionRegistry` 的持久化兜底与历史归档。
- 全链路审计日志 (Audit Logs) 的存储。
- 多版本文档大纲与草稿内容 (支持 JSONB 字段存储 Document Blackboard 的各个 Patch 记录)。
**ORM 框架**：SQLAlchemy / SQLModel (结合 Pydantic 提供端到端类型校验)。

### 4.2 内存数据库 (NoSQL / Cache) - 会话中转站
**选型：Redis 7+**
**用途**：
- `ANP.SessionRegistry` 的高速运行时快照。
- Token 全局硬熔断原子计数器。
- 热点文献数据字典缓存、会话去重与防重放 (Idempotency Keys, Nonce TTL)。

### 4.3 向量数据库 (Vector DB) - 知识库大脑
**选型：Qdrant (Mandatory)**
**用途**：
- **学术文献库 (Literature RAG)**：存储上传的 PDF/学术论文切割后的文本 Chunk及其 Embedding 向量，支持文献语义检索 (`Literature_Researcher_Agent` 调用的核心依赖)。
- **记忆与先验知识 (Agent Memory)**：存储长期记忆、相似历史对话、已解决的冲突仲裁范式。
**选择优势**：
- 基于 Rust 构建，性能卓越，处理高并发检索时延迟低。
- 强大的过滤搜索 (Payload Filtering)，能够针对“作者”、“发表年份”、“期刊评级”进行非常细粒度的前置布尔过滤，这对于学术系统中的 *约束查询* 尤为重要。
- 原生支持 HNSW 图算法和标量量化机制，节约内存。

### 4.4 对象存储 (Object Storage)
**选型：MinIO / AWS S3**
**用途**：
- 存放原始文献 PDF、用户上传的辅助数据集 (CSV/Excel 供 Data_Analyst_Agent 读取)。
- 存放挂载的中间态资产：系统生成的逻辑架构图表原图 (.png/.svg)、数据统计分析报告等。

## 5. 部署与运维架构 (DevOps)
- **容器化编排**：Docker + Docker Compose (单机部署) / Kubernetes (多机分布式)。
- **网关层**：Nginx / APISIX (负责负载均衡、JWT 校验过滤)。
- **可观测性 (Observability)**：
  - 链路追踪：OpenTelemetry
  - 指标监控：Prometheus + Grafana (监控 Token 消耗、仲裁延迟、NACK 重试率)
  - 日志聚合：ELK Stack (Elasticsearch, Logstash, Kibana) 或 Loki

---

**技术栈协同逻辑总结：**
系统接到用户请求时，FastAPI 接受指令并唤起 LangGraph 主会话。主会话调度各 Agent 时，状态注册表暂存于 Redis；通信经 RabbitMQ 保障关键控制节点；一旦 Writer 需引入客观事实，触发 Qdrant 进行带 Payload 过滤的向量检索；当章节成型或被人类代理强行修正（经 CRDT ProseMirror 同步）时，数据保存进 PostgreSQL JSONB；所有步骤日志均交由 OpenTelemetry/Loki 进行可溯源监控。
