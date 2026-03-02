# PD-MAWS: 协议驱动的多智能体学术写作系统架构设计（完整修正版）

## 一、设计目标与全局不变量

### 1.1 设计目标

本系统目标不是“让 Agent 能跑”，而是“在可验证、可审计、可恢复前提下稳定运行”。

核心目标：

1. **正确性优先**：事实引用、冲突仲裁、图文一致性可追溯。
2. **可靠性优先**：关键控制消息不丢失，系统可在局部故障下退化运行。
3. **一致性优先**：会话状态只有一个权威来源，拒绝多源写入。
4. **安全与合规优先**：消息可鉴权、可防重放、可审计。
5. **工程可落地**：协议字段、状态机、错误码、SLO 和验收标准明确。

### 1.2 全局不变量（必须满足）

1. **会话权威唯一性**：`ANP.SessionRegistry` 是会话状态唯一权威源；其他层只能读取快照，不得直接改写。
2. **文档版本唯一权威性**：核心资产（草稿）必须存在独立的“文档知识库（Document Blackboard）”中，所有针对文档的修改必须通过带有版本锁的 Diff/Patch 进行，严禁在控制面消息中全量传递长文本。
3. **关键消息可恢复**：所有控制面消息必须走“可持久化 + ACK + 重试 + 死信”链路。
4. **消息幂等**：同一 `message_id` 重放不会造成重复副作用。
5. **引用可验证**：涉及学术结论的输出必须绑定合法 `context_grounding` 或被明确标记为低置信。
6. **安全可证明**：所有跨 Agent 消息必须通过身份鉴权和完整性校验。

---

## 二、四层协议栈（职责边界重定义）

1. **L1 - 基础设施层（Skills & MCP）**
   - 责任：外部交互（文献库、文件、数据库、模型 API）。
   - 约束：L1 不参与会话控制，不做全局路由决策。

2. **L2 - 内部控制层（ACP）**
   - 责任：单 Agent 内部状态机、任务推进、约束检查。
   - 约束：L2 不能越权修改跨 Agent 协议字段。

3. **L3 - 通信语义层（A2A）**
   - 责任：消息 Schema、语义、错误码、幂等语义。
   - 约束：L3 本身无会话存储能力，只携带会话快照。

4. **L4 - 网络组织层（ANP）**
   - 责任：会话状态中心、路由与调度、负载治理、熔断、仲裁升级。
   - 约束：L4 不生成学术内容。

> 关键澄清：A2A 报文可携带 `current_turn`，但它是“发送时快照”；接收时必须以 `ANP.SessionRegistry` 的版本号与状态为准。

---

## 三、A2A 协议（完整字段规范）

### 3.1 报文结构

```json
{
  "meta": {
    "message_id": "uuid-v7",
    "correlation_id": "req-root-id",
    "causation_id": "parent-message-id",
    "timestamp_ms": 1760000000000,
    "schema_version": "a2a.v1",
    "priority": "normal",
    "ttl_ms": 30000,
    "requires_ack": true,
    "idempotency_key": "optional-business-key"
  },
  "session": {
    "session_id": "sess_xxx",
    "parent_session_id": "sess_root_01",
    "sub_task_id": "task_methodology",
    "session_version": 12,
    "current_turn": 2,
    "max_turns_allowed": 6,
    "state_hint": "NEGOTIATING"
  },
  "route": {
    "source_agent": "Academic_Writer_01",
    "target_agent": "Visual_Diagram_01",
    "intent": "REQUEST_DIAGRAM_GENERATION",
    "reply_to": "agent.Academic_Writer_01.inbox"
  },
  "payload": {
    "context_grounding": ["doc_ref_112", "doc_ref_115"],
    "document_pointer": {
      "draft_id": "doc_123",
      "version_hash": "v12_abc",
      "patch_operations": [{"op": "replace", "path": "/sec3", "value": "..."}]
    },
    "constraints": {}
  },
  "control": {
    "timeout_ms": 15000,
    "requires_human_arbiter": false,
    "degrade_mode": "none"
  },
  "telemetry": {
    "prompt_tokens_used": 1450,
    "completion_tokens_used": 820,
    "model": "...",
    "latency_ms": 932
  },
  "security": {
    "auth_type": "jwt",
    "signature": "hmac-sha256",
    "nonce": "random",
    "nonce_ttl_ms": 60000
  }
}
```

### 3.2 强制校验顺序（接收侧）

1. Schema 校验（版本、必填、类型）。
2. 安全校验（签名、token、nonce 防重放）。
3. TTL 校验（过期直接拒绝）。
4. 幂等校验（`message_id`/`idempotency_key` 去重）。
5. 会话一致性校验（`session_version` 与 Registry 对比）。
6. 业务校验（grounding、参数完整性等）。

### 3.3 ACK/NACK 语义

- **ACK**：消息已被可靠接收并通过基础校验，不代表业务完成。
- **NACK_RETRYABLE**：可重试错误（网络抖动、临时依赖不可达）。
- **NACK_FATAL**：不可重试错误（签名失败、Schema 错误、越权访问）。

### 3.4 错误码（统一）

- `ERR_SCHEMA_INVALID`
- `ERR_AUTH_INVALID`
- `ERR_REPLAY_DETECTED`
- `ERR_SESSION_STALE`
- `ERR_GROUNDING_NOT_FOUND`
- `ERR_GROUNDING_UNAVAILABLE`
- `ERR_TIMEOUT`
- `ERR_DEADLOCK_SUSPECTED`
- `ERR_RATE_LIMITED`
- `ERR_POLICY_VIOLATION`

---

## 四、ANP 协议（有状态控制面）

### 4.0 多层级任务树（Map-Reduce 编排）

支持父子会话（Parent-Child Sessions）结构：
1. **拆解（Map）**：`PI_Agent` 负责将全局论文大纲拆解为多个子章节（如 `sec_intro`, `sec_method`），在 `SessionRegistry` 中创建相互隔离的子会话，分发给独立的 Writer 组并发执行。
2. **聚合（Reduce）**：各子会话达到 `COMPLETED` 后，向上游抛出 `sub_task.ready`，主会话收集所有子节点的指针进行组装。

### 4.1 Session Registry（唯一权威）

每个 `session_id` 保存：

- `parent_session_id`（若是子会话，须携带该字段）
- `sub_task_id`
- `session_version`（单调递增）
- `state`（`INIT`/`RUNNING`/`NEGOTIATING`/`ARBITRATION`/`DEGRADED`/`HALTED`/`COMPLETED`/`FAILED`）
- `participants`
- `turn_counter`
- `deadline_ms`
- `last_progress_ts`
- `conflict_counter`
- `budget_snapshot`

会话变更流程：

1. Agent 上报意图。
2. ANP 校验并原子更新 `session_version`。
3. ANP 下发新快照。
4. Agent 仅按新快照执行。

### 4.2 死锁检测（不只看轮次）

触发条件任一满足即判定“疑似死锁”：

1. `turn_counter > max_turns_allowed`
2. `last_progress_ts` 超过阈值（如 2×超时窗口）
3. 同一争议在相同参与者间往返超过 N 次
4. 同一 `intent` 在短窗内重复 N 次

动作：

1. 会话状态转 `ARBITRATION`
2. 冻结普通写入
3. 仅允许 `PI_Agent` 仲裁流消息
4. 仲裁结束后恢复或终止会话

### 4.3 Token 熔断（双层治理）

为避免“异步轮询导致硬上限穿透”，采用双层治理：

1. **本地软限流（Agent 侧）**
   - 每 Agent 维护滑窗预算。
   - 接近阈值先降级：减少采样、缩短上下文、切小任务。

2. **全局硬熔断（ANP 侧）**
   - Redis 原子计数器聚合。
   - 周期检测 + 事件触发检测并行。
   - 达到硬阈值时发布 `HALT`，并写审计日志。

3. **恢复机制**
   - 进入 `HALTED` 后只允许“恢复/终止”控制消息。
   - 人工确认或预算重置后才可恢复。

### 4.4 文档草稿对象的状态机与版本锁 (Document Blackboard)

将文档数据面（长文本）从控制面消息中剥离。草稿实体存放于独立的黑板（Blackboard）/知识库中，具备类似 Git 的版本控制特性。

**文档状态流转：**
`EMPTY -> DRAFTING -> CONFLICT -> REVIEW_PENDING -> INTEGRATED -> FINAL`

- **协议格式**：并发修改采用**乐观锁（Optimistic Locking）**或 **CRDT**，Agent 提交修改（Diff/Patch）时必须夹带上一轮的基线 `version_hash`。
- **并发约束**：如果发生版本冲突（如多个智能体同时更改了一段内容），ANP 会将该 `draft_id` 状态置为 `CONFLICT`，并在相应的会话中挂起，要求基于当前上下文生成解决冲突的合并请求。

### 4.5 上下文记忆浓缩机制 (Memory Consolidation)

当会话由于复杂的局部推理（如 Red Team 与 Writer 取证辩论）导致上下文膨胀逼近熔断阈值时：
1. 任何节点或 ANP 监控组件均可发出 `INTENT: COMPRESS_CONTEXT`。
2. 将前序多轮往返辩论交由专门的内部压缩模块（或 `Summarizer_Agent`）精简。
3. 压缩生成：“核心争议点 + 已达成共识的结论”的结构化快照。
4. `ANP.SessionRegistry` 截断旧历史，基于该快照重新定义 `baseline_context` 释放 Token 供会话继续。

---

## 五、消息通道分级（可靠性修正）

### 5.1 通道分类

1. **数据面（可丢）**：状态通知、非关键中间事件。
   - 可用 Redis Pub/Sub。

2. **控制面（不可丢）**：仲裁指令、状态迁移、`HALT`、`RESUME`、`CRITICAL` 冲突。
   - 必须使用 Redis Streams 或 RabbitMQ（持久化 + ACK + 重试 + DLQ）。

### 5.2 重试策略

- 指数退避：`base=200ms, factor=2, max=5s`
- 最大重试次数：`N=5`
- 超限进入 DLQ 并触发告警。

### 5.3 幂等策略

- 接收侧维护去重表（`message_id`，TTL 建议 24h）。
- 对有副作用动作（写文档、改状态）要求 `idempotency_key`。

---

## 六、Grounding 校验与降级策略（完整闭环）

### 6.1 校验规则

下游 Agent 对 `context_grounding` 执行：

1. 全量存在性检查
2. 引用来源合法性检查（白名单数据源）
3. 版本一致性检查（引用文档快照版本）

### 6.2 处理矩阵

1. 全部合法：正常执行。
2. 部分缺失：返回 `ERR_GROUNDING_NOT_FOUND` + 无效列表。
3. 服务不可用：进入 `DEGRADED` 子模式，不允许新增事实结论。

### 6.3 降级模式（严格）

`ERR_GROUNDING_UNAVAILABLE` 时，不再“直接跳过校验”，改为：

1. 仅允许使用本地缓存且未过期的引用。
2. 输出必须打标签：`LOW_CONFIDENCE`。
3. 禁止输出“新实验结论”类内容。
4. ANP 记录审计事件，并将该部分内容的引用索引推入**“存疑验证挂起队列 (Pending Validation Queue)”**。

### 6.4 服务恢复与异步回填 (Backfill Validation)

1. 当网络或外部文献服务恢复（健康检查通过）时，ANP 自动拉取 Pending Queue。
2. 发起无守护的后台任务，针对带有 `LOW_CONFIDENCE` 标签的结论重新执行 `context_grounding`。
3. 验证通过后，自动清除该记录的不确定标签；若验证不通过，生成更正告警报告，发往 `Human_Proxy_Agent` 节点或 `Red_Team_Reviewer`。

---

## 七、ACP（单 Agent 内核）

### 7.1 统一状态机

`IDLE -> PLAN -> EXECUTE -> VERIFY -> EMIT -> WAIT -> DONE/ERROR/INTERRUPTED`

规则：

1. 任意状态接收到 `HALT`，必须跳到 `INTERRUPTED`。
2. `VERIFY` 不通过不可进入 `EMIT`。
3. `ERROR` 连续超阈值自动上报 ANP 请求托管。

### 7.2 约束执行

每个 Agent 必须声明：

- `Role`
- `AllowedActions`
- `ForbiddenActions`
- `QualityGates`

违反 `ForbiddenActions`：立即 NACK + 审计记录。

---

## 八、核心节点定义（修正版）

### 8.1 PI_Agent（调度与仲裁）

职责：任务拆解、会话编排、冲突仲裁、人工升级。

仲裁引擎顺序：

1. 规则引擎（确定性）
2. LLM 仲裁（输出 `ArbDecision`，Pydantic 校验）
3. 人类在环（低置信或循环冲突）

新增硬规则：

- 同争议连续 2 次 LLM 结论不一致，直接人工升级。
- 同争议总处理时长超过 SLA（如 120s），直接人工升级。

### 8.2 Literature_Researcher_Agent

职责：检索并返回可验证文献证据。

输出必须结构化：

- `claim`
- `evidence_ids`
- `doi_or_ref`
- `confidence`
- `retrieved_at`

无证据不得输出结论。

### 8.3 Visual_Diagram_Agent

职责：将文本逻辑转图表代码（Mermaid / Matplotlib）。

新增质量门禁：

1. 语义一致性校验（图中实体须在文本中有来源）。
2. 风格约束校验（颜色、字体、对比度、标签可读性）。
3. 结构合法性校验（Mermaid 语法、Matplotlib 脚本可执行性）。

#### ColorValidator（升级版）

校验范围必须覆盖：

- `#RRGGBB`
- `#RGB`
- `rgb()/rgba()`
- 命名色（如 `red`）
- Mermaid `classDef` 颜色字段

校验逻辑：

1. 提取全部颜色
2. 统一转换到 HSL
3. 校验饱和度与亮度区间
4. 对超限值进行映射替换
5. 生成替换前后对照日志

> 低饱和不等于可读；必须同时满足最小对比度阈值（建议 WCAG AA）。

### 8.4 Red_Team_Reviewer_Agent

职责：主动发现逻辑漏洞和证据断裂。

修正触发机制：

- 不再只订阅 `draft_ready`。
- 改为订阅 `draft.integrated.ready`（图文合并完成事件）。
- 避免审查半成品导致误报。

### 8.5 Human_Proxy_Agent（人类数字代理）

职责：将人类操作提升为系统中的“一等公民”，不再仅仅是被动等触发死锁兜底的裁判。
- 人类可随时发出主动的 `INTERRUPT` 消息改变 Agent 或会话流向。
- 人类拥有最高权限控制面意图 `FORCE_UPDATE_DRAFT`，可直接强写 Blackboard 段落。
- 当发生人类强写后，系统将其视为顶层环境变更事件，自动将该变更相关的子会话或依赖进度退回至 `VERIFY` 或 `PLAN` 重新校验学术一致性、并触发补实验验证。

### 8.6 Format_Controller_Agent（排版与规范代理）

职责：承接图文集成（`Integrated`）后阶段，进一步解耦 Writer 对具体排版的关注。
- 负责执行严格格式化约束：IEEE/Nature 双排版面规整、LaTeX 宏编译或特殊的 Word 样式替换。
- 执行引文样式转换并做最终的短文长图约束裁剪。

### 8.7 Data_Analyst_Agent（核心数据分析代理）

职责：解决 `Visual_Diagram_Agent` 只长于“画现成静态图”而不具备探索分析能力的缺口。
- 在安全隔离的沙箱（如 Docker/Jupyter 容器）中运行构建的 Python/R，对挂载的外部数据集执行严谨的数值统计算法。
- 返回具备学术实验置信度的模型分数、整理表格或衍生数据集，供 Writer 引为新的可靠证据。

---

## 九、完整工作流（基于 Map-Reduce 与文档黑板版）

1. **会话创建与树状发散（Map）**：`PI_Agent` 接受论文框架，由 ANP 创建主会话 `SessionRegistry(state=INIT, version=1)`，并沿核心章节拓扑出 N 个并发执行的子会话节点。
2. **多编撰者执笔**：不同的 Writer 被调度到子会话中。文本修改以携带 `version_hash` 的 Patch 指令向共享外部实体（Blackboard）提交，A2A 控制报文内仅需携带数据指针与业务意图。
3. **复合证据获取**：编撰者借助不同通道的辅助服务（`Literature_Researcher` 调研论文，`Data_Analyst_Agent` 跑代码出数据）。
4. **人工协作无缝强插**：真实作者通过数字代理 `Human_Proxy_Agent` 以最高权限随时向 Blackboard 灌入核心见解（`FORCE_UPDATE_DRAFT`），引动局部会话重校验。
5. **资源组合及排印**：文字逻辑饱满后引渡至视觉处理节点 `Visual_Diagram_Agent` 创建表现图，之后让 `Format_Controller` 校验图文排版样式基准无误。
6. **归拢集成审读（Reduce）**：各个支线完成并挂出 `sub_task.ready`，主会话归拢触发 `draft.integrated.ready`，呼唤 `Red_Team_Reviewer` 进场做全盘逻辑校验与盲点阻击。
7. **争端消解与上下文保养**：若出现红蓝推拉使 token 逼近阈值，ANP 即刻下发 `COMPRESS_CONTEXT` 使对话主干重置于共识快照上，仅凭精简状态与黑板继续工作。
8. **落卷定档**：全员确认无误，系统进入 `COMPLETED` 状态封锁快照，产出完全抗重放与可验证全息追溯链。

---

## 十、安全、审计与可观测性

### 10.1 安全基线

1. Agent 身份认证：JWT/OAuth2。
2. 消息完整性：HMAC 签名。
3. 防重放：`nonce + timestamp + ttl`。
4. 最小权限：按 `intent` 做 ACL。

### 10.2 审计日志（不可省）

每条关键动作记录：

- `who`
- `when`
- `message_id/correlation_id`
- `before_state/after_state`
- `decision_reason`
- `evidence_links`

### 10.3 指标与告警

核心指标：

- 会话成功率
- 仲裁平均时延
- `NACK_RETRYABLE` 比例
- DLQ 堆积量
- grounding 失败率
- 熔断触发次数

---

## 十一、技术栈落地（最终建议）

1. **消息系统**
   - 数据面：Redis Pub/Sub
   - 控制面：Redis Streams（轻量）或 RabbitMQ（强可靠）

2. **状态与计数**
   - Session Registry：Redis Hash / PostgreSQL（高可靠场景）
   - Token 聚合：Redis `INCRBY` + 周期任务

3. **推理编排**
   - L2：LangGraph `StateGraph`

4. **数据校验**
   - Pydantic：A2A Schema、仲裁对象、配置对象

5. **可观测**
   - OpenTelemetry + Prometheus + Grafana

---

## 十二、验收标准（Definition of Done）

1. 控制面消息在单节点故障下不丢失。
2. 任意消息重放 3 次，业务副作用仍只发生一次。
3. grounding 服务不可用时系统进入 `DEGRADED`，且不产生未标记新结论。
4. 超预算后 5 秒内全网收到 `HALT` 并中断执行。
5. Red Team 只审查 `draft.integrated.ready` 事件对应成品。
6. 全链路审计可回放到任一关键决策节点。

---

## 十三、与原方案相比的关键修正摘要

1. 明确了 A2A 快照与 ANP 权威状态的冲突处理规则。
2. 将“关键不可丢消息”从 Pub/Sub 中剥离到可靠通道。
3. 将熔断从单一异步轮询升级为“本地软限流 + 全局硬熔断”。
4. 将 grounding “跳过校验”改为“受限降级模式”。
5. 补齐幂等、防重放、签名鉴权、审计与 SLO。
6. 修复 Red Team 审查竞态，避免半成品误判。

> 结论：该修正版可作为工程实施基线，不再停留在概念架构层。